from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

from nova.runtime.atheria_bridge import load_aion_chronik, load_information_einstein_like, load_market_future_projection


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _tokenize(text: str) -> list[str]:
    return [token for token in "".join(ch if ch.isalnum() else " " for ch in str(text or "").lower()).split() if token]


def _overlap(left: str, right: str) -> float:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens.intersection(right_tokens)) / max(1, len(left_tokens.union(right_tokens)))


class MyceliaAtheriaCoEvolutionLab:
    """Blends Mycelia fitness with Atheria forecasting, invariants and curvature penalties."""

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = Path(storage_root).resolve(strict=False)
        self.state_dir = self.storage_root / "mycelia_coevolution"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.state_dir / "history.jsonl"
        self.status_path = self.state_dir / "status.json"

    def blend_score(
        self,
        *,
        population_name: str,
        member: Any,
        base_score_payload: dict[str, Any],
        task_input: str,
        output_text: str,
        error_text: str,
        atheria_hits: list[dict[str, Any]],
        report_file: str = "",
    ) -> dict[str, Any]:
        base_fitness = _safe_float(base_score_payload.get("fitness"), 0.0)
        projection = self._projection_bundle(report_file)
        invariant = self._latest_invariant(report_file)
        curvature = self._curvature_bundle(report_file)

        top_drivers = dict(projection.get("forecast") or {}).get("drivers") or []
        driver_text = " ".join(str(item.get("feature") or "") for item in top_drivers[:5])
        forecast_quality = dict(projection.get("quality") or {})
        forecast_alignment = _clamp(
            0.72 * _safe_float(forecast_quality.get("predictability_index"), 0.0)
            + 0.28 * _overlap(driver_text, output_text),
        )

        invariant_statement = str(invariant.get("statement") or "")
        invariant_alignment = _clamp(
            0.65 * _overlap(invariant_statement, output_text)
            + 0.35 * _safe_float(invariant.get("confidence"), 0.0)
        )
        if atheria_hits:
            invariant_alignment = _clamp(
                invariant_alignment * 0.75
                + 0.25 * max(0.0, min(1.0, _safe_float(atheria_hits[0].get("score"), 0.0))),
            )

        success_ratio = 0.0
        if member is not None:
            total = max(1, int(getattr(member, "success_count", 0)) + int(getattr(member, "error_count", 0)))
            success_ratio = int(getattr(member, "success_count", 0)) / total
        tool_integrity = _clamp(0.68 * (0.0 if error_text else 1.0) + 0.32 * success_ratio)

        output_complexity = min(1.4, len(_tokenize(output_text)) / 90.0)
        prompt_complexity = min(1.0, len(_tokenize(getattr(getattr(member, "genome", None), "prompt_template", ""))) / 120.0)
        tool_count = len(getattr(getattr(member, "genome", None), "tool_names", []) or [])
        complexity = min(1.5, 0.55 * output_complexity + 0.25 * prompt_complexity + 0.20 * min(1.0, tool_count / 4.0))
        curvature_penalty = _clamp(_safe_float(curvature.get("mean_curvature"), 0.0) * complexity * 0.18, 0.0, 0.24)

        blended = _clamp(
            0.58 * base_fitness
            + 0.16 * forecast_alignment
            + 0.12 * invariant_alignment
            + 0.14 * tool_integrity
            - curvature_penalty
        )
        metrics = dict(base_score_payload.get("metrics") or {})
        metrics.update(
            {
                "forecast_alignment": round(forecast_alignment, 6),
                "invariant_alignment": round(invariant_alignment, 6),
                "tool_integrity": round(tool_integrity, 6),
                "curvature_penalty": round(curvature_penalty, 6),
                "base_fitness": round(base_fitness, 6),
                "coevolution_blended_fitness": round(blended, 6),
            }
        )
        return {
            "fitness": round(blended, 6),
            "metrics": metrics,
            "coevolution": {
                "forecast_quality": {
                    "predictability_index": round(_safe_float(forecast_quality.get("predictability_index"), 0.0), 6),
                    "proof_verdict": str(forecast_quality.get("proof_verdict") or ""),
                },
                "invariant": {
                    "statement": invariant_statement,
                    "confidence": round(_safe_float(invariant.get("confidence"), 0.0), 6),
                },
                "curvature": {
                    "mean_curvature": round(_safe_float(curvature.get("mean_curvature"), 0.0), 6),
                    "point_count": int(curvature.get("point_count", 0)),
                },
            },
        }

    def record_run(self, *, population_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "run_id": f"coevo_{int(time.time() * 1000)}",
            "population": population_name,
            "created_at": round(time.time(), 6),
            "payload": payload,
        }
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        status = self.status(population_name=population_name)
        self.status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return row

    def status(self, *, population_name: str | None = None, limit: int = 12) -> dict[str, Any]:
        rows = self._history(limit=max(1, limit))
        if population_name:
            rows = [row for row in rows if str(row.get("population") or "") == population_name]
        latest = rows[-1] if rows else {}
        return {
            "run_count": len(rows),
            "population": population_name or "",
            "last_run": latest,
        }

    def _projection_bundle(self, report_file: str) -> dict[str, Any]:
        path = self._resolve_report_file(report_file)
        if path is None or not path.exists():
            return {}
        module = load_market_future_projection()
        try:
            events = module.load_events_from_jsonl(path, limit=96)
            projector = module.MarketLandscapeFutureProjector(latent_dims=3, ridge=0.08, horizon_steps=6, step_seconds=300.0)
            return projector.run(events)
        except Exception:
            return {}

    def _curvature_bundle(self, report_file: str) -> dict[str, Any]:
        path = self._resolve_report_file(report_file)
        if path is None or not path.exists():
            return {"mean_curvature": 0.0, "point_count": 0}
        module = load_information_einstein_like()
        try:
            events = module.load_events_from_jsonl(path, limit=72)
            simulator = module.InformationEinsteinLikeSimulator(mode="conservative")
            report = simulator.reconstruct(events)
            curvatures = [float(point.curvature_proxy) for point in report.points]
            mean_curvature = sum(curvatures) / max(1, len(curvatures)) if curvatures else 0.0
            return {"mean_curvature": mean_curvature, "point_count": len(curvatures)}
        except Exception:
            return {"mean_curvature": 0.0, "point_count": 0}

    def _latest_invariant(self, report_file: str) -> dict[str, Any]:
        module = load_aion_chronik()
        report_root = self._resolve_report_root(report_file)
        if report_root is None:
            return {}
        with contextlib.suppress(Exception):
            payload = module._latest_resonance_invariant(report_root)
            if isinstance(payload, dict):
                return payload
        return {}

    def _resolve_report_root(self, report_file: str) -> Path | None:
        path = self._resolve_report_file(report_file)
        if path is not None and path.exists():
            if path.parent.name == "daemon_runtime":
                return path.parent.parent
            return path.parent
        if self.storage_root.exists():
            return self.storage_root
        return None

    def _resolve_report_file(self, report_file: str) -> Path | None:
        if report_file:
            path = Path(report_file).resolve(strict=False)
            if path.exists():
                return path
        fallback = self.storage_root / "daemon_runtime" / "atheria_daemon_audit.jsonl"
        if fallback.exists():
            return fallback
        return None

    def _history(self, *, limit: int) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for raw in self.history_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
        return rows[-max(1, limit) :]
