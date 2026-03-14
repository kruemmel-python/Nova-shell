from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FlowPrimitive:
    name: str
    steps: list[str] = field(default_factory=list)

    def plan(self) -> list[str]:
        return list(self.steps)
