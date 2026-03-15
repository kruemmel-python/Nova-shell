from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import torch


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


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


def _tensor_correlation(a: torch.Tensor, b: torch.Tensor) -> float:
    if a.numel() <= 1 or b.numel() <= 1:
        return 0.0
    xa = a - torch.mean(a)
    xb = b - torch.mean(b)
    denom = torch.sqrt(torch.sum(xa * xa) * torch.sum(xb * xb)) + 1e-9
    return float((torch.sum(xa * xb) / denom).item())


def _normalize_tensor(values: torch.Tensor) -> torch.Tensor:
    if values.numel() == 0:
        return values
    lo = torch.min(values)
    hi = torch.max(values)
    span = hi - lo
    if float(span.item()) <= 1e-9:
        return torch.zeros_like(values)
    return (values - lo) / span


def _unit_vector(vec: torch.Tensor) -> torch.Tensor:
    norm = torch.linalg.norm(vec)
    if float(norm.item()) <= 1e-9:
        base = torch.zeros_like(vec)
        base[0] = 1.0
        return base
    return vec / norm


def _angle_deg(a: torch.Tensor, b: torch.Tensor) -> float:
    ua = _unit_vector(a)
    ub = _unit_vector(b)
    cosv = _clamp(float(torch.dot(ua, ub).item()), -1.0, 1.0)
    return math.degrees(math.acos(cosv))


@dataclass
class InformationEvent:
    event_id: str
    timestamp: float
    vector: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EinsteinPoint:
    event_id: str
    timestamp: float
    emergent_time: float
    spatial: List[float]
    entropy: float
    curvature_proxy: float
    mass: float
    potential: float
    acceleration: List[float]
    metric_diag: List[float]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": round(float(self.timestamp), 6),
            "emergent_time": round(float(self.emergent_time), 6),
            "spatial": [round(float(item), 6) for item in self.spatial],
            "entropy": round(float(self.entropy), 6),
            "curvature_proxy": round(float(self.curvature_proxy), 6),
            "mass": round(float(self.mass), 6),
            "potential": round(float(self.potential), 6),
            "acceleration": [round(float(item), 6) for item in self.acceleration],
            "metric_diag": [round(float(item), 6) for item in self.metric_diag],
        }


@dataclass
class ProbeTrajectory:
    probe_id: str
    start: List[float]
    direction: List[float]
    deflection_deg: float
    arc_length: float
    max_potential: float
    min_g00: float
    redshift_proxy: float
    path: List[List[float]]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "start": [round(float(item), 6) for item in self.start],
            "direction": [round(float(item), 6) for item in self.direction],
            "deflection_deg": round(float(self.deflection_deg), 6),
            "arc_length": round(float(self.arc_length), 6),
            "max_potential": round(float(self.max_potential), 6),
            "min_g00": round(float(self.min_g00), 6),
            "redshift_proxy": round(float(self.redshift_proxy), 6),
            "path": [[round(float(item), 6) for item in row] for row in self.path],
        }


@dataclass
class EinsteinLikeReconstruction:
    points: List[EinsteinPoint]
    probes: List[ProbeTrajectory]
    information_distance: List[List[float]]
    quality: Dict[str, Any]
    field_summary: Dict[str, Any]
    invariants: List[Dict[str, Any]]
    attractors: List[Dict[str, Any]]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "points": [point.as_dict() for point in self.points],
            "probes": [probe.as_dict() for probe in self.probes],
            "information_distance": [
                [round(float(item), 6) for item in row] for row in self.information_distance
            ],
            "quality": self.quality,
            "field_summary": self.field_summary,
            "invariants": self.invariants,
            "attractors": self.attractors,
        }


