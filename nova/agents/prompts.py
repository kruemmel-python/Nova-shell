from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class PromptRegistry:
    """Persistent prompt registry with versioned prompts per agent."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "prompt-registry.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompts (
                    agent_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (agent_name, version)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_heads (
                    agent_name TEXT PRIMARY KEY,
                    active_version TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def register_agent(self, agent_name: str, prompts: dict[str, str], *, active_version: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            for version, prompt_text in prompts.items():
                self._conn.execute(
                    """
                    INSERT INTO prompts(agent_name, version, prompt_text, metadata_json, updated_at)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(agent_name, version) DO UPDATE SET
                        prompt_text=excluded.prompt_text,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (agent_name, version, prompt_text, json.dumps(metadata or {}, ensure_ascii=False), now),
                )
            if prompts:
                self._conn.execute(
                    """
                    INSERT INTO prompt_heads(agent_name, active_version, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(agent_name) DO UPDATE SET
                        active_version=excluded.active_version,
                        updated_at=excluded.updated_at
                    """,
                    (agent_name, active_version, now),
                )
        return {"agent_name": agent_name, "versions": self.list_versions(agent_name), "active_version": self.active_version(agent_name)}

    def resolve(self, agent_name: str, version: str | None = None) -> str | None:
        selected_version = version or self.active_version(agent_name)
        if selected_version is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT prompt_text FROM prompts WHERE agent_name=? AND version=?",
                (agent_name, selected_version),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def active_version(self, agent_name: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT active_version FROM prompt_heads WHERE agent_name=?", (agent_name,)).fetchone()
        return str(row[0]) if row is not None else None

    def list_versions(self, agent_name: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT version, prompt_text, metadata_json, updated_at FROM prompts WHERE agent_name=? ORDER BY version",
                (agent_name,),
            ).fetchall()
        return [
            {"version": row[0], "prompt": row[1], "metadata": json.loads(row[2]), "updated_at": row[3]}
            for row in rows
        ]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            count = int(self._conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0])
            agents = [row[0] for row in self._conn.execute("SELECT agent_name FROM prompt_heads ORDER BY agent_name").fetchall()]
        return {"prompt_count": count, "agents": {agent: self.list_versions(agent) for agent in agents}}
