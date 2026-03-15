from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar


@dataclass(slots=True, frozen=True)
class SourceSpan:
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None


@dataclass(slots=True)
class ImportDeclaration:
    target: str
    alias: str | None = None
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class AgentDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class DatasetDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class ToolDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class ServiceDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class PackageDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class StateDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class SystemDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class EventDeclaration:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class FlowStep:
    operation: str
    arguments: tuple[str, ...] = ()
    alias: str | None = None
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


@dataclass(slots=True)
class FlowDeclaration:
    name: str
    steps: list[FlowStep] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    span: SourceSpan = field(default_factory=lambda: SourceSpan(1, 1))


TopLevelDeclaration = (
    ImportDeclaration
    |
    AgentDeclaration
    | DatasetDeclaration
    | ToolDeclaration
    | ServiceDeclaration
    | PackageDeclaration
    | StateDeclaration
    | SystemDeclaration
    | EventDeclaration
    | FlowDeclaration
)

T = TypeVar("T", bound=TopLevelDeclaration)


@dataclass(slots=True)
class NovaAST:
    declarations: list[TopLevelDeclaration] = field(default_factory=list)
    source: str = ""

    def by_type(self, node_type: type[T]) -> list[T]:
        return [node for node in self.declarations if isinstance(node, node_type)]

    def by_name(self) -> dict[str, TopLevelDeclaration]:
        return {getattr(node, "name"): node for node in self.declarations if hasattr(node, "name")}

    def flows(self) -> dict[str, FlowDeclaration]:
        return {node.name: node for node in self.by_type(FlowDeclaration)}

    def imports(self) -> list[ImportDeclaration]:
        return self.by_type(ImportDeclaration)

    def agents(self) -> dict[str, AgentDeclaration]:
        return {node.name: node for node in self.by_type(AgentDeclaration)}

    def datasets(self) -> dict[str, DatasetDeclaration]:
        return {node.name: node for node in self.by_type(DatasetDeclaration)}

    def tools(self) -> dict[str, ToolDeclaration]:
        return {node.name: node for node in self.by_type(ToolDeclaration)}

    def services(self) -> dict[str, ServiceDeclaration]:
        return {node.name: node for node in self.by_type(ServiceDeclaration)}

    def packages(self) -> dict[str, PackageDeclaration]:
        return {node.name: node for node in self.by_type(PackageDeclaration)}

    def events(self) -> dict[str, EventDeclaration]:
        return {node.name: node for node in self.by_type(EventDeclaration)}

    def states(self) -> dict[str, StateDeclaration]:
        return {node.name: node for node in self.by_type(StateDeclaration)}

    def systems(self) -> dict[str, SystemDeclaration]:
        return {node.name: node for node in self.by_type(SystemDeclaration)}
