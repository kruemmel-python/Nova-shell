from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _rank_tensor(values: torch.Tensor) -> torch.Tensor:
    order = torch.argsort(values)
    rank = torch.zeros_like(values, dtype=torch.float32)
    rank[order] = torch.arange(values.numel(), dtype=torch.float32)
    return rank


@dataclass
class MarketEvent:
    event_id: str
    timestamp: float
    features: List[float]
    signal: float
    metadata: Dict[str, Any]


@dataclass
class LandscapePoint:
    event_id: str
    timestamp: float
    signal: float
    coords: List[float]
    density: float
    regime: str
    mean_return: float
    mean_volatility: float
    mean_imbalance: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": round(self.timestamp, 6),
            "signal": round(self.signal, 6),
            "coords": [round(float(x), 6) for x in self.coords],
            "density": round(self.density, 6),
            "regime": self.regime,
            "mean_return": round(self.mean_return, 6),
            "mean_volatility": round(self.mean_volatility, 6),
            "mean_imbalance": round(self.mean_imbalance, 6),
        }


@dataclass
class ForecastStep:
    step: int
    timestamp_est: float
    signal_mean: float
    signal_lo: float
    signal_hi: float
    confidence: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step": int(self.step),
            "timestamp_est": round(self.timestamp_est, 6),
            "signal_mean": round(self.signal_mean, 6),
            "signal_lo": round(self.signal_lo, 6),
            "signal_hi": round(self.signal_hi, 6),
            "confidence": round(self.confidence, 6),
        }


