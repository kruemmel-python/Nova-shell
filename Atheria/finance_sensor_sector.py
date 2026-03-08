from __future__ import annotations

from typing import Any, Dict


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


class SectorRotationSensor:
    """
    Detects defensive-vs-cyclical rotation from sector ETFs:
    XLU -> UTILITIES, XLE -> ENERGY, XLK -> SOFTWARE.
    """

    def required_symbols(self) -> list[str]:
        return ["XLU", "XLE", "XLK"]

    def analyze(self, structured: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        software = dict(structured.get("SOFTWARE") or {})
        utilities = dict(structured.get("UTILITIES") or {})
        energy = dict(structured.get("ENERGY") or {})
        if not software and not utilities and not energy:
            return {
                "available": False,
                "rotation_score": 0.0,
                "rotation_bias": "unknown",
            }

        software_r = _safe_float(software.get("recent_return"), 0.0)
        utilities_r = _safe_float(utilities.get("recent_return"), 0.0)
        energy_r = _safe_float(energy.get("recent_return"), 0.0)
        defensive_mean = (utilities_r + energy_r) / 2.0
        spread = defensive_mean - software_r
        defensive_score = max(0.0, spread) * 16.0
        cyclical_score = max(0.0, -spread) * 16.0
        rotation_score = _clamp(max(defensive_score, cyclical_score), 0.0, 1.0)

        if defensive_score > cyclical_score and rotation_score >= 0.32:
            bias = "defensive"
        elif cyclical_score > defensive_score and rotation_score >= 0.32:
            bias = "cyclical"
        else:
            bias = "mixed"

        return {
            "available": True,
            "software_recent_return": round(software_r, 6),
            "utilities_recent_return": round(utilities_r, 6),
            "energy_recent_return": round(energy_r, 6),
            "defensive_spread": round(spread, 6),
            "rotation_score": round(rotation_score, 6),
            "rotation_bias": bias,
        }
