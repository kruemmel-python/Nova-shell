from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

MAX_EVAL_OUTPUT_CHARS = 8192
MAX_EVAL_LIST_OUTPUT_CHARS = 4096
MAX_EVAL_METADATA_DEPTH = 4
MAX_EVAL_METADATA_ITEMS = 16
MAX_EVAL_METADATA_STRING_CHARS = 1024


def _truncate_text(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    overflow = len(value) - limit
    return f"{value[:limit].rstrip()}... [truncated {overflow} chars]"


def _sanitize_metadata(value: Any, *, depth: int = MAX_EVAL_METADATA_DEPTH) -> Any:
    if depth <= 0:
        return "..."
    match value:
        case None | bool() | int() | float():
            return value
        case str():
            return _truncate_text(value, limit=MAX_EVAL_METADATA_STRING_CHARS)
        case list() | tuple():
            items = [_sanitize_metadata(item, depth=depth - 1) for item in list(value)[:MAX_EVAL_METADATA_ITEMS]]
            overflow = len(value) - len(items)
            if overflow > 0:
                items.append(f"... ({overflow} more)")
            return items
        case dict():
            result: dict[str, Any] = {}
            items = list(value.items())
            for key, item in items[:MAX_EVAL_METADATA_ITEMS]:
                result[str(key)] = _sanitize_metadata(item, depth=depth - 1)
            overflow = len(items) - len(result)
            if overflow > 0:
                result["..."] = f"{overflow} more"
            return result
        case _:
            return _truncate_text(str(value), limit=MAX_EVAL_METADATA_STRING_CHARS)


class AgentEvalStore:
    """Persistent evaluation store for agent executions."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "agent-evals.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_records (
                    eval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    score REAL NOT NULL,
                    output_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def record(
        self,
        agent_name: str,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        output_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_output = _truncate_text(str(output_text), limit=MAX_EVAL_OUTPUT_CHARS)
        normalized_metadata = _sanitize_metadata(metadata or {})
        score = self._score(normalized_output)
        verdict = "pass" if score >= 0.5 else "review"
        now = time.time()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO eval_records(agent_name, provider, model, prompt_version, verdict, score, output_text, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (agent_name, provider, model, prompt_version, verdict, score, normalized_output, json.dumps(normalized_metadata, ensure_ascii=False), now),
            )
        return {
            "eval_id": int(cursor.lastrowid),
            "agent_name": agent_name,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "verdict": verdict,
            "score": score,
            "created_at": now,
        }

    def list_recent(self, agent_name: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
        query = """
            SELECT eval_id, agent_name, provider, model, prompt_version, verdict, score, substr(output_text, 1, ?), metadata_json, created_at
            FROM eval_records
        """
        params: tuple[Any, ...] = (MAX_EVAL_LIST_OUTPUT_CHARS,)
        if agent_name:
            query += " WHERE agent_name=?"
            params = (*params, agent_name)
        query += " ORDER BY eval_id DESC LIMIT ?"
        params = (*params, int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "eval_id": int(row[0]),
                "agent_name": row[1],
                "provider": row[2],
                "model": row[3],
                "prompt_version": row[4],
                "verdict": row[5],
                "score": float(row[6]),
                "output": row[7],
                "metadata": json.loads(row[8]),
                "created_at": row[9],
            }
            for row in rows
        ]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            count = int(self._conn.execute("SELECT COUNT(*) FROM eval_records").fetchone()[0])
        return {"eval_count": count, "recent": self.list_recent(limit=10)}

    def _score(self, output_text: str) -> float:
        compact = output_text.strip()
        if not compact:
            return 0.0
        return min(1.0, 0.3 + min(len(compact), 200) / 200.0)