class MarketLandscapeFutureProjector:
    """
    Forecast module:
    1) maps an information landscape from market/audit traces,
    2) learns one-step dynamics,
    3) projects probabilistic future paths with uncertainty bands.
    """

    def __init__(
        self,
        *,
        latent_dims: int = 3,
        ridge: float = 0.08,
        horizon_steps: int = 12,
        step_seconds: float = 300.0,
    ) -> None:
        self.latent_dims = max(2, int(latent_dims))
        self.ridge = max(1e-6, float(ridge))
        self.horizon_steps = max(1, int(horizon_steps))
        self.step_seconds = max(1.0, float(step_seconds))
        self.feature_names = [
            "trauma_pressure",
            "signal_strength",
            "system_temperature",
            "entropic_index",
            "structural_tension",
            "guardian_score",
            "resource_pool_log",
            "mean_return",
            "return_dispersion",
            "mean_volatility",
            "mean_abs_imbalance",
            "mean_volume_log",
            "market_activity",
            "snapshot_quality",
        ]

    def _stack_features(self, events: Sequence[MarketEvent]) -> torch.Tensor:
        if not events:
            raise ValueError("no_events")
        width = max(len(event.features) for event in events)
        if width <= 0:
            raise ValueError("empty_features")
        rows: List[List[float]] = []
        for event in events:
            row = [_safe_float(item, 0.0) for item in event.features]
            if len(row) < width:
                row.extend([0.0] * (width - len(row)))
            rows.append(row[:width])
        return torch.tensor(rows, dtype=torch.float32)

    def _latent_coords(self, matrix: torch.Tensor) -> Tuple[torch.Tensor, float]:
        means = torch.mean(matrix, dim=0, keepdim=True)
        stds = torch.std(matrix, dim=0, keepdim=True, unbiased=False)
        standardized = (matrix - means) / torch.clamp(stds, min=1e-6)
        u, s, vh = torch.linalg.svd(standardized, full_matrices=False)

        dims = min(self.latent_dims, int(vh.shape[0]))
        basis = vh[:dims].T
        coords = standardized @ basis
        if dims < 3:
            pad = torch.zeros((coords.shape[0], 3 - dims), dtype=torch.float32)
            coords = torch.cat([coords, pad], dim=1)
        else:
            coords = coords[:, :3]

        radius = torch.max(torch.linalg.norm(coords, dim=1))
        coords = coords / max(1e-6, float(radius.item()))
        explained = 0.0
        if s.numel() > 0:
            total = torch.sum(torch.square(s)) + 1e-9
            explained = float((torch.sum(torch.square(s[:dims])) / total).item())
        return coords, _clamp(explained, 0.0, 1.0)

    def _densities(self, coords: torch.Tensor, *, neighbors: int = 6) -> torch.Tensor:
        n = int(coords.shape[0])
        if n <= 1:
            return torch.ones(n, dtype=torch.float32)
        dmat = torch.cdist(coords, coords, p=2)
        values, _ = torch.sort(dmat, dim=1)
        k = max(1, min(neighbors, n - 1))
        local = torch.mean(values[:, 1 : k + 1], dim=1)
        return 1.0 / torch.clamp(local, min=1e-4)

    def _regime_labels(self, signal: torch.Tensor) -> Tuple[List[str], Dict[str, float]]:
        sorted_signal, _ = torch.sort(signal)
        n = int(signal.numel())
        if n == 0:
            return [], {"q33": 0.0, "q66": 0.0}
        i33 = int(max(0, min(n - 1, round((n - 1) * 0.33))))
        i66 = int(max(0, min(n - 1, round((n - 1) * 0.66))))
        q33 = float(sorted_signal[i33].item())
        q66 = float(sorted_signal[i66].item())
        labels: List[str] = []
        for value in signal.tolist():
            v = float(value)
            if v <= q33:
                labels.append("calm")
            elif v >= q66:
                labels.append("stress")
            else:
                labels.append("transition")
        return labels, {"q33": q33, "q66": q66}

    def _regime_stability(self, labels: Sequence[str]) -> float:
        if len(labels) <= 1:
            return 0.0
        same = 0
        total = 0
        for idx in range(1, len(labels)):
            total += 1
            if labels[idx] == labels[idx - 1]:
                same += 1
        return same / max(1, total)

    def _transition_entropy(self, labels: Sequence[str]) -> float:
        if len(labels) <= 1:
            return 0.0
        mapping = {"calm": 0, "transition": 1, "stress": 2}
        counts = torch.zeros((3, 3), dtype=torch.float32)
        for idx in range(1, len(labels)):
            a = mapping.get(labels[idx - 1], 1)
            b = mapping.get(labels[idx], 1)
            counts[a, b] += 1.0
        row_sum = torch.sum(counts, dim=1, keepdim=True)
        probs = counts / torch.clamp(row_sum, min=1e-9)
        p = torch.clamp(probs, min=1e-12)
        entropy = -torch.sum(probs * torch.log(p))
        return float((entropy / math.log(3.0 * 3.0 + 1e-9)).item())

    def _build_training(
        self,
        features: torch.Tensor,
        signal: torch.Tensor,
        coords: torch.Tensor,
        density: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, List[str]]:
        n = int(features.shape[0])
        if n < 8:
            raise ValueError("need_at_least_8_events_for_forecast")

        rows: List[torch.Tensor] = []
        targets: List[float] = []
        names = (
            ["bias", "signal_t", "delta_signal_t"]
            + [f"f_{name}" for name in self.feature_names[: int(features.shape[1])]]
            + ["coord_x", "coord_y", "coord_z", "density"]
        )
        for t in range(1, n - 1):
            delta = float(signal[t].item() - signal[t - 1].item())
            x = torch.cat(
                [
                    torch.tensor([1.0, float(signal[t].item()), delta], dtype=torch.float32),
                    features[t],
                    coords[t],
                    torch.tensor([float(density[t].item())], dtype=torch.float32),
                ]
            )
            rows.append(x)
            targets.append(float(signal[t + 1].item()))
        x_mat = torch.stack(rows, dim=0)
        y_vec = torch.tensor(targets, dtype=torch.float32)
        return x_mat, y_vec, names

    def _fit_ridge(self, x: torch.Tensor, y: torch.Tensor) -> Tuple[torch.Tensor, Dict[str, float]]:
        cols = int(x.shape[1])
        eye = torch.eye(cols, dtype=torch.float32) * self.ridge
        eye[0, 0] = 1e-6
        xtx = x.T @ x + eye
        xty = x.T @ y
        w = torch.linalg.solve(xtx, xty)
        pred = x @ w
        resid = y - pred

        mae = float(torch.mean(torch.abs(resid)).item())
        rmse = float(torch.sqrt(torch.mean(torch.square(resid))).item())
        y_mean = torch.mean(y)
        ss_res = torch.sum(torch.square(resid))
        ss_tot = torch.sum(torch.square(y - y_mean)) + 1e-9
        r2 = float((1.0 - (ss_res / ss_tot)).item())
        residual_std = float(torch.std(resid).item()) if resid.numel() > 1 else 0.02
        return w, {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "residual_std": max(1e-5, residual_std),
        }

    def _forecast(
        self,
        *,
        weights: torch.Tensor,
        last_signal: float,
        last_delta: float,
        last_features: torch.Tensor,
        last_coords: torch.Tensor,
        last_density: float,
        residual_std: float,
        last_timestamp: float,
    ) -> List[ForecastStep]:
        signal = float(last_signal)
        delta = float(last_delta)
        steps: List[ForecastStep] = []
        for step in range(1, self.horizon_steps + 1):
            x = torch.cat(
                [
                    torch.tensor([1.0, signal, delta], dtype=torch.float32),
                    last_features,
                    last_coords,
                    torch.tensor([last_density], dtype=torch.float32),
                ]
            )
            mean = float(torch.dot(x, weights).item())
            mean = _clamp(mean, -0.2, 1.8)
            sigma = max(1e-4, residual_std * math.sqrt(step))
            lo = mean - 1.64 * sigma
            hi = mean + 1.64 * sigma
            conf = _clamp(math.exp(-sigma * 2.8), 0.05, 0.99)
            steps.append(
                ForecastStep(
                    step=step,
                    timestamp_est=float(last_timestamp + self.step_seconds * step),
                    signal_mean=mean,
                    signal_lo=lo,
                    signal_hi=hi,
                    confidence=conf,
                )
            )

            next_delta = mean - signal
            delta = 0.62 * delta + 0.38 * next_delta
            signal = mean
        return steps

    def _scenario_probabilities(self, current_signal: float, forecast: Sequence[ForecastStep]) -> Dict[str, float]:
        if not forecast:
            return {"stress_up": 0.0, "sideways": 1.0, "stress_down": 0.0}
        last = forecast[-1]
        delta_mean = float(last.signal_mean - current_signal)
        sigma = max(1e-4, float((last.signal_hi - last.signal_lo) / (2.0 * 1.64)))
        threshold = 0.03
        z_lo = (-threshold - delta_mean) / sigma
        z_hi = (threshold - delta_mean) / sigma
        p_down = _normal_cdf(z_lo)
        p_up = 1.0 - _normal_cdf(z_hi)
        p_flat = 1.0 - p_down - p_up
        return {
            "stress_up": round(_clamp(p_up, 0.0, 1.0), 6),
            "sideways": round(_clamp(p_flat, 0.0, 1.0), 6),
            "stress_down": round(_clamp(p_down, 0.0, 1.0), 6),
        }

    def _top_drivers(self, weights: torch.Tensor, names: Sequence[str], *, top_k: int = 10) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for idx in range(1, min(len(names), int(weights.numel()))):
            name = str(names[idx])
            value = float(weights[idx].item())
            rows.append({"feature": name, "weight": round(value, 6), "abs_weight": abs(value)})
        rows.sort(key=lambda item: float(item["abs_weight"]), reverse=True)
        return [{"feature": row["feature"], "weight": row["weight"]} for row in rows[: max(3, int(top_k))]]

    def _predictability_index(self, *, r2: float, residual_std: float, regime_stability: float, n: int) -> float:
        r2_norm = _clamp((r2 + 0.2) / 0.9, 0.0, 1.0)
        noise_norm = _clamp(1.0 - residual_std / 0.22, 0.0, 1.0)
        sample_norm = _clamp((float(n) - 12.0) / 120.0, 0.0, 1.0)
        score = 0.42 * r2_norm + 0.22 * noise_norm + 0.2 * regime_stability + 0.16 * sample_norm
        return _clamp(score, 0.0, 1.0)

    def run(self, events: Sequence[MarketEvent]) -> Dict[str, Any]:
        if not events:
            raise ValueError("no_events")
        features = self._stack_features(events)
        signal = torch.tensor([_safe_float(event.signal, 0.0) for event in events], dtype=torch.float32)
        timestamps = torch.tensor([_safe_float(event.timestamp, 0.0) for event in events], dtype=torch.float32)
        coords, explained = self._latent_coords(features)
        density = self._densities(coords)
        labels, cut = self._regime_labels(signal)
        regime_stability = self._regime_stability(labels)
        transition_entropy = self._transition_entropy(labels)
        n = len(events)
        signal_std = float(torch.std(signal).item()) if signal.numel() > 1 else 0.0
        flat_signal = bool(signal_std <= 1e-5)
        signal_mode_counts: Dict[str, int] = {}
        for event in events:
            meta = dict(event.metadata or {})
            mode = str(meta.get("signal_mode") or "market_snapshot")
            signal_mode_counts[mode] = int(signal_mode_counts.get(mode, 0)) + 1
        market_signal_count = int(signal_mode_counts.get("market_snapshot", 0))
        proxy_signal_count = int(signal_mode_counts.get("dashboard_proxy", 0))
        market_signal_ratio = float(market_signal_count / max(1, n))
        proxy_signal_ratio = float(proxy_signal_count / max(1, n))
        last_signal = float(signal[-1].item())
        last_delta = float(signal[-1].item() - signal[-2].item()) if signal.numel() >= 2 else 0.0
        metrics: Dict[str, float]
        forecast: List[ForecastStep]
        scenarios: Dict[str, float]
        top_drivers: List[Dict[str, Any]]
        proof_verdict: str
        statement: str

        if n < 8:
            volatility_proxy = float(torch.std(signal).item()) if signal.numel() > 1 else 0.06
            residual_std = max(0.035, volatility_proxy)
            forecast = []
            for step in range(1, self.horizon_steps + 1):
                sigma = max(1e-4, residual_std * math.sqrt(step) + 0.03)
                mean = _clamp(last_signal, -0.2, 1.8)
                forecast.append(
                    ForecastStep(
                        step=step,
                        timestamp_est=float(timestamps[-1].item() + self.step_seconds * step),
                        signal_mean=mean,
                        signal_lo=mean - 1.64 * sigma,
                        signal_hi=mean + 1.64 * sigma,
                        confidence=_clamp(math.exp(-sigma * 3.3), 0.05, 0.82),
                    )
                )
            scenarios = self._scenario_probabilities(last_signal, forecast)

            driver_rows: List[Dict[str, Any]] = []
            max_features = min(int(features.shape[1]), len(self.feature_names))
            for idx in range(max_features):
                col = features[:, idx]
                score = float(torch.std(col).item()) if col.numel() > 1 else abs(float(col[0].item()))
                driver_rows.append(
                    {
                        "feature": "f_" + str(self.feature_names[idx]),
                        "weight": round(score, 6),
                        "abs_weight": abs(score),
                    }
                )
            driver_rows.sort(key=lambda item: float(item["abs_weight"]), reverse=True)
            top_drivers = [
                {"feature": row["feature"], "weight": row["weight"]}
                for row in driver_rows[: max(3, min(10, len(driver_rows)))]
            ]

            mae = abs(last_delta) if n > 1 else abs(last_signal)
            metrics = {
                "mae": float(mae),
                "rmse": float(mae),
                "r2": 0.0,
                "residual_std": float(residual_std),
            }
            proof_verdict = "Weak"
            statement = "Zu wenige Events fuer robustes Training. Das Modul liefert nur eine konservative Baseline-Projektion."
            notes: List[str] = []
            if flat_signal:
                notes.append("Das Zielsignal ist nahezu konstant.")
            if int(signal_mode_counts.get("dashboard_proxy", 0)) > 0:
                notes.append("Marktdatenpakete fehlen; Signal wurde teilweise aus Dashboard-Proxies approximiert.")
            if notes:
                statement = statement + " " + " ".join(notes)
        else:
            x_train, y_train, driver_names = self._build_training(features, signal, coords, density)
            weights, metrics = self._fit_ridge(x_train, y_train)
            forecast = self._forecast(
                weights=weights,
                last_signal=last_signal,
                last_delta=last_delta,
                last_features=features[-1],
                last_coords=coords[-1],
                last_density=float(density[-1].item()),
                residual_std=metrics["residual_std"],
                last_timestamp=float(timestamps[-1].item()),
            )
            scenarios = self._scenario_probabilities(last_signal, forecast)
            top_drivers = self._top_drivers(weights, driver_names, top_k=10)

            if flat_signal:
                floor = max(abs(last_delta), 1e-4)
                metrics["mae"] = max(float(metrics["mae"]), floor)
                metrics["rmse"] = max(float(metrics["rmse"]), floor)
                metrics["r2"] = min(float(metrics["r2"]), 0.0)
                metrics["residual_std"] = max(float(metrics["residual_std"]), floor * 0.75)

            predictability_for_gate = self._predictability_index(
                r2=metrics["r2"],
                residual_std=metrics["residual_std"],
                regime_stability=regime_stability,
                n=n,
            )
            min_market_events = max(4, int(math.ceil(0.2 * float(n))))
            if market_signal_count < min_market_events:
                proof_verdict = "Weak"
                statement = "Noch schwach: Zu wenig direkte Marktsnapshots fuer belastbare Prognoseguete; Ergebnis basiert ueberwiegend auf Dashboard-Proxies."
            elif flat_signal:
                proof_verdict = "Weak"
                statement = "Noch schwach: Das Zielsignal ist nahezu konstant; belastbare Prognoseguete ist nicht nachweisbar."
            elif n >= 40 and predictability_for_gate >= 0.67 and metrics["r2"] >= 0.3:
                proof_verdict = "Verified"
                statement = "Ja, bedingt: Die Landschaft erlaubt robuste probabilistische Kurzfristprognosen."
            elif n >= 20 and predictability_for_gate >= 0.45 and metrics["r2"] >= 0.12:
                proof_verdict = "Partial"
                statement = "Teilweise: Die Landschaft liefert nutzbare, aber noch begrenzt stabile Prognosesignale."
            else:
                proof_verdict = "Weak"
                statement = "Noch schwach: Mehr Daten oder klarere Marktstruktur sind noetig."

        points: List[LandscapePoint] = []
        for idx, event in enumerate(events):
            meta = dict(event.metadata or {})
            points.append(
                LandscapePoint(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    signal=event.signal,
                    coords=[float(v) for v in coords[idx].tolist()],
                    density=float(density[idx].item()),
                    regime=labels[idx] if idx < len(labels) else "transition",
                    mean_return=_safe_float(meta.get("mean_return"), 0.0),
                    mean_volatility=_safe_float(meta.get("mean_volatility"), 0.0),
                    mean_imbalance=_safe_float(meta.get("mean_imbalance"), 0.0),
                )
            )

        regime_counts = {"calm": 0, "transition": 0, "stress": 0}
        regime_signal = {"calm": [], "transition": [], "stress": []}
        for point in points:
            regime_counts[point.regime] = regime_counts.get(point.regime, 0) + 1
            regime_signal.setdefault(point.regime, []).append(point.signal)

        regimes = []
        for name in ("calm", "transition", "stress"):
            values = regime_signal.get(name, [])
            regimes.append(
                {
                    "name": name,
                    "count": int(regime_counts.get(name, 0)),
                    "mean_signal": round(sum(values) / max(1, len(values)), 6) if values else 0.0,
                }
            )

        predictability = self._predictability_index(
            r2=metrics["r2"],
            residual_std=metrics["residual_std"],
            regime_stability=regime_stability,
            n=n,
        )
        if n < 8:
            predictability = _clamp(predictability * 0.55, 0.0, 0.35)
        coverage_factor = _clamp(0.25 + 0.75 * market_signal_ratio, 0.25, 1.0)
        predictability = _clamp(predictability * coverage_factor, 0.0, 1.0)

        now_ts = float(timestamps[-1].item())
        answer_strength = round(float(predictability), 6)
        answer_text = (
            "Ja, aber nur probabilistisch. Die kartierte Informationslandschaft erhoeht die Vorhersagbarkeit, "
            "liefert jedoch keine deterministische Zukunft."
        )

        payload = {
            "question": "Kann man die Zukunft vorhersagen, wenn man die Landschaft der Marktinformationen kartieren kann?",
            "answer": answer_text,
            "answer_strength": answer_strength,
            "created_at": now_ts,
            "landscape": {
                "points": [point.as_dict() for point in points],
                "regimes": regimes,
                "topology": {
                    "latent_dims": 3,
                    "explained_variance": round(explained, 6),
                    "regime_stability": round(regime_stability, 6),
                    "transition_entropy": round(transition_entropy, 6),
                    "q33_signal": round(cut.get("q33", 0.0), 6),
                    "q66_signal": round(cut.get("q66", 0.0), 6),
                },
            },
            "forecast": {
                "horizon_steps": self.horizon_steps,
                "step_seconds": self.step_seconds,
                "series": [step.as_dict() for step in forecast],
                "scenario_probabilities": scenarios,
                "drivers": top_drivers,
            },
            "quality": {
                "sample_count": n,
                "r2_one_step": round(float(metrics["r2"]), 6),
                "mae_one_step": round(float(metrics["mae"]), 6),
                "rmse_one_step": round(float(metrics["rmse"]), 6),
                "residual_std": round(float(metrics["residual_std"]), 6),
                "regime_stability": round(float(regime_stability), 6),
                "predictability_index": round(float(predictability), 6),
                "has_supervised_fit": bool(n >= 8),
                "min_events_for_supervised_fit": 8,
                "events_missing_for_supervised_fit": max(0, 8 - n),
                "signal_std": round(float(signal_std), 6),
                "flat_signal": bool(flat_signal),
                "signal_mode_counts": signal_mode_counts,
                "market_signal_count": int(market_signal_count),
                "proxy_signal_count": int(proxy_signal_count),
                "market_signal_ratio": round(float(market_signal_ratio), 6),
                "proxy_signal_ratio": round(float(proxy_signal_ratio), 6),
                "proof_verdict": proof_verdict,
                "statement": statement,
            },
        }
        return payload


