from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
from torch import nn

from atheria_market_future_projection import MarketEvent, MarketLandscapeFutureProjector, load_events_from_jsonl


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    z = float(value)
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _std(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    tensor = torch.tensor([float(v) for v in values], dtype=torch.float32)
    return float(torch.std(tensor, unbiased=False).item())


def _gaussian_scenario_probs(delta_mean: float, sigma: float, threshold: float) -> Dict[str, float]:
    sigma_safe = max(1e-4, float(sigma))
    z_lo = (-threshold - float(delta_mean)) / sigma_safe
    z_hi = (threshold - float(delta_mean)) / sigma_safe
    p_down = _normal_cdf(z_lo)
    p_up = 1.0 - _normal_cdf(z_hi)
    p_sideways = _clamp(1.0 - p_down - p_up, 0.0, 1.0)
    total = max(1e-9, p_up + p_sideways + p_down)
    return {
        "stress_up": float(p_up / total),
        "sideways": float(p_sideways / total),
        "stress_down": float(p_down / total),
    }


def _target_label(delta: float, threshold: float) -> str:
    d = float(delta)
    if d >= threshold:
        return "stress_up"
    if d <= -threshold:
        return "stress_down"
    return "sideways"


def _brier_multi(prob_rows: Sequence[Dict[str, float]], targets: Sequence[str]) -> float:
    if not prob_rows:
        return 0.0
    keys = ("stress_up", "sideways", "stress_down")
    total = 0.0
    for probs, target in zip(prob_rows, targets):
        row = 0.0
        for key in keys:
            o = 1.0 if key == target else 0.0
            p = _clamp(_safe_float(probs.get(key), 0.0), 0.0, 1.0)
            row += (p - o) ** 2
        total += row / 3.0
    return total / max(1, len(prob_rows))


def _crps_gaussian(mu: float, sigma: float, y: float) -> float:
    sigma_safe = max(1e-4, float(sigma))
    z = (float(y) - float(mu)) / sigma_safe
    phi = _normal_pdf(z)
    cdf = _normal_cdf(z)
    return sigma_safe * (z * (2.0 * cdf - 1.0) + 2.0 * phi - 1.0 / math.sqrt(math.pi))


def _metrics(y_true: Sequence[float], y_pred: Sequence[float], sigma: Sequence[float], probs: Sequence[Dict[str, float]], last_values: Sequence[float], threshold: float) -> Dict[str, Any]:
    n = len(y_true)
    if n == 0:
        return {
            "mae": 0.0,
            "rmse": 0.0,
            "r2": None,
            "r2_defined": False,
            "directional_accuracy": 0.0,
            "brier": 0.0,
            "crps_gaussian": 0.0,
        }
    abs_errors = [abs(float(a) - float(b)) for a, b in zip(y_true, y_pred)]
    sq_errors = [(float(a) - float(b)) ** 2 for a, b in zip(y_true, y_pred)]
    mae = sum(abs_errors) / n
    rmse = math.sqrt(sum(sq_errors) / n)
    y_mean = sum(float(v) for v in y_true) / n
    ss_tot = sum((float(v) - y_mean) ** 2 for v in y_true)
    ss_res = sum(sq_errors)
    if ss_tot <= 1e-12:
        r2: Optional[float] = None
        r2_defined = False
    else:
        r2 = 1.0 - (ss_res / ss_tot)
        r2_defined = True

    target_labels = []
    pred_labels = []
    for actual, pred, last in zip(y_true, y_pred, last_values):
        target_labels.append(_target_label(float(actual) - float(last), threshold))
        pred_labels.append(_target_label(float(pred) - float(last), threshold))
    directional = sum(1 for a, b in zip(target_labels, pred_labels) if a == b) / n
    brier = _brier_multi(probs, target_labels)
    crps = sum(_crps_gaussian(mu=pred, sigma=sig, y=actual) for actual, pred, sig in zip(y_true, y_pred, sigma)) / n
    return {
        "mae": round(float(mae), 6),
        "rmse": round(float(rmse), 6),
        "r2": (round(float(r2), 6) if r2 is not None else None),
        "r2_defined": bool(r2_defined),
        "directional_accuracy": round(float(directional), 6),
        "brier": round(float(brier), 6),
        "crps_gaussian": round(float(crps), 6),
    }


def _append_row(rows: Dict[str, Dict[str, List[Any]]], model: str, *, y_true: float, y_pred: float, sigma: float, probs: Dict[str, float], last_value: float) -> None:
    bucket = rows.setdefault(
        model,
        {"y_true": [], "y_pred": [], "sigma": [], "probs": [], "last": []},
    )
    bucket["y_true"].append(float(y_true))
    bucket["y_pred"].append(float(y_pred))
    bucket["sigma"].append(max(1e-4, float(sigma)))
    bucket["probs"].append(dict(probs))
    bucket["last"].append(float(last_value))


def _random_forecast(train: Sequence[float], *, generator: torch.Generator) -> Tuple[float, float]:
    last = float(train[-1])
    sigma = max(0.02, _std(train))
    noise = float(torch.randn((), generator=generator).item()) * sigma
    return last + noise, sigma


def _arima_110_forecast(train: Sequence[float]) -> Tuple[float, float]:
    values = torch.tensor([float(v) for v in train], dtype=torch.float32)
    if values.numel() < 5:
        sigma = max(0.02, _std(train))
        return float(values[-1].item()), sigma
    diff = values[1:] - values[:-1]
    if diff.numel() < 3:
        sigma = max(0.02, float(torch.std(diff, unbiased=False).item()) if diff.numel() > 1 else 0.02)
        return float(values[-1].item()), sigma
    x = torch.stack([torch.ones(diff.numel() - 1, dtype=torch.float32), diff[:-1]], dim=1)
    y = diff[1:]
    ridge = torch.eye(2, dtype=torch.float32) * 1e-6
    beta = torch.linalg.solve(x.T @ x + ridge, x.T @ y)
    next_diff = float((beta[0] + beta[1] * diff[-1]).item())
    pred = float(values[-1].item() + next_diff)
    resid = y - (x @ beta)
    sigma = float(torch.std(resid, unbiased=False).item()) if resid.numel() > 1 else float(torch.std(diff, unbiased=False).item())
    sigma = max(1e-4, sigma)
    return pred, sigma


def _garch_11_forecast(train: Sequence[float]) -> Tuple[float, float]:
    values = torch.tensor([float(v) for v in train], dtype=torch.float32)
    if values.numel() < 8:
        sigma = max(0.02, _std(train))
        return float(values[-1].item()), sigma
    returns = values[1:] - values[:-1]
    mu = float(torch.mean(returns).item())
    centered = returns - mu
    base_var = float(torch.mean(torch.square(centered)).item())
    base_var = max(1e-8, base_var)
    grid = [
        (0.05, 0.70),
        (0.08, 0.78),
        (0.10, 0.82),
        (0.12, 0.84),
        (0.15, 0.80),
        (0.18, 0.76),
    ]
    best = None
    best_ll = -1e18
    eps = 1e-8
    for alpha, beta in grid:
        if alpha + beta >= 0.98:
            continue
        omega = base_var * (1.0 - alpha - beta)
        h = torch.empty_like(centered)
        h[0] = base_var
        for idx in range(1, centered.numel()):
            h[idx] = omega + alpha * torch.square(centered[idx - 1]) + beta * h[idx - 1]
            h[idx] = torch.clamp(h[idx], min=eps)
        ll = -0.5 * torch.sum(torch.log(h + eps) + torch.square(centered) / (h + eps))
        score = float(ll.item())
        if score > best_ll:
            best_ll = score
            best = (alpha, beta, omega, h)
    if best is None:
        sigma = math.sqrt(base_var)
        return float(values[-1].item()), max(1e-4, sigma)
    alpha, beta, omega, h = best
    next_h = float(omega + alpha * float(centered[-1].item() ** 2) + beta * float(h[-1].item()))
    next_h = max(1e-8, next_h)
    sigma = math.sqrt(next_h)
    last_centered = float(centered[-1].item())
    momentum = 0.10 * (1.0 if last_centered >= 0.0 else -1.0) * sigma
    pred = float(values[-1].item() + mu + momentum)
    return pred, max(1e-4, sigma)


class _TinyTransformer(nn.Module):
    def __init__(self, lookback: int, d_model: int = 16, nhead: int = 4, ff: int = 48, layers: int = 1) -> None:
        super().__init__()
        self.lookback = max(4, int(lookback))
        self.in_proj = nn.Linear(1, d_model)
        self.pos = nn.Parameter(torch.zeros(1, self.lookback, d_model))
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=ff,
            dropout=0.0,
            activation="gelu",
            batch_first=True,
            norm_first=False,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=max(1, int(layers)))
        self.out = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        length = int(x.shape[1])
        h = self.in_proj(x) + self.pos[:, :length, :]
        z = self.encoder(h)
        return self.out(z[:, -1, :]).squeeze(-1)


