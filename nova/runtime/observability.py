from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RuntimeTraceRecord:
    kind: str
    name: str
    status: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    correlation_id: str | None = None
    flow: str | None = None
    node_id: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "correlation_id": self.correlation_id,
            "flow": self.flow,
            "node_id": self.node_id,
            "duration_ms": round(self.duration_ms, 3),
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class RuntimeObservability:
    """In-memory + JSONL trace store for Nova runtime execution."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = state_dir / "runtime-observability.jsonl"
        self._lock = threading.RLock()
        self._records: list[RuntimeTraceRecord] = []
        self._alert_rules: list[dict[str, Any]] = [
            {"name": "error-rate", "metric": "error_rate", "threshold": 0.2},
            {"name": "flow-p95-latency", "metric": "flow_p95_ms", "threshold": 5000.0},
        ]

    def record(
        self,
        *,
        kind: str,
        name: str,
        status: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        correlation_id: str | None = None,
        flow: str | None = None,
        node_id: str | None = None,
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeTraceRecord:
        record = RuntimeTraceRecord(
            kind=kind,
            name=name,
            status=status,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            correlation_id=correlation_id,
            flow=flow,
            node_id=node_id,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
        with self._lock:
            self._records.append(record)
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def add_alert_rule(self, name: str, metric: str, threshold: float) -> dict[str, Any]:
        rule = {"name": name, "metric": metric, "threshold": float(threshold)}
        with self._lock:
            self._alert_rules = [item for item in self._alert_rules if item["name"] != name]
            self._alert_rules.append(rule)
        return rule

    def traces(self, limit: int = 100, *, trace_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            records = self._records
            if trace_id:
                records = [record for record in records if record.trace_id == trace_id]
            return [record.to_dict() for record in records[-max(1, limit) :]]

    def histogram(self) -> dict[str, Any]:
        buckets = [5.0, 25.0, 100.0, 250.0, 1000.0, 5000.0]
        counts = {bucket: 0 for bucket in buckets}
        durations = [float(record.duration_ms) for record in self._records if float(record.duration_ms) > 0.0]
        for duration in durations:
            for bucket in buckets:
                if duration <= bucket:
                    counts[bucket] += 1
        flows = [float(record.duration_ms) for record in self._records if record.kind == "flow" and float(record.duration_ms) > 0.0]
        node_errors = sum(1 for record in self._records if record.kind == "node" and record.status == "error")
        total_records = len(self._records)
        flow_p95 = 0.0
        if flows:
            ordered = sorted(flows)
            index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * 0.95))))
            flow_p95 = ordered[index]
        error_rate = (sum(1 for record in self._records if record.status == "error") / total_records) if total_records else 0.0
        return {
            "buckets": {str(bucket): count for bucket, count in counts.items()},
            "flow_p95_ms": flow_p95,
            "node_error_count": node_errors,
            "error_rate": error_rate,
            "trace_count": total_records,
        }

    def alerts(self) -> list[dict[str, Any]]:
        histogram = self.histogram()
        alerts: list[dict[str, Any]] = []
        for rule in self._alert_rules:
            observed = float(histogram.get(rule["metric"], 0.0))
            if observed >= float(rule["threshold"]):
                alerts.append({"name": rule["name"], "metric": rule["metric"], "threshold": rule["threshold"], "observed": observed, "status": "firing"})
        return alerts

    def validate_trace_store(self) -> dict[str, Any]:
        if not self.trace_path.exists():
            return {"valid": True, "records": 0}
        lines = self.trace_path.read_text(encoding="utf-8").splitlines()
        parsed = 0
        for line in lines:
            if not line.strip():
                continue
            json.loads(line)
            parsed += 1
        return {"valid": True, "records": parsed}

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        with self._lock:
            recent = [record.to_dict() for record in self._records[-max(1, limit) :]]
            error_count = sum(1 for record in self._records if record.status == "error")
            node_count = sum(1 for record in self._records if record.kind == "node")
            flow_count = sum(1 for record in self._records if record.kind == "flow")
        return {
            "trace_path": str(self.trace_path),
            "records": recent,
            "error_count": error_count,
            "node_count": node_count,
            "flow_count": flow_count,
            "histogram": self.histogram(),
            "alerts": self.alerts(),
            "validation": self.validate_trace_store(),
        }
