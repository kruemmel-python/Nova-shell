from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceSpan:
    line: int
    column: int = 1


@dataclass(slots=True)
class NovaNode:
    name: str
    span: SourceSpan


@dataclass(slots=True)
class AgentDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DatasetDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StateDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SystemDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SensorDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MeshDecl(NovaNode):
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EventDecl(NovaNode):
    trigger: str
    actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FlowDecl(NovaNode):
    steps: list[str] = field(default_factory=list)


Declaration = (
    AgentDecl
    | DatasetDecl
    | ToolDecl
    | StateDecl
    | SystemDecl
    | SensorDecl
    | MemoryDecl
    | MeshDecl
    | EventDecl
    | FlowDecl
)


@dataclass(slots=True)
class NovaProgram:
    declarations: list[Declaration]

    def by_type(self, node_type: type[Declaration]) -> list[Declaration]:
        return [decl for decl in self.declarations if isinstance(decl, node_type)]

    def names(self) -> set[str]:
        return {decl.name for decl in self.declarations}
