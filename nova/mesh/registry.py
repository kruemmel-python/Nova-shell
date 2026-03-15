from __future__ import annotations

import json
import ssl
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

from .control_plane import PersistentMeshControlPlane
from .protocol import ExecutorResult, ExecutorTask


TaskExecutor = Callable[[dict[str, Any]], Any]


@dataclass(slots=True)
class WorkerNode:
    worker_id: str
    capabilities: set[str] = field(default_factory=set)
    endpoint: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    executor: TaskExecutor | None = None
    auth_token: str | None = None
    tls_profile: str | None = None
    tenant: str | None = None
    draining: bool = False
    last_heartbeat: float = field(default_factory=time.time)

    def heartbeat(self) -> None:
        self.last_heartbeat = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "capabilities": sorted(self.capabilities),
            "endpoint": self.endpoint,
            "labels": self.labels,
            "tls_profile": self.tls_profile,
            "tenant": self.tenant,
            "draining": self.draining,
            "last_heartbeat": self.last_heartbeat,
        }


class MeshRegistry:
    """Registry for local and remote workers in the Nova mesh."""

    def __init__(self, control_plane: PersistentMeshControlPlane | None = None, security_plane: Any | None = None) -> None:
        self._workers: dict[str, WorkerNode] = {}
        self.control_plane = control_plane
        self.security_plane = security_plane

    def register(self, worker: WorkerNode) -> None:
        if self.security_plane is not None and hasattr(self.security_plane, "authorize_worker"):
            allowed = self.security_plane.authorize_worker(
                worker_id=worker.worker_id,
                tenant_id=worker.tenant,
                namespace=worker.labels.get("namespace"),
                capabilities=worker.capabilities,
                labels=worker.labels,
                tls_profile=worker.tls_profile,
            )
            if not allowed:
                raise PermissionError(f"worker '{worker.worker_id}' does not satisfy runtime trust policies")
        worker.heartbeat()
        self._workers[worker.worker_id] = worker
        if self.control_plane is not None:
            self.control_plane.register_worker(worker.worker_id, worker.capabilities, worker.endpoint, worker.labels)

    def heartbeat(self, worker_id: str) -> None:
        self._workers[worker_id].heartbeat()
        if self.control_plane is not None:
            self.control_plane.heartbeat(worker_id)

    def list_workers(self) -> list[WorkerNode]:
        return list(self._workers.values())

    def candidates(
        self,
        capability: str,
        *,
        selector: dict[str, str] | None = None,
        tenant: str | None = None,
        require_tls: bool = False,
    ) -> list[WorkerNode]:
        candidates = [
            worker
            for worker in self._workers.values()
            if capability in worker.capabilities
            and not worker.draining
            and self._matches_selector(worker, selector)
            and self._matches_tenant(worker, tenant)
            and self._matches_transport(worker, require_tls)
        ]
        candidates.sort(key=lambda worker: worker.last_heartbeat, reverse=True)
        return candidates

    def select(self, capability: str) -> WorkerNode | None:
        candidates = self.candidates(capability)
        if not candidates:
            return None
        return candidates[0]

    def dispatch(self, capability: str, task: dict[str, Any], fallback: Callable[[], Any]) -> Any:
        selector = task.get("selector")
        selector_dict = {str(key): str(value) for key, value in selector.items()} if isinstance(selector, dict) else None
        tenant = str(task["tenant"]) if task.get("tenant") else None
        require_tls = bool(task.get("require_tls"))
        candidates = self.candidates(capability, selector=selector_dict, tenant=tenant, require_tls=require_tls)
        if not candidates:
            return fallback()

        last_error: Exception | None = None
        for worker in candidates:
            worker.heartbeat()
            task_record = self.control_plane.start_task(capability, worker.worker_id, task) if self.control_plane is not None else None
            try:
                if worker.executor is not None:
                    result = worker.executor(task)
                elif worker.endpoint:
                    result = self._dispatch_protocol(
                        worker.endpoint,
                        ExecutorTask.from_dispatch_task(capability, task),
                        auth_token=worker.auth_token,
                        ssl_context=self._ssl_context_for_worker(worker),
                    )
                else:
                    continue
                if task_record is not None:
                    result_payload = result.to_dict() if hasattr(result, "to_dict") and callable(result.to_dict) else {"result": str(result)}
                    self.control_plane.finish_task(task_record.task_id, status="ok", result=result_payload)
                return result
            except Exception as exc:
                last_error = exc
                if task_record is not None:
                    self.control_plane.finish_task(task_record.task_id, status="error", result={"error": str(exc)})
                continue

        if last_error is not None:
            raise last_error
        return fallback()

    def _dispatch_protocol(
        self,
        endpoint: str,
        task: ExecutorTask,
        *,
        auth_token: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib.request.Request(
            endpoint.rstrip("/") + "/protocol/execute",
            data=json.dumps(task.to_dict(), ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        open_kwargs: dict[str, Any] = {"timeout": 20}
        if ssl_context is not None:
            open_kwargs["context"] = ssl_context
        try:
            with urllib.request.urlopen(request, **open_kwargs) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            if task.command is None:
                raise
            request = urllib.request.Request(
                endpoint.rstrip("/") + "/execute",
                data=json.dumps({"command": task.command, "pipeline_data": task.pipeline_data}, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, **open_kwargs) as response:
                payload = json.loads(response.read().decode("utf-8"))
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        result = ExecutorResult(
            request_id=str(payload.get("request_id") or task.request_id),
            status=str(payload.get("status") or "ok"),
            output=str(payload.get("output", "")),
            data=payload.get("data"),
            error=payload.get("error"),
            data_type=str(payload.get("data_type") or "text"),
            metadata=dict(payload.get("metadata") or {}),
        )
        return result.to_dict()

    def _matches_selector(self, worker: WorkerNode, selector: dict[str, str] | None) -> bool:
        if not selector:
            return True
        for key, expected in selector.items():
            if worker.labels.get(key) != expected:
                return False
        return True

    def _matches_tenant(self, worker: WorkerNode, tenant: str | None) -> bool:
        if tenant is None or worker.tenant is None:
            return True
        return worker.tenant == tenant

    def _matches_transport(self, worker: WorkerNode, require_tls: bool) -> bool:
        if not require_tls:
            return True
        if worker.endpoint is None:
            return True
        parsed = urllib.parse.urlparse(worker.endpoint)
        return parsed.scheme == "https"

    def _ssl_context_for_worker(self, worker: WorkerNode) -> ssl.SSLContext | None:
        if self.security_plane is None or worker.tls_profile is None:
            return None
        profile = self.security_plane.get_tls_profile(worker.tls_profile)
        if not isinstance(profile, dict):
            return None
        from nova.runtime.security import TLSProfile

        tls_profile = TLSProfile(
            name=str(profile["name"]),
            certfile=str(profile["certfile"]),
            keyfile=str(profile["keyfile"]),
            cafile=str(profile["cafile"]) if profile.get("cafile") else None,
            verify=bool(profile.get("verify", True)),
            server_hostname=str(profile["server_hostname"]) if profile.get("server_hostname") else None,
        )
        return tls_profile.create_client_context()

    def health_report(self, timeout: float = 1.0) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for worker in self.list_workers():
            started = time.perf_counter()
            healthy = True
            error: str | None = None
            payload: dict[str, Any] | None = None
            try:
                if worker.executor is None and worker.endpoint:
                    request = urllib.request.Request(worker.endpoint.rstrip("/") + "/health", method="GET")
                    open_kwargs: dict[str, Any] = {"timeout": timeout}
                    ssl_context = self._ssl_context_for_worker(worker)
                    if ssl_context is not None:
                        open_kwargs["context"] = ssl_context
                    with urllib.request.urlopen(request, **open_kwargs) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                else:
                    payload = {"status": "ok", "mode": "local"}
            except Exception as exc:
                healthy = False
                error = str(exc)
            rows.append(
                {
                    "worker_id": worker.worker_id,
                    "endpoint": worker.endpoint,
                    "capabilities": sorted(worker.capabilities),
                    "tenant": worker.tenant,
                    "labels": dict(worker.labels),
                    "healthy": healthy,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "error": error,
                    "payload": payload,
                }
            )
        return rows

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        workers = [worker.to_dict() for worker in self.list_workers()]
        if self.control_plane is None:
            return {"workers": workers, "health": self.health_report(), "tasks": [], "worker_count": len(workers), "task_count": 0}
        payload = self.control_plane.snapshot(limit=limit)
        payload["live_workers"] = workers
        payload["health"] = self.health_report()
        return payload
