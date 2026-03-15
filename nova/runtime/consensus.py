from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import uuid


@dataclass(slots=True)
class ConsensusPeer:
    peer_name: str
    endpoint: str
    auth_token: str | None = None
    tls_profile: str | None = None
    voter: bool = True
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    last_contact_at: float | None = None
    match_index: int = 0
    next_index: int = 1
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_name": self.peer_name,
            "endpoint": self.endpoint,
            "auth_token": self.auth_token,
            "tls_profile": self.tls_profile,
            "voter": self.voter,
            "active": self.active,
            "metadata": self.metadata,
            "last_contact_at": self.last_contact_at,
            "match_index": self.match_index,
            "next_index": self.next_index,
            "last_error": self.last_error,
        }


@dataclass(slots=True)
class ConsensusLogEntry:
    log_index: int
    term: int
    command_type: str
    command: dict[str, Any]
    committed: bool = False
    applied: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_index": self.log_index,
            "term": self.term,
            "command_type": self.command_type,
            "command": self.command,
            "committed": self.committed,
            "applied": self.applied,
            "created_at": self.created_at,
        }


class ControlPlaneConsensus:
    """Small persistent Raft-like consensus layer for Nova control-plane mutations."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "runtime-consensus.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._open_connection()
        self._init_schema()
        self.configure(cluster_name="nova-consensus", node_id="local")

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
                CREATE TABLE IF NOT EXISTS consensus_state (
                    state_name TEXT PRIMARY KEY,
                    cluster_name TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    current_term INTEGER NOT NULL,
                    voted_for TEXT,
                    role TEXT NOT NULL,
                    leader_id TEXT,
                    commit_index INTEGER NOT NULL,
                    last_applied INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consensus_peers (
                    peer_name TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    auth_token TEXT,
                    tls_profile TEXT,
                    voter INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    last_contact_at REAL,
                    match_index INTEGER NOT NULL,
                    next_index INTEGER NOT NULL,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consensus_log (
                    log_index INTEGER PRIMARY KEY AUTOINCREMENT,
                    term INTEGER NOT NULL,
                    command_type TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    committed INTEGER NOT NULL,
                    applied INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consensus_meta (
                    meta_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consensus_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    last_included_index INTEGER NOT NULL,
                    last_included_term INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _set_meta(self, meta_key: str, value: Any) -> None:
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO consensus_meta(meta_key, value_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(meta_key) DO UPDATE SET
                    value_json=excluded.value_json,
                    updated_at=excluded.updated_at
                """,
                (meta_key, json.dumps(value, ensure_ascii=False), time.time()),
            )

    def _get_meta(self, meta_key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._ensure_connection().execute(
                "SELECT value_json FROM consensus_meta WHERE meta_key=?",
                (meta_key,),
            ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def touch_leader_contact(self, timestamp: float | None = None) -> float:
        actual = float(timestamp if timestamp is not None else time.time())
        self._set_meta("leader_contact_at", actual)
        return actual

    def leader_contact_at(self) -> float | None:
        value = self._get_meta("leader_contact_at")
        return float(value) if value is not None else None

    def configure(self, *, cluster_name: str, node_id: str, enabled: bool = False) -> dict[str, Any]:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            existing = conn.execute(
                """
                SELECT current_term, voted_for, role, leader_id, commit_index, last_applied
                FROM consensus_state
                WHERE state_name='local'
                """
            ).fetchone()
            current_term = int(existing[0]) if existing is not None else 0
            voted_for = str(existing[1]) if existing is not None and existing[1] is not None else None
            role = str(existing[2]) if existing is not None else ("leader" if enabled and not self.list_peers() else "follower")
            leader_id = str(existing[3]) if existing is not None and existing[3] is not None else (node_id if role == "leader" else None)
            commit_index = int(existing[4]) if existing is not None else 0
            last_applied = int(existing[5]) if existing is not None else 0
            conn.execute(
                """
                INSERT INTO consensus_state(state_name, cluster_name, node_id, enabled, current_term, voted_for, role, leader_id, commit_index, last_applied, updated_at)
                VALUES('local', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_name) DO UPDATE SET
                    cluster_name=excluded.cluster_name,
                    node_id=excluded.node_id,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (cluster_name, node_id, int(bool(enabled)), current_term, voted_for, role, leader_id, commit_index, last_applied, now),
            )
        if leader_id:
            self.touch_leader_contact(now)
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT cluster_name, node_id, enabled, current_term, voted_for, role, leader_id, commit_index, last_applied, updated_at
                FROM consensus_state
                WHERE state_name='local'
                """
            ).fetchone()
        if row is None:
            return {
                "cluster_name": "nova-consensus",
                "node_id": "local",
                "enabled": False,
                "current_term": 0,
                "voted_for": None,
                "role": "follower",
                "leader_id": None,
                "commit_index": 0,
                "last_applied": 0,
                "peer_count": 0,
                "quorum_size": 1,
                "log_length": 0,
                "leader_contact_at": self.leader_contact_at(),
                "snapshot_index": int(self._get_meta("snapshot_index", 0) or 0),
            }
        return {
            "cluster_name": row[0],
            "node_id": row[1],
            "enabled": bool(row[2]),
            "current_term": int(row[3]),
            "voted_for": row[4],
            "role": row[5],
            "leader_id": row[6],
            "commit_index": int(row[7]),
            "last_applied": int(row[8]),
            "updated_at": row[9],
            "peer_count": len(self.list_peers()),
            "quorum_size": self.quorum_size(),
            "log_length": self.last_log_index(),
            "leader_contact_at": self.leader_contact_at(),
            "snapshot_index": int(self._get_meta("snapshot_index", 0) or 0),
            "snapshot_term": int(self._get_meta("snapshot_term", 0) or 0),
        }

    def is_enabled(self) -> bool:
        return bool(self.status().get("enabled"))

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        state = self.status()
        return self.configure(cluster_name=str(state["cluster_name"]), node_id=str(state["node_id"]), enabled=enabled)

    def _update_state(self, **values: Any) -> dict[str, Any]:
        state = self.status()
        payload = {
            "cluster_name": state["cluster_name"],
            "node_id": state["node_id"],
            "enabled": int(bool(state["enabled"])),
            "current_term": int(state["current_term"]),
            "voted_for": state.get("voted_for"),
            "role": state["role"],
            "leader_id": state.get("leader_id"),
            "commit_index": int(state["commit_index"]),
            "last_applied": int(state["last_applied"]),
            "updated_at": time.time(),
        }
        payload.update(values)
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE consensus_state
                SET cluster_name=?, node_id=?, enabled=?, current_term=?, voted_for=?, role=?, leader_id=?, commit_index=?, last_applied=?, updated_at=?
                WHERE state_name='local'
                """,
                (
                    payload["cluster_name"],
                    payload["node_id"],
                    int(bool(payload["enabled"])),
                    int(payload["current_term"]),
                    payload["voted_for"],
                    payload["role"],
                    payload["leader_id"],
                    int(payload["commit_index"]),
                    int(payload["last_applied"]),
                    payload["updated_at"],
                ),
            )
        return self.status()

    def register_peer(
        self,
        peer_name: str,
        endpoint: str,
        *,
        auth_token: str | None = None,
        tls_profile: str | None = None,
        voter: bool = True,
        active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO consensus_peers(peer_name, endpoint, auth_token, tls_profile, voter, active, metadata_json, last_contact_at, match_index, next_index, last_error)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_name) DO UPDATE SET
                    endpoint=excluded.endpoint,
                    auth_token=excluded.auth_token,
                    tls_profile=excluded.tls_profile,
                    voter=excluded.voter,
                    active=excluded.active,
                    metadata_json=excluded.metadata_json
                """,
                (
                    peer_name,
                    endpoint,
                    auth_token,
                    tls_profile,
                    int(bool(voter)),
                    int(bool(active)),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    None,
                    0,
                    self.last_log_index() + 1,
                    None,
                ),
            )
        return next(peer for peer in self.list_peers() if peer["peer_name"] == peer_name)

    def update_peer(self, peer_name: str, **values: Any) -> dict[str, Any] | None:
        peer = next((item for item in self.list_peers() if item["peer_name"] == peer_name), None)
        if peer is None:
            return None
        payload = dict(peer)
        payload.update(values)
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                UPDATE consensus_peers
                SET endpoint=?, auth_token=?, tls_profile=?, voter=?, active=?, metadata_json=?, last_contact_at=?, match_index=?, next_index=?, last_error=?
                WHERE peer_name=?
                """,
                (
                    payload["endpoint"],
                    payload.get("auth_token"),
                    payload.get("tls_profile"),
                    int(bool(payload.get("voter", True))),
                    int(bool(payload.get("active", True))),
                    json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
                    payload.get("last_contact_at"),
                    int(payload.get("match_index") or 0),
                    int(payload.get("next_index") or 1),
                    payload.get("last_error"),
                    peer_name,
                ),
            )
        return next((item for item in self.list_peers() if item["peer_name"] == peer_name), None)

    def remove_peer(self, peer_name: str) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock, conn:
            cursor = conn.execute("DELETE FROM consensus_peers WHERE peer_name=?", (peer_name,))
        return {"peer_name": peer_name, "removed": cursor.rowcount > 0, "peer_count": len(self.list_peers())}

    def list_peers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT peer_name, endpoint, auth_token, tls_profile, voter, active, metadata_json, last_contact_at, match_index, next_index, last_error
                FROM consensus_peers
                ORDER BY peer_name
                """
            ).fetchall()
        return [
            ConsensusPeer(
                peer_name=row[0],
                endpoint=row[1],
                auth_token=row[2],
                tls_profile=row[3],
                voter=bool(row[4]),
                active=bool(row[5]),
                metadata=json.loads(row[6]),
                last_contact_at=row[7],
                match_index=int(row[8]),
                next_index=int(row[9]),
                last_error=row[10],
            ).to_dict()
            for row in rows
        ]

    def latest_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT snapshot_id, last_included_index, last_included_term, payload_json, created_at
                FROM consensus_snapshots
                ORDER BY last_included_index DESC, created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row[0],
            "last_included_index": int(row[1]),
            "last_included_term": int(row[2]),
            "payload": json.loads(row[3]),
            "created_at": row[4],
        }

    def needs_election(self, heartbeat_timeout: float = 10.0) -> bool:
        state = self.status()
        if not bool(state.get("enabled")):
            return False
        if state.get("role") == "leader":
            return False
        leader_contact = self.leader_contact_at()
        if state.get("leader_id") is None:
            return True
        if leader_contact is None:
            return True
        return float(leader_contact) + float(heartbeat_timeout) < time.time()

    def quorum_size(self) -> int:
        voters = 1 + sum(1 for peer in self.list_peers() if peer.get("voter", True) and peer.get("active", True))
        return max(1, (voters // 2) + 1)

    def last_log_index(self) -> int:
        with self._lock:
            row = self._ensure_connection().execute("SELECT COALESCE(MAX(log_index), 0) FROM consensus_log").fetchone()
        log_index = int(row[0]) if row is not None else 0
        snapshot = self.latest_snapshot()
        snapshot_index = int(snapshot["last_included_index"]) if snapshot is not None else 0
        return max(log_index, snapshot_index)

    def last_log_term(self) -> int:
        with self._lock:
            row = self._ensure_connection().execute(
                "SELECT term FROM consensus_log ORDER BY log_index DESC LIMIT 1"
            ).fetchone()
        if row is not None:
            return int(row[0])
        snapshot = self.latest_snapshot()
        return int(snapshot["last_included_term"]) if snapshot is not None else 0

    def get_entry(self, log_index: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT log_index, term, command_type, command_json, committed, applied, created_at
                FROM consensus_log
                WHERE log_index=?
                """,
                (int(log_index),),
            ).fetchone()
        if row is None:
            return None
        return ConsensusLogEntry(
            log_index=int(row[0]),
            term=int(row[1]),
            command_type=row[2],
            command=json.loads(row[3]),
            committed=bool(row[4]),
            applied=bool(row[5]),
            created_at=row[6],
        ).to_dict()

    def list_log(self, *, since_index: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT log_index, term, command_type, command_json, committed, applied, created_at
                FROM consensus_log
                WHERE log_index > ?
                ORDER BY log_index ASC
                LIMIT ?
                """,
                (max(0, int(since_index)), max(1, int(limit))),
            ).fetchall()
        return [
            ConsensusLogEntry(
                log_index=int(row[0]),
                term=int(row[1]),
                command_type=row[2],
                command=json.loads(row[3]),
                committed=bool(row[4]),
                applied=bool(row[5]),
                created_at=row[6],
            ).to_dict()
            for row in rows
        ]

    def request_vote(self, *, candidate_id: str, term: int, last_log_index: int, last_log_term: int) -> dict[str, Any]:
        state = self.status()
        current_term = int(state["current_term"])
        voted_for = state.get("voted_for")
        if int(term) < current_term:
            return {
                "term": current_term,
                "vote_granted": False,
                "reason": "stale_term",
                "node_id": state["node_id"],
            }
        if int(term) > current_term:
            state = self._update_state(current_term=int(term), voted_for=None, role="follower", leader_id=None)
            current_term = int(state["current_term"])
            voted_for = state.get("voted_for")
        up_to_date = (int(last_log_term), int(last_log_index)) >= (self.last_log_term(), self.last_log_index())
        if not up_to_date:
            return {
                "term": current_term,
                "vote_granted": False,
                "reason": "log_outdated",
                "node_id": state["node_id"],
            }
        if voted_for not in {None, candidate_id}:
            return {
                "term": current_term,
                "vote_granted": False,
                "reason": "already_voted",
                "node_id": state["node_id"],
            }
        self._update_state(current_term=current_term, voted_for=candidate_id, role="follower", leader_id=None)
        return {
            "term": current_term,
            "vote_granted": True,
            "node_id": state["node_id"],
        }

    def start_election(self, sender: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        state = self.status()
        new_term = int(state["current_term"]) + 1
        state = self._update_state(current_term=new_term, voted_for=str(state["node_id"]), role="candidate", leader_id=None)
        votes = 1
        responses: list[dict[str, Any]] = []
        payload = {
            "candidate_id": state["node_id"],
            "term": new_term,
            "last_log_index": self.last_log_index(),
            "last_log_term": self.last_log_term(),
        }
        for peer in self.list_peers():
            if not peer.get("active", True) or not peer.get("voter", True):
                continue
            try:
                response = sender(peer, payload)
                responses.append({"peer_name": peer["peer_name"], "response": response})
                self.update_peer(peer["peer_name"], last_contact_at=time.time(), last_error=None)
                response_term = int(response.get("term") or new_term)
                if response_term > new_term:
                    self._update_state(current_term=response_term, voted_for=None, role="follower", leader_id=None)
                    continue
                if bool(response.get("vote_granted")):
                    votes += 1
            except Exception as exc:
                self.update_peer(peer["peer_name"], last_error=str(exc))
                responses.append({"peer_name": peer["peer_name"], "error": str(exc)})
        won = votes >= self.quorum_size()
        if won:
            self._update_state(role="leader", leader_id=str(state["node_id"]))
        else:
            self._update_state(role="follower", leader_id=None)
        result = self.status()
        result["election"] = {
            "term": new_term,
            "votes": votes,
            "quorum_size": self.quorum_size(),
            "won": won,
            "responses": responses,
        }
        return result

    def append_entries(
        self,
        *,
        leader_id: str,
        term: int,
        prev_log_index: int,
        prev_log_term: int,
        entries: list[dict[str, Any]],
        leader_commit: int,
    ) -> dict[str, Any]:
        state = self.status()
        current_term = int(state["current_term"])
        if int(term) < current_term:
            return {"term": current_term, "success": False, "reason": "stale_term", "match_index": self.last_log_index()}
        if int(term) > current_term or state.get("leader_id") != leader_id:
            state = self._update_state(current_term=int(term), voted_for=None, role="follower", leader_id=leader_id)
        self.touch_leader_contact()
        if int(prev_log_index) > 0:
            previous = self.get_entry(int(prev_log_index))
            snapshot = self.latest_snapshot()
            snapshot_matches = snapshot is not None and int(snapshot["last_included_index"]) == int(prev_log_index) and int(snapshot["last_included_term"]) == int(prev_log_term)
            if (previous is None or int(previous["term"]) != int(prev_log_term)) and not snapshot_matches:
                return {"term": int(state["current_term"]), "success": False, "reason": "log_mismatch", "match_index": self.last_log_index()}
        conn = self._ensure_connection()
        with self._lock, conn:
            for raw_entry in entries:
                log_index = int(raw_entry["log_index"])
                existing = conn.execute("SELECT term FROM consensus_log WHERE log_index=?", (log_index,)).fetchone()
                if existing is not None and int(existing[0]) != int(raw_entry["term"]):
                    conn.execute("DELETE FROM consensus_log WHERE log_index >= ?", (log_index,))
                    existing = None
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO consensus_log(log_index, term, command_type, command_json, committed, applied, created_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            log_index,
                            int(raw_entry["term"]),
                            str(raw_entry["command_type"]),
                            json.dumps(dict(raw_entry.get("command") or {}), ensure_ascii=False),
                            int(bool(raw_entry.get("committed", False))),
                            int(bool(raw_entry.get("applied", False))),
                            float(raw_entry.get("created_at") or time.time()),
                        ),
                    )
        if int(leader_commit) > int(state["commit_index"]):
            commit_index = min(int(leader_commit), self.last_log_index())
            self.mark_committed(commit_index)
        self._update_state(current_term=max(int(term), int(state["current_term"])), role="follower", leader_id=leader_id)
        return {"term": int(self.status()["current_term"]), "success": True, "match_index": self.last_log_index()}

    def append_local(self, command_type: str, command: dict[str, Any], *, term: int | None = None) -> dict[str, Any]:
        state = self.status()
        actual_term = int(term if term is not None else state["current_term"])
        created_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            cursor = conn.execute(
                """
                INSERT INTO consensus_log(term, command_type, command_json, committed, applied, created_at)
                VALUES(?, ?, ?, 0, 0, ?)
                """,
                (actual_term, command_type, json.dumps(command, ensure_ascii=False), created_at),
            )
            index = int(cursor.lastrowid)
        return self.get_entry(index) or {
            "log_index": index,
            "term": actual_term,
            "command_type": command_type,
            "command": command,
            "committed": False,
            "applied": False,
            "created_at": created_at,
        }

    def mark_committed(self, commit_index: int) -> dict[str, Any]:
        state = self.status()
        target = max(int(state["commit_index"]), int(commit_index))
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute("UPDATE consensus_log SET committed=1 WHERE log_index <= ?", (target,))
        return self._update_state(commit_index=target)

    def mark_applied(self, log_index: int) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute("UPDATE consensus_log SET applied=1 WHERE log_index=?", (int(log_index),))
        return self._update_state(last_applied=max(int(self.status()["last_applied"]), int(log_index)))

    def send_heartbeats(self, sender: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        state = self.status()
        if state.get("role") != "leader":
            return {"sent": 0, "failures": 0, "role": state.get("role")}
        failures = 0
        sent = 0
        latest_snapshot = self.latest_snapshot()
        for peer in [peer for peer in self.list_peers() if peer.get("active", True)]:
            payload = {
                "leader_id": state["node_id"],
                "term": int(state["current_term"]),
                "prev_log_index": self.last_log_index(),
                "prev_log_term": self.last_log_term(),
                "entries": [],
                "leader_commit": int(state["commit_index"]),
            }
            if latest_snapshot is not None and int(peer.get("next_index") or 1) <= int(latest_snapshot["last_included_index"]):
                payload["snapshot"] = latest_snapshot
            try:
                response = sender(peer, payload)
                self.update_peer(peer["peer_name"], last_contact_at=time.time(), last_error=None, match_index=int(response.get("match_index") or peer.get("match_index") or 0))
                sent += 1
            except Exception as exc:
                failures += 1
                self.update_peer(peer["peer_name"], last_error=str(exc))
        return {"sent": sent, "failures": failures, "role": state.get("role"), "leader_id": state.get("node_id")}

    def compact_log(self, up_to_index: int, payload: dict[str, Any]) -> dict[str, Any]:
        if int(up_to_index) < 0:
            raise ValueError("up_to_index must be >= 0")
        if int(up_to_index) > 0:
            entry = self.get_entry(int(up_to_index))
            snapshot_term = int(entry["term"]) if entry is not None else int(self._get_meta("snapshot_term", 0) or 0)
        else:
            snapshot_term = 0
        snapshot_id = uuid.uuid4().hex[:16]
        created_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO consensus_snapshots(snapshot_id, last_included_index, last_included_term, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (snapshot_id, int(up_to_index), snapshot_term, json.dumps(payload, ensure_ascii=False), created_at),
            )
            conn.execute("DELETE FROM consensus_log WHERE log_index <= ? AND applied=1", (int(up_to_index),))
        self._set_meta("snapshot_index", int(up_to_index))
        self._set_meta("snapshot_term", snapshot_term)
        return self.latest_snapshot() or {"snapshot_id": snapshot_id}

    def install_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(snapshot.get("snapshot_id") or uuid.uuid4().hex[:16])
        last_included_index = int(snapshot.get("last_included_index") or 0)
        last_included_term = int(snapshot.get("last_included_term") or 0)
        payload = dict(snapshot.get("payload") or {})
        created_at = float(snapshot.get("created_at") or time.time())
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO consensus_snapshots(snapshot_id, last_included_index, last_included_term, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    last_included_index=excluded.last_included_index,
                    last_included_term=excluded.last_included_term,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (snapshot_id, last_included_index, last_included_term, json.dumps(payload, ensure_ascii=False), created_at),
            )
            conn.execute("DELETE FROM consensus_log WHERE log_index <= ?", (last_included_index,))
        self._set_meta("snapshot_index", last_included_index)
        self._set_meta("snapshot_term", last_included_term)
        self._update_state(commit_index=max(int(self.status()["commit_index"]), last_included_index), last_applied=max(int(self.status()["last_applied"]), last_included_index))
        return self.latest_snapshot() or snapshot

    def propose(
        self,
        command_type: str,
        command: dict[str, Any],
        sender: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        state = self.status()
        if not bool(state["enabled"]):
            entry = self.append_local(command_type, command, term=int(state["current_term"]))
            self.mark_committed(int(entry["log_index"]))
            return {"entry": self.get_entry(int(entry["log_index"])), "committed": True, "acks": 1, "quorum_size": 1}
        if state["role"] != "leader":
            raise RuntimeError("consensus proposals require leader role")
        entry = self.append_local(command_type, command, term=int(state["current_term"]))
        acks = 1
        peers = [peer for peer in self.list_peers() if peer.get("active", True) and peer.get("voter", True)]
        previous = self.get_entry(int(entry["log_index"]) - 1) if int(entry["log_index"]) > 1 else None
        for peer in peers:
            payload = {
                "leader_id": state["node_id"],
                "term": int(state["current_term"]),
                "prev_log_index": int(previous["log_index"]) if previous is not None else 0,
                "prev_log_term": int(previous["term"]) if previous is not None else 0,
                "entries": [entry],
                "leader_commit": int(self.status()["commit_index"]),
            }
            try:
                response = sender(peer, payload)
                self.update_peer(
                    peer["peer_name"],
                    last_contact_at=time.time(),
                    last_error=None,
                    match_index=int(response.get("match_index") or 0),
                    next_index=int(response.get("match_index") or 0) + 1,
                )
                response_term = int(response.get("term") or state["current_term"])
                if response_term > int(state["current_term"]):
                    self._update_state(current_term=response_term, voted_for=None, role="follower", leader_id=None)
                    continue
                if bool(response.get("success")):
                    acks += 1
            except Exception as exc:
                self.update_peer(peer["peer_name"], last_error=str(exc))
        committed = acks >= self.quorum_size()
        if committed:
            self.mark_committed(int(entry["log_index"]))
            committed_index = int(entry["log_index"])
            for peer in peers:
                try:
                    sender(
                        peer,
                        {
                            "leader_id": state["node_id"],
                            "term": int(self.status()["current_term"]),
                            "prev_log_index": int(entry["log_index"]),
                            "prev_log_term": int(entry["term"]),
                            "entries": [],
                            "leader_commit": committed_index,
                        },
                    )
                except Exception:
                    continue
        return {
            "entry": self.get_entry(int(entry["log_index"])),
            "committed": committed,
            "acks": acks,
            "quorum_size": self.quorum_size(),
        }

    def apply_committed(
        self,
        applier: Callable[[dict[str, Any]], Any],
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        state = self.status()
        rows = self.list_log(since_index=int(state["last_applied"]), limit=limit)
        applied: list[dict[str, Any]] = []
        for entry in rows:
            if not entry.get("committed") or entry.get("applied"):
                continue
            result = applier(entry)
            self.mark_applied(int(entry["log_index"]))
            applied.append({"entry": entry, "result": result})
        return applied

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        status = self.status()
        return {
            "db_path": str(self.db_path),
            "status": status,
            "peers": self.list_peers(),
            "log": self.list_log(limit=limit),
            "latest_snapshot": self.latest_snapshot(),
        }
