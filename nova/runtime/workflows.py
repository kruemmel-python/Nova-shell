from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class PersistentWorkflowStore:
    """Durable flow execution history for replay and recovery."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "runtime-workflows.db"
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
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    flow_name TEXT NOT NULL,
                    trigger_event TEXT,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def record_run(
        self,
        flow_name: str,
        *,
        trigger_event: str | None,
        status: str,
        record: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        created_at = time.time()
        run_id = run_id or uuid.uuid4().hex[:16]
        payload = {
            "run_id": run_id,
            "flow_name": flow_name,
            "trigger_event": trigger_event,
            "status": status,
            "record": record,
            "metadata": metadata or {},
            "created_at": created_at,
        }
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO workflow_runs(run_id, flow_name, trigger_event, status, record_json, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    flow_name,
                    trigger_event,
                    status,
                    json.dumps(record, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at,
                ),
            )
        return payload

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT run_id, flow_name, trigger_event, status, record_json, metadata_json, created_at
                FROM workflow_runs
                WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "flow_name": row[1],
            "trigger_event": row[2],
            "status": row[3],
            "record": json.loads(row[4]),
            "metadata": json.loads(row[5]),
            "created_at": row[6],
        }

    def list_runs(self, *, flow_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = """
            SELECT run_id, flow_name, trigger_event, status, record_json, metadata_json, created_at
            FROM workflow_runs
        """
        params: list[Any] = []
        if flow_name:
            query += " WHERE flow_name=?"
            params.append(flow_name)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "run_id": row[0],
                "flow_name": row[1],
                "trigger_event": row[2],
                "status": row[3],
                "record": json.loads(row[4]),
                "metadata": json.loads(row[5]),
                "created_at": row[6],
            }
            for row in rows
        ]

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        with self._lock:
            conn = self._ensure_connection()
            run_count = int(conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0])
        return {
            "db_path": str(self.db_path),
            "run_count": run_count,
            "runs": self.list_runs(limit=limit),
        }
