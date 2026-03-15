from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class RuntimeOperations:
    """Backup, migration, failpoint and load-test utilities for Nova runtime."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path
        self.state_dir = (base_path / ".nova").resolve(strict=False)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.state_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "operations.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS migrations (
                    component TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failpoints (
                    name TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backups (
                    backup_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS load_runs (
                    run_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    iterations INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    throughput REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def register_component(self, component: str, version: str) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO migrations(component, version, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(component) DO UPDATE SET
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (component, version, now),
            )
        return {"component": component, "version": version, "updated_at": now}

    def validate_migrations(self, expected: dict[str, str] | None = None) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT component, version, updated_at FROM migrations ORDER BY component").fetchall()
        components = {str(row[0]): {"version": str(row[1]), "updated_at": row[2]} for row in rows}
        mismatches: list[dict[str, Any]] = []
        for component, version in dict(expected or {}).items():
            current = components.get(component, {}).get("version")
            if current != str(version):
                mismatches.append({"component": component, "expected": str(version), "actual": current})
        return {"ok": not mismatches, "components": components, "mismatches": mismatches}

    def set_failpoint(self, name: str, action: str = "raise", *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO failpoints(name, action, metadata_json, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    action=excluded.action,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (name, action, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
        return {"name": name, "action": action, "metadata": metadata or {}, "updated_at": now}

    def clear_failpoint(self, name: str) -> dict[str, Any]:
        with self._lock, self._conn:
            deleted = int(self._conn.execute("DELETE FROM failpoints WHERE name=?", (name,)).rowcount)
        return {"name": name, "cleared": deleted > 0}

    def list_failpoints(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT name, action, metadata_json, updated_at FROM failpoints ORDER BY name").fetchall()
        return [{"name": row[0], "action": row[1], "metadata": json.loads(row[2]), "updated_at": row[3]} for row in rows]

    def check_failpoint(self, name: str) -> None:
        with self._lock:
            row = self._conn.execute("SELECT action, metadata_json FROM failpoints WHERE name=?", (name,)).fetchone()
        if row is None:
            return
        action = str(row[0])
        metadata = json.loads(row[1])
        if action == "raise":
            raise RuntimeError(str(metadata.get("message") or f"failpoint '{name}' triggered"))
        if action == "delay":
            time.sleep(float(metadata.get("seconds") or 0.1))

    def create_backup(self, *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        backup_id = uuid.uuid4().hex[:12]
        target = self.backup_dir / backup_id
        target.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        for item in self.state_dir.iterdir():
            if item.name == "backups":
                continue
            if item.is_file() and item.suffix.lower() in {".db", ".json", ".jsonl", ".pem", ".crt", ".key"}:
                destination = target / item.name
                shutil.copy2(item, destination)
                files.append(str(destination))
        if snapshot is not None:
            snapshot_file = target / "runtime-snapshot.json"
            snapshot_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            files.append(str(snapshot_file))
        metadata = {"file_count": len(files), "files": files}
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO backups(backup_id, path, metadata_json, created_at) VALUES(?, ?, ?, ?)",
                (backup_id, str(target), json.dumps(metadata, ensure_ascii=False), time.time()),
            )
        return {"backup_id": backup_id, "path": str(target), **metadata}

    def list_backups(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT backup_id, path, metadata_json, created_at FROM backups ORDER BY created_at DESC").fetchall()
        return [{"backup_id": row[0], "path": row[1], "metadata": json.loads(row[2]), "created_at": row[3]} for row in rows]

    def restore_backup(self, backup_id: str) -> dict[str, Any]:
        backups = {item["backup_id"]: item for item in self.list_backups()}
        backup = backups.get(backup_id)
        if backup is None:
            raise ValueError(f"unknown backup '{backup_id}'")
        source = Path(str(backup["path"]))
        restored: list[str] = []
        for item in source.iterdir():
            if not item.is_file():
                continue
            destination = self.state_dir / item.name
            shutil.copy2(item, destination)
            restored.append(str(destination))
        return {"backup_id": backup_id, "restored_files": restored}

    def run_load(self, target: str, iterations: int, runner: Callable[[int], Any], *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        for index in range(iterations):
            runner(index)
        duration_ms = (time.perf_counter() - started) * 1000.0
        throughput = float(iterations) / max(duration_ms / 1000.0, 0.001)
        run_id = uuid.uuid4().hex[:12]
        payload = {
            "run_id": run_id,
            "target": target,
            "iterations": iterations,
            "duration_ms": duration_ms,
            "throughput": throughput,
            "metadata": dict(metadata or {}),
            "created_at": time.time(),
        }
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO load_runs(run_id, target, iterations, duration_ms, throughput, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, target, iterations, duration_ms, throughput, json.dumps(payload["metadata"], ensure_ascii=False), payload["created_at"]),
            )
        return payload

    def list_load_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, target, iterations, duration_ms, throughput, metadata_json, created_at FROM load_runs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "target": row[1],
                "iterations": int(row[2]),
                "duration_ms": float(row[3]),
                "throughput": float(row[4]),
                "metadata": json.loads(row[5]),
                "created_at": row[6],
            }
            for row in rows
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "backup_count": len(self.list_backups()),
            "failpoint_count": len(self.list_failpoints()),
            "load_run_count": len(self.list_load_runs()),
            "failpoints": self.list_failpoints(),
            "backups": self.list_backups()[:10],
            "load_runs": self.list_load_runs(limit=10),
        }
