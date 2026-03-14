from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SensorPrimitive:
    name: str
    kind: str

    def poll(self) -> dict[str, Any]:
        return {"sensor": self.name, "kind": self.kind, "status": "ok"}
