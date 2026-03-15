from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class ReplicatedLogStore:
    """Persistent replication queue and peer registry for event/state/workflow records."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "runtime-replication.db"
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
                CREATE TABLE IF NOT EXISTS replica_peers (
                    peer_name TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    auth_token TEXT,
                    tls_profile TEXT,
                    enabled INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL,
                    last_sync_at REAL,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replicated_records (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    record_type TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    source_node TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
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

    def register_peer(
        self,
        peer_name: str,
        endpoint: str,
        *,
        auth_token: str | None = None,
        tls_profile: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO replica_peers(peer_name, endpoint, auth_token, tls_profile, enabled, metadata_json, last_sequence, last_sync_at, last_error)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_name) DO UPDATE SET
                    endpoint=excluded.endpoint,
                    auth_token=excluded.auth_token,
                    tls_profile=excluded.tls_profile,
                    enabled=excluded.enabled,
                    metadata_json=excluded.metadata_json
                """,
                (
                    peer_name,
                    endpoint,
                    auth_token,
                    tls_profile,
                    int(bool(enabled)),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    0,
                    None,
                    None,
                ),
            )
        return next(peer for peer in self.list_peers() if peer["peer_name"] == peer_name)

    def list_peers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT peer_name, endpoint, auth_token, tls_profile, enabled, metadata_json, last_sequence, last_sync_at, last_error
                FROM replica_peers
                ORDER BY peer_name
                """
            ).fetchall()
        return [
            {
                "peer_name": row[0],
                "endpoint": row[1],
                "auth_token": row[2],
                "tls_profile": row[3],
                "enabled": bool(row[4]),
                "metadata": json.loads(row[5]),
                "last_sequence": row[6],
                "last_sync_at": row[7],
                "last_error": row[8],
            }
            for row in rows
        ]

    def append_record(
        self,
        record_type: str,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        namespace: str,
        source_node: str,
        metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        record_id = record_id or uuid.uuid4().hex[:16]
        created_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO replicated_records(record_id, record_type, tenant_id, namespace, source_node, payload_json, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    record_type,
                    tenant_id,
                    namespace,
                    source_node,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            if cursor.rowcount:
                sequence = int(cursor.lastrowid)
                inserted = True
            else:
                row = conn.execute("SELECT sequence FROM replicated_records WHERE record_id=?", (record_id,)).fetchone()
                sequence = int(row[0]) if row is not None else 0
                inserted = False
        return {
            "sequence": sequence,
            "inserted": inserted,
            "record_id": record_id,
            "record_type": record_type,
            "tenant_id": tenant_id,
            "namespace": namespace,
            "source_node": source_node,
            "payload": payload,
            "metadata": metadata or {},
            "created_at": created_at,
        }

    def list_records(
        self,
        *,
        since_sequence: int = 0,
        record_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT sequence, record_id, record_type, tenant_id, namespace, source_node, payload_json, metadata_json, created_at
            FROM replicated_records
            WHERE sequence > ?
        """
        params: list[Any] = [max(0, int(since_sequence))]
        if record_type:
            query += " AND record_type=?"
            params.append(record_type)
        query += " ORDER BY sequence ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        return [
            {
                "sequence": row[0],
                "record_id": row[1],
                "record_type": row[2],
                "tenant_id": row[3],
                "namespace": row[4],
                "source_node": row[5],
                "payload": json.loads(row[6]),
                "metadata": json.loads(row[7]),
                "created_at": row[8],
            }
            for row in rows
        ]

    def update_peer_status(self, peer_name: str, *, last_sequence: int, last_error: str | None = None) -> dict[str, Any] | None:
        conn = self._ensure_connection()
        now = time.time()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE replica_peers
                SET last_sequence=?, last_sync_at=?, last_error=?
                WHERE peer_name=?
                """,
                (last_sequence, now, last_error, peer_name),
            )
        for peer in self.list_peers():
            if peer["peer_name"] == peer_name:
                return peer
        return None

    def sync(
        self,
        sender: Callable[[dict[str, Any], dict[str, Any]], None],
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        peers = [peer for peer in self.list_peers() if peer.get("enabled")]
        synced: list[dict[str, Any]] = []
        for peer in peers:
            last_sequence = int(peer.get("last_sequence") or 0)
            records = self.list_records(since_sequence=last_sequence, limit=limit)
            if not records:
                continue
            highest = last_sequence
            error: str | None = None
            try:
                for record in records:
                    sender(peer, record)
                    highest = max(highest, int(record["sequence"]))
            except Exception as exc:
                error = str(exc)
            self.update_peer_status(peer["peer_name"], last_sequence=highest, last_error=error)
            synced.append(
                {
                    "peer_name": peer["peer_name"],
                    "records_attempted": len(records),
                    "last_sequence": highest,
                    "error": error,
                }
            )
        return {"peers": synced, "peer_count": len(peers)}

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        with self._lock:
            conn = self._ensure_connection()
            record_count = int(conn.execute("SELECT COUNT(*) FROM replicated_records").fetchone()[0])
            peer_count = int(conn.execute("SELECT COUNT(*) FROM replica_peers").fetchone()[0])
        return {
            "db_path": str(self.db_path),
            "record_count": record_count,
            "peer_count": peer_count,
            "peers": self.list_peers(),
            "records": self.list_records(limit=limit),
        }
