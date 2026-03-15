from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from nova.agents.evals import AgentEvalStore
from nova.agents.memory import DistributedMemoryStore
from nova.agents.prompts import PromptRegistry
from nova.agents.providers import ProviderRegistry
from nova.agents.runtime import AgentRuntime
from nova.agents.sandbox import ToolSandbox
from nova.events.bus import Event, EventBus
from nova.graph.model import ExecutionGraph
from nova.mesh.control_plane import PersistentMeshControlPlane
from nova.mesh.registry import MeshRegistry
from nova.parser.ast import NovaAST

from .cluster import ClusterPlane
from .consensus import ControlPlaneConsensus
from .control_plane import DurableControlPlane
from .observability import RuntimeObservability
from .operations import RuntimeOperations
from .policy import RuntimeAuditLog, RuntimePolicy
from .security import SecurityPlane
from .service_fabric import ServiceFabric
from .executors import NativeExecutorManager
from .state_store import PersistentStateStore
from .telemetry import RuntimeTelemetryExporter
from .traffic_plane import ServiceTrafficPlane
from .workflows import PersistentWorkflowStore
from .replication import ReplicatedLogStore

if TYPE_CHECKING:
    from .backends import BackendRouter


class CommandExecutor(Protocol):
    def execute(self, command: str, *, pipeline_data: Any = None, cwd: Path | None = None) -> "CommandExecution":
        ...


def to_jsonable(value: Any) -> Any:
    match value:
        case None | bool() | int() | float() | str():
            return value
        case list():
            return [to_jsonable(item) for item in value]
        case tuple():
            return [to_jsonable(item) for item in value]
        case dict():
            return {str(key): to_jsonable(item) for key, item in value.items()}
        case Path():
            return str(value)
        case _ if hasattr(value, "to_dict") and callable(value.to_dict):
            return to_jsonable(value.to_dict())
        case _:
            return str(value)


@dataclass(slots=True)
class CommandExecution:
    output: str = ""
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "data": to_jsonable(self.data),
            "error": self.error,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(slots=True)
class DatasetSnapshot:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    records: list[Any] = field(default_factory=list)
    version: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def update(self, records: list[Any], *, metadata: dict[str, Any] | None = None) -> None:
        self.records = records
        self.version += 1
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "properties": to_jsonable(self.properties),
            "records": to_jsonable(self.records),
            "version": self.version,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(slots=True)
class NodeExecutionRecord:
    node_id: str
    kind: str
    name: str
    status: str = "ok"
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "output": to_jsonable(self.output),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(slots=True)
class FlowExecutionRecord:
    flow: str
    nodes: list[NodeExecutionRecord] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    trigger_event: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow": self.flow,
            "trigger_event": self.trigger_event,
            "nodes": [node.to_dict() for node in self.nodes],
            "outputs": to_jsonable(self.outputs),
        }


@dataclass(slots=True)
class CompiledNovaProgram:
    ast: NovaAST
    graph: ExecutionGraph
    source_name: str = "<memory>"
    base_path: Path = field(default_factory=Path.cwd)
    modules: list[dict[str, Any]] = field(default_factory=list)
    lockfile: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "base_path": str(self.base_path),
            "graph": self.graph.to_dict(),
            "modules": to_jsonable(self.modules),
            "lockfile": to_jsonable(self.lockfile),
        }


