from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkerNode:
    worker_id: str
    capabilities: set[str] = field(default_factory=set)
    running_tasks: int = 0


@dataclass(slots=True)
class MeshRegistry:
    workers: dict[str, WorkerNode] = field(default_factory=dict)

    def register(self, worker: WorkerNode) -> None:
        self.workers[worker.worker_id] = worker

    def pick_worker(self, capability: str | None = None) -> WorkerNode | None:
        candidates = list(self.workers.values())
        if capability:
            candidates = [worker for worker in candidates if capability in worker.capabilities]
        if not candidates:
            return None
        return min(candidates, key=lambda worker: worker.running_tasks)


class MeshExecutor:
    """Routes tasks to local or registered mesh worker nodes."""

    def __init__(self) -> None:
        self.registry = MeshRegistry()

    def execute(self, task_name: str, payload: dict[str, Any] | None = None, capability: str | None = None) -> dict[str, Any]:
        payload = payload or {}
        worker = self.registry.pick_worker(capability)
        if worker is None:
            return {"mode": "local", "task": task_name, "payload": payload}

        worker.running_tasks += 1
        try:
            return {
                "mode": "mesh",
                "worker": worker.worker_id,
                "task": task_name,
                "payload": payload,
            }
        finally:
            worker.running_tasks = max(0, worker.running_tasks - 1)
