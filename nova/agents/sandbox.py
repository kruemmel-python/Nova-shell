from __future__ import annotations

import time
from typing import Any


class ToolSandbox:
    """Tracks and enforces agent tool sessions."""

    def __init__(self) -> None:
        self._sessions: list[dict[str, Any]] = []

    def authorize(self, agent_name: str, *, allowed_tools: tuple[str, ...], requested_tools: set[str], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        allowed = set(allowed_tools)
        if requested_tools and not requested_tools.issubset(allowed):
            denied = sorted(requested_tools.difference(allowed))
            raise PermissionError(f"agent '{agent_name}' requested sandboxed tools outside allowlist: {', '.join(denied)}")
        session = {
            "agent_name": agent_name,
            "allowed_tools": sorted(allowed),
            "requested_tools": sorted(requested_tools),
            "created_at": time.time(),
            "metadata": dict(metadata or {}),
        }
        self._sessions.append(session)
        return session

    def snapshot(self) -> dict[str, Any]:
        return {"session_count": len(self._sessions), "sessions": list(self._sessions[-20:])}
