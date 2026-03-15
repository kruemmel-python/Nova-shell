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
class StateRecord:
    tenant_id: str
    namespace: str
    key: str
    value: Any
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "version": self.version,
            "metadata": self.metadata,
            "updated_at": self.updated_at,
        }


class PersistentStateStore:
    """SQLite-backed state store with append-only change log."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "runtime-state.db"
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
                CREATE TABLE IF NOT EXISTS durable_state (
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value_json TEXT,
                    version INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (tenant_id, namespace, state_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value_json TEXT,
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

    def set_state(
        self,
        tenant_id: str,
        namespace: str,
        key: str,
        value: Any,
        *,
        metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        record_id = record_id or uuid.uuid4().hex[:16]
        conn = self._ensure_connection()
        with self._lock, conn:
            row = conn.execute(
                """
                SELECT version
                FROM durable_state
                WHERE tenant_id=? AND namespace=? AND state_key=?
                """,
                (tenant_id, namespace, key),
            ).fetchone()
            version = int(row[0]) + 1 if row is not None else 1
            payload_json = json.dumps(value, ensure_ascii=False) if value is not None else None
            metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO durable_state(tenant_id, namespace, state_key, value_json, version, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, namespace, state_key) DO UPDATE SET
                    value_json=excluded.value_json,
                    version=excluded.version,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (tenant_id, namespace, key, payload_json, version, metadata_json, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO state_log(record_id, tenant_id, namespace, state_key, value_json, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, tenant_id, namespace, key, payload_json, metadata_json, now),
            )
        return {
            "record_id": record_id,
            "tenant_id": tenant_id,
            "namespace": namespace,
            "key": key,
            "value": value,
            "version": version,
            "metadata": metadata or {},
            "updated_at": now,
        }

    def get_state(self, tenant_id: str, namespace: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT tenant_id, namespace, state_key, value_json, version, metadata_json, updated_at
                FROM durable_state
                WHERE tenant_id=? AND namespace=? AND state_key=?
                """,
                (tenant_id, namespace, key),
            ).fetchone()
        if row is None:
            return None
        return {
            "tenant_id": row[0],
            "namespace": row[1],
            "key": row[2],
            "value": json.loads(row[3]) if row[3] else None,
            "version": row[4],
            "metadata": json.loads(row[5]),
            "updated_at": row[6],
        }

    def list_state(
        self,
        *,
        tenant_id: str | None = None,
        namespace: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT tenant_id, namespace, state_key, value_json, version, metadata_json, updated_at
            FROM durable_state
        """
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if namespace:
            clauses.append("namespace=?")
            params.append(namespace)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY tenant_id, namespace, state_key LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "tenant_id": row[0],
                "namespace": row[1],
                "key": row[2],
                "value": json.loads(row[3]) if row[3] else None,
                "version": row[4],
                "metadata": json.loads(row[5]),
                "updated_at": row[6],
            }
            for row in rows
        ]

    def replay(
        self,
        *,
        since_sequence: int = 0,
        tenant_id: str | None = None,
        namespace: str | None = None,
        key: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT sequence, record_id, tenant_id, namespace, state_key, value_json, metadata_json, created_at
            FROM state_log
            WHERE sequence > ?
        """
        params: list[Any] = [max(0, int(since_sequence))]
        if tenant_id:
            query += " AND tenant_id=?"
            params.append(tenant_id)
        if namespace:
            query += " AND namespace=?"
            params.append(namespace)
        if key:
            query += " AND state_key=?"
            params.append(key)
        query += " ORDER BY sequence ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "sequence": row[0],
                "record_id": row[1],
                "tenant_id": row[2],
                "namespace": row[3],
                "key": row[4],
                "value": json.loads(row[5]) if row[5] else None,
                "metadata": json.loads(row[6]),
                "created_at": row[7],
            }
            for row in rows
        ]

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        with self._lock:
            conn = self._ensure_connection()
            state_count = int(conn.execute("SELECT COUNT(*) FROM durable_state").fetchone()[0])
            change_count = int(conn.execute("SELECT COUNT(*) FROM state_log").fetchone()[0])
        return {
            "db_path": str(self.db_path),
            "state_count": state_count,
            "change_count": change_count,
            "states": self.list_state(limit=limit),
            "changes": self.replay(limit=limit),
        }