class InformationEinsteinLikeSimulator:
    """
    Einstein-like standalone reconstruction:
    1) build latent coordinates from informational distances,
    2) derive an effective mass/potential/metric field,
    3) fire probe trajectories through that field and quantify deflection.
    """

    def __init__(
        self,
        *,
        spatial_dims: int = 3,
        probe_count: int = 24,
        probe_steps: int = 180,
        dt: float = 0.045,
        gravity: float = 0.55,
        path_decimation: int = 2,
        mode: str = "standard",
        conservative_overrides: Optional[Dict[str, float]] = None,
    ) -> None:
        self.spatial_dims = max(2, int(spatial_dims))
        self.probe_count = max(4, int(probe_count))
        self.probe_steps = max(20, int(probe_steps))
        mode_value = str(mode).strip().lower()
        if mode_value not in {"standard", "conservative"}:
            raise ValueError(f"unknown_mode:{mode}")
        self.mode = mode_value

        raw_dt = max(0.005, float(dt))
        raw_gravity = max(1e-5, float(gravity))
        if self.mode == "conservative":
            self.coupling_strength = 0.28
            self.dt = raw_dt * 0.52
            self.gravity = raw_gravity * self.coupling_strength
            self.softening = 0.14
            self.mass_base = 0.46
            self.mass_entropy_weight = 0.38
            self.mass_curvature_weight = 0.16
            self.mass_floor = 0.12
            self.probe_start_radius = 3.1
            self.probe_inward = 0.92
            self.probe_tangent = 0.28
            self.probe_speed = 1.32
            self.probe_min_speed = 0.42
            self.probe_max_speed = 2.2
            self.probe_step_factor = 0.35
            self.quality_coupling_gain = self.coupling_strength
        else:
            self.coupling_strength = 1.0
            self.dt = raw_dt
            self.gravity = raw_gravity
            self.softening = 0.08
            self.mass_base = 0.14
            self.mass_entropy_weight = 0.62
            self.mass_curvature_weight = 0.24
            self.mass_floor = 0.05
            self.probe_start_radius = 1.8
            self.probe_inward = -0.88
            self.probe_tangent = 0.32
            self.probe_speed = 0.92
            self.probe_min_speed = 0.12
            self.probe_max_speed = 1.6
            self.probe_step_factor = 1.0
            self.quality_coupling_gain = 1.0

        if self.mode == "conservative" and conservative_overrides:
            overrides = dict(conservative_overrides)
            if "coupling_strength" in overrides:
                self.coupling_strength = _clamp(overrides["coupling_strength"], 0.12, 0.62)
            if "dt_scale" in overrides:
                self.dt = raw_dt * _clamp(overrides["dt_scale"], 0.22, 1.35)
            else:
                self.dt = max(0.005, float(self.dt))
            gravity_scale = _clamp(overrides.get("gravity_scale", 1.0), 0.4, 2.4)
            self.gravity = raw_gravity * self.coupling_strength * gravity_scale
            if "softening" in overrides:
                self.softening = _clamp(overrides["softening"], 0.08, 0.42)
            if "mass_base" in overrides:
                self.mass_base = _clamp(overrides["mass_base"], 0.05, 0.9)
            if "mass_entropy_weight" in overrides:
                self.mass_entropy_weight = _clamp(overrides["mass_entropy_weight"], 0.05, 0.95)
            if "mass_curvature_weight" in overrides:
                self.mass_curvature_weight = _clamp(overrides["mass_curvature_weight"], 0.02, 0.7)
            if "mass_floor" in overrides:
                self.mass_floor = _clamp(overrides["mass_floor"], 0.01, 0.4)
            if "probe_start_radius" in overrides:
                self.probe_start_radius = _clamp(overrides["probe_start_radius"], 2.0, 4.8)
            if "probe_inward" in overrides:
                self.probe_inward = _clamp(overrides["probe_inward"], -1.25, 1.25)
            if "probe_tangent" in overrides:
                self.probe_tangent = _clamp(overrides["probe_tangent"], 0.02, 1.35)
            if "probe_speed" in overrides:
                self.probe_speed = _clamp(overrides["probe_speed"], 0.2, 2.8)
            if "probe_min_speed" in overrides:
                self.probe_min_speed = _clamp(overrides["probe_min_speed"], 0.08, 1.4)
            if "probe_max_speed" in overrides:
                self.probe_max_speed = _clamp(overrides["probe_max_speed"], 0.5, 3.8)
            if self.probe_min_speed > self.probe_max_speed:
                self.probe_min_speed = max(0.08, self.probe_max_speed * 0.58)
            if "probe_step_factor" in overrides:
                self.probe_step_factor = _clamp(overrides["probe_step_factor"], 0.2, 1.15)
            self.quality_coupling_gain = self.coupling_strength

        self.path_decimation = max(1, int(path_decimation))

    def _stack_vectors(self, events: Sequence[InformationEvent]) -> torch.Tensor:
        width = max(len(event.vector) for event in events)
        if width <= 0:
            raise ValueError("information_vectors_empty")
        rows: List[List[float]] = []
        for event in events:
            base = [_safe_float(item, 0.0) for item in event.vector]
            if len(base) < width:
                base.extend([0.0] * (width - len(base)))
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
        dims = min(self.spatial_dims, max(2, n - 1))

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

        mean = torch.mean(coords, dim=0, keepdim=True)
        centered = coords - mean
        radius = torch.max(torch.linalg.norm(centered, dim=1))
        scale = max(1e-6, float(radius.item()))
        return centered / scale

    def _emergent_time(
        self,
        events: Sequence[InformationEvent],
        entropy: torch.Tensor,
        curvature: torch.Tensor,
    ) -> torch.Tensor:
        n = len(events)
        timestamps = torch.tensor([_safe_float(event.timestamp, 0.0) for event in events], dtype=torch.float32)
        time_norm = _normalize_tensor(timestamps)
        ent_rank = _rank_tensor(entropy) / max(1.0, float(n - 1))
        curv_rank = _rank_tensor(curvature) / max(1.0, float(n - 1))
        emergent = 0.62 * time_norm + 0.26 * ent_rank + 0.12 * curv_rank
        return _normalize_tensor(emergent)

    def _curvature_proxy(self, distance_matrix: torch.Tensor, *, neighbors: int = 5) -> torch.Tensor:
        n = int(distance_matrix.shape[0])
        out = torch.zeros(n, dtype=torch.float32)
        k = max(1, min(neighbors, n - 1))
        for idx in range(n):
            row = distance_matrix[idx]
            values, _ = torch.sort(row)
            local = values[1 : k + 1] if n > 1 else values[:1]
            out[idx] = torch.mean(local) if local.numel() > 0 else 0.0
        return out

    def _mass_field(self, entropy: torch.Tensor, curvature: torch.Tensor) -> torch.Tensor:
        ent_norm = _normalize_tensor(entropy)
        curv_norm = _normalize_tensor(curvature)
        mass = self.mass_base + self.mass_entropy_weight * ent_norm + self.mass_curvature_weight * curv_norm
        return torch.clamp(mass, min=self.mass_floor)

    def _potential_and_acceleration(
        self, spatial: torch.Tensor, mass: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        n = int(spatial.shape[0])
        potential = torch.zeros(n, dtype=torch.float32)
        accel = torch.zeros((n, int(spatial.shape[1])), dtype=torch.float32)
        eps2 = self.softening * self.softening

        for i in range(n):
            diff = spatial - spatial[i]
            r2 = torch.sum(diff * diff, dim=1) + eps2
            inv_r_all = 1.0 / torch.sqrt(r2)
            potential[i] = -self.gravity * torch.sum(mass * inv_r_all)

            r2[i] = float("inf")
            inv_r3 = torch.pow(r2, -1.5)
            inv_r3[i] = 0.0
            accel[i] = self.gravity * torch.sum((mass * inv_r3).unsqueeze(1) * diff, dim=0)
        return potential, accel

    def _metric_diag(self, potential: torch.Tensor) -> torch.Tensor:
        scale = max(1e-6, float(torch.mean(torch.abs(potential)).item()))
        phi = potential / scale
        g00 = -(1.0 + 0.32 * phi)
        gij = 1.0 - 0.18 * phi
        metric = torch.stack([g00, gij, gij, gij], dim=1)
        metric[:, 1:] = torch.clamp(metric[:, 1:], min=0.1, max=4.0)
        metric[:, 0] = torch.clamp(metric[:, 0], min=-4.0, max=-0.05)
        return metric

    def _field_at(self, pos: torch.Tensor, spatial: torch.Tensor, mass: torch.Tensor) -> torch.Tensor:
        eps2 = self.softening * self.softening
        diff = spatial - pos.unsqueeze(0)
        r2 = torch.sum(diff * diff, dim=1) + eps2
        inv_r3 = torch.pow(r2, -1.5)
        return self.gravity * torch.sum((mass * inv_r3).unsqueeze(1) * diff, dim=0)

    def _potential_at(self, pos: torch.Tensor, spatial: torch.Tensor, mass: torch.Tensor) -> float:
        eps2 = self.softening * self.softening
        diff = spatial - pos.unsqueeze(0)
        r2 = torch.sum(diff * diff, dim=1) + eps2
        inv_r = 1.0 / torch.sqrt(r2)
        return float((-self.gravity * torch.sum(mass * inv_r)).item())

    def _probe_seed(self, idx: int, total: int) -> tuple[torch.Tensor, torch.Tensor]:
        # Fibonacci sphere for deterministic probe starts.
        golden = math.pi * (3.0 - math.sqrt(5.0))
        y = 1.0 - (2.0 * (idx + 0.5) / float(total))
        radius = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden * (idx + 0.5)
        unit = torch.tensor(
            [radius * math.cos(theta), y, radius * math.sin(theta)],
            dtype=torch.float32,
        )

        up = torch.tensor([0.0, 1.0, 0.0], dtype=torch.float32)
        tangent = torch.linalg.cross(unit, up)
        if float(torch.linalg.norm(tangent).item()) <= 1e-8:
            tangent = torch.tensor([1.0, 0.0, 0.0], dtype=torch.float32)
        tangent = _unit_vector(tangent)
        direction = _unit_vector((self.probe_inward * unit) + (self.probe_tangent * tangent))
        start = unit * self.probe_start_radius
        return start, direction

    def _simulate_probes(
        self,
        spatial: torch.Tensor,
        mass: torch.Tensor,
        potential: torch.Tensor,
    ) -> List[ProbeTrajectory]:
        probes: List[ProbeTrajectory] = []
        phi_scale = max(1e-6, float(torch.mean(torch.abs(potential)).item()))
        step_count = max(20, int(round(self.probe_steps * self.probe_step_factor)))

        for idx in range(self.probe_count):
            start, direction = self._probe_seed(idx, self.probe_count)
            pos = start.clone()
            vel = direction * self.probe_speed
            initial_vel = vel.clone()
            path: List[List[float]] = []
            arc = 0.0
            max_phi = -1e9
            min_g00 = 1e9
            phi_start = self._potential_at(pos, spatial, mass)
            for step in range(step_count):
                acc = self._field_at(pos, spatial, mass)
                vel = vel + acc * self.dt
                speed = float(torch.linalg.norm(vel).item())
                if speed > self.probe_max_speed:
                    vel = vel * (self.probe_max_speed / speed)
                elif speed < self.probe_min_speed:
                    vel = _unit_vector(vel) * self.probe_min_speed

                nxt = pos + vel * self.dt
                arc += float(torch.linalg.norm(nxt - pos).item())
                pos = nxt

                phi = self._potential_at(pos, spatial, mass)
                phi_scaled = phi / phi_scale
                g00 = -(1.0 + 0.32 * phi_scaled)
                max_phi = max(max_phi, phi)
                min_g00 = min(min_g00, g00)
                if (step % self.path_decimation) == 0:
                    path.append([float(pos[0].item()), float(pos[1].item()), float(pos[2].item())])

            phi_end = self._potential_at(pos, spatial, mass)
            denom = max(1e-6, abs(1.0 + 0.32 * (phi_end / phi_scale)))
            numer = max(1e-6, abs(1.0 + 0.32 * (phi_start / phi_scale)))
            redshift_proxy = math.sqrt(numer / denom)
            probes.append(
                ProbeTrajectory(
                    probe_id=f"probe_{idx:03d}",
                    start=[float(item) for item in start.tolist()],
                    direction=[float(item) for item in direction.tolist()],
                    deflection_deg=_angle_deg(initial_vel, vel),
                    arc_length=arc,
                    max_potential=max_phi,
                    min_g00=min_g00,
                    redshift_proxy=redshift_proxy,
                    path=path,
                )
            )
        return probes

    def _quality(
        self,
        info_distance: torch.Tensor,
        spatial: torch.Tensor,
        entropy: torch.Tensor,
        mass: torch.Tensor,
        potential: torch.Tensor,
        acceleration: torch.Tensor,
        probes: Sequence[ProbeTrajectory],
    ) -> Dict[str, Any]:
        reconstructed = torch.cdist(spatial, spatial, p=2)
        den_scale = torch.sum(torch.square(reconstructed)) + 1e-9
        alpha = torch.sum(info_distance * reconstructed) / den_scale
        aligned = reconstructed * alpha
        num = torch.sum(torch.square(info_distance - aligned))
        den = torch.sum(torch.square(info_distance)) + 1e-9
        stress = float(torch.sqrt(num / den).item())

        accel_mag = torch.linalg.norm(acceleration, dim=1)
        effective_source = 0.55 * _normalize_tensor(accel_mag) + 0.45 * _normalize_tensor(entropy)
        corr_raw = _clamp(_tensor_correlation(effective_source, -potential), -1.0, 1.0)
        corr_scaled = _clamp(corr_raw * self.quality_coupling_gain, -1.0, 1.0)
        deflections = [probe.deflection_deg for probe in probes]
        mean_deflection = sum(deflections) / max(1, len(deflections))
        max_deflection = max(deflections) if deflections else 0.0
        lensing_threshold = 2.0 if self.mode == "standard" else 8.0
        lensing_ratio = sum(1 for d in deflections if d >= lensing_threshold) / max(1, len(deflections))
        redshift_avg = sum(probe.redshift_proxy for probe in probes) / max(1, len(probes))
        coherence = sum(1 for probe in probes if probe.arc_length > 0.1) / max(1, len(probes))

        verified = (
            spatial.shape[0] >= 8
            and stress <= 0.55
            and corr_raw >= 0.35
            and mean_deflection >= 1.2
            and lensing_ratio >= 0.35
        )
        partial = (
            spatial.shape[0] >= 6
            and stress <= 0.8
            and corr_raw >= 0.2
            and mean_deflection >= 0.7
        )

        return {
            "event_count": int(spatial.shape[0]),
            "mode": self.mode,
            "coupling_strength": round(self.coupling_strength, 6),
            "stress": round(stress, 6),
            "source_potential_corr_raw": round(corr_raw, 6),
            "source_potential_corr_scaled": round(corr_scaled, 6),
            "mass_potential_correlation": round(corr_raw, 6),
            "mean_deflection_deg": round(mean_deflection, 6),
            "max_deflection_deg": round(max_deflection, 6),
            "lensing_threshold_deg": round(lensing_threshold, 3),
            "lensing_ratio": round(lensing_ratio, 6),
            "geodesic_coherence": round(coherence, 6),
            "redshift_proxy_avg": round(redshift_avg, 6),
            "verified": bool(verified),
            "verdict": "Verified" if verified else ("Partial" if partial else "Weak"),
        }

    def reconstruct(self, events: Sequence[InformationEvent]) -> EinsteinLikeReconstruction:
        if len(events) < 4:
            raise ValueError("need_at_least_four_events_for_einstein_like_reconstruction")

        vectors = self._stack_vectors(events)
        info_distance, entropy = self._information_distance(vectors)
        spatial = self._classical_mds(info_distance)
        if int(spatial.shape[1]) < 3:
            pad = torch.zeros((int(spatial.shape[0]), 3 - int(spatial.shape[1])), dtype=torch.float32)
            spatial = torch.cat([spatial, pad], dim=1)
        else:
            spatial = spatial[:, :3]

        curvature = self._curvature_proxy(info_distance)
        emergent_time = self._emergent_time(events, entropy, curvature)
        mass = self._mass_field(entropy, curvature)
        potential, acceleration = self._potential_and_acceleration(spatial, mass)
        metric_diag = self._metric_diag(potential)
        probes = self._simulate_probes(spatial, mass, potential)

        points: List[EinsteinPoint] = []
        for idx, event in enumerate(events):
            points.append(
                EinsteinPoint(
                    event_id=str(event.event_id),
                    timestamp=_safe_float(event.timestamp, 0.0),
                    emergent_time=float(emergent_time[idx].item()),
                    spatial=[float(item) for item in spatial[idx].tolist()],
                    entropy=float(entropy[idx].item()),
                    curvature_proxy=float(curvature[idx].item()),
                    mass=float(mass[idx].item()),
                    potential=float(potential[idx].item()),
                    acceleration=[float(item) for item in acceleration[idx].tolist()],
                    metric_diag=[float(item) for item in metric_diag[idx].tolist()],
                )
            )

        quality = self._quality(info_distance, spatial, entropy, mass, potential, acceleration, probes)
        field_summary = {
            "mode": self.mode,
            "coupling_strength": round(self.coupling_strength, 6),
            "dt_effective": round(float(self.dt), 6),
            "gravity_effective": round(float(self.gravity), 6),
            "potential_min": round(float(torch.min(potential).item()), 6),
            "potential_max": round(float(torch.max(potential).item()), 6),
            "mass_total": round(float(torch.sum(mass).item()), 6),
            "entropy_mean": round(float(torch.mean(entropy).item()), 6),
            "curvature_mean": round(float(torch.mean(curvature).item()), 6),
            "g00_min": round(float(torch.min(metric_diag[:, 0]).item()), 6),
            "g00_max": round(float(torch.max(metric_diag[:, 0]).item()), 6),
            "probe_count": len(probes),
            "probe_steps": self.probe_steps,
        }

        lensing_threshold = float(quality.get("lensing_threshold_deg", 2.0))
        invariants = [
            {
                "name": "Quell-Potential Kopplung",
                "formula": "corr(rho_eff, -Phi)",
                "value": quality["mass_potential_correlation"],
                "status": "ok" if quality["mass_potential_correlation"] >= 0.35 else "weak",
            },
            {
                "name": "Geodesische Deflektion",
                "formula": "mean(delta_theta)_probe",
                "value": quality["mean_deflection_deg"],
                "status": "ok" if quality["mean_deflection_deg"] >= 1.2 else "weak",
            },
            {
                "name": "Lensing-Anteil",
                "formula": f"P(delta_theta >= {lensing_threshold:.1f}deg)",
                "value": quality["lensing_ratio"],
                "status": "ok" if quality["lensing_ratio"] >= 0.35 else "weak",
            },
            {
                "name": "Rekonstruktions-Stress",
                "formula": "sqrt(||D-Dhat||^2/||D||^2)",
                "value": quality["stress"],
                "status": "ok" if quality["stress"] <= 0.55 else "weak",
            },
        ]

        ranked = sorted(points, key=lambda item: item.mass, reverse=True)[:8]
        attractors = [
            {
                "event_id": point.event_id,
                "mass": round(point.mass, 6),
                "potential": round(point.potential, 6),
                "entropy": round(point.entropy, 6),
            }
            for point in ranked
        ]

        return EinsteinLikeReconstruction(
            points=points,
            probes=probes,
            information_distance=[[float(item) for item in row.tolist()] for row in info_distance],
            quality=quality,
            field_summary=field_summary,
            invariants=invariants,
            attractors=attractors,
        )


def daemon_entry_to_event(entry: Dict[str, Any], index: int, *, max_assets: int = 8) -> InformationEvent:
    market = dict(entry.get("market") or {})
    dashboard = dict(entry.get("dashboard") or {})
    snapshot = dict(market.get("last_market_snapshot") or {})
    symbols = dict(snapshot.get("symbols") or {})

    vector: List[float] = [
        _safe_float(market.get("trauma_pressure"), 0.0),
        _safe_float(market.get("last_signal_strength"), 0.0),
        _safe_float(dashboard.get("system_temperature"), 25.0) / 120.0,
        math.log1p(max(0.0, _safe_float(dashboard.get("resource_pool"), 0.0))) / 12.0,
        _safe_float(dashboard.get("entropic_index"), 0.0),
        _safe_float(dashboard.get("structural_tension"), 0.0),
        _safe_float(dashboard.get("market_guardian_score"), 0.0),
        _safe_float(dashboard.get("holographic_energy"), 0.0),
    ]

    if symbols:
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
    else:
        vector.extend(
            [
                _safe_float(dashboard.get("ecological_complexity"), 0.0),
                _safe_float(dashboard.get("aether_density"), 0.0) / 100.0,
                _safe_float(dashboard.get("selection_pressure"), 0.0),
            ]
        )

    timestamp = _safe_float(entry.get("timestamp"), float(index))
    reason = str(entry.get("reason") or "event")
    event_id = reason + f"::{index:04d}"
    return InformationEvent(
        event_id=event_id,
        timestamp=timestamp,
        vector=[_safe_float(item, 0.0) for item in vector],
        metadata={"reason": reason},
    )


def load_events_from_jsonl(path: Path, *, limit: int = 220) -> List[InformationEvent]:
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

    selected = rows[-max(4, int(limit)) :]
    return [daemon_entry_to_event(entry, idx) for idx, entry in enumerate(selected)]


def _conservative_trial_overrides() -> List[Dict[str, float]]:
    # Deterministic compact search set around conservative defaults.
    return [
        {},
        {"coupling_strength": 0.30, "softening": 0.08},
        {"coupling_strength": 0.32, "softening": 0.08},
        {"coupling_strength": 0.34, "softening": 0.08},
        {"coupling_strength": 0.30, "softening": 0.09},
        {"coupling_strength": 0.32, "softening": 0.09},
        {"coupling_strength": 0.30},
        {"coupling_strength": 0.32},
        {"coupling_strength": 0.34},
        {"coupling_strength": 0.36},
        {"coupling_strength": 0.32, "softening": 0.12},
        {"coupling_strength": 0.34, "softening": 0.12},
        {"coupling_strength": 0.34, "softening": 0.12, "probe_step_factor": 0.42},
        {"coupling_strength": 0.32, "softening": 0.12, "probe_step_factor": 0.45},
        {"coupling_strength": 0.30, "softening": 0.12, "probe_step_factor": 0.50},
        {"coupling_strength": 0.34, "probe_start_radius": 2.9, "probe_inward": 0.72, "probe_tangent": 0.50},
        {"coupling_strength": 0.32, "probe_start_radius": 2.8, "probe_inward": 0.58, "probe_tangent": 0.65},
        {"coupling_strength": 0.28, "dt_scale": 0.46, "probe_step_factor": 0.30},
        {"coupling_strength": 0.30, "dt_scale": 0.48, "probe_step_factor": 0.34},
        {"coupling_strength": 0.32, "dt_scale": 0.50, "probe_step_factor": 0.38},
        {"coupling_strength": 0.36, "softening": 0.10, "probe_step_factor": 0.52, "dt_scale": 0.55},
    ]


def _conservative_trial_score(quality: Dict[str, Any]) -> float:
    corr = _safe_float(quality.get("source_potential_corr_raw"), 0.0)
    stress = _safe_float(quality.get("stress"), 9.0)
    lensing = _safe_float(quality.get("lensing_ratio"), 0.0)
    deflection = _safe_float(quality.get("mean_deflection_deg"), 0.0)
    coupling = _safe_float(quality.get("coupling_strength"), 0.0)

    score = 0.0
    score += 4.0 * _clamp(corr / 0.35, 0.0, 1.25)
    score += 2.0 * _clamp((0.55 - stress) / 0.55, 0.0, 1.1)
    score += 1.6 * _clamp(lensing / 0.35, 0.0, 1.25)

    if deflection < 4.0:
        score += 0.6 * _clamp(deflection / 4.0, 0.0, 1.0)
    elif deflection <= 20.0:
        score += 1.25
    elif deflection <= 30.0:
        score += 0.75
    else:
        score -= (deflection - 30.0) / 18.0

    if coupling > 0.42:
        score -= (coupling - 0.42) * 8.0

    verdict = str(quality.get("verdict") or "").lower()
    if verdict == "verified":
        score += 2.3
    elif verdict == "partial":
        score += 0.9
    return float(score)


def _run_einstein_like(
    events: Sequence[InformationEvent],
    *,
    spatial_dims: int,
    probe_count: int,
    probe_steps: int,
    dt: float,
    gravity: float,
    path_decimation: int,
    mode: str,
    conservative_overrides: Optional[Dict[str, float]] = None,
) -> tuple[InformationEinsteinLikeSimulator, EinsteinLikeReconstruction]:
    simulator = InformationEinsteinLikeSimulator(
        spatial_dims=max(2, int(spatial_dims)),
        probe_count=max(4, int(probe_count)),
        probe_steps=max(20, int(probe_steps)),
        dt=max(0.005, float(dt)),
        gravity=max(1e-6, float(gravity)),
        path_decimation=max(1, int(path_decimation)),
        mode=str(mode),
        conservative_overrides=conservative_overrides,
    )
    return simulator, simulator.reconstruct(events)


def _auto_tune_conservative(
    events: Sequence[InformationEvent],
    *,
    spatial_dims: int,
    probe_count: int,
    probe_steps: int,
    dt: float,
    gravity: float,
    path_decimation: int,
    max_trials: int,
    target_corr: float,
    stop_on_verified: bool,
) -> tuple[InformationEinsteinLikeSimulator, EinsteinLikeReconstruction, Dict[str, Any]]:
    overrides_bank = _conservative_trial_overrides()
    trials_to_run = overrides_bank[: max(1, min(int(max_trials), len(overrides_bank)))]

    best_sim: Optional[InformationEinsteinLikeSimulator] = None
    best_report: Optional[EinsteinLikeReconstruction] = None
    best_row: Optional[Dict[str, Any]] = None
    best_score = -1e9
    trial_rows: List[Dict[str, Any]] = []

    for idx, overrides in enumerate(trials_to_run, start=1):
        sim, report = _run_einstein_like(
            events,
            spatial_dims=spatial_dims,
            probe_count=probe_count,
            probe_steps=probe_steps,
            dt=dt,
            gravity=gravity,
            path_decimation=path_decimation,
            mode="conservative",
            conservative_overrides=overrides,
        )
        quality = dict(report.quality or {})
        score = _conservative_trial_score(quality)

        row = {
            "trial": idx,
            "score": round(score, 6),
            "overrides": dict(overrides),
            "verdict": str(quality.get("verdict") or "Weak"),
            "source_potential_corr_raw": round(_safe_float(quality.get("source_potential_corr_raw"), 0.0), 6),
            "source_potential_corr_scaled": round(_safe_float(quality.get("source_potential_corr_scaled"), 0.0), 6),
            "stress": round(_safe_float(quality.get("stress"), 0.0), 6),
            "mean_deflection_deg": round(_safe_float(quality.get("mean_deflection_deg"), 0.0), 6),
            "lensing_ratio": round(_safe_float(quality.get("lensing_ratio"), 0.0), 6),
            "coupling_strength": round(_safe_float(quality.get("coupling_strength"), sim.coupling_strength), 6),
        }
        trial_rows.append(row)

        if score > best_score:
            best_score = score
            best_sim = sim
            best_report = report
            best_row = row

        corr_ok = _safe_float(quality.get("source_potential_corr_raw"), 0.0) >= float(target_corr)
        if stop_on_verified and str(quality.get("verdict") or "").lower() == "verified" and corr_ok:
            break

    if best_sim is None or best_report is None:
        raise RuntimeError("auto_tune_failed_no_trials")

    best_quality = dict(best_report.quality or {})
    diagnostic = {
        "enabled": True,
        "mode": "conservative",
        "target_corr": round(float(target_corr), 6),
        "trials_run": len(trial_rows),
        "max_trials": int(max_trials),
        "best_score": round(float(best_score), 6),
        "best_verdict": str(best_quality.get("verdict") or "Weak"),
        "best_source_potential_corr_raw": round(_safe_float(best_quality.get("source_potential_corr_raw"), 0.0), 6),
        "best_source_potential_corr_scaled": round(_safe_float(best_quality.get("source_potential_corr_scaled"), 0.0), 6),
        "best_mean_deflection_deg": round(_safe_float(best_quality.get("mean_deflection_deg"), 0.0), 6),
        "best_lensing_ratio": round(_safe_float(best_quality.get("lensing_ratio"), 0.0), 6),
        "selected_coupling_strength": round(_safe_float(best_quality.get("coupling_strength"), best_sim.coupling_strength), 6),
        "selected_overrides": dict(best_row.get("overrides", {})) if best_row else {},
        "top_trials": sorted(trial_rows, key=lambda item: float(item.get("score", -1e9)), reverse=True)[:8],
    }
    return best_sim, best_report, diagnostic


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atheria_information_einstein_like.py",
        description="Builds an Einstein-like effective geometry from Atheria information traces.",
    )
    parser.add_argument(
        "--report-file",
        default="daemon_runtime/atheria_daemon_audit.jsonl",
        help="Input JSONL source from atheria_daemon audit logs.",
    )
    parser.add_argument("--limit", type=int, default=180, help="Recent row count used for reconstruction.")
    parser.add_argument("--spatial-dims", type=int, default=3, help="Latent space dimensions before projection.")
    parser.add_argument("--probe-count", type=int, default=24, help="Number of geodesic probes.")
    parser.add_argument("--probe-steps", type=int, default=180, help="Integration steps for each probe.")
    parser.add_argument("--dt", type=float, default=0.045, help="Integration timestep.")
    parser.add_argument("--gravity", type=float, default=0.55, help="Effective gravity coupling.")
    parser.add_argument(
        "--mode",
        default="standard",
        choices=["standard", "conservative"],
        help="Simulation mode: conservative reduces coupling and deflection.",
    )
    parser.add_argument(
        "--auto-tune-conservative",
        action="store_true",
        help="Runs a deterministic conservative parameter search and selects the strongest trial.",
    )
    parser.add_argument(
        "--auto-tune-max-trials",
        type=int,
        default=12,
        help="Maximum number of conservative tuning trials.",
    )
    parser.add_argument(
        "--auto-tune-target-corr",
        type=float,
        default=0.35,
        help="Target lower bound for source-potential raw correlation in conservative auto-tune.",
    )
    parser.add_argument(
        "--auto-tune-stop-on-verified",
        action="store_true",
        help="Stops conservative auto-tune early if a verified trial reaches target correlation.",
    )
    parser.add_argument(
        "--path-decimation",
        type=int,
        default=2,
        help="Stores only every N-th probe step for JSON size control.",
    )
    parser.add_argument("--json-out", default=None, help="Optional path to write full reconstruction JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print full JSON to stdout.")
    return parser


