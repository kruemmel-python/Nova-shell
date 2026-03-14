from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MemoryPrimitive:
    name: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, item: dict[str, Any]) -> None:
        self.entries.append(item)

    def query(self, key: str, value: Any) -> list[dict[str, Any]]:
        return [item for item in self.entries if item.get(key) == value]
