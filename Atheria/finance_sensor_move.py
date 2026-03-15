from __future__ import annotations

from typing import Any, Dict


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


class MoveIndexSensor:
    """
    Bond stress proxy from MOVE, optionally compared with VIX.
    """

    def required_symbols(self) -> list[str]:
        return ["^MOVE"]

    def analyze(self, structured: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        move = dict(structured.get("MOVE") or {})
        vix = dict(structured.get("VIX") or {})
        if not move:
            return {
                "available": False,
                "stress_score": 0.0,
                "stress_level": "unknown",
            }

        move_price = _safe_float(move.get("price"), 0.0)
        move_return = _safe_float(move.get("recent_return"), 0.0)
        move_volatility = _safe_float(move.get("volatility"), 0.0)
        move_change_pct = _safe_float(move.get("price_change_pct"), 0.0)
        vix_return = _safe_float(vix.get("recent_return"), 0.0)

        score = _clamp(
            max(0.0, move_return) * 8.0
            + max(0.0, move_volatility) * 14.0
            + max(0.0, (move_price - 105.0) / 50.0),
            0.0,
            1.0,
        )
        spread = move_return - max(0.0, vix_return)
        if score >= 0.72:
            level = "high"
        elif score >= 0.42:
            level = "elevated"
        else:
            level = "calm"

        return {
            "available": True,
            "move_price": round(move_price, 6),
            "move_recent_return": round(move_return, 6),
            "move_volatility": round(move_volatility, 6),
            "move_price_change_pct": round(move_change_pct, 6),
            "vix_recent_return": round(vix_return, 6),
            "stress_spread_vs_vix": round(spread, 6),
            "stress_score": round(score, 6),
            "stress_level": level,
        }
