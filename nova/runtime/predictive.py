from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atheria_bridge import load_market_future_projection


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _tokenize(text: str) -> list[str]:
    return [token for token in "".join(ch if ch.isalnum() else " " for ch in str(text or "").lower()).split() if token]


def _rolling_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / max(1, len(values))


def _rolling_std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    return float(statistics.pstdev(values))


def _engine_from_stage(stage: str) -> str:
    lowered = str(stage or "").strip().lower()
    if lowered.startswith("cpp"):
        return "cpp"
    if lowered.startswith("gpu"):
        return "gpu"
    if lowered.startswith("mesh"):
        return "mesh"
    if lowered.startswith(("atheria", "agent", "ai", "memory")):
        return "ai"
    if lowered.startswith(("py", "python")):
        return "py"
    return "other"


@dataclass(slots=True)
class PredictiveTelemetryEvent:
    timestamp: float
    stage: str
    engine: str
    duration_ms: float
    cpu_percent: float
    rss_mb: float
    rows_processed: int
    error: str
    recent_event_count: int
    active_reactive_triggers: int
    mesh_worker_count: int
    system_temperature: float
    structural_tension: float
    guardian_score: float
    payload_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 6),
            "stage": self.stage,
            "engine": self.engine,
            "duration_ms": round(self.duration_ms, 6),
            "cpu_percent": round(self.cpu_percent, 6),
            "rss_mb": round(self.rss_mb, 6),
            "rows_processed": int(self.rows_processed),
            "error": self.error,
            "recent_event_count": int(self.recent_event_count),
            "active_reactive_triggers": int(self.active_reactive_triggers),
            "mesh_worker_count": int(self.mesh_worker_count),
            "system_temperature": round(self.system_temperature, 6),
            "structural_tension": round(self.structural_tension, 6),
            "guardian_score": round(self.guardian_score, 6),
            "payload_size": int(self.payload_size),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PredictiveTelemetryEvent":
        return cls(
            timestamp=_safe_float(payload.get("timestamp"), time.time()),
            stage=str(payload.get("stage") or ""),
            engine=str(payload.get("engine") or _engine_from_stage(str(payload.get("stage") or ""))),
            duration_ms=_safe_float(payload.get("duration_ms"), 0.0),
            cpu_percent=_safe_float(payload.get("cpu_percent"), 0.0),
            rss_mb=_safe_float(payload.get("rss_mb"), 0.0),
            rows_processed=int(_safe_float(payload.get("rows_processed"), 0.0)),
            error=str(payload.get("error") or ""),
            recent_event_count=int(_safe_float(payload.get("recent_event_count"), 0.0)),
            active_reactive_triggers=int(_safe_float(payload.get("active_reactive_triggers"), 0.0)),
            mesh_worker_count=int(_safe_float(payload.get("mesh_worker_count"), 0.0)),
            system_temperature=_safe_float(payload.get("system_temperature"), 25.0),
            structural_tension=_safe_float(payload.get("structural_tension"), 0.0),
            guardian_score=_safe_float(payload.get("guardian_score"), 0.0),
            payload_size=int(_safe_float(payload.get("payload_size"), 0.0)),
        )


