from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from nova.parser.ast import SourceSpan


@dataclass(slots=True)
class DatasetNode:
    node_id: str
    name: str
    dataset_name: str
    properties: dict[str, Any]
    span: SourceSpan
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolNode:
    node_id: str
    name: str
    tool_name: str
    arguments: tuple[str, ...] = ()
    alias: str | None = None
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentNode:
    node_id: str
    name: str
    agent_name: str
    action: str | None = None
    inputs: tuple[str, ...] = ()
    alias: str | None = None
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ServiceNode:
    node_id: str
    name: str
    service_name: str
    properties: dict[str, Any]
    span: SourceSpan
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PackageNode:
    node_id: str
    name: str
    package_name: str
    properties: dict[str, Any]
    span: SourceSpan
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FlowNode:
    node_id: str
    name: str
    flow_name: str
    properties: dict[str, Any]
    span: SourceSpan
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EventNode:
    node_id: str
    name: str
    event_name: str
    trigger: str
    flows: tuple[str, ...]
    span: SourceSpan
    flow: str | None = None
    resource: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


GraphNode = DatasetNode | ToolNode | AgentNode | ServiceNode | PackageNode | FlowNode | EventNode


@dataclass(slots=True, frozen=True)
class ExecutionEdge:
    source: str
    target: str
    edge_type: str = "control"
    label: str = ""


@dataclass(slots=True)
class ExecutionGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[ExecutionEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, source: str, target: str, edge_type: str = "control", label: str = "") -> None:
        if source not in self.nodes:
            raise KeyError(f"unknown source node: {source}")
        if target not in self.nodes:
            raise KeyError(f"unknown target node: {target}")
        self.edges.append(ExecutionEdge(source=source, target=target, edge_type=edge_type, label=label))

    def successors(self, node_id: str) -> list[str]:
        return [edge.target for edge in self.edges if edge.source == node_id]

    def flow_root(self, flow_name: str) -> FlowNode:
        for node in self.nodes.values():
            if isinstance(node, FlowNode) and node.flow_name == flow_name and node.resource:
                return node
        raise KeyError(f"unknown flow: {flow_name}")

    def closure_for_flow(self, flow_name: str) -> set[str]:
        root = self.flow_root(flow_name).node_id
        selected: set[str] = {root}
        queue = [root]

        while queue:
            current = queue.pop(0)
            for successor in self.successors(current):
                if successor not in selected:
                    selected.add(successor)
                    queue.append(successor)

        changed = True
        while changed:
            changed = False
            for edge in self.edges:
                if edge.target in selected and edge.source not in selected:
                    selected.add(edge.source)
                    changed = True

        return selected

    def topological_order(self, node_ids: set[str] | None = None) -> list[str]:
        selected = set(node_ids or self.nodes)
        indegree = {node_id: 0 for node_id in selected}

        for edge in self.edges:
            if edge.source in selected and edge.target in selected:
                indegree[edge.target] += 1

        ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
        order: list[str] = []

        while ready:
            current = ready.pop(0)
            order.append(current)
            for edge in self.edges:
                if edge.source != current or edge.target not in indegree:
                    continue
                indegree[edge.target] -= 1
                if indegree[edge.target] == 0:
                    ready.append(edge.target)
                    ready.sort()

        if len(order) != len(selected):
            unresolved = sorted(node_id for node_id in selected if node_id not in order)
            raise ValueError(f"graph contains a cycle involving: {', '.join(unresolved)}")

        return order

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [self._serialize_node(node) for node in self.nodes.values()],
            "edges": [asdict(edge) for edge in self.edges],
        }

    def _serialize_node(self, node: GraphNode) -> dict[str, Any]:
        match node:
            case DatasetNode():
                return {
                    "id": node.node_id,
                    "kind": "dataset",
                    "name": node.name,
                    "dataset": node.dataset_name,
                    "flow": node.flow,
                    "resource": node.resource,
                    "metadata": node.metadata,
                }
            case ToolNode():
                return {
                    "id": node.node_id,
                    "kind": "tool",
                    "name": node.name,
                    "tool": node.tool_name,
                    "arguments": list(node.arguments),
                    "alias": node.alias,
                    "flow": node.flow,
                    "resource": node.resource,
                    "metadata": node.metadata,
                }
            case AgentNode():
                return {
                    "id": node.node_id,
                    "kind": "agent",
                    "name": node.name,
                    "agent": node.agent_name,
                    "action": node.action,
                    "inputs": list(node.inputs),
                    "alias": node.alias,
                    "flow": node.flow,
                    "resource": node.resource,
                    "metadata": node.metadata,
                }
            case ServiceNode():
                return {
                    "id": node.node_id,
                    "kind": "service",
                    "name": node.name,
                    "service": node.service_name,
                    "resource": node.resource,
                    "metadata": node.metadata,
                    "properties": node.properties,
                }
            case PackageNode():
                return {
                    "id": node.node_id,
                    "kind": "package",
                    "name": node.name,
                    "package": node.package_name,
                    "resource": node.resource,
                    "metadata": node.metadata,
                    "properties": node.properties,
                }
            case FlowNode():
                return {
                    "id": node.node_id,
                    "kind": "flow",
                    "name": node.name,
                    "flow": node.flow_name,
                    "resource": node.resource,
                    "metadata": node.metadata,
                    "properties": node.properties,
                }
            case EventNode():
                return {
                    "id": node.node_id,
                    "kind": "event",
                    "name": node.name,
                    "event": node.event_name,
                    "trigger": node.trigger,
                    "flows": list(node.flows),
                    "resource": node.resource,
                    "metadata": node.metadata,
                }
            case _:
                raise TypeError(f"unsupported graph node: {node}")
