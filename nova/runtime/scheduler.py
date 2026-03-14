from __future__ import annotations

from dataclasses import dataclass

from nova.graph import ExecutionGraph


@dataclass(slots=True)
class Schedule:
    order: list[str]


class RuntimeScheduler:
    """Deterministic scheduler for DAG execution."""

    def create_schedule(self, graph: ExecutionGraph) -> Schedule:
        return Schedule(order=graph.topological_order())
