from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import torch


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _softmax_distribution(vector: torch.Tensor) -> torch.Tensor:
    if vector.numel() == 0:
        return torch.ones(1, dtype=torch.float32)
    shifted = vector - torch.max(vector)
    expv = torch.exp(shifted)
    denom = torch.sum(expv)
    if float(denom.item()) <= 1e-12:
        return torch.full_like(expv, 1.0 / max(1, expv.numel()))
    return expv / denom


def _shannon_entropy(distribution: torch.Tensor) -> float:
    p = torch.clamp(distribution, min=1e-12)
    entropy = -torch.sum(p * torch.log(p))
    return float(entropy.item())


def _jensen_shannon_distance(p: torch.Tensor, q: torch.Tensor) -> float:
    p = torch.clamp(p, min=1e-12)
    q = torch.clamp(q, min=1e-12)
    m = 0.5 * (p + q)
    kl_pm = torch.sum(p * (torch.log(p) - torch.log(m)))
    kl_qm = torch.sum(q * (torch.log(q) - torch.log(m)))
    js_div = 0.5 * (kl_pm + kl_qm)
    return math.sqrt(max(0.0, float(js_div.item())))


def _rank_tensor(values: torch.Tensor) -> torch.Tensor:
    order = torch.argsort(values)
    rank = torch.zeros_like(values, dtype=torch.float32)
    rank[order] = torch.arange(values.numel(), dtype=torch.float32)
    return rank


@dataclass
class InformationEvent:
    event_id: str
    timestamp: float
    vector: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpacetimePoint:
    event_id: str
    timestamp: float
    emergent_time: float
    spatial: List[float]
    entropy: float
    curvature_proxy: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": round(float(self.timestamp), 6),
            "emergent_time": round(float(self.emergent_time), 6),
            "spatial": [round(float(item), 6) for item in self.spatial],
            "entropy": round(float(self.entropy), 6),
            "curvature_proxy": round(float(self.curvature_proxy), 6),
        }


@dataclass
class SpacetimeReconstruction:
    points: List[SpacetimePoint]
    information_distance: List[List[float]]
    metric_tensor: List[List[float]]
    quality: Dict[str, Any]
    causal_links: List[Dict[str, Any]]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "points": [point.as_dict() for point in self.points],
            "information_distance": [
                [round(float(item), 6) for item in row] for row in self.information_distance
            ],
            "metric_tensor": [[round(float(item), 6) for item in row] for row in self.metric_tensor],
            "quality": self.quality,
            "causal_links": self.causal_links,
        }


