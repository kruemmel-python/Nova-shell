from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DatasetPrimitive:
    name: str
    source: str
    config: dict[str, Any]

    def descriptor(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source, "config": self.config}
