from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VectorPrimitive:
    provider: str = "atheria"

    def embed(self, text: str) -> list[float]:
        seed = sum(ord(ch) for ch in text)
        return [float((seed + idx) % 97) / 97.0 for idx in range(8)]

    def similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        length = min(len(left), len(right))
        dot = sum(left[i] * right[i] for i in range(length))
        ln = sum(v * v for v in left[:length]) ** 0.5
        rn = sum(v * v for v in right[:length]) ** 0.5
        if ln == 0 or rn == 0:
            return 0.0
        return dot / (ln * rn)
