from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RuntimeTelemetryExporter:
    """Export runtime metrics as JSON, Prometheus text, and OTLP-like payloads."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = (base_path / ".nova").resolve(strict=False)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.prometheus_path = self.base_path / "runtime-metrics.prom"
        self.otlp_path = self.base_path / "runtime-metrics.otlp.json"

    def snapshot(self) -> dict[str, Any]:
        return {
            "prometheus_path": str(self.prometheus_path),
            "otlp_path": str(self.otlp_path),
        }

    def collect(self, runtime: Any) -> dict[str, Any]:
        context = runtime.context
        if context is None:
            return {}
        control = context.control_runtime.snapshot(limit=10)
        state = context.state_store.snapshot(limit=10)
        workflows = context.workflow_store.snapshot(limit=10)
        mesh = context.mesh.snapshot(limit=10)
        observability = context.observability.snapshot(limit=50)
        histogram = observability.get("histogram", {})
        cluster = context.cluster.snapshot(limit=10)
        security = context.security.snapshot(limit=10)
        return {
            "tenant": context.active_tenant,
            "namespace": context.active_namespace,
            "node_id": context.node_id,
            "datasets": len(context.datasets),
            "services": len(context.services),
            "packages": len(context.packages),
            "queue_total": int(control.get("queued_count", 0)),
            "schedule_total": int(control.get("schedule_count", 0)),
            "event_total": int(control.get("event_count", 0)),
            "state_total": int(state.get("state_count", 0)),
            "workflow_total": int(workflows.get("run_count", 0)),
            "mesh_workers": int(mesh.get("worker_count", 0)),
            "mesh_tasks": int(mesh.get("task_count", 0)),
            "trace_nodes": int(observability.get("node_count", 0)),
            "trace_flows": int(observability.get("flow_count", 0)),
            "trace_errors": int(observability.get("error_count", 0)),
            "trace_count": int(histogram.get("trace_count", 0)),
            "flow_p95_ms": float(histogram.get("flow_p95_ms", 0.0)),
            "error_rate": float(histogram.get("error_rate", 0.0)),
            "cluster_runs": int(cluster.get("run_count", 0)),
            "deployments": len(cluster.get("deployments", [])),
            "tenants": int(security.get("tenant_count", 0)),
            "alerts": len(observability.get("alerts", [])),
        }

    def export_prometheus(self, runtime: Any) -> str:
        metrics = self.collect(runtime)
        lines = [
            "# HELP nova_runtime_metric Nova runtime metric",
            "# TYPE nova_runtime_metric gauge",
        ]
        for key, value in sorted(metrics.items()):
            if isinstance(value, (int, float)):
                lines.append(f"nova_runtime_metric{{name=\"{key}\"}} {float(value)}")
        histogram = runtime.context.observability.histogram() if runtime.context is not None else {}
        for bucket, count in sorted((histogram.get("buckets") or {}).items(), key=lambda item: float(item[0])):
            lines.append(f"nova_runtime_latency_bucket{{le=\"{bucket}\"}} {float(count)}")
        rendered = "\n".join(lines) + "\n"
        self.prometheus_path.write_text(rendered, encoding="utf-8")
        return rendered

    def export_otlp(self, runtime: Any) -> dict[str, Any]:
        metrics = self.collect(runtime)
        payload = {
            "resource": {
                "service.name": "nova-runtime",
                "service.instance.id": metrics.get("node_id"),
                "nova.tenant": metrics.get("tenant"),
                "nova.namespace": metrics.get("namespace"),
            },
            "metrics": [
                {"name": key, "type": "gauge", "value": value}
                for key, value in sorted(metrics.items())
                if isinstance(value, (int, float))
            ],
            "histograms": runtime.context.observability.histogram() if runtime.context is not None else {},
            "alerts": runtime.context.observability.alerts() if runtime.context is not None else [],
        }
        self.otlp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
