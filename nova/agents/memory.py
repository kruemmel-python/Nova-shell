from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

MAX_MEMORY_TEXT_CHARS = 8192
MAX_MEMORY_SEARCH_TEXT_CHARS = 4096
MAX_MEMORY_SEARCH_METADATA_CHARS = 4096
MAX_MEMORY_METADATA_DEPTH = 4
MAX_MEMORY_METADATA_ITEMS = 16
MAX_MEMORY_METADATA_STRING_CHARS = 1024


def _truncate_text(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    overflow = len(value) - limit
    return f"{value[:limit].rstrip()}... [truncated {overflow} chars]"


def _sanitize_metadata(value: Any, *, depth: int = MAX_MEMORY_METADATA_DEPTH) -> Any:
    if depth <= 0:
        return "..."
    match value:
        case None | bool() | int() | float():
            return value
        case str():
            return _truncate_text(value, limit=MAX_MEMORY_METADATA_STRING_CHARS)
        case list() | tuple():
            items = [_sanitize_metadata(item, depth=depth - 1) for item in list(value)[:MAX_MEMORY_METADATA_ITEMS]]
            overflow = len(value) - len(items)
            if overflow > 0:
                items.append(f"... ({overflow} more)")
            return items
        case dict():
            result: dict[str, Any] = {}
            items = list(value.items())
            for key, item in items[:MAX_MEMORY_METADATA_ITEMS]:
                result[str(key)] = _sanitize_metadata(item, depth=depth - 1)
            overflow = len(items) - len(result)
            if overflow > 0:
                result["..."] = f"{overflow} more"
            return result
        case _:
            return _truncate_text(str(value), limit=MAX_MEMORY_METADATA_STRING_CHARS)


class DistributedMemoryStore:
    """Shard-aware persistent memory store with simple semantic search."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "agent-memory.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    shard TEXT NOT NULL,
                    text_value TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def append(self, scope: str, text_value: str, *, shard: str = "0", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        normalized_text = _truncate_text(str(text_value), limit=MAX_MEMORY_TEXT_CHARS)
        normalized_metadata = _sanitize_metadata(metadata or {})
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO memory_records(scope, shard, text_value, metadata_json, created_at) VALUES(?, ?, ?, ?, ?)",
                (scope, shard, normalized_text, json.dumps(normalized_metadata, ensure_ascii=False), now),
            )
        return {"record_id": int(cursor.lastrowid), "scope": scope, "shard": shard, "text": normalized_text, "metadata": normalized_metadata, "created_at": now}

    def search(self, scope: str, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        tokens = {token.lower() for token in query.split() if token.strip()}
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT record_id, scope, shard, substr(text_value, 1, ?), substr(metadata_json, 1, ?), created_at
                FROM memory_records
                WHERE scope LIKE ?
                ORDER BY record_id DESC
                LIMIT 200
                """,
                (MAX_MEMORY_SEARCH_TEXT_CHARS, MAX_MEMORY_SEARCH_METADATA_CHARS, f"{scope}%"),
            )
        scored: list[tuple[int, dict[str, Any]]] = []
        while True:
            rows = cursor.fetchmany(64)
            if not rows:
                break
            for row in rows:
                text = str(row[3])
                record_tokens = {token.lower() for token in text.split() if token.strip()}
                score = len(tokens.intersection(record_tokens))
                metadata: dict[str, Any]
                try:
                    decoded = json.loads(row[4])
                    metadata = decoded if isinstance(decoded, dict) else {"value": decoded}
                except Exception:
                    metadata = {}
                scored.append(
                    (
                        score,
                        {
                            "record_id": int(row[0]),
                            "scope": row[1],
                            "shard": row[2],
                            "text": text,
                            "metadata": metadata,
                            "created_at": row[5],
                        },
                    )
                )
        scored.sort(key=lambda item: (item[0], item[1]["record_id"]), reverse=True)
        return [record for _, record in scored[:top_k]]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            count = int(self._conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0])
            scopes = [row[0] for row in self._conn.execute("SELECT DISTINCT scope FROM memory_records ORDER BY scope").fetchall()]
        return {"record_count": count, "scopes": scopes}
