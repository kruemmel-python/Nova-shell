from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentPrimitive:
    name: str
    model: str
    tools: list[str] = field(default_factory=list)

    def invoke(self, task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "agent": self.name,
            "model": self.model,
            "task": task,
            "payload": payload or {},
            "tools": self.tools,
        }