@dataclass
class _TransformerState:
    model: Optional[_TinyTransformer]
    mean: float
    std: float
    residual_std: float
    last_refit_fold: int
    lookback: int


class _TransformerBaseline:
    def __init__(self, *, lookback: int = 12, epochs: int = 32, refit_every: int = 6, lr: float = 0.01) -> None:
        self.lookback = max(6, int(lookback))
        self.epochs = max(8, int(epochs))
        self.refit_every = max(1, int(refit_every))
        self.lr = max(1e-4, float(lr))
        self.state = _TransformerState(
            model=None,
            mean=0.0,
            std=1.0,
            residual_std=0.15,
            last_refit_fold=-1,
            lookback=self.lookback,
        )

    def _dataset(self, train: Sequence[float]) -> Tuple[torch.Tensor, torch.Tensor, float, float]:
        values = torch.tensor([float(v) for v in train], dtype=torch.float32)
        mean = float(torch.mean(values).item())
        std = float(torch.std(values, unbiased=False).item())
        std = max(1e-4, std)
        z = (values - mean) / std
        xs: List[torch.Tensor] = []
        ys: List[torch.Tensor] = []
        for end in range(self.lookback, z.numel()):
            xs.append(z[end - self.lookback : end].unsqueeze(-1))
            ys.append(z[end])
        if not xs:
            return torch.empty((0, self.lookback, 1), dtype=torch.float32), torch.empty((0,), dtype=torch.float32), mean, std
        return torch.stack(xs, dim=0), torch.stack(ys, dim=0), mean, std

    def _fit(self, train: Sequence[float], fold_idx: int) -> None:
        x, y, mean, std = self._dataset(train)
        if x.numel() == 0 or y.numel() < 6:
            self.state.model = None
            self.state.mean = mean
            self.state.std = std
            self.state.residual_std = max(0.08, _std(train))
            self.state.last_refit_fold = fold_idx
            return
        model = _TinyTransformer(self.lookback)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.lr)
        loss_fn = nn.MSELoss()
        model.train()
        for _ in range(self.epochs):
            optimizer.zero_grad(set_to_none=True)
            pred = model(x)
            loss = loss_fn(pred, y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            residuals = y - model(x)
        resid_std = float(torch.std(residuals, unbiased=False).item()) if residuals.numel() > 1 else 0.15
        self.state.model = model
        self.state.mean = mean
        self.state.std = std
        self.state.residual_std = max(1e-4, resid_std)
        self.state.last_refit_fold = fold_idx

    def forecast(self, train: Sequence[float], fold_idx: int) -> Tuple[float, float]:
        if len(train) < self.lookback + 8:
            sigma = max(0.02, _std(train))
            return float(train[-1]), sigma
        need_refit = self.state.model is None or ((fold_idx - self.state.last_refit_fold) >= self.refit_every)
        if need_refit:
            self._fit(train, fold_idx)
        if self.state.model is None:
            sigma = max(0.02, _std(train))
            return float(train[-1]), sigma
        values = torch.tensor([float(v) for v in train[-self.lookback :]], dtype=torch.float32)
        z = (values - self.state.mean) / max(1e-4, self.state.std)
        x = z.unsqueeze(0).unsqueeze(-1)
        self.state.model.eval()
        with torch.no_grad():
            next_z = float(self.state.model(x).item())
        pred = self.state.mean + self.state.std * next_z
        sigma = max(1e-4, self.state.std * self.state.residual_std)
        return float(pred), float(sigma)


def _atheria_forecast(projector: MarketLandscapeFutureProjector, train_events: Sequence[MarketEvent]) -> Tuple[float, float]:
    payload = projector.run(train_events)
    quality = dict(payload.get("quality") or {})
    forecast = dict(payload.get("forecast") or {})
    series = list(forecast.get("series") or [])
    if series:
        pred = _safe_float(series[0].get("signal_mean"), train_events[-1].signal)
    else:
        pred = float(train_events[-1].signal)
    sigma = max(1e-4, _safe_float(quality.get("residual_std"), 0.08))
    return float(pred), float(sigma)


def run_benchmark(
    *,
    events: Sequence[MarketEvent],
    min_train_events: int,
    scenario_threshold: float,
    include_transformer: bool,
    seed: int,
    step_seconds: float,
) -> Dict[str, Any]:
    if len(events) < max(12, min_train_events + 2):
        raise ValueError("not_enough_events_for_benchmark")

    torch.manual_seed(int(seed))
    rng = torch.Generator().manual_seed(int(seed) + 17)
    projector = MarketLandscapeFutureProjector(latent_dims=3, ridge=0.08, horizon_steps=1, step_seconds=max(1.0, float(step_seconds)))
    transformer = _TransformerBaseline() if include_transformer else None

    rows: Dict[str, Dict[str, List[Any]]] = {}
    model_order = ["atheria", "random", "arima", "garch"] + (["transformer"] if include_transformer else [])
    fold_count = 0
    full_window_payload = projector.run(events)
    full_window_quality = dict(full_window_payload.get("quality") or {})

    for fold_idx, train_end in enumerate(range(min_train_events - 1, len(events) - 1)):
        train_events = list(events[: train_end + 1])
        train_signal = [float(e.signal) for e in train_events]
        actual = float(events[train_end + 1].signal)
        last_value = float(train_signal[-1])

        pred_atheria, sigma_atheria = _atheria_forecast(projector, train_events)
        probs_atheria = _gaussian_scenario_probs(pred_atheria - last_value, sigma_atheria, scenario_threshold)
        _append_row(rows, "atheria", y_true=actual, y_pred=pred_atheria, sigma=sigma_atheria, probs=probs_atheria, last_value=last_value)

        pred_random, sigma_random = _random_forecast(train_signal, generator=rng)
        probs_random = _gaussian_scenario_probs(pred_random - last_value, sigma_random, scenario_threshold)
        _append_row(rows, "random", y_true=actual, y_pred=pred_random, sigma=sigma_random, probs=probs_random, last_value=last_value)

        pred_arima, sigma_arima = _arima_110_forecast(train_signal)
        probs_arima = _gaussian_scenario_probs(pred_arima - last_value, sigma_arima, scenario_threshold)
        _append_row(rows, "arima", y_true=actual, y_pred=pred_arima, sigma=sigma_arima, probs=probs_arima, last_value=last_value)

        pred_garch, sigma_garch = _garch_11_forecast(train_signal)
        probs_garch = _gaussian_scenario_probs(pred_garch - last_value, sigma_garch, scenario_threshold)
        _append_row(rows, "garch", y_true=actual, y_pred=pred_garch, sigma=sigma_garch, probs=probs_garch, last_value=last_value)

        if transformer is not None:
            pred_tf, sigma_tf = transformer.forecast(train_signal, fold_idx)
            probs_tf = _gaussian_scenario_probs(pred_tf - last_value, sigma_tf, scenario_threshold)
            _append_row(rows, "transformer", y_true=actual, y_pred=pred_tf, sigma=sigma_tf, probs=probs_tf, last_value=last_value)

        fold_count += 1

    labels = {
        "atheria": "ATHERIA field model",
        "random": "Random baseline",
        "arima": "ARIMA(1,1,0) baseline",
        "garch": "GARCH(1,1) baseline",
        "transformer": "Transformer baseline",
    }
    notes = {
        "atheria": "Rolling one-step prediction from the market landscape projector.",
        "random": "Random-walk with Gaussian noise based on training volatility.",
        "arima": "Lightweight ARIMA(1,1,0) via ridge-regularized differenced AR fit.",
        "garch": "Lightweight GARCH(1,1) variance recursion with volatility-aware drift.",
        "transformer": "Tiny encoder Transformer with periodic refits on rolling windows.",
    }

    model_rows: List[Dict[str, Any]] = []
    for model_name in model_order:
        bucket = rows.get(model_name, {})
        y_true = list(bucket.get("y_true") or [])
        if not y_true:
            continue
        metric_block = _metrics(
            y_true=y_true,
            y_pred=list(bucket.get("y_pred") or []),
            sigma=list(bucket.get("sigma") or []),
            probs=list(bucket.get("probs") or []),
            last_values=list(bucket.get("last") or []),
            threshold=scenario_threshold,
        )
        model_rows.append(
            {
                "name": model_name,
                "label": labels.get(model_name, model_name),
                "folds": len(y_true),
                "metrics": metric_block,
                "notes": notes.get(model_name, ""),
            }
        )

    by_mae = sorted(model_rows, key=lambda item: _safe_float(item.get("metrics", {}).get("mae"), 1e9))
    by_brier = sorted(model_rows, key=lambda item: _safe_float(item.get("metrics", {}).get("brier"), 1e9))
    by_crps = sorted(model_rows, key=lambda item: _safe_float(item.get("metrics", {}).get("crps_gaussian"), 1e9))

    signal_modes: Dict[str, int] = {}
    for event in events:
        mode = str((event.metadata or {}).get("signal_mode") or "market_snapshot")
        signal_modes[mode] = int(signal_modes.get(mode, 0) + 1)
    market_count = int(signal_modes.get("market_snapshot", 0))
    proxy_count = int(signal_modes.get("dashboard_proxy", 0))
    total_events = len(events)
    signals = [float(e.signal) for e in events]

    atheria_bucket = rows.get("atheria", {})
    truth = list(atheria_bucket.get("y_true") or [])
    last_vals = list(atheria_bucket.get("last") or [])
    deltas = [float(y) - float(l) for y, l in zip(truth, last_vals)]
    class_counts = {"stress_up": 0, "sideways": 0, "stress_down": 0}
    for delta in deltas:
        key = _target_label(delta, scenario_threshold)
        class_counts[key] = int(class_counts.get(key, 0) + 1)
    majority_class = max(class_counts.keys(), key=lambda key: class_counts.get(key, 0)) if class_counts else "sideways"
    majority_ratio = float(class_counts.get(majority_class, 0) / max(1, len(deltas)))

    return {
        "created_at": float(time.time()),
        "comparison": {
            "full_window_in_sample_r2": full_window_quality.get("r2_one_step"),
            "full_window_in_sample_predictability": full_window_quality.get("predictability_index"),
            "full_window_in_sample_sample_count": full_window_quality.get("sample_count"),
            "note": "This block mirrors the direct future-projection fit on the full event window (in-sample).",
        },
        "source": {
            "events_used": total_events,
            "market_signal_count": market_count,
            "proxy_signal_count": proxy_count,
            "market_signal_ratio": round(float(market_count / max(1, total_events)), 6),
            "proxy_signal_ratio": round(float(proxy_count / max(1, total_events)), 6),
            "signal_min": round(min(signals), 6),
            "signal_max": round(max(signals), 6),
            "signal_std": round(_std(signals), 6),
            "timestamp_start": round(float(events[0].timestamp), 6),
            "timestamp_end": round(float(events[-1].timestamp), 6),
        },
        "protocol": {
            "rolling_mode": "expanding_window_one_step",
            "folds": fold_count,
            "min_train_events": int(min_train_events),
            "scenario_threshold": float(scenario_threshold),
            "step_seconds": float(step_seconds),
            "seed": int(seed),
        },
        "evaluation_diagnostics": {
            "delta_std": round(_std(deltas), 6),
            "delta_min": round(min(deltas), 6) if deltas else 0.0,
            "delta_max": round(max(deltas), 6) if deltas else 0.0,
            "target_class_counts": class_counts,
            "majority_target_class": majority_class,
            "majority_target_ratio": round(majority_ratio, 6),
            "class_imbalance_flag": bool(majority_ratio >= 0.85),
        },
        "models": model_rows,
        "ranking": {
            "by_mae": [item["name"] for item in by_mae],
            "by_brier": [item["name"] for item in by_brier],
            "by_crps": [item["name"] for item in by_crps],
        },
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    source = dict(report.get("source") or {})
    protocol = dict(report.get("protocol") or {})
    models = list(report.get("models") or [])
    lines: List[str] = []
    lines.append("# Market Benchmark Report")
    lines.append("")
    lines.append(f"- created_at_unix: `{_safe_float(report.get('created_at'), 0.0):.3f}`")
    lines.append(f"- events_used: `{int(_safe_float(source.get('events_used'), 0))}`")
    lines.append(f"- folds: `{int(_safe_float(protocol.get('folds'), 0))}`")
    lines.append(f"- market_signal_ratio: `{_safe_float(source.get('market_signal_ratio'), 0.0):.4f}`")
    lines.append(f"- proxy_signal_ratio: `{_safe_float(source.get('proxy_signal_ratio'), 0.0):.4f}`")
    comparison = dict(report.get("comparison") or {})
    r2_comp = comparison.get("full_window_in_sample_r2")
    if r2_comp is None:
        comp_r2_text = "n/a"
    else:
        comp_r2_text = f"{_safe_float(r2_comp, 0.0):.6f}"
    lines.append(f"- full_window_in_sample_r2: `{comp_r2_text}`")
    lines.append(f"- full_window_in_sample_predictability: `{_safe_float(comparison.get('full_window_in_sample_predictability'), 0.0):.6f}`")
    diag = dict(report.get("evaluation_diagnostics") or {})
    lines.append(f"- delta_std: `{_safe_float(diag.get('delta_std'), 0.0):.6f}`")
    lines.append(f"- majority_target_class: `{str(diag.get('majority_target_class') or 'sideways')}`")
    lines.append(f"- majority_target_ratio: `{_safe_float(diag.get('majority_target_ratio'), 0.0):.4f}`")
    lines.append(f"- class_imbalance_flag: `{str(bool(diag.get('class_imbalance_flag'))).lower()}`")
    lines.append("")
    lines.append("| Model | MAE | RMSE | R2 | Direction Acc | Brier | CRPS |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for item in models:
        metrics = dict(item.get("metrics") or {})
        r2_value = metrics.get("r2")
        if r2_value is None:
            r2_cell = "n/a"
        else:
            r2_cell = f"{_safe_float(r2_value, 0.0):.4f}"
        lines.append(
            "| {label} | {mae:.4f} | {rmse:.4f} | {r2} | {da:.4f} | {brier:.4f} | {crps:.4f} |".format(
                label=str(item.get("label") or item.get("name") or "model"),
                mae=_safe_float(metrics.get("mae"), 0.0),
                rmse=_safe_float(metrics.get("rmse"), 0.0),
                r2=r2_cell,
                da=_safe_float(metrics.get("directional_accuracy"), 0.0),
                brier=_safe_float(metrics.get("brier"), 0.0),
                crps=_safe_float(metrics.get("crps_gaussian"), 0.0),
            )
        )
    lines.append("")
    lines.append("## Ranking")
    lines.append("")
    ranking = dict(report.get("ranking") or {})
    lines.append(f"- by_mae: `{', '.join(list(ranking.get('by_mae') or []))}`")
    lines.append(f"- by_brier: `{', '.join(list(ranking.get('by_brier') or []))}`")
    lines.append(f"- by_crps: `{', '.join(list(ranking.get('by_crps') or []))}`")
    lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atheria_market_benchmarks.py",
        description="Rolling baseline benchmarks for ATHERIA market future projection.",
    )
    parser.add_argument("--report-file", default="daemon_runtime_live/atheria_daemon_audit.jsonl", help="Input daemon audit JSONL.")
    parser.add_argument("--limit", type=int, default=220, help="Use recent N events.")
    parser.add_argument("--min-train-events", type=int, default=24, help="Initial expanding-window train size.")
    parser.add_argument("--scenario-threshold", type=float, default=0.03, help="Threshold for up/sideways/down labeling.")
    parser.add_argument("--step-seconds", type=float, default=300.0, help="Step width used by ATHERIA one-step forecast.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--skip-transformer", action="store_true", help="Skip transformer baseline.")
    parser.add_argument("--json-out", default="runtime_audit/market_benchmark_report.json", help="Output JSON report path.")
    parser.add_argument("--markdown-out", default="runtime_audit/market_benchmark_table.md", help="Output markdown table path.")
    parser.add_argument("--pretty", action="store_true", help="Print complete JSON to stdout.")
    return parser


def _summary(report: Dict[str, Any]) -> str:
    models = list(report.get("models") or [])
    if not models:
        return "Atheria Market Benchmarks\nNo model results."
    best = min(models, key=lambda item: _safe_float(item.get("metrics", {}).get("mae"), 1e9))
    source = dict(report.get("source") or {})
    protocol = dict(report.get("protocol") or {})
    return (
        "Atheria Market Benchmarks\n"
        f"Events used: {int(_safe_float(source.get('events_used'), 0))}\n"
        f"Folds: {int(_safe_float(protocol.get('folds'), 0))}\n"
        f"Market signal ratio: {_safe_float(source.get('market_signal_ratio'), 0.0):.4f}\n"
        f"Proxy signal ratio: {_safe_float(source.get('proxy_signal_ratio'), 0.0):.4f}\n"
        f"Best MAE model: {best.get('label', best.get('name', 'model'))} ({_safe_float(best.get('metrics', {}).get('mae'), 0.0):.4f})"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    events = load_events_from_jsonl(Path(str(args.report_file)), limit=max(12, int(args.limit)))
    min_train = max(12, int(args.min_train_events))
    report = run_benchmark(
        events=events,
        min_train_events=min_train,
        scenario_threshold=max(1e-6, float(args.scenario_threshold)),
        include_transformer=(not bool(args.skip_transformer)),
        seed=int(args.seed),
        step_seconds=max(1.0, float(args.step_seconds)),
    )

    json_path = Path(str(args.json_out))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = Path(str(args.markdown_out))
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    if bool(args.pretty):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
