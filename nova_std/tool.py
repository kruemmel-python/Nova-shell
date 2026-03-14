from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolPrimitive:
    name: str

    def run(self, **kwargs: Any) -> dict[str, Any]:
        return {"tool": self.name, "ok": True, "args": kwargs}