@dataclass(slots=True)
class RuntimeContext:
    base_path: Path
    command_executor: CommandExecutor | None = None
    event_bus: EventBus = field(default_factory=EventBus)
    agent_runtime: AgentRuntime = field(default_factory=AgentRuntime)
    control_plane: PersistentMeshControlPlane | None = None
    mesh: MeshRegistry = field(init=False)
    backend_router: "BackendRouter" = field(init=False)
    observability: RuntimeObservability = field(init=False)
    audit: RuntimeAuditLog = field(init=False)
    policy: RuntimePolicy = field(init=False)
    security: SecurityPlane = field(init=False)
    cluster: ClusterPlane = field(init=False)
    consensus: ControlPlaneConsensus = field(init=False)
    control_runtime: DurableControlPlane = field(init=False)
    datasets: dict[str, DatasetSnapshot] = field(default_factory=dict)
    states: dict[str, Any] = field(default_factory=dict)
    systems: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_definitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    embeddings: dict[str, Any] = field(default_factory=dict)
    agent_memory: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    services: dict[str, dict[str, Any]] = field(default_factory=dict)
    packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_tenant: str = "default"
    active_namespace: str = "default"
    cluster_name: str = "nova"
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    principal: Any = None
    state_store: PersistentStateStore = field(init=False)
    workflow_store: PersistentWorkflowStore = field(init=False)
    replication: ReplicatedLogStore = field(init=False)
    telemetry: RuntimeTelemetryExporter = field(init=False)
    service_fabric: ServiceFabric = field(init=False)
    executors: NativeExecutorManager = field(init=False)
    traffic_plane: ServiceTrafficPlane = field(init=False)
    prompt_registry: PromptRegistry = field(init=False)
    memory_store: DistributedMemoryStore = field(init=False)
    eval_store: AgentEvalStore = field(init=False)
    provider_registry: ProviderRegistry = field(init=False)
    tool_sandbox: ToolSandbox = field(init=False)
    operations: RuntimeOperations = field(init=False)

    def __post_init__(self) -> None:
        from .backends import BackendRouter

        self.control_plane = self.control_plane or PersistentMeshControlPlane(self.base_path)
        self.security = SecurityPlane(self.base_path)
        self.mesh = MeshRegistry(control_plane=self.control_plane, security_plane=self.security)
        self.executors = NativeExecutorManager(self.base_path, command_executor=self.command_executor)
        self.backend_router = BackendRouter(self.command_executor, executor_manager=self.executors)
        self.observability = RuntimeObservability(self.base_path)
        self.audit = RuntimeAuditLog(self.base_path)
        self.policy = RuntimePolicy()
        self.cluster = ClusterPlane(self.base_path)
        self.consensus = ControlPlaneConsensus(self.base_path)
        self.control_runtime = DurableControlPlane(self.base_path)
        self.state_store = PersistentStateStore(self.base_path)
        self.workflow_store = PersistentWorkflowStore(self.base_path)
        self.replication = ReplicatedLogStore(self.base_path)
        self.telemetry = RuntimeTelemetryExporter(self.base_path)
        self.service_fabric = ServiceFabric(self.base_path)
        self.traffic_plane = ServiceTrafficPlane(self.base_path)
        self.prompt_registry = PromptRegistry(self.base_path)
        self.memory_store = DistributedMemoryStore(self.base_path)
        self.eval_store = AgentEvalStore(self.base_path)
        self.provider_registry = ProviderRegistry()
        self.tool_sandbox = ToolSandbox()
        self.operations = RuntimeOperations(self.base_path)
        for component, version in {
            "service_fabric": "2",
            "traffic_plane": "1",
            "control_plane": "2",
            "consensus": "2",
            "prompt_registry": "1",
            "memory_store": "1",
            "eval_store": "1",
            "operations": "1",
        }.items():
            self.operations.register_component(component, version)

    def close(self) -> None:
        if self.control_plane is not None:
            self.control_plane.close()
        self.security.close()
        self.cluster.close()
        self.consensus.close()
        self.control_runtime.close()
        self.state_store.close()
        self.workflow_store.close()
        self.replication.close()
        self.executors.close()
        self.service_fabric.close()
        self.traffic_plane.close()
        self.prompt_registry.close()
        self.memory_store.close()
        self.eval_store.close()
        self.operations.close()

    def resolve_reference(self, token: str) -> Any:
        if token in self.outputs:
            return self.outputs[token]
        if token in self.datasets:
            return self.datasets[token].records
        if token in self.states:
            return self.states[token]
        return token

    def snapshot(self) -> dict[str, Any]:
        return {
            "tenant": self.active_tenant,
            "namespace": self.active_namespace,
            "cluster_name": self.cluster_name,
            "node_id": self.node_id,
            "principal": to_jsonable(self.principal.to_dict() if hasattr(self.principal, "to_dict") else self.principal),
            "datasets": {name: snapshot.to_dict() for name, snapshot in self.datasets.items()},
            "states": to_jsonable(self.states),
            "outputs": to_jsonable(self.outputs),
            "embeddings": to_jsonable(self.embeddings),
            "agent_memory": to_jsonable(self.agent_memory),
            "services": to_jsonable(self.services),
            "packages": to_jsonable(self.packages),
            "mesh": to_jsonable(self.mesh.snapshot()),
            "control_plane": to_jsonable(self.control_runtime.snapshot()),
            "state_store": to_jsonable(self.state_store.snapshot()),
            "workflow_store": to_jsonable(self.workflow_store.snapshot()),
            "replication": to_jsonable(self.replication.snapshot()),
            "policy": to_jsonable(self.policy.snapshot()),
            "audit": to_jsonable(self.audit.snapshot()),
            "security": to_jsonable(self.security.snapshot()),
            "cluster": to_jsonable(self.cluster.snapshot()),
            "consensus": to_jsonable(self.consensus.snapshot()),
            "observability": to_jsonable(self.observability.snapshot()),
            "telemetry": to_jsonable(self.telemetry.snapshot()),
            "service_fabric": to_jsonable(self.service_fabric.snapshot()),
            "executors": to_jsonable(self.executors.snapshot()),
            "traffic_plane": to_jsonable(self.traffic_plane.snapshot()),
            "prompt_registry": to_jsonable(self.prompt_registry.snapshot()),
            "memory_store": to_jsonable(self.memory_store.snapshot()),
            "eval_store": to_jsonable(self.eval_store.snapshot()),
            "tool_sandbox": to_jsonable(self.tool_sandbox.snapshot()),
            "operations": to_jsonable(self.operations.snapshot()),
        }


@dataclass(slots=True)
class NovaRuntimeResult:
    source_name: str
    flows: list[FlowExecutionRecord] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "flows": [flow.to_dict() for flow in self.flows],
            "events": [event.to_dict() for event in self.events],
            "context": to_jsonable(self.context_snapshot),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
