from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nova.ast import NovaProgram
from nova.compiler import NovaGraphBuilder
from nova.runtime.core import NovaRuntime
from nova.runtime.scheduler import RuntimeScheduler


@dataclass(slots=True)
class ExecutionResult:
    schedule: list[str]
    flow_results: dict[str, list[dict[str, Any]]]


class RuntimeExecutor:
    """High-level runtime executor for compiled Nova programs."""

    def __init__(self) -> None:
        self.runtime = NovaRuntime()
        self.builder = NovaGraphBuilder()
        self.scheduler = RuntimeScheduler()

    def execute(self, source: str, entry_flows: list[str] | None = None) -> ExecutionResult:
        graph = self.runtime.load(source)
        schedule = self.scheduler.create_schedule(graph).order
        program: NovaProgram = self.runtime.program  # type: ignore[assignment]

        flows = [decl.name for decl in program.declarations if decl.__class__.__name__ == "FlowDecl"]
        selected_flows = entry_flows or flows

        flow_results: dict[str, list[dict[str, Any]]] = {}
        for flow_name in selected_flows:
            flow_results[flow_name] = self.runtime.run_flow(flow_name)

        return ExecutionResult(schedule=schedule, flow_results=flow_results)