def _summary_text(report: EinsteinLikeReconstruction) -> str:
    quality = dict(report.quality or {})
    fields = dict(report.field_summary or {})
    auto_line = ""
    if bool(quality.get("auto_tune_used")):
        auto_line = f"Auto-tune: on ({int(_safe_float(quality.get('auto_tune_trials'), 0))} trials)\n"
    return (
        "Atheria Einstein-like Reconstruction\n"
        + auto_line
        + f"Mode: {quality.get('mode', fields.get('mode', 'standard'))}\n"
        + f"Coupling strength: {quality.get('coupling_strength', fields.get('coupling_strength', 1.0)):.4f}\n"
        + f"Events: {quality.get('event_count', 0)}\n"
        + f"Stress: {quality.get('stress', 0.0):.4f}\n"
        + f"Source-Potential corr: {quality.get('mass_potential_correlation', 0.0):.4f}\n"
        + f"Source-Potential corr (scaled): {quality.get('source_potential_corr_scaled', 0.0):.4f}\n"
        + f"Mean deflection: {quality.get('mean_deflection_deg', 0.0):.4f} deg\n"
        + f"Lensing ratio (>{quality.get('lensing_threshold_deg', 2.0):.1f} deg): {quality.get('lensing_ratio', 0.0):.4f}\n"
        + f"g00 range: {fields.get('g00_min', 0.0):.4f} .. {fields.get('g00_max', 0.0):.4f}\n"
        + f"Verdict: {quality.get('verdict', 'n/a')}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    events = load_events_from_jsonl(Path(str(args.report_file)), limit=max(4, int(args.limit)))
    mode_value = "conservative" if bool(args.auto_tune_conservative) else str(args.mode)
    auto_diag: Optional[Dict[str, Any]] = None
    if bool(args.auto_tune_conservative):
        simulator, report, auto_diag = _auto_tune_conservative(
            events,
            spatial_dims=max(2, int(args.spatial_dims)),
            probe_count=max(4, int(args.probe_count)),
            probe_steps=max(20, int(args.probe_steps)),
            dt=max(0.005, float(args.dt)),
            gravity=max(1e-6, float(args.gravity)),
            path_decimation=max(1, int(args.path_decimation)),
            max_trials=max(1, int(args.auto_tune_max_trials)),
            target_corr=max(0.0, float(args.auto_tune_target_corr)),
            stop_on_verified=bool(args.auto_tune_stop_on_verified),
        )
    else:
        simulator, report = _run_einstein_like(
            events,
            spatial_dims=max(2, int(args.spatial_dims)),
            probe_count=max(4, int(args.probe_count)),
            probe_steps=max(20, int(args.probe_steps)),
            dt=max(0.005, float(args.dt)),
            gravity=max(1e-6, float(args.gravity)),
            path_decimation=max(1, int(args.path_decimation)),
            mode=mode_value,
        )

    payload = report.as_dict()
    if auto_diag is not None:
        payload["auto_tune"] = auto_diag
        quality = dict(payload.get("quality") or {})
        quality["auto_tune_used"] = True
        quality["auto_tune_trials"] = int(auto_diag.get("trials_run", 0))
        quality["auto_tune_best_score"] = round(_safe_float(auto_diag.get("best_score"), 0.0), 6)
        payload["quality"] = quality
        field_summary = dict(payload.get("field_summary") or {})
        field_summary["auto_tune_used"] = True
        field_summary["auto_tune_trials"] = int(auto_diag.get("trials_run", 0))
        payload["field_summary"] = field_summary

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
