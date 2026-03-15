from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NovaSyntaxError(Exception):
    message: str
    line: int
    column: int = 1
    source_line: str = ""

    def __str__(self) -> str:
        pointer = ""
        if self.source_line:
            pointer = f"\n{self.source_line}\n{' ' * max(self.column - 1, 0)}^"
        return f"{self.message} at line {self.line}, column {self.column}{pointer}"
