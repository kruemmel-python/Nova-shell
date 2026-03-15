from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class QueuedTask:
    task_id: str
    queue_name: str
    kind: str
    target: str
    payload: Any = None
    priority: int = 100
    status: str = "queued"
    not_before: float = field(default_factory=time.time)
    claimed_by: str | None = None
    claimed_at: float | None = None
    attempts: int = 0
    max_attempts: int = 3
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "queue_name": self.queue_name,
            "kind": self.kind,
            "target": self.target,
            "payload": self.payload,
            "priority": self.priority,
            "status": self.status,
            "not_before": self.not_before,
            "claimed_by": self.claimed_by,
            "claimed_at": self.claimed_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "result": self.result,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class ScheduledJob:
    job_name: str
    queue_name: str
    kind: str
    target: str
    payload: Any = None
    interval_seconds: float | None = None
    once_at: float | None = None
    enabled: bool = True
    next_run_at: float | None = None
    last_enqueued_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_name": self.job_name,
            "queue_name": self.queue_name,
            "kind": self.kind,
            "target": self.target,
            "payload": self.payload,
            "interval_seconds": self.interval_seconds,
            "once_at": self.once_at,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at,
            "last_enqueued_at": self.last_enqueued_at,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class DurableEventRecord:
    sequence: int
    event_name: str
    source: str
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_name": self.event_name,
            "source": self.source,
            "payload": self.payload,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class DurableControlPlane:
    """SQLite-backed queue, scheduler, daemon, and durable event log."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "runtime-control-plane.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._open_connection()
        self._init_schema()
        self.record_daemon_state(running=False, tick_interval=0.0, tasks_processed=0, jobs_enqueued=0)

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
                CREATE TABLE IF NOT EXISTS queued_tasks (
                    task_id TEXT PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    payload_json TEXT,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    not_before REAL NOT NULL,
                    claimed_by TEXT,
                    claimed_at REAL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    result_json TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    job_name TEXT PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    payload_json TEXT,
                    interval_seconds REAL,
                    once_at REAL,
                    enabled INTEGER NOT NULL,
                    next_run_at REAL,
                    last_enqueued_at REAL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daemon_state (
                    daemon_name TEXT PRIMARY KEY,
                    running INTEGER NOT NULL,
                    tick_interval REAL NOT NULL,
                    last_tick_at REAL,
                    tasks_processed INTEGER NOT NULL,
                    jobs_enqueued INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_leases (
                    lease_name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_effects (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    completed_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_task_effects_idempotency_key ON task_effects(idempotency_key) WHERE idempotency_key IS NOT NULL")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def enqueue_task(
        self,
        *,
        kind: str,
        target: str,
        task_id: str | None = None,
        idempotency_key: str | None = None,
        queue_name: str = "default",
        payload: Any = None,
        priority: int = 100,
        not_before: float | None = None,
        max_attempts: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        if idempotency_key:
            existing = self.find_task_by_idempotency(idempotency_key)
            if existing is not None:
                return existing
        task = QueuedTask(
            task_id=task_id or uuid.uuid4().hex[:16],
            queue_name=queue_name,
            kind=kind,
            target=target,
            payload=payload,
            priority=int(priority),
            not_before=float(not_before if not_before is not None else now),
            max_attempts=max(1, int(max_attempts)),
            metadata={"idempotency_key": idempotency_key, **dict(metadata or {})},
            created_at=now,
            updated_at=now,
        )
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO queued_tasks(task_id, queue_name, kind, target, payload_json, priority, status, not_before, claimed_by, claimed_at, attempts, max_attempts, result_json, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    queue_name=excluded.queue_name,
                    kind=excluded.kind,
                    target=excluded.target,
                    payload_json=excluded.payload_json,
                    priority=excluded.priority,
                    status=excluded.status,
                    not_before=excluded.not_before,
                    max_attempts=excluded.max_attempts,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.queue_name,
                    task.kind,
                    task.target,
                    json.dumps(task.payload, ensure_ascii=False) if task.payload is not None else None,
                    task.priority,
                    task.status,
                    task.not_before,
                    None,
                    None,
                    task.attempts,
                    task.max_attempts,
                    None,
                    json.dumps(task.metadata, ensure_ascii=False),
                    task.created_at,
                    task.updated_at,
                ),
            )
        return task.to_dict()

    def find_task_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        tasks = self.list_tasks(limit=10000)
        for task in tasks:
            if str(task.get("metadata", {}).get("idempotency_key") or "") == str(idempotency_key):
                return task
        return None

    def acquire_scheduler_lease(
        self,
        owner_id: str,
        *,
        lease_name: str = "global",
        lease_seconds: int = 15,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            row = conn.execute(
                """
                SELECT owner_id, fencing_token, lease_expires_at, metadata_json, updated_at
                FROM scheduler_leases
                WHERE lease_name=?
                """,
                (lease_name,),
            ).fetchone()
            if row is None:
                fencing_token = 1
                conn.execute(
                    """
                    INSERT INTO scheduler_leases(lease_name, owner_id, fencing_token, lease_expires_at, metadata_json, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (lease_name, owner_id, fencing_token, now + max(1, lease_seconds), json.dumps(metadata or {}, ensure_ascii=False), now),
                )
            else:
                current_owner = str(row[0])
                current_token = int(row[1])
                expires_at = float(row[2])
                if expires_at >= now and current_owner != owner_id:
                    return {
                        "lease_name": lease_name,
                        "owner_id": current_owner,
                        "fencing_token": current_token,
                        "lease_expires_at": expires_at,
                        "metadata": json.loads(row[3]),
                        "updated_at": row[4],
                        "acquired": False,
                    }
                fencing_token = current_token if current_owner == owner_id and expires_at >= now else current_token + 1
                conn.execute(
                    """
                    UPDATE scheduler_leases
                    SET owner_id=?, fencing_token=?, lease_expires_at=?, metadata_json=?, updated_at=?
                    WHERE lease_name=?
                    """,
                    (owner_id, fencing_token, now + max(1, lease_seconds), json.dumps(metadata or {}, ensure_ascii=False), now, lease_name),
                )
        return self.scheduler_owner(lease_name) | {"acquired": True}

    def scheduler_owner(self, lease_name: str = "global") -> dict[str, Any]:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT lease_name, owner_id, fencing_token, lease_expires_at, metadata_json, updated_at
                FROM scheduler_leases
                WHERE lease_name=?
                """,
                (lease_name,),
            ).fetchone()
        if row is None:
            return {
                "lease_name": lease_name,
                "owner_id": None,
                "fencing_token": 0,
                "lease_expires_at": 0.0,
                "metadata": {},
                "updated_at": None,
                "expired": True,
            }
        return {
            "lease_name": row[0],
            "owner_id": row[1],
            "fencing_token": int(row[2]),
            "lease_expires_at": float(row[3]),
            "metadata": json.loads(row[4]),
            "updated_at": row[5],
            "expired": float(row[3]) < time.time(),
        }

    def recover_stale_tasks(self, *, timeout_seconds: float = 60.0, now: float | None = None) -> dict[str, Any]:
        current_time = float(now if now is not None else time.time())
        threshold = current_time - max(1.0, float(timeout_seconds))
        conn = self._ensure_connection()
        with self._lock, conn:
            rows = conn.execute(
                """
                SELECT task_id
                FROM queued_tasks
                WHERE status='running' AND claimed_at IS NOT NULL AND claimed_at <= ?
                """,
                (threshold,),
            ).fetchall()
            task_ids = [str(row[0]) for row in rows]
            for task_id in task_ids:
                conn.execute(
                    """
                    UPDATE queued_tasks
                    SET status='queued', claimed_by=NULL, claimed_at=NULL, updated_at=?
                    WHERE task_id=?
                    """,
                    (current_time, task_id),
                )
        return {"recovered": len(task_ids), "task_ids": task_ids, "threshold": threshold}

    def record_task_effect(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        completed_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO task_effects(task_id, idempotency_key, status, result_json, completed_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    idempotency_key=excluded.idempotency_key,
                    status=excluded.status,
                    result_json=excluded.result_json,
                    completed_at=excluded.completed_at
                """,
                (
                    task_id,
                    idempotency_key,
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    completed_at,
                ),
            )
        return self.get_task_effect(task_id) or {"task_id": task_id, "status": status}

    def get_task_effect(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT task_id, idempotency_key, status, result_json, completed_at
                FROM task_effects
                WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "idempotency_key": row[1],
            "status": row[2],
            "result": json.loads(row[3]) if row[3] else None,
            "completed_at": row[4],
        }

    def get_task_effect_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT task_id, idempotency_key, status, result_json, completed_at
                FROM task_effects
                WHERE idempotency_key=?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "idempotency_key": row[1],
            "status": row[2],
            "result": json.loads(row[3]) if row[3] else None,
            "completed_at": row[4],
        }

    def claim_tasks(self, worker_id: str, *, queue_name: str | None = None, limit: int = 1, now: float | None = None) -> list[dict[str, Any]]:
        claim_time = float(now if now is not None else time.time())
        conn = self._ensure_connection()
        with self._lock, conn:
            query = """
                SELECT task_id
                FROM queued_tasks
                WHERE status='queued' AND not_before <= ?
            """
            params: list[Any] = [claim_time]
            if queue_name:
                query += " AND queue_name=?"
                params.append(queue_name)
            query += " ORDER BY priority ASC, created_at ASC LIMIT ?"
            params.append(max(1, int(limit)))
            task_ids = [str(row[0]) for row in conn.execute(query, tuple(params)).fetchall()]
            for task_id in task_ids:
                conn.execute(
                    """
                    UPDATE queued_tasks
                    SET status='running', claimed_by=?, claimed_at=?, attempts=attempts+1, updated_at=?
                    WHERE task_id=?
                    """,
                    (worker_id, claim_time, claim_time, task_id),
                )
        return self.list_tasks(task_ids=task_ids)

    def complete_task(self, task_id: str, *, status: str = "ok", result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE queued_tasks
                SET status=?, result_json=?, updated_at=?
                WHERE task_id=?
                """,
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None, now, task_id),
            )
        rows = self.list_tasks(task_ids=[task_id])
        return rows[0] if rows else None

    def fail_task(self, task_id: str, *, error: str, base_backoff_seconds: float = 5.0) -> dict[str, Any] | None:
        rows = self.list_tasks(task_ids=[task_id])
        if not rows:
            return None
        task = rows[0]
        attempts = int(task.get("attempts") or 0)
        max_attempts = int(task.get("max_attempts") or 1)
        metadata = dict(task.get("metadata") or {})
        multiplier = float(metadata.get("backoff_multiplier") or 2.0)
        max_backoff = float(metadata.get("max_backoff_seconds") or 300.0)
        now = time.time()
        next_status = "queued" if attempts < max_attempts else "error"
        delay = min(max_backoff, float(base_backoff_seconds) * (multiplier ** max(0, attempts - 1)))
        not_before = now + delay if next_status == "queued" else float(task.get("not_before") or now)
        result = {"error": error, "attempts": attempts}
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE queued_tasks
                SET status=?, not_before=?, result_json=?, updated_at=?
                WHERE task_id=?
                """,
                (next_status, not_before, json.dumps(result, ensure_ascii=False), now, task_id),
            )
        rows = self.list_tasks(task_ids=[task_id])
        return rows[0] if rows else None

    def list_tasks(
        self,
        *,
        queue_name: str | None = None,
        status: str | None = None,
        task_ids: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT task_id, queue_name, kind, target, payload_json, priority, status, not_before, claimed_by, claimed_at, attempts, max_attempts, result_json, metadata_json, created_at, updated_at
            FROM queued_tasks
        """
        clauses: list[str] = []
        params: list[Any] = []
        if queue_name:
            clauses.append("queue_name=?")
            params.append(queue_name)
        if status:
            clauses.append("status=?")
            params.append(status)
        if task_ids:
            placeholders = ",".join("?" for _ in task_ids)
            clauses.append(f"task_id IN ({placeholders})")
            params.extend(task_ids)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit if task_ids is None else max(limit, len(task_ids)))))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "task_id": row[0],
                "queue_name": row[1],
                "kind": row[2],
                "target": row[3],
                "payload": json.loads(row[4]) if row[4] else None,
                "priority": row[5],
                "status": row[6],
                "not_before": row[7],
                "claimed_by": row[8],
                "claimed_at": row[9],
                "attempts": row[10],
                "max_attempts": row[11],
                "result": json.loads(row[12]) if row[12] else None,
                "metadata": json.loads(row[13]),
                "created_at": row[14],
                "updated_at": row[15],
            }
            for row in rows
        ]

    def schedule_job(
        self,
        job_name: str,
        *,
        kind: str,
        target: str,
        queue_name: str = "default",
        payload: Any = None,
        interval_seconds: float | None = None,
        once_at: float | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        next_run_at = float(once_at) if once_at is not None else (now + float(interval_seconds) if interval_seconds is not None else now)
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO scheduled_jobs(job_name, queue_name, kind, target, payload_json, interval_seconds, once_at, enabled, next_run_at, last_enqueued_at, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    queue_name=excluded.queue_name,
                    kind=excluded.kind,
                    target=excluded.target,
                    payload_json=excluded.payload_json,
                    interval_seconds=excluded.interval_seconds,
                    once_at=excluded.once_at,
                    enabled=excluded.enabled,
                    next_run_at=excluded.next_run_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    job_name,
                    queue_name,
                    kind,
                    target,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    interval_seconds,
                    once_at,
                    int(bool(enabled)),
                    next_run_at if enabled else None,
                    None,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        rows = self.list_schedules(job_name=job_name)
        return rows[0] if rows else {"job_name": job_name}

    def list_schedules(self, *, job_name: str | None = None, enabled: bool | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT job_name, queue_name, kind, target, payload_json, interval_seconds, once_at, enabled, next_run_at, last_enqueued_at, metadata_json, created_at, updated_at
            FROM scheduled_jobs
        """
        clauses: list[str] = []
        params: list[Any] = []
        if job_name:
            clauses.append("job_name=?")
            params.append(job_name)
        if enabled is not None:
            clauses.append("enabled=?")
            params.append(int(bool(enabled)))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "job_name": row[0],
                "queue_name": row[1],
                "kind": row[2],
                "target": row[3],
                "payload": json.loads(row[4]) if row[4] else None,
                "interval_seconds": row[5],
                "once_at": row[6],
                "enabled": bool(row[7]),
                "next_run_at": row[8],
                "last_enqueued_at": row[9],
                "metadata": json.loads(row[10]),
                "created_at": row[11],
                "updated_at": row[12],
            }
            for row in rows
        ]

    def scheduler_tick(
        self,
        *,
        owner_id: str,
        lease_name: str = "global",
        lease_seconds: int = 15,
        now: float | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        tick_time = float(now if now is not None else time.time())
        lease = self.acquire_scheduler_lease(owner_id, lease_name=lease_name, lease_seconds=lease_seconds, metadata={"tick_time": tick_time})
        if not bool(lease.get("acquired")):
            return {"tick_time": tick_time, "jobs_enqueued": 0, "tasks": [], "lease": lease}
        jobs = self.list_schedules(enabled=True, limit=max(1, int(limit)))
        enqueued: list[dict[str, Any]] = []
        conn = self._ensure_connection()
        for job in jobs:
            next_run_at = job.get("next_run_at")
            if next_run_at is None or float(next_run_at) > tick_time:
                continue
            fire_key = f"{job['job_name']}:{float(next_run_at):.6f}"
            task = self.enqueue_task(
                kind=str(job["kind"]),
                target=str(job["target"]),
                queue_name=str(job["queue_name"]),
                idempotency_key=fire_key,
                payload=job.get("payload"),
                priority=int(job.get("metadata", {}).get("priority") or 100),
                metadata={"scheduled_by": job["job_name"], "fencing_token": lease["fencing_token"], **dict(job.get("metadata") or {})},
            )
            enqueued.append(task)
            interval_seconds = job.get("interval_seconds")
            once_at = job.get("once_at")
            enabled = bool(job.get("enabled", True))
            next_value = None
            if interval_seconds is not None:
                next_value = tick_time + float(interval_seconds)
            elif once_at is not None:
                enabled = False
            with self._lock, conn:
                conn.execute(
                    """
                    UPDATE scheduled_jobs
                    SET enabled=?, next_run_at=?, last_enqueued_at=?, updated_at=?
                    WHERE job_name=?
                    """,
                    (int(bool(enabled)), next_value, tick_time, tick_time, job["job_name"]),
                )
        return {"tick_time": tick_time, "jobs_enqueued": len(enqueued), "tasks": enqueued, "lease": lease}

    def publish_event(self, event_name: str, *, payload: Any = None, source: str = "nova", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        created_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            cursor = conn.execute(
                """
                INSERT INTO durable_events(event_name, source, payload_json, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event_name,
                    source,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            sequence = int(cursor.lastrowid)
        return DurableEventRecord(sequence=sequence, event_name=event_name, source=source, payload=payload, metadata=dict(metadata or {}), created_at=created_at).to_dict()

    def replay_events(self, *, event_name: str | None = None, since_sequence: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        query = """
            SELECT sequence, event_name, source, payload_json, metadata_json, created_at
            FROM durable_events
            WHERE sequence > ?
        """
        params: list[Any] = [max(0, int(since_sequence))]
        if event_name:
            query += " AND event_name=?"
            params.append(event_name)
        query += " ORDER BY sequence ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "sequence": row[0],
                "event_name": row[1],
                "source": row[2],
                "payload": json.loads(row[3]) if row[3] else None,
                "metadata": json.loads(row[4]),
                "created_at": row[5],
            }
            for row in rows
        ]

    def record_daemon_state(
        self,
        *,
        running: bool,
        tick_interval: float,
        tasks_processed: int,
        jobs_enqueued: int,
        last_tick_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updated_at = time.time()
        daemon_name = "nova-runtime"
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO daemon_state(daemon_name, running, tick_interval, last_tick_at, tasks_processed, jobs_enqueued, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(daemon_name) DO UPDATE SET
                    running=excluded.running,
                    tick_interval=excluded.tick_interval,
                    last_tick_at=excluded.last_tick_at,
                    tasks_processed=excluded.tasks_processed,
                    jobs_enqueued=excluded.jobs_enqueued,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    daemon_name,
                    int(bool(running)),
                    float(tick_interval),
                    last_tick_at,
                    int(tasks_processed),
                    int(jobs_enqueued),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    updated_at,
                ),
            )
        return self.daemon_status()

    def daemon_status(self) -> dict[str, Any]:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT daemon_name, running, tick_interval, last_tick_at, tasks_processed, jobs_enqueued, metadata_json, updated_at
                FROM daemon_state
                WHERE daemon_name='nova-runtime'
                """
            ).fetchone()
        if row is None:
            return {
                "daemon_name": "nova-runtime",
                "running": False,
                "tick_interval": 0.0,
                "last_tick_at": None,
                "tasks_processed": 0,
                "jobs_enqueued": 0,
                "metadata": {},
                "updated_at": None,
            }
        return {
            "daemon_name": row[0],
            "running": bool(row[1]),
            "tick_interval": row[2],
            "last_tick_at": row[3],
            "tasks_processed": row[4],
            "jobs_enqueued": row[5],
            "metadata": json.loads(row[6]),
            "updated_at": row[7],
        }

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        with self._lock:
            conn = self._ensure_connection()
            queued_count = int(conn.execute("SELECT COUNT(*) FROM queued_tasks").fetchone()[0])
            schedule_count = int(conn.execute("SELECT COUNT(*) FROM scheduled_jobs").fetchone()[0])
            event_count = int(conn.execute("SELECT COUNT(*) FROM durable_events").fetchone()[0])
            effect_count = int(conn.execute("SELECT COUNT(*) FROM task_effects").fetchone()[0])
        return {
            "db_path": str(self.db_path),
            "queued_count": queued_count,
            "schedule_count": schedule_count,
            "event_count": event_count,
            "effect_count": effect_count,
            "daemon": self.daemon_status(),
            "scheduler": self.scheduler_owner(),
            "tasks": self.list_tasks(limit=limit),
            "schedules": self.list_schedules(limit=limit),
            "events": self.replay_events(limit=limit),
        }
