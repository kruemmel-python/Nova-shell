from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nova.ast import AgentDecl, DatasetDecl, EventDecl, FlowDecl, MemoryDecl, MeshDecl, NovaProgram, SensorDecl, SystemDecl, ToolDecl


class NodeKind(str, Enum):
    AGENT = "agent"
    DATASET = "dataset"
    TOOL = "tool"
    FLOW = "flow"
    EVENT = "event"
    SENSOR = "sensor"
    MEMORY = "memory"
    MESH = "mesh"
    SYSTEM = "system"


@dataclass(slots=True)
class GraphNode:
    id: str
    kind: NodeKind
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str = "control"


@dataclass(slots=True)
class ExecutionGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, source: str, target: str, relation: str = "control") -> None:
        if source not in self.nodes or target not in self.nodes:
            raise KeyError(f"edge references unknown nodes: {source} -> {target}")
        self.edges.append(GraphEdge(source=source, target=target, relation=relation))

    def topological_order(self) -> list[str]:
        incoming = {node_id: 0 for node_id in self.nodes}
        outgoing: dict[str, list[GraphEdge]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            incoming[edge.target] += 1
            outgoing[edge.source].append(edge)

        ready = [node_id for node_id, count in incoming.items() if count == 0]
        ordered: list[str] = []

        while ready:
            node_id = ready.pop(0)
            ordered.append(node_id)
            for edge in outgoing[node_id]:
                incoming[edge.target] -= 1
                if incoming[edge.target] == 0:
                    ready.append(edge.target)

        if len(ordered) != len(self.nodes):
            raise ValueError("graph contains a cycle")
        return ordered


class GraphCompiler:
    """Compile Nova AST declarations into a DAG execution graph."""

    def compile(self, program: NovaProgram) -> ExecutionGraph:
        graph = ExecutionGraph()

        for declaration in program.declarations:
            match declaration:
                case AgentDecl(name=name):
                    graph.add_node(GraphNode(id=f"agent:{name}", kind=NodeKind.AGENT, metadata=declaration.properties))
                case DatasetDecl(name=name):
                    graph.add_node(GraphNode(id=f"dataset:{name}", kind=NodeKind.DATASET, metadata=declaration.properties))
                case ToolDecl(name=name):
                    graph.add_node(GraphNode(id=f"tool:{name}", kind=NodeKind.TOOL, metadata=declaration.properties))
                case FlowDecl(name=name):
                    graph.add_node(GraphNode(id=f"flow:{name}", kind=NodeKind.FLOW, metadata={"steps": declaration.steps}))
                case EventDecl(name=name, trigger=trigger):
                    graph.add_node(GraphNode(id=f"event:{name}", kind=NodeKind.EVENT, metadata={"trigger": trigger, "actions": declaration.actions}))
                case SensorDecl(name=name):
                    graph.add_node(GraphNode(id=f"sensor:{name}", kind=NodeKind.SENSOR, metadata=declaration.properties))
                case MemoryDecl(name=name):
                    graph.add_node(GraphNode(id=f"memory:{name}", kind=NodeKind.MEMORY, metadata=declaration.properties))
                case MeshDecl(name=name):
                    graph.add_node(GraphNode(id=f"mesh:{name}", kind=NodeKind.MESH, metadata=declaration.properties))
                case SystemDecl(name=name):
                    graph.add_node(GraphNode(id=f"system:{name}", kind=NodeKind.SYSTEM, metadata=declaration.properties))
                case _:
                    continue

        self._add_flow_edges(graph)
        self._add_event_edges(graph)
        graph.topological_order()
        return graph

    def _add_flow_edges(self, graph: ExecutionGraph) -> None:
        flow_nodes = [node for node in graph.nodes.values() if node.kind is NodeKind.FLOW]
        for flow in flow_nodes:
            steps = flow.metadata.get("steps", [])
            if not isinstance(steps, list):
                continue
            for step in steps:
                parts = step.split()
                if not parts:
                    continue
                target = self._resolve_step_target(parts[0], graph)
                if target:
                    graph.add_edge(target, flow.id, relation="feeds")

    def _add_event_edges(self, graph: ExecutionGraph) -> None:
        for event in [node for node in graph.nodes.values() if node.kind is NodeKind.EVENT]:
            actions = event.metadata.get("actions", [])
            if not isinstance(actions, list):
                continue
            for action in actions:
                flow_id = f"flow:{action}"
                if flow_id in graph.nodes:
                    graph.add_edge(event.id, flow_id, relation="triggers")

    def _resolve_step_target(self, token: str, graph: ExecutionGraph) -> str | None:
        if "." in token:
            ns, name = token.split(".", 1)
            candidate = f"{ns}:{name}"
            if candidate in graph.nodes:
                return candidate

        for prefix in ("dataset", "tool", "agent", "sensor", "memory", "mesh"):
            candidate = f"{prefix}:{token}"
            if candidate in graph.nodes:
                return candidate
        return None
