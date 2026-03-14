from __future__ import annotations

from dataclasses import asdict, dataclass

from nova.ast import EventDecl, FlowDecl, NovaProgram
from nova.graph import ExecutionGraph, GraphCompiler


@dataclass(slots=True)
class CompiledPlan:
    nodes: list[dict[str, object]]
    edges: list[dict[str, str]]
    order: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"nodes": self.nodes, "edges": self.edges, "order": self.order}


class NovaGraphBuilder:
    """Compile AST into a graph and execution plan."""

    def __init__(self) -> None:
        self.compiler = GraphCompiler()

    def build(self, program: NovaProgram) -> tuple[ExecutionGraph, CompiledPlan]:
        graph = self.compiler.compile(program)
        plan = CompiledPlan(
            nodes=[{"id": node.id, "kind": node.kind.value, "metadata": node.metadata} for node in graph.nodes.values()],
            edges=[asdict(edge) for edge in graph.edges],
            order=graph.topological_order(),
        )
        return graph, plan

    def render_plan(self, program: NovaProgram) -> list[str]:
        """Human-readable execution plan lines."""
        lines: list[str] = []
        for declaration in program.declarations:
            match declaration:
                case FlowDecl(name=name, steps=steps):
                    lines.append(f"flow {name}")
                    lines.extend([f"  - {step}" for step in steps])
                case EventDecl(name=name, trigger=trigger, actions=actions):
                    lines.append(f"event {name}: on {trigger} -> {', '.join(actions)}")
                case _:
                    continue
        return lines
