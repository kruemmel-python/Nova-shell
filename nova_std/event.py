from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EventPrimitive:
    topic: str
    actions: list[str] = field(default_factory=list)

    def descriptor(self) -> dict[str, object]:
        return {"topic": self.topic, "actions": self.actions}
