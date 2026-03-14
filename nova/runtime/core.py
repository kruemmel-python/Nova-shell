from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova.agents import AgentConfig, AgentRuntime
from nova.ast import AgentDecl, DatasetDecl, EventDecl, FlowDecl, NovaProgram, ToolDecl
from nova.events import EventBus
from nova.graph import ExecutionGraph, GraphCompiler
from nova.mesh import MeshExecutor
from nova.parser import NovaParser


@dataclass(slots=True)
class RuntimeState:
    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    system: dict[str, Any] = field(default_factory=dict)


class NovaRuntime:
    """AI operating system runtime for Nova language programs."""

    def __init__(self) -> None:
        self.parser = NovaParser()
        self.graph_compiler = GraphCompiler()
        self.event_bus = EventBus()
        self.agent_runtime = AgentRuntime()
        self.mesh_executor = MeshExecutor()
        self.state = RuntimeState()
        self.program: NovaProgram | None = None
        self.graph: ExecutionGraph | None = None
        self._active_flows: set[str] = set()

    def load(self, source: str) -> ExecutionGraph:
        self.program = self.parser.parse(source)
        self.graph = self.graph_compiler.compile(self.program)
        self._register_program_components(self.program)
        return self.graph

    def load_file(self, file_path: str | Path) -> ExecutionGraph:
        source = Path(file_path).read_text(encoding="utf-8")
        return self.load(source)

    def run_flow(self, flow_name: str) -> list[dict[str, Any]]:
        if self.program is None:
            raise RuntimeError("no program loaded")
        flow = next((decl for decl in self.program.declarations if isinstance(decl, FlowDecl) and decl.name == flow_name), None)
        if flow is None:
            raise KeyError(f"flow '{flow_name}' not found")

        if flow_name in self._active_flows:
            return [{"flow": flow_name, "status": "skipped_recursive"}]

        outputs: list[dict[str, Any]] = []
        self._active_flows.add(flow_name)
        try:
            for step in flow.steps:
                outputs.append(self._execute_step(step))
            self.event_bus.publish("flow.finished", {"flow": flow_name, "steps": len(flow.steps)})
        finally:
            self._active_flows.discard(flow_name)
        return outputs

    def emit(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        self.event_bus.publish(topic, payload)

    def _register_program_components(self, program: NovaProgram) -> None:
        for declaration in program.declarations:
            match declaration:
                case AgentDecl(name=name, properties=properties):
                    config = AgentConfig(
                        name=name,
                        model=str(properties.get("model", "llama3")),
                        embeddings_backend=str(properties.get("embeddings", "atheria")),
                    )
                    tools = properties.get("tools")
                    if isinstance(tools, str):
                        config.tools = [item.strip() for item in tools.split(",") if item.strip()]
                    self.agent_runtime.register_agent(config)
                case DatasetDecl(name=name, properties=properties):
                    self.state.datasets[name] = {"definition": properties, "rows": []}
                case ToolDecl(name=name):
                    self.agent_runtime.register_tool(name, lambda payload, tool_name=name: {"tool": tool_name, "ok": True, **payload})
                case EventDecl(trigger=trigger, actions=actions):
                    for action in actions:
                        self.event_bus.subscribe(trigger, lambda _topic, _payload, flow_name=action: self.run_flow(flow_name))
                case _:
                    continue

    def _execute_step(self, step: str) -> dict[str, Any]:
        tokens = step.split()
        if not tokens:
            return {"step": step, "status": "skipped"}

        head, *tail = tokens
        match head, tail:
            case _ if "." in head:
                return self.mesh_executor.execute(task_name=head, payload={"args": tail})
            case agent_name, [task, *args] if agent_name in self.agent_runtime._agents:
                return self.agent_runtime.execute_task(
                    agent_name=agent_name,
                    task=task,
                    payload={"args": args},
                )
            case "emit", [topic, *rest]:
                payload = {"message": " ".join(rest)} if rest else {}
                self.emit(topic, payload)
                return {"step": step, "status": "event_published", "topic": topic}
            case _:
                return {"step": step, "status": "noop", "tokens": tokens}
