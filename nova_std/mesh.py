from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MeshPrimitive:
    workers: int = 0

    def capacity(self) -> dict[str, int]:
        return {"workers": self.workers}