class PredictiveEngineShifter:
    """Forecast-driven engine steering over Nova-shell telemetry."""

    def __init__(self, base_path: Path, *, horizon_steps: int = 6, step_seconds: float = 30.0) -> None:
        self.base_path = Path(base_path).resolve(strict=False)
        self.state_dir = self.base_path / ".nova"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.state_dir / "predictive-engine-telemetry.jsonl"
        self.status_path = self.state_dir / "predictive-engine-status.json"
        self.horizon_steps = max(2, int(horizon_steps))
        self.step_seconds = max(1.0, float(step_seconds))

    def record_event(
        self,
        event_payload: dict[str, Any],
        *,
        pulse_status: dict[str, Any] | None = None,
        atheria_status: dict[str, Any] | None = None,
        mesh_worker_count: int = 0,
        payload_size: int = 0,
    ) -> dict[str, Any]:
        pulse_status = dict(pulse_status or {})
        atheria_status = dict(atheria_status or {})
        dashboard = dict(atheria_status.get("dashboard") or {})
        event = PredictiveTelemetryEvent(
            timestamp=time.time(),
            stage=str(event_payload.get("stage") or ""),
            engine=_engine_from_stage(str(event_payload.get("stage") or "")),
            duration_ms=_safe_float(event_payload.get("duration_ms"), 0.0),
            cpu_percent=_safe_float(event_payload.get("cpu_percent"), 0.0),
            rss_mb=_safe_float(event_payload.get("rss_mb"), 0.0),
            rows_processed=int(_safe_float(event_payload.get("rows_processed"), 0.0)),
            error=str(event_payload.get("error") or ""),
            recent_event_count=int(_safe_float(pulse_status.get("recent_event_count"), 0.0)),
            active_reactive_triggers=int(_safe_float(pulse_status.get("active_reactive_triggers"), 0.0)),
            mesh_worker_count=int(mesh_worker_count),
            system_temperature=_safe_float(dashboard.get("system_temperature"), 25.0),
            structural_tension=_safe_float(dashboard.get("structural_tension"), 0.0),
            guardian_score=_safe_float(dashboard.get("market_guardian_score"), _safe_float(dashboard.get("guardian_score"), 0.0)),
            payload_size=int(payload_size),
        )
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event.to_dict()

    def recent_events(self, *, limit: int = 180) -> list[PredictiveTelemetryEvent]:
        if not self.events_path.exists():
            return []
        rows: list[PredictiveTelemetryEvent] = []
        for raw in self.events_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(PredictiveTelemetryEvent.from_dict(payload))
        return rows[-max(1, int(limit)) :]

    def forecast(self, *, limit: int = 120) -> dict[str, Any]:
        projector_module = load_market_future_projection()
        projector = projector_module.MarketLandscapeFutureProjector(
            latent_dims=3,
            ridge=0.12,
            horizon_steps=self.horizon_steps,
            step_seconds=self.step_seconds,
        )
        telemetry_events = self.recent_events(limit=limit)
        if len(telemetry_events) < 8:
            payload = {
                "status": "insufficient_history",
                "sample_count": len(telemetry_events),
                "min_samples": 8,
                "recent": [event.to_dict() for event in telemetry_events[-8:]],
            }
            self.status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload

        market_events = [self._telemetry_to_market_event(projector_module, telemetry_events, index) for index in range(len(telemetry_events))]
        projection = projector.run(market_events)
        engine_pressure = self._engine_pressure_summary(telemetry_events)
        payload = {
            "status": "ok",
            "sample_count": len(telemetry_events),
            "engine_pressure": engine_pressure,
            "projection": projection,
            "generated_at": round(time.time(), 6),
        }
        self.status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def recommend_engine(
        self,
        task: str,
        payload: str,
        *,
        mesh_available: bool,
        gpu_available: bool,
        heuristic: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        forecast = self.forecast()
        tokens = _tokenize(" ".join([task, payload]))
        loop_heavy = any(token in tokens for token in {"for", "while", "loop", "iterate", "batch"})
        numeric_heavy = any(token in tokens for token in {"matrix", "tensor", "vector", "fft", "convolution", "embedding"})
        training_heavy = any(token in tokens for token in {"atheria", "train", "training", "fit", "epoch"})
        heuristic_scores = {str(key): float(value) for key, value in dict((heuristic or {}).get("scores") or {}).items()}
        scores = {
            "py": max(-5.0, min(4.0, heuristic_scores.get("py", 1.0))),
            "cpp": max(-5.0, min(4.0, heuristic_scores.get("cpp", 1.0))),
            "gpu": max(-5.0, min(4.0, heuristic_scores.get("gpu", 1.0))),
            "mesh": max(-5.0, min(4.0, heuristic_scores.get("mesh", 1.0))),
        }
        reasons = list((heuristic or {}).get("reasons") or [])

        engine_pressure = dict(forecast.get("engine_pressure") or {})
        projection = dict(forecast.get("projection") or {})
        scenarios = dict(dict(projection.get("forecast") or {}).get("scenario_probabilities") or {})
        quality = dict(projection.get("quality") or {})
        stress_up = _safe_float(scenarios.get("stress_up"), 0.0)
        predictability = _safe_float(quality.get("predictability_index"), 0.0)
        pressure = max(
            _safe_float(engine_pressure.get("system_temperature_norm"), 0.0),
            _safe_float(engine_pressure.get("structural_tension"), 0.0),
            stress_up,
        )

        if "insufficient_history" == forecast.get("status"):
            reasons.append("predictive history still warming up; blending with heuristics only")
        else:
            if stress_up >= 0.45:
                scores["py"] -= 0.8 + stress_up
                scores["cpp"] += 0.5 + stress_up
                reasons.append("forecast anticipates rising execution stress")
            if pressure >= 0.65 and mesh_available:
                scores["mesh"] += 0.8 + pressure
                reasons.append("forecasted pressure favors pre-emptive mesh offloading")
            if pressure >= 0.55 and gpu_available and any(token in tokens for token in {"matrix", "tensor", "vector", "fft", "embedding"}):
                scores["gpu"] += 0.7 + pressure
                reasons.append("forecast + numeric signature favor GPU migration")
            if predictability < 0.2:
                reasons.append("predictive confidence is low; recommendation remains conservative")

        if pressure >= 0.72:
            scores["py"] -= 0.75 + (pressure - 0.72)
            scores["cpp"] += 0.3 + max(0.0, pressure - 0.72)
            reasons.append("high projected pressure penalizes interpreter-bound execution")

        if loop_heavy:
            scores["cpp"] += 1.2
            scores["py"] -= 0.9
            reasons.append("loop-heavy workload favors compiled execution")
        if numeric_heavy:
            scores["gpu"] += 1.6
            scores["cpp"] += 0.4
            scores["py"] -= 0.4
            reasons.append("numeric workload signature boosts GPU/C++")
        if training_heavy:
            if mesh_available:
                scores["mesh"] += 1.25
                reasons.append("training workload can be offloaded to available mesh workers")
            scores["gpu"] += 0.4
        if len(payload) > 5000:
            scores["cpp"] += 0.8
            reasons.append("large payload benefits from lower interpreter overhead")
        elif len(payload) < 5000 and (loop_heavy or pressure >= 0.7 or training_heavy):
            scores["py"] -= 1.0
            reasons.append("small payload advantage is overridden by predicted execution pressure")

        if not mesh_available:
            scores["mesh"] = -1e9
        if not gpu_available:
            scores["gpu"] = -1e9

        engine = max(scores, key=scores.get)
        delegated_command, migration_kind = self._delegated_command(engine, task, payload, gpu_available=gpu_available, mesh_available=mesh_available)
        response = {
            "engine": engine,
            "scores": {key: round(value, 6) for key, value in scores.items()},
            "reasons": reasons,
            "forecast": forecast,
            "pressure_index": round(pressure, 6),
            "predictability_index": round(predictability, 6),
            "delegated_command": delegated_command,
            "migration_kind": migration_kind,
        }
        return response

    def _telemetry_to_market_event(self, module: Any, events: list[PredictiveTelemetryEvent], index: int) -> Any:
        current = events[index]
        recent = events[max(0, index - 11) : index + 1]
        durations = [event.duration_ms for event in recent]
        cpus = [event.cpu_percent / 100.0 for event in recent]
        rss_values = [min(1.0, event.rss_mb / 4096.0) for event in recent]
        tension_values = [event.structural_tension for event in recent]
        error_ratio = sum(1 for event in recent if event.error) / max(1, len(recent))
        stage_counts: dict[str, int] = {}
        for event in recent:
            stage_counts[event.engine] = stage_counts.get(event.engine, 0) + 1
        proportions = [count / max(1, len(recent)) for count in stage_counts.values()]
        entropy = 0.0
        for probability in proportions:
            if probability > 1e-9:
                entropy -= probability * math.log(probability)
        entropy = entropy / max(1e-9, math.log(max(2, len(stage_counts))))
        mean_duration = _rolling_mean(durations)
        duration_dispersion = _rolling_std(durations)
        rows_mean = _rolling_mean([float(event.rows_processed) for event in recent]) / 1000.0
        payload_mean = _rolling_mean([float(event.payload_size) for event in recent]) / 100000.0
        resource_pool_log = math.log1p(max(0.0, current.mesh_worker_count + 1.0)) / 12.0
        signal = _clamp(
            0.28 * _clamp(current.cpu_percent / 100.0)
            + 0.18 * _clamp(mean_duration / 250.0)
            + 0.18 * _clamp(current.structural_tension)
            + 0.12 * _clamp(current.system_temperature / 120.0)
            + 0.12 * _clamp(error_ratio)
            + 0.12 * _clamp(1.0 - current.guardian_score),
            -0.2,
            1.8,
        )
        features = [
            _clamp(current.cpu_percent / 100.0),
            _clamp(mean_duration / 250.0),
            _clamp(current.system_temperature / 120.0),
            _clamp(entropy),
            _clamp(current.structural_tension),
            _clamp(current.guardian_score),
            resource_pool_log,
            _clamp(mean_duration / 250.0),
            _clamp(duration_dispersion / 200.0),
            _clamp(_rolling_mean(rss_values)),
            _clamp(abs(_rolling_mean(cpus) - _rolling_mean(tension_values))),
            _clamp(payload_mean),
            _clamp(current.recent_event_count / 200.0),
            _clamp(1.0 - error_ratio),
        ]
        return module.MarketEvent(
            event_id=f"telemetry::{index:04d}",
            timestamp=current.timestamp,
            features=features,
            signal=signal,
            metadata={
                "engine": current.engine,
                "mean_duration_ms": mean_duration,
                "rows_mean": rows_mean,
                "error_ratio": error_ratio,
            },
        )

    def _engine_pressure_summary(self, events: list[PredictiveTelemetryEvent]) -> dict[str, Any]:
        if not events:
            return {}
        recent = events[-min(24, len(events)) :]
        duration_by_engine: dict[str, list[float]] = {}
        for event in recent:
            duration_by_engine.setdefault(event.engine, []).append(event.duration_ms)
        return {
            "recent_event_count": len(recent),
            "mean_duration_ms": round(_rolling_mean([event.duration_ms for event in recent]), 6),
            "mean_cpu_percent": round(_rolling_mean([event.cpu_percent for event in recent]), 6),
            "mean_rss_mb": round(_rolling_mean([event.rss_mb for event in recent]), 6),
            "system_temperature_norm": round(_clamp(recent[-1].system_temperature / 120.0), 6),
            "structural_tension": round(_clamp(recent[-1].structural_tension), 6),
            "guardian_score": round(_clamp(recent[-1].guardian_score), 6),
            "mesh_worker_count": int(recent[-1].mesh_worker_count),
            "engine_duration_ms": {key: round(_rolling_mean(values), 6) for key, values in duration_by_engine.items()},
            "error_ratio": round(sum(1 for event in recent if event.error) / max(1, len(recent)), 6),
        }

    def _delegated_command(
        self,
        engine: str,
        task: str,
        payload: str,
        *,
        gpu_available: bool,
        mesh_available: bool,
    ) -> tuple[str, str]:
        stripped = payload.strip() or task.strip()
        normalized = stripped if stripped.startswith(("py ", "cpp ", "gpu ", "sys ", "mesh ")) else f"py {stripped}"
        body = normalized[3:].strip() if normalized.startswith("py ") else stripped
        if engine == "cpp":
            if self._looks_like_expression_chain(body):
                return f"cpp.expr_chain {body}", "python_to_cpp_chain"
            return f"cpp.expr {body}", "python_to_cpp_expr"
        if engine == "gpu" and gpu_available:
            if any(body.lower().endswith(suffix) for suffix in [".cl", ".opencl"]):
                return f"gpu {body}", "local_gpu_kernel"
            if mesh_available:
                return f"mesh intelligent-run gpu py {json.dumps(body, ensure_ascii=False)}", "mesh_gpu_offload"
            return f"cpp.expr {body}", "gpu_fallback_to_cpp"
        if engine == "mesh" and mesh_available:
            capability = "gpu" if gpu_available and any(token in _tokenize(body) for token in {"matrix", "tensor", "vector", "fft"}) else "cpu"
            return f"mesh intelligent-run {capability} py {json.dumps(body, ensure_ascii=False)}", "predictive_mesh_offload"
        return normalized, "local_python"

    def _looks_like_expression_chain(self, code: str) -> bool:
        stripped = str(code or "").strip()
        if ";" in stripped:
            return True
        if any(token in stripped for token in [" for ", " while ", "\n"]):
            return False
        return any(op in stripped for op in ["+", "-", "*", "/", "%", "math.", "**"])
