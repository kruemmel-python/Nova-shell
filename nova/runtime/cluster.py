from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True)
class LeaderLease:
    cluster_name: str
    leader_id: str
    lease_expires_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        return {
            "cluster_name": self.cluster_name,
            "leader_id": self.leader_id,
            "lease_expires_at": self.lease_expires_at,
            "metadata": self.metadata,
            "updated_at": self.updated_at,
            "is_expired": self.lease_expires_at < now,
        }


@dataclass(slots=True)
class DeploymentRevision:
    deployment_name: str
    revision: int
    spec: dict[str, Any]
    strategy: str
    status: str
    active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_name": self.deployment_name,
            "revision": self.revision,
            "spec": self.spec,
            "strategy": self.strategy,
            "status": self.status,
            "active": self.active,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ClusterPlane:
    """Cluster coordination for leases, deployments, and recovery."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "cluster-plane.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._open_connection()
        self._init_schema()

    def _open_connection(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._open_connection()
        return self._conn

    def _init_schema(self) -> None:
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cluster_leases (
                    cluster_name TEXT PRIMARY KEY,
                    leader_id TEXT NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deployments (
                    deployment_name TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    spec_json TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (deployment_name, revision)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recovery_playbooks (
                    playbook_name TEXT PRIMARY KEY,
                    snapshot_path TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deployment_health (
                    deployment_name TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    target_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    checked_at REAL NOT NULL,
                    PRIMARY KEY (deployment_name, revision, target_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recovery_runs (
                    run_id TEXT PRIMARY KEY,
                    playbook_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def acquire_leadership(
        self,
        cluster_name: str,
        node_id: str,
        *,
        lease_seconds: int = 30,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        lease_expires_at = now + max(1, lease_seconds)
        conn = self._ensure_connection()
        with self._lock, conn:
            row = conn.execute(
                """
                SELECT leader_id, lease_expires_at, metadata_json, updated_at
                FROM cluster_leases
                WHERE cluster_name=?
                """,
                (cluster_name,),
            ).fetchone()
            if row is not None and float(row[1]) >= now and str(row[0]) != node_id:
                lease = LeaderLease(
                    cluster_name=cluster_name,
                    leader_id=str(row[0]),
                    lease_expires_at=float(row[1]),
                    metadata=json.loads(row[2]),
                    updated_at=float(row[3]),
                )
                payload = lease.to_dict()
                payload["acquired"] = False
                return payload

            conn.execute(
                """
                INSERT INTO cluster_leases(cluster_name, leader_id, lease_expires_at, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(cluster_name) DO UPDATE SET
                    leader_id=excluded.leader_id,
                    lease_expires_at=excluded.lease_expires_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (cluster_name, node_id, lease_expires_at, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
        return {
            "cluster_name": cluster_name,
            "leader_id": node_id,
            "lease_expires_at": lease_expires_at,
            "metadata": metadata or {},
            "updated_at": now,
            "is_expired": False,
            "acquired": True,
        }

    def renew_leadership(self, cluster_name: str, node_id: str, *, lease_seconds: int = 30) -> dict[str, Any]:
        status = self.leader_status(cluster_name)
        if status is None:
            raise ValueError(f"no leader lease found for cluster '{cluster_name}'")
        if str(status["leader_id"]) != node_id:
            raise ValueError(f"node '{node_id}' is not the current leader for cluster '{cluster_name}'")
        return self.acquire_leadership(cluster_name, node_id, lease_seconds=lease_seconds, metadata=dict(status.get("metadata") or {}))

    def release_leadership(self, cluster_name: str, node_id: str) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock, conn:
            current = conn.execute(
                "SELECT leader_id FROM cluster_leases WHERE cluster_name=?",
                (cluster_name,),
            ).fetchone()
            if current is None or str(current[0]) != node_id:
                return {"cluster_name": cluster_name, "leader_id": node_id, "released": False}
            conn.execute("DELETE FROM cluster_leases WHERE cluster_name=?", (cluster_name,))
        return {"cluster_name": cluster_name, "leader_id": node_id, "released": True}

    def leader_status(self, cluster_name: str | None = None) -> dict[str, Any] | list[dict[str, Any]] | None:
        query = """
            SELECT cluster_name, leader_id, lease_expires_at, metadata_json, updated_at
            FROM cluster_leases
        """
        params: tuple[Any, ...] = ()
        if cluster_name:
            query += " WHERE cluster_name=?"
            params = (cluster_name,)
        query += " ORDER BY cluster_name"
        with self._lock:
            rows = self._ensure_connection().execute(query, params).fetchall()
        leases = [
            LeaderLease(
                cluster_name=row[0],
                leader_id=row[1],
                lease_expires_at=float(row[2]),
                metadata=json.loads(row[3]),
                updated_at=float(row[4]),
            ).to_dict()
            for row in rows
        ]
        if cluster_name:
            return leases[0] if leases else None
        return leases

    def create_rollout(
        self,
        deployment_name: str,
        spec: dict[str, Any],
        *,
        strategy: str = "rolling",
        metadata: dict[str, Any] | None = None,
        auto_promote: bool = True,
    ) -> dict[str, Any]:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM deployments WHERE deployment_name=?",
                (deployment_name,),
            ).fetchone()
            revision = int(row[0]) + 1 if row is not None else 1
            has_active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM deployments WHERE deployment_name=? AND active=1",
                    (deployment_name,),
                ).fetchone()[0]
            )
            normalized_strategy = str(strategy or "rolling")
            if auto_promote and has_active == 0:
                status = "active"
            elif normalized_strategy == "canary":
                status = "canary"
            elif normalized_strategy == "blue_green":
                status = "staged"
            else:
                status = "pending"
            active = 1 if status == "active" else 0
            conn.execute(
                """
                INSERT INTO deployments(deployment_name, revision, spec_json, strategy, status, active, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deployment_name,
                    revision,
                    json.dumps(spec, ensure_ascii=False),
                    strategy,
                    status,
                    active,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_revision(deployment_name, revision) or {"deployment_name": deployment_name, "revision": revision}

    def get_revision(self, deployment_name: str, revision: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT deployment_name, revision, spec_json, strategy, status, active, metadata_json, created_at, updated_at
                FROM deployments
                WHERE deployment_name=? AND revision=?
                """,
                (deployment_name, revision),
            ).fetchone()
        if row is None:
            return None
        revision_record = DeploymentRevision(
            deployment_name=row[0],
            revision=int(row[1]),
            spec=json.loads(row[2]),
            strategy=row[3],
            status=row[4],
            active=bool(row[5]),
            metadata=json.loads(row[6]),
            created_at=float(row[7]),
            updated_at=float(row[8]),
        )
        return revision_record.to_dict()

    def promote_revision(self, deployment_name: str, revision: int) -> dict[str, Any]:
        target = self.get_revision(deployment_name, revision)
        if target is None:
            raise ValueError(f"deployment '{deployment_name}' revision '{revision}' not found")
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE deployments
                SET active=0, status=CASE WHEN active=1 THEN 'superseded' ELSE status END, updated_at=?
                WHERE deployment_name=?
                """,
                (now, deployment_name),
            )
            conn.execute(
                """
                UPDATE deployments
                SET active=1, status='active', updated_at=?
                WHERE deployment_name=? AND revision=?
                """,
                (now, deployment_name, revision),
            )
        return self.deployment_status(deployment_name)

    def rollback(self, deployment_name: str, target_revision: int | None = None) -> dict[str, Any]:
        status = self.deployment_status(deployment_name)
        revisions = list(status.get("revisions", []))
        if not revisions:
            raise ValueError(f"deployment '{deployment_name}' has no revisions")
        current = next((revision for revision in revisions if revision.get("active")), None)
        if target_revision is None:
            if current is None:
                raise ValueError(f"deployment '{deployment_name}' has no active revision")
            candidates = [revision for revision in revisions if int(revision["revision"]) < int(current["revision"])]
            if not candidates:
                raise ValueError(f"deployment '{deployment_name}' has no previous revision to roll back to")
            target_revision = int(candidates[0]["revision"])
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE deployments
                SET active=0, status=CASE WHEN active=1 THEN 'rolled_back' ELSE status END, updated_at=?
                WHERE deployment_name=?
                """,
                (now, deployment_name),
            )
            conn.execute(
                """
                UPDATE deployments
                SET active=1, status='active', updated_at=?
                WHERE deployment_name=? AND revision=?
                """,
                (now, deployment_name, target_revision),
            )
        payload = self.deployment_status(deployment_name)
        payload["rolled_back_to"] = target_revision
        return payload

    def deployment_status(self, deployment_name: str | None = None) -> dict[str, Any]:
        query = """
            SELECT deployment_name, revision, spec_json, strategy, status, active, metadata_json, created_at, updated_at
            FROM deployments
        """
        params: tuple[Any, ...] = ()
        if deployment_name:
            query += " WHERE deployment_name=?"
            params = (deployment_name,)
        query += " ORDER BY deployment_name, revision DESC"
        with self._lock:
            rows = self._ensure_connection().execute(query, params).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            record = DeploymentRevision(
                deployment_name=row[0],
                revision=int(row[1]),
                spec=json.loads(row[2]),
                strategy=row[3],
                status=row[4],
                active=bool(row[5]),
                metadata=json.loads(row[6]),
                created_at=float(row[7]),
                updated_at=float(row[8]),
            ).to_dict()
            record["health"] = self.health_summary(str(row[0]), int(row[1]))
            grouped.setdefault(str(row[0]), []).append(record)
        if deployment_name:
            revisions = grouped.get(deployment_name, [])
            return {
                "deployment_name": deployment_name,
                "revision_count": len(revisions),
                "active_revision": next((item["revision"] for item in revisions if item["active"]), None),
                "revisions": revisions,
            }
        return {
            "deployment_count": len(grouped),
            "deployments": [
                {
                    "deployment_name": name,
                    "revision_count": len(revisions),
                    "active_revision": next((item["revision"] for item in revisions if item["active"]), None),
                    "revisions": revisions,
                }
                for name, revisions in grouped.items()
            ],
        }

    def record_health(
        self,
        deployment_name: str,
        revision: int,
        target_name: str,
        *,
        status: str,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checked_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO deployment_health(deployment_name, revision, target_name, status, metrics_json, checked_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(deployment_name, revision, target_name) DO UPDATE SET
                    status=excluded.status,
                    metrics_json=excluded.metrics_json,
                    checked_at=excluded.checked_at
                """,
                (deployment_name, int(revision), target_name, status, json.dumps(metrics or {}, ensure_ascii=False), checked_at),
            )
        return {
            "deployment_name": deployment_name,
            "revision": int(revision),
            "target_name": target_name,
            "status": status,
            "metrics": metrics or {},
            "checked_at": checked_at,
        }

    def list_health(self, deployment_name: str | None = None, revision: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = """
            SELECT deployment_name, revision, target_name, status, metrics_json, checked_at
            FROM deployment_health
        """
        clauses: list[str] = []
        params: list[Any] = []
        if deployment_name:
            clauses.append("deployment_name=?")
            params.append(deployment_name)
        if revision is not None:
            clauses.append("revision=?")
            params.append(int(revision))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY checked_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "deployment_name": row[0],
                "revision": int(row[1]),
                "target_name": row[2],
                "status": row[3],
                "metrics": json.loads(row[4]),
                "checked_at": row[5],
            }
            for row in rows
        ]

    def health_summary(self, deployment_name: str, revision: int) -> dict[str, Any]:
        rows = self.list_health(deployment_name, revision, limit=200)
        if not rows:
            return {
                "deployment_name": deployment_name,
                "revision": revision,
                "target_count": 0,
                "healthy_count": 0,
                "unhealthy_count": 0,
                "average_error_rate": None,
                "targets": [],
            }
        error_rates = [float(row["metrics"].get("error_rate", 0.0)) for row in rows if isinstance(row.get("metrics"), dict) and row["metrics"].get("error_rate") is not None]
        healthy_count = sum(1 for row in rows if row["status"] == "healthy")
        unhealthy_count = sum(1 for row in rows if row["status"] != "healthy")
        return {
            "deployment_name": deployment_name,
            "revision": revision,
            "target_count": len(rows),
            "healthy_count": healthy_count,
            "unhealthy_count": unhealthy_count,
            "average_error_rate": (sum(error_rates) / len(error_rates)) if error_rates else None,
            "targets": rows,
        }

    def evaluate_rollout(
        self,
        deployment_name: str,
        revision: int,
        *,
        minimum_healthy_targets: int = 1,
        max_error_rate: float = 0.2,
    ) -> dict[str, Any]:
        revision_payload = self.get_revision(deployment_name, revision)
        if revision_payload is None:
            raise ValueError(f"deployment '{deployment_name}' revision '{revision}' not found")
        strategy = str(revision_payload.get("strategy") or "rolling")
        summary = self.health_summary(deployment_name, revision)
        average_error_rate = summary.get("average_error_rate")
        healthy_enough = int(summary.get("healthy_count") or 0) >= max(1, int(minimum_healthy_targets))
        error_budget_ok = average_error_rate is None or float(average_error_rate) <= float(max_error_rate)
        any_unhealthy = int(summary.get("unhealthy_count") or 0) > 0 and not healthy_enough

        action = "pending"
        if strategy in {"canary", "blue_green"} and healthy_enough and error_budget_ok:
            payload = self.promote_revision(deployment_name, revision)
            action = "promote"
        elif strategy in {"canary", "rolling"} and any_unhealthy:
            payload = self.rollback(deployment_name)
            action = "rollback"
        elif strategy == "blue_green" and any_unhealthy:
            payload = self.deployment_status(deployment_name)
            action = "hold"
        else:
            payload = self.deployment_status(deployment_name)

        payload["evaluation"] = {
            "deployment_name": deployment_name,
            "revision": revision,
            "strategy": strategy,
            "action": action,
            "minimum_healthy_targets": minimum_healthy_targets,
            "max_error_rate": max_error_rate,
            "health": summary,
        }
        return payload

    def register_playbook(
        self,
        playbook_name: str,
        snapshot_path: str,
        *,
        steps: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        playbook_steps = steps or [{"action": "resume_snapshot", "snapshot_path": snapshot_path}]
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO recovery_playbooks(playbook_name, snapshot_path, steps_json, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(playbook_name) DO UPDATE SET
                    snapshot_path=excluded.snapshot_path,
                    steps_json=excluded.steps_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    playbook_name,
                    snapshot_path,
                    json.dumps(playbook_steps, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_playbook(playbook_name) or {"playbook_name": playbook_name}

    def get_playbook(self, playbook_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT playbook_name, snapshot_path, steps_json, metadata_json, created_at, updated_at
                FROM recovery_playbooks
                WHERE playbook_name=?
                """,
                (playbook_name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "playbook_name": row[0],
            "snapshot_path": row[1],
            "steps": json.loads(row[2]),
            "metadata": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }

    def list_playbooks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT playbook_name, snapshot_path, steps_json, metadata_json, created_at, updated_at
                FROM recovery_playbooks
                ORDER BY playbook_name
                """
            ).fetchall()
        return [
            {
                "playbook_name": row[0],
                "snapshot_path": row[1],
                "steps": json.loads(row[2]),
                "metadata": json.loads(row[3]),
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    def run_playbook(self, playbook_name: str, executor: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        playbook = self.get_playbook(playbook_name)
        if playbook is None:
            raise ValueError(f"recovery playbook '{playbook_name}' not found")

        run_id = uuid.uuid4().hex[:16]
        started_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO recovery_runs(run_id, playbook_name, status, result_json, created_at, completed_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (run_id, playbook_name, "running", None, started_at, None),
            )

        step_results: list[dict[str, Any]] = []
        status = "ok"
        error_text: str | None = None
        try:
            for step in list(playbook.get("steps") or []):
                action = str(step.get("action") or "").strip()
                match action:
                    case "resume_snapshot":
                        snapshot_path = str(step.get("snapshot_path") or playbook["snapshot_path"])
                        result = executor({"action": action, "snapshot_path": snapshot_path})
                    case "promote_revision":
                        result = self.promote_revision(str(step["deployment_name"]), int(step["revision"]))
                    case "rollback":
                        result = self.rollback(str(step["deployment_name"]), int(step["target_revision"]) if step.get("target_revision") is not None else None)
                    case "acquire_leadership":
                        result = self.acquire_leadership(
                            str(step["cluster_name"]),
                            str(step["node_id"]),
                            lease_seconds=int(step.get("lease_seconds") or 30),
                            metadata=dict(step.get("metadata") or {}),
                        )
                    case _:
                        raise ValueError(f"unsupported recovery action '{action}'")
                step_results.append({"step": step, "result": result})
        except Exception as exc:
            status = "error"
            error_text = str(exc)

        completed_at = time.time()
        payload = {
            "run_id": run_id,
            "playbook_name": playbook_name,
            "status": status,
            "step_results": step_results,
            "error": error_text,
            "started_at": started_at,
            "completed_at": completed_at,
        }
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE recovery_runs
                SET status=?, result_json=?, completed_at=?
                WHERE run_id=?
                """,
                (status, json.dumps(payload, ensure_ascii=False), completed_at, run_id),
            )
        if error_text is not None:
            raise RuntimeError(error_text)
        return payload

    def list_recovery_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT run_id, playbook_name, status, result_json, created_at, completed_at
                FROM recovery_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "playbook_name": row[1],
                "status": row[2],
                "result": json.loads(row[3]) if row[3] else None,
                "created_at": row[4],
                "completed_at": row[5],
            }
            for row in rows
        ]

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock:
            deployment_count = int(conn.execute("SELECT COUNT(DISTINCT deployment_name) FROM deployments").fetchone()[0])
            playbook_count = int(conn.execute("SELECT COUNT(*) FROM recovery_playbooks").fetchone()[0])
            run_count = int(conn.execute("SELECT COUNT(*) FROM recovery_runs").fetchone()[0])
        leaders = self.leader_status()
        return {
            "db_path": str(self.db_path),
            "leader_count": len(leaders),
            "deployment_count": deployment_count,
            "playbook_count": playbook_count,
            "run_count": run_count,
            "leaders": leaders,
            "deployments": self.deployment_status().get("deployments", [])[: max(1, limit)],
            "playbooks": self.list_playbooks()[: max(1, limit)],
            "recovery_runs": self.list_recovery_runs(limit=limit),
        }