class InformationSpacetimeReconstructor:
    """
    Standalone module for "spacetime from information":
    1) build an information-distance geometry from event vectors,
    2) reconstruct spatial coordinates via classical MDS,
    3) infer an emergent time coordinate from timestamps and directed information flow.
    """

    def __init__(self, *, spatial_dims: int = 3, top_links: int = 8) -> None:
        self.spatial_dims = max(1, int(spatial_dims))
        self.top_links = max(1, int(top_links))

    def _stack_vectors(self, events: Sequence[InformationEvent]) -> torch.Tensor:
        width = max(len(event.vector) for event in events)
        if width <= 0:
            raise ValueError("information_vectors_empty")
        rows: List[List[float]] = []
        for event in events:
            base = [_safe_float(item, 0.0) for item in event.vector]
            if len(base) < width:
                base = base + [0.0] * (width - len(base))
            rows.append(base[:width])
        return torch.tensor(rows, dtype=torch.float32)

    def _information_distance(self, matrix: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        n = int(matrix.shape[0])
        dists = torch.zeros((n, n), dtype=torch.float32)
        entropy = torch.zeros(n, dtype=torch.float32)
        distributions: List[torch.Tensor] = []

        for idx in range(n):
            probs = _softmax_distribution(matrix[idx])
            distributions.append(probs)
            entropy[idx] = float(_shannon_entropy(probs))

        for i in range(n):
            for j in range(i + 1, n):
                js = _jensen_shannon_distance(distributions[i], distributions[j])
                dists[i, j] = js
                dists[j, i] = js
        return dists, entropy

    def _classical_mds(self, distance_matrix: torch.Tensor) -> torch.Tensor:
        n = int(distance_matrix.shape[0])
        if n < 2:
            raise ValueError("need_at_least_two_events")
        dims = min(self.spatial_dims, max(1, n - 1))

        d2 = torch.square(distance_matrix)
        eye = torch.eye(n, dtype=torch.float32)
        ones = torch.full((n, n), 1.0 / float(n), dtype=torch.float32)
        centering = eye - ones
        gram = -0.5 * centering @ d2 @ centering

        eigvals, eigvecs = torch.linalg.eigh(gram)
        order = torch.argsort(eigvals, descending=True)
        eigvals = eigvals[order]
        eigvecs = eigvecs[:, order]

        positive = torch.clamp(eigvals[:dims], min=1e-10)
        coords = eigvecs[:, :dims] * torch.sqrt(positive).unsqueeze(0)
        return coords

    def _emergent_time(
        self,
        events: Sequence[InformationEvent],
        distance_matrix: torch.Tensor,
        entropy: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        n = len(events)
        timestamps = torch.tensor([_safe_float(event.timestamp, 0.0) for event in events], dtype=torch.float32)

        has_clock = bool(torch.max(timestamps).item() - torch.min(timestamps).item() > 1e-9)
        if has_clock:
            t0 = float(torch.min(timestamps).item())
            t1 = float(torch.max(timestamps).item())
            clock_time = (timestamps - t0) / max(1e-9, t1 - t0)
        else:
            clock_time = torch.zeros(n, dtype=torch.float32)

        affinity = torch.exp(-distance_matrix)
        flow = torch.zeros((n, n), dtype=torch.float32)
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                gradient = max(0.0, float(entropy[i].item() - entropy[j].item()))
                if gradient <= 0.0:
                    continue
                flow[i, j] = affinity[i, j] * gradient

        outflow = torch.sum(flow, dim=1)
        inflow = torch.sum(flow, dim=0)
        causal_score = outflow - inflow
        causal_rank = _rank_tensor(causal_score)
        if n > 1:
            causal_rank = causal_rank / float(n - 1)

        if has_clock:
            emergent = 0.7 * clock_time + 0.3 * causal_rank
        else:
            emergent = causal_rank

        min_time = float(torch.min(emergent).item())
        max_time = float(torch.max(emergent).item())
        if max_time - min_time > 1e-9:
            emergent = (emergent - min_time) / (max_time - min_time)
        else:
            emergent = torch.zeros_like(emergent)
        return emergent, flow

    def _quality(
        self,
        info_distance: torch.Tensor,
        spatial: torch.Tensor,
        emergent_time: torch.Tensor,
        timestamps: torch.Tensor,
    ) -> Dict[str, Any]:
        n = int(info_distance.shape[0])
        rec = torch.cdist(spatial, spatial, p=2)
        num = torch.sum(torch.square(info_distance - rec))
        den = torch.sum(torch.square(info_distance)) + 1e-9
        stress = float(torch.sqrt(num / den).item())

        if n >= 2 and float(torch.max(timestamps).item() - torch.min(timestamps).item()) > 1e-9:
            rank_a = _rank_tensor(emergent_time)
            rank_b = _rank_tensor(timestamps)
            a = rank_a - torch.mean(rank_a)
            b = rank_b - torch.mean(rank_b)
            corr = float((torch.sum(a * b) / (torch.sqrt(torch.sum(a * a) * torch.sum(b * b)) + 1e-9)).item())
        else:
            corr = 1.0
        temporal_consistency = _clamp((corr + 1.0) * 0.5, 0.0, 1.0)
        return {
            "stress": round(stress, 6),
            "temporal_consistency": round(temporal_consistency, 6),
            "event_count": n,
        }

    def _metric_tensor(self, spatial: torch.Tensor) -> List[List[float]]:
        dims = int(spatial.shape[1])
        metric = torch.zeros((dims + 1, dims + 1), dtype=torch.float32)
        metric[0, 0] = -1.0
        for axis in range(dims):
            variance = float(torch.var(spatial[:, axis]).item()) if spatial.shape[0] > 1 else 1.0
            metric[axis + 1, axis + 1] = max(1e-6, variance)
        return metric.tolist()

    def _curvature_proxy(self, distance_matrix: torch.Tensor, *, neighbors: int = 4) -> torch.Tensor:
        n = int(distance_matrix.shape[0])
        out = torch.zeros(n, dtype=torch.float32)
        k = max(1, min(neighbors, n - 1))
        for idx in range(n):
            row = distance_matrix[idx]
            values, _ = torch.sort(row)
            local = values[1 : k + 1] if n > 1 else values[:1]
            out[idx] = torch.mean(local) if local.numel() > 0 else 0.0
        return out

    def _top_causal_links(self, flow: torch.Tensor, events: Sequence[InformationEvent]) -> List[Dict[str, Any]]:
        n = int(flow.shape[0])
        links: List[Dict[str, Any]] = []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                weight = float(flow[i, j].item())
                if weight <= 1e-8:
                    continue
                links.append(
                    {
                        "source": str(events[i].event_id),
                        "target": str(events[j].event_id),
                        "weight": round(weight, 6),
                    }
                )
        links.sort(key=lambda item: float(item["weight"]), reverse=True)
        return links[: self.top_links]

    def reconstruct(self, events: Sequence[InformationEvent]) -> SpacetimeReconstruction:
        if len(events) < 3:
            raise ValueError("need_at_least_three_events_for_reconstruction")

        vectors = self._stack_vectors(events)
        info_distance, entropy = self._information_distance(vectors)
        spatial = self._classical_mds(info_distance)
        emergent_time, flow = self._emergent_time(events, info_distance, entropy)
        curvature = self._curvature_proxy(info_distance)
        timestamps = torch.tensor([_safe_float(event.timestamp, 0.0) for event in events], dtype=torch.float32)

        points: List[SpacetimePoint] = []
        for idx, event in enumerate(events):
            points.append(
                SpacetimePoint(
                    event_id=str(event.event_id),
                    timestamp=_safe_float(event.timestamp, 0.0),
                    emergent_time=float(emergent_time[idx].item()),
                    spatial=[float(item) for item in spatial[idx].tolist()],
                    entropy=float(entropy[idx].item()),
                    curvature_proxy=float(curvature[idx].item()),
                )
            )

        quality = self._quality(info_distance, spatial, emergent_time, timestamps)
        metric = self._metric_tensor(spatial)
        links = self._top_causal_links(flow, events)
        return SpacetimeReconstruction(
            points=points,
            information_distance=[[float(item) for item in row.tolist()] for row in info_distance],
            metric_tensor=metric,
            quality=quality,
            causal_links=links,
        )


def daemon_entry_to_event(entry: Dict[str, Any], index: int, *, max_assets: int = 8) -> InformationEvent:
    market = dict(entry.get("market") or {})
    snapshot = dict(market.get("last_market_snapshot") or {})
    symbols = dict(snapshot.get("symbols") or {})
    trauma_pressure = _safe_float(market.get("trauma_pressure"), 0.0)

    vector: List[float] = [trauma_pressure]
    for asset in sorted(symbols.keys())[: max(1, int(max_assets))]:
        row = dict(symbols.get(asset) or {})
        vector.extend(
            [
                _safe_float(row.get("recent_return"), _safe_float(row.get("price_change_pct"), 0.0) / 100.0),
                _safe_float(row.get("volatility"), 0.0),
                _safe_float(row.get("orderbook_imbalance"), 0.0),
                _safe_float(row.get("price_change_pct"), 0.0) / 100.0,
                math.log1p(max(0.0, _safe_float(row.get("volume_1m"), 0.0))) / 12.0,
            ]
        )

    if len(vector) <= 1:
        dashboard = dict(entry.get("dashboard") or {})
        vector.extend(
            [
                _safe_float(dashboard.get("system_temperature"), 0.0) / 100.0,
                _safe_float(dashboard.get("resource_pool"), 0.0) / 10000.0,
            ]
        )

    timestamp = _safe_float(entry.get("timestamp"), float(index))
    event_id = str(entry.get("reason") or "event") + f"::{index:04d}"
    return InformationEvent(
        event_id=event_id,
        timestamp=timestamp,
        vector=[_safe_float(item, 0.0) for item in vector],
        metadata={"reason": str(entry.get("reason") or "")},
    )


def load_events_from_jsonl(path: Path, *, limit: int = 160) -> List[InformationEvent]:
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

    selected = rows[-max(3, int(limit)) :]
    return [daemon_entry_to_event(entry, idx) for idx, entry in enumerate(selected)]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atheria_spacetime_reconstruction.py",
        description="Reconstructs an emergent spacetime manifold from information traces (standalone module).",
    )
    parser.add_argument(
        "--report-file",
        default="daemon_runtime/atheria_daemon_audit.jsonl",
        help="Input JSONL source for information events.",
    )
    parser.add_argument("--limit", type=int, default=120, help="Number of recent rows used for reconstruction.")
    parser.add_argument("--spatial-dims", type=int, default=3, help="Spatial dimensions in the latent manifold.")
    parser.add_argument("--top-links", type=int, default=8, help="Number of strongest causal links in output.")
    parser.add_argument("--json-out", default=None, help="Optional path to write full reconstruction JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print full JSON to stdout.")
    return parser


def _summary_text(report: SpacetimeReconstruction) -> str:
    quality = dict(report.quality or {})
    points = report.points
    first = points[0]
    last = points[-1]
    return (
        "Atheria Spacetime Reconstruction\n"
        f"Events: {len(points)}\n"
        f"Stress: {quality.get('stress', 0.0):.4f}\n"
        f"Temporal consistency: {quality.get('temporal_consistency', 0.0):.4f}\n"
        f"First event: {first.event_id} -> t={first.emergent_time:.4f}\n"
        f"Last event: {last.event_id} -> t={last.emergent_time:.4f}\n"
        f"Causal links: {len(report.causal_links)}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    events = load_events_from_jsonl(Path(str(args.report_file)), limit=max(3, int(args.limit)))
    reconstructor = InformationSpacetimeReconstructor(
        spatial_dims=max(1, int(args.spatial_dims)),
        top_links=max(1, int(args.top_links)),
    )
    report = reconstructor.reconstruct(events)
    payload = report.as_dict()

    if args.json_out:
        out_path = Path(str(args.json_out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.pretty):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_summary_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
