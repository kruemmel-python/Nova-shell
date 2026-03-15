from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nova.parser.ast import (
    AgentDeclaration,
    DatasetDeclaration,
    EventDeclaration,
    FlowDeclaration,
    FlowStep,
    ImportDeclaration,
    NovaAST,
    PackageDeclaration,
    ServiceDeclaration,
    StateDeclaration,
    SystemDeclaration,
    ToolDeclaration,
)

from .model import AgentNode, DatasetNode, EventNode, ExecutionGraph, FlowNode, PackageNode, ServiceNode, ToolNode


class GraphCompileError(ValueError):
    pass


class GraphCycleError(GraphCompileError):
    pass


@dataclass(slots=True)
class _DefinitionIndex:
    agents: dict[str, AgentDeclaration]
    datasets: dict[str, DatasetDeclaration]
    tools: dict[str, ToolDeclaration]
    services: dict[str, ServiceDeclaration]
    packages: dict[str, PackageDeclaration]
    flows: dict[str, FlowDeclaration]
    events: dict[str, EventDeclaration]
    states: dict[str, StateDeclaration]
    systems: dict[str, SystemDeclaration]


class NovaGraphCompiler:
    """Compile Nova AST into a DAG-based execution graph."""

    def compile(self, ast: NovaAST) -> ExecutionGraph:
        graph = ExecutionGraph()
        index = _DefinitionIndex(
            agents=ast.agents(),
            datasets=ast.datasets(),
            tools=ast.tools(),
            services=ast.services(),
            packages=ast.packages(),
            flows=ast.flows(),
            events=ast.events(),
            states=ast.states(),
            systems=ast.systems(),
        )

        for declaration in ast.declarations:
            match declaration:
                case AgentDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        AgentNode(
                            node_id=f"agent::{name}",
                            name=name,
                            agent_name=name,
                            span=span,
                            resource=True,
                            metadata={"definition": properties},
                        )
                    )
                case DatasetDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        DatasetNode(
                            node_id=f"dataset::{name}",
                            name=name,
                            dataset_name=name,
                            properties=properties,
                            span=span,
                            resource=True,
                            metadata={"definition": properties},
                        )
                    )
                case ToolDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        ToolNode(
                            node_id=f"tool::{name}",
                            name=name,
                            tool_name=name,
                            span=span,
                            resource=True,
                            metadata={"definition": properties},
                        )
                    )
                case ServiceDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        ServiceNode(
                            node_id=f"service::{name}",
                            name=name,
                            service_name=name,
                            properties=properties,
                            span=span,
                            resource=True,
                            metadata={"definition": properties, "tenant": properties.get("tenant"), "namespace": properties.get("namespace")},
                        )
                    )
                case PackageDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        PackageNode(
                            node_id=f"package::{name}",
                            name=name,
                            package_name=name,
                            properties=properties,
                            span=span,
                            resource=True,
                            metadata={"definition": properties, "tenant": properties.get("tenant"), "namespace": properties.get("namespace")},
                        )
                    )
                case FlowDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        FlowNode(
                            node_id=f"flow::{name}",
                            name=name,
                            flow_name=name,
                            properties=properties,
                            span=span,
                            resource=True,
                            metadata={"definition": properties},
                        )
                    )
                case EventDeclaration(name=name, properties=properties, span=span):
                    graph.add_node(
                        EventNode(
                            node_id=f"event::{name}",
                            name=name,
                            event_name=name,
                            trigger=str(properties.get("on", name)),
                            flows=self._event_flows(properties),
                            span=span,
                            resource=True,
                            metadata={"definition": properties},
                        )
                    )
                case ImportDeclaration() | StateDeclaration() | SystemDeclaration():
                    continue
                case _:
                    raise GraphCompileError(f"unsupported declaration: {declaration}")

        for flow in index.flows.values():
            self._compile_flow(flow, index, graph)

        for event in index.events.values():
            self._compile_event_edges(event, index, graph)

        try:
            graph.topological_order()
        except ValueError as exc:
            raise GraphCycleError(str(exc)) from exc
        return graph

    def _compile_flow(self, flow: FlowDeclaration, index: _DefinitionIndex, graph: ExecutionGraph) -> None:
        previous_node = f"flow::{flow.name}"
        aliases: dict[str, str] = {}

        for step_index, step in enumerate(flow.steps, start=1):
            node_id = f"flow::{flow.name}::step::{step_index}"
            node = self._compile_flow_step(flow, step, node_id, index)
            graph.add_node(node)
            graph.add_edge(previous_node, node.node_id, "control", "sequence")

            for argument in step.arguments:
                if argument in index.datasets:
                    graph.add_edge(f"dataset::{argument}", node.node_id, "data", argument)
                if argument in aliases:
                    graph.add_edge(aliases[argument], node.node_id, "data", argument)
                if argument in index.states:
                    node.metadata.setdefault("state_inputs", []).append(argument)

            match node:
                case AgentNode(agent_name=agent_name):
                    graph.add_edge(f"agent::{agent_name}", node.node_id, "definition", agent_name)
                case ToolNode(tool_name=tool_name) if tool_name in index.tools:
                    graph.add_edge(f"tool::{tool_name}", node.node_id, "definition", tool_name)
                case _:
                    pass

            if step.alias:
                aliases[step.alias] = node.node_id
            previous_node = node.node_id

    def _compile_flow_step(
        self,
        flow: FlowDeclaration,
        step: FlowStep,
        node_id: str,
        index: _DefinitionIndex,
    ) -> AgentNode | ToolNode:
        flow_system = str(flow.properties.get("system", "") or "").strip() or None

        if step.operation in index.agents:
            action, inputs = self._agent_action_and_inputs(step, index)
            agent_definition = index.agents[step.operation]
            system_name, system_definition = self._resolve_system(agent_definition.properties.get("system"), flow_system, index)
            metadata: dict[str, Any] = {
                "system": system_name,
                "system_definition": system_definition,
                "capability": str(agent_definition.properties.get("capability") or system_definition.get("capability") or "agent"),
                "provider": str(agent_definition.properties.get("provider") or ""),
                "model": str(agent_definition.properties.get("model") or ""),
                "tenant": self._resolve_property("tenant", agent_definition.properties, flow.properties, system_definition),
                "namespace": self._resolve_property("namespace", agent_definition.properties, flow.properties, system_definition),
                "required_roles": self._normalize_list_property(self._resolve_property("required_roles", agent_definition.properties, flow.properties, system_definition)),
                "selector": self._normalize_dict_property(self._resolve_property("selector", agent_definition.properties, flow.properties, system_definition)),
                "require_tls": bool(self._resolve_property("require_tls", agent_definition.properties, flow.properties, system_definition)),
            }
            return AgentNode(
                node_id=node_id,
                name=f"{flow.name}:{step.operation}",
                agent_name=step.operation,
                action=action,
                inputs=inputs,
                alias=step.alias,
                span=step.span,
                flow=flow.name,
                metadata=metadata,
            )

        tool_properties = index.tools.get(step.operation).properties if step.operation in index.tools else {}
        system_name, system_definition = self._resolve_system(tool_properties.get("system"), flow_system, index)
        metadata = {
            "system": system_name,
            "system_definition": system_definition,
            "capability": str(tool_properties.get("capability") or system_definition.get("capability") or self._infer_capability(step.operation)),
            "backend": self._infer_backend(step.operation),
            "tenant": self._resolve_property("tenant", tool_properties, flow.properties, system_definition),
            "namespace": self._resolve_property("namespace", tool_properties, flow.properties, system_definition),
            "required_roles": self._normalize_list_property(self._resolve_property("required_roles", tool_properties, flow.properties, system_definition)),
            "selector": self._normalize_dict_property(self._resolve_property("selector", tool_properties, flow.properties, system_definition)),
            "require_tls": bool(self._resolve_property("require_tls", tool_properties, flow.properties, system_definition)),
        }
        return ToolNode(
            node_id=node_id,
            name=f"{flow.name}:{step.operation}",
            tool_name=step.operation,
            arguments=step.arguments,
            alias=step.alias,
            span=step.span,
            flow=flow.name,
            metadata=metadata,
        )

    def _agent_action_and_inputs(self, step: FlowStep, index: _DefinitionIndex) -> tuple[str | None, tuple[str, ...]]:
        if not step.arguments:
            return None, ()
        first_argument = step.arguments[0]
        if first_argument in index.datasets or first_argument in index.states:
            return None, step.arguments
        return first_argument, step.arguments[1:]

    def _resolve_system(self, preferred: Any, flow_system: str | None, index: _DefinitionIndex) -> tuple[str | None, dict[str, Any]]:
        system_name = str(preferred or flow_system or "").strip() or None
        if system_name is None:
            return None, {}
        declaration = index.systems.get(system_name)
        return system_name, dict(declaration.properties) if declaration is not None else {}

    def _resolve_property(self, key: str, primary: dict[str, Any], secondary: dict[str, Any], tertiary: dict[str, Any]) -> Any:
        if key in primary:
            return primary[key]
        if key in secondary:
            return secondary[key]
        return tertiary.get(key)

    def _normalize_list_property(self, value: Any) -> list[str]:
        match value:
            case None:
                return []
            case str():
                return [item.strip() for item in value.split(",") if item.strip()]
            case list() | tuple() | set():
                return [str(item) for item in value if str(item)]
            case _:
                return [str(value)]

    def _normalize_dict_property(self, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(key): str(item) for key, item in value.items()}

    def _infer_backend(self, operation: str) -> str:
        prefixes = {
            "py.": "python",
            "cpp.": "cpp",
            "gpu.": "gpu",
            "wasm.": "wasm",
            "sys.": "system",
            "system.": "system",
            "ai.": "ai",
            "atheria.": "atheria",
            "memory.": "memory",
            "mesh.": "mesh",
            "data.": "data",
            "event.": "event",
            "flow.": "flow",
            "state.": "state",
        }
        for prefix, backend in prefixes.items():
            if operation.startswith(prefix):
                return backend
        return "tool"

    def _infer_capability(self, operation: str) -> str:
        backend = self._infer_backend(operation)
        aliases = {
            "python": "py",
            "system": "cpu",
            "cpp": "cpp",
            "gpu": "gpu",
            "wasm": "wasm",
            "ai": "ai",
            "atheria": "ai",
            "memory": "memory",
            "mesh": "mesh",
            "data": "data",
            "event": "event",
            "flow": "flow",
            "state": "state",
            "tool": "tool",
        }
        return aliases.get(backend, "tool")

    def _compile_event_edges(self, event: EventDeclaration, index: _DefinitionIndex, graph: ExecutionGraph) -> None:
        node_id = f"event::{event.name}"
        flows = self._event_flows(event.properties)
        if not flows:
            raise GraphCompileError(f"event '{event.name}' does not reference any flow")
        for flow_name in flows:
            if flow_name not in index.flows:
                raise GraphCompileError(f"event '{event.name}' references unknown flow '{flow_name}'")
            graph.add_edge(node_id, f"flow::{flow_name}", "trigger", event.name)

    def _event_flows(self, properties: dict[str, Any]) -> tuple[str, ...]:
        flows_value = properties.get("flows")
        if isinstance(flows_value, list):
            return tuple(str(item) for item in flows_value)
        if "flow" in properties:
            return (str(properties["flow"]),)
        if isinstance(flows_value, str):
            return (flows_value,)
        if isinstance(properties.get("run"), str):
            return (str(properties["run"]),)
        if isinstance(properties.get("run"), list):
            return tuple(str(item) for item in properties["run"])
        return ()