def _extract_symbol_rows(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    symbols = dict(snapshot.get("symbols") or {})
    rows: List[Dict[str, Any]] = []
    for key in sorted(symbols.keys()):
        row = dict(symbols.get(key) or {})
        rows.append(row)
    return rows


def daemon_entry_to_event(entry: Dict[str, Any], index: int) -> MarketEvent:
    market = dict(entry.get("market") or {})
    dashboard = dict(entry.get("dashboard") or {})
    snapshot = dict(market.get("last_market_snapshot") or {})
    rows = _extract_symbol_rows(snapshot)

    returns = [_safe_float(row.get("recent_return"), _safe_float(row.get("price_change_pct"), 0.0) / 100.0) for row in rows]
    vols = [_safe_float(row.get("volatility"), 0.0) for row in rows]
    imbs = [_safe_float(row.get("orderbook_imbalance"), 0.0) for row in rows]
    vols_1m = [_safe_float(row.get("volume_1m"), 0.0) for row in rows]

    if returns:
        mean_ret = float(sum(returns) / len(returns))
        ret_disp = float(torch.std(torch.tensor(returns, dtype=torch.float32)).item()) if len(returns) > 1 else 0.0
    else:
        mean_ret = 0.0
        ret_disp = 0.0
    mean_vol = float(sum(vols) / len(vols)) if vols else 0.0
    mean_abs_imb = float(sum(abs(v) for v in imbs) / len(imbs)) if imbs else 0.0
    mean_volume_log = float(sum(math.log1p(max(0.0, v)) for v in vols_1m) / max(1, len(vols_1m))) / 12.0

    trauma = _safe_float(market.get("trauma_pressure"), 0.0)
    signal_strength = _safe_float(market.get("last_signal_strength"), 0.0)
    system_temp = _safe_float(dashboard.get("system_temperature"), 25.0) / 120.0
    entropic_index = _safe_float(dashboard.get("entropic_index"), 0.0)
    structural_tension = _safe_float(dashboard.get("structural_tension"), 0.0)
    guardian = _safe_float(dashboard.get("market_guardian_score"), 0.0)
    resource_log = math.log1p(max(0.0, _safe_float(dashboard.get("resource_pool"), 0.0))) / 12.0
    market_activity = _safe_float(market.get("samples_ingested"), 0.0) / 120.0
    snapshot_quality = _safe_float(market.get("last_packet_quality"), 0.0)

    features = [
        trauma,
        signal_strength,
        system_temp,
        entropic_index,
        structural_tension,
        guardian,
        resource_log,
        mean_ret,
        ret_disp,
        mean_vol,
        mean_abs_imb,
        mean_volume_log,
        market_activity,
        snapshot_quality,
    ]

    has_snapshot_rows = bool(rows)
    has_market_activity = _safe_float(market.get("samples_ingested"), 0.0) > 0.0
    has_raw_market_features = bool(returns) or bool(vols) or bool(imbs)
    use_market_signal = bool(has_raw_market_features and (has_snapshot_rows or has_market_activity))

    if use_market_signal:
        signal = (
            0.48 * trauma
            + 0.24 * max(0.0, mean_vol)
            + 0.18 * mean_abs_imb
            + 0.10 * max(0.0, -mean_ret)
        )
        signal_mode = "market_snapshot"
    else:
        selection_pressure = _safe_float(dashboard.get("selection_pressure"), 0.34)
        entropy_pressure = _clamp((entropic_index - 0.2) / 0.8, 0.0, 1.0)
        temperature_pressure = _clamp((system_temp - (25.0 / 120.0)) / 0.75, 0.0, 1.0)
        signal = (
            0.42 * max(0.0, structural_tension)
            + 0.24 * entropy_pressure
            + 0.20 * temperature_pressure
            + 0.14 * max(0.0, selection_pressure - 0.34)
        )
        signal_mode = "dashboard_proxy"
    signal = _clamp(signal, -0.2, 1.8)

    timestamp = _safe_float(entry.get("timestamp"), float(index))
    reason = str(entry.get("reason") or "event")
    event_id = reason + f"::{index:04d}"
    metadata = {
        "mean_return": mean_ret,
        "mean_volatility": mean_vol,
        "mean_imbalance": mean_abs_imb,
        "symbol_count": len(rows),
        "signal_mode": signal_mode,
        "snapshot_rows": len(rows),
    }
    return MarketEvent(
        event_id=event_id,
        timestamp=timestamp,
        features=[_safe_float(v, 0.0) for v in features],
        signal=signal,
        metadata=metadata,
    )


def load_events_from_jsonl(path: Path, *, limit: int = 220) -> List[MarketEvent]:
    if not path.exists():
        raise FileNotFoundError(f"jsonl_not_found:{path}")
    rows: List[Dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    if not rows:
        raise ValueError("jsonl_has_no_valid_rows")
    selected = rows[-max(8, int(limit)) :]
    return [daemon_entry_to_event(entry, idx) for idx, entry in enumerate(selected)]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atheria_market_future_projection.py",
        description="Maps market information landscapes and produces probabilistic future projections.",
    )
    parser.add_argument(
        "--report-file",
        default="daemon_runtime/atheria_daemon_audit.jsonl",
        help="Input JSONL source from atheria_daemon audit logs.",
    )
    parser.add_argument("--limit", type=int, default=180, help="Recent row count used for projection.")
    parser.add_argument("--horizon-steps", type=int, default=12, help="Future forecast steps.")
    parser.add_argument("--step-seconds", type=float, default=300.0, help="Seconds between forecast steps.")
    parser.add_argument("--ridge", type=float, default=0.08, help="Ridge regularization.")
    parser.add_argument("--json-out", default=None, help="Optional path to write projection JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print full JSON to stdout.")
    return parser


def _summary_text(payload: Dict[str, Any]) -> str:
    quality = dict(payload.get("quality") or {})
    forecast = dict(payload.get("forecast") or {})
    scenarios = dict(forecast.get("scenario_probabilities") or {})
    return (
        "Atheria Market Future Projection\n"
        f"Samples: {int(_safe_float(quality.get('sample_count'), 0))}\n"
        f"Predictability index: {_safe_float(quality.get('predictability_index'), 0.0):.4f}\n"
        f"R2 (one-step): {_safe_float(quality.get('r2_one_step'), 0.0):.4f}\n"
        f"Proof verdict: {quality.get('proof_verdict', 'Weak')}\n"
        f"Stress-up probability: {_safe_float(scenarios.get('stress_up'), 0.0):.4f}\n"
        f"Sideways probability: {_safe_float(scenarios.get('sideways'), 0.0):.4f}\n"
        f"Stress-down probability: {_safe_float(scenarios.get('stress_down'), 0.0):.4f}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    events = load_events_from_jsonl(Path(str(args.report_file)), limit=max(8, int(args.limit)))
    projector = MarketLandscapeFutureProjector(
        latent_dims=3,
        ridge=max(1e-6, float(args.ridge)),
        horizon_steps=max(1, int(args.horizon_steps)),
        step_seconds=max(1.0, float(args.step_seconds)),
    )
    payload = projector.run(events)

    if args.json_out:
        out_path = Path(str(args.json_out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.pretty):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_summary_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
