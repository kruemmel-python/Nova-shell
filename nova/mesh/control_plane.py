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
class MeshTaskRecord:
    task_id: str
    capability: str
    worker_id: str
    task: dict[str, Any]
    status: str = "running"
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "worker_id": self.worker_id,
            "task": self.task,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PersistentMeshControlPlane:
    """SQLite-backed worker registry and task history for Nova mesh scheduling."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "mesh-control-plane.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mesh_workers (
                    worker_id TEXT PRIMARY KEY,
                    capabilities TEXT NOT NULL,
                    endpoint TEXT,
                    labels TEXT NOT NULL,
                    last_heartbeat REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mesh_tasks (
                    task_id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def register_worker(self, worker_id: str, capabilities: set[str], endpoint: str | None, labels: dict[str, str]) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO mesh_workers(worker_id, capabilities, endpoint, labels, last_heartbeat)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    capabilities=excluded.capabilities,
                    endpoint=excluded.endpoint,
                    labels=excluded.labels,
                    last_heartbeat=excluded.last_heartbeat
                """,
                (worker_id, json.dumps(sorted(capabilities)), endpoint, json.dumps(labels, ensure_ascii=False), now),
            )

    def heartbeat(self, worker_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE mesh_workers SET last_heartbeat=? WHERE worker_id=?", (time.time(), worker_id))

    def start_task(self, capability: str, worker_id: str, task: dict[str, Any]) -> MeshTaskRecord:
        record = MeshTaskRecord(task_id=uuid.uuid4().hex[:12], capability=capability, worker_id=worker_id, task=task)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO mesh_tasks(task_id, capability, worker_id, task_json, status, result_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    capability,
                    worker_id,
                    json.dumps(task, ensure_ascii=False),
                    record.status,
                    None,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def finish_task(self, task_id: str, *, status: str, result: dict[str, Any] | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE mesh_tasks
                SET status=?, result_json=?, updated_at=?
                WHERE task_id=?
                """,
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None, time.time(), task_id),
            )

    def list_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT worker_id, capabilities, endpoint, labels, last_heartbeat FROM mesh_workers ORDER BY worker_id"
            ).fetchall()
        return [
            {
                "worker_id": worker_id,
                "capabilities": json.loads(capabilities),
                "endpoint": endpoint,
                "labels": json.loads(labels),
                "last_heartbeat": last_heartbeat,
            }
            for worker_id, capabilities, endpoint, labels, last_heartbeat in rows
        ]

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT task_id, capability, worker_id, task_json, status, result_json, created_at, updated_at
                FROM mesh_tasks
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [
            {
                "task_id": task_id,
                "capability": capability,
                "worker_id": worker_id,
                "task": json.loads(task_json),
                "status": status,
                "result": json.loads(result_json) if result_json else None,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            for task_id, capability, worker_id, task_json, status, result_json, created_at, updated_at in rows
        ]

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        workers = self.list_workers()
        tasks = self.list_tasks(limit=limit)
        return {
            "db_path": str(self.db_path),
            "worker_count": len(workers),
            "task_count": len(tasks),
            "workers": workers,
            "tasks": tasks,
        }
