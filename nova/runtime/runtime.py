from __future__ import annotations

import json
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from nova.agents.runtime import AgentTask
from nova.events.bus import Event
from nova.graph.compiler import NovaGraphCompiler
from nova.graph.model import AgentNode, DatasetNode, EventNode, FlowNode, PackageNode, ServiceNode, ToolNode
from nova.parser.ast import AgentDeclaration, EventDeclaration, NovaAST, PackageDeclaration, ServiceDeclaration, StateDeclaration, SystemDeclaration, ToolDeclaration
from nova.parser.parser import NovaParser
from nova.toolchain import NovaFormatter, NovaLanguageServerFacade, NovaLinter, NovaModuleLoader, NovaPackageRegistry, NovaTestRunner

from .backends import BackendExecutionRequest
from .context import CommandExecution, CompiledNovaProgram, DatasetSnapshot, FlowExecutionRecord, NodeExecutionRecord, NovaRuntimeResult, RuntimeContext, to_jsonable
from .security import AuthPrincipal


class NovaRuntime:
    """Runtime for declarative Nova programs compiled into execution graphs."""

    def __init__(
        self,
        *,
        parser: NovaParser | None = None,
        compiler: NovaGraphCompiler | None = None,
        command_executor: Any | None = None,
        event_bridge: Callable[[Event], None] | None = None,
    ) -> None:
        self.parser = parser or NovaParser()
        self.compiler = compiler or NovaGraphCompiler()
        self.command_executor = command_executor
        self.event_bridge = event_bridge
        self.program: CompiledNovaProgram | None = None
        self.context: RuntimeContext | None = None
        self._execution_stack: list[str] = []
        self._triggered_flows: list[FlowExecutionRecord] = []
        self._daemon_thread: threading.Thread | None = None
        self._daemon_stop = threading.Event()
        self._daemon_interval = 1.0
        self._api_server: Any | None = None
        self._trace_stack: list[dict[str, str]] = []
        self._package_registry: NovaPackageRegistry | None = None
        self._module_loader: NovaModuleLoader | None = None
        self._formatter = NovaFormatter()
        self._linter = NovaLinter()
        self._lsp = NovaLanguageServerFacade()
        self._test_runner = NovaTestRunner()

    def __enter__(self) -> "NovaRuntime":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        self.stop_control_api()
        self.stop_control_daemon()
        if self.context is not None:
            self.context.close()
        self.context = None

    def compile(self, source: str, *, source_name: str = "<memory>", base_path: str | Path | None = None) -> CompiledNovaProgram:
        target_base = Path(base_path or Path.cwd()).resolve(strict=False)
        self._package_registry = NovaPackageRegistry(target_base)
        self._module_loader = NovaModuleLoader(self.parser, self._package_registry)
        loaded_program = self._module_loader.load(source, source_name=source_name, base_path=target_base)
        ast = loaded_program.ast
        graph = self.compiler.compile(ast)
        return CompiledNovaProgram(
            ast=ast,
            graph=graph,
            source_name=source_name,
            base_path=target_base,
            modules=[
                {
                    "module_id": item.module_id,
                    "source_name": item.source_name,
                    "path": item.path,
                    "checksum": item.checksum,
                    "imports": item.imports,
                }
                for item in loaded_program.modules
            ],
            lockfile=loaded_program.lockfile,
        )

    def load(self, program_or_source: CompiledNovaProgram | str, *, source_name: str = "<memory>", base_path: str | Path | None = None) -> CompiledNovaProgram:
        program = program_or_source if isinstance(program_or_source, CompiledNovaProgram) else self.compile(program_or_source, source_name=source_name, base_path=base_path)
        if self.context is not None:
            self.context.close()
        self.program = program
        self.context = RuntimeContext(base_path=program.base_path, command_executor=self.command_executor)
        self._register_program_resources(program)
        self._configure_platform(program)
        self._refresh_state_cache()
        self._register_event_bindings(program)
        return program

    def run(
        self,
        program_or_source: CompiledNovaProgram | str,
        *,
        flow: str | None = None,
        source_name: str = "<memory>",
        base_path: str | Path | None = None,
    ) -> NovaRuntimeResult:
        program = self.load(program_or_source, source_name=source_name, base_path=base_path)
        target_flows = [flow] if flow else self._entry_flows(program.ast)
        executed_flows = [self.execute_flow(flow_name) for flow_name in target_flows]
        return NovaRuntimeResult(
            source_name=program.source_name,
            flows=executed_flows,
            events=list(self.context.event_bus.history if self.context else []),
            context_snapshot=self.context.snapshot() if self.context else {},
        )

    def execute_flow(self, flow_name: str, *, trigger_event: str | None = None) -> FlowExecutionRecord:
        if self.program is None or self.context is None:
            raise RuntimeError("no Nova program is loaded")
        if flow_name in self._execution_stack:
            return FlowExecutionRecord(flow=flow_name, trigger_event=trigger_event)

        graph = self.program.graph
        ordered_nodes = graph.topological_order(graph.closure_for_flow(flow_name))
        flow_record = FlowExecutionRecord(flow=flow_name, trigger_event=trigger_event)
        started_at = time.perf_counter()
        flow_status = "ok"
        flow_error: str | None = None

        self._maybe_failpoint("flow.execute.start")
        self._authorize_flow(flow_name)
        flow_trace = self._begin_trace("flow", flow_name, trigger_event=trigger_event)

        self._execution_stack.append(flow_name)
        self._publish_event("flow.started", {"flow": flow_name, "trigger_event": trigger_event}, source=flow_name)
        try:
            for node_id in ordered_nodes:
                node = graph.nodes[node_id]
                record = self._execute_node(node)
                if record is not None:
                    flow_record.nodes.append(record)
            flow_record.outputs = dict(self.context.outputs)
        except Exception as exc:
            flow_status = "error"
            flow_error = str(exc)
            self._audit("flow", flow_name, "error", {"trigger_event": trigger_event, "error": flow_error})
            raise
        finally:
            self._execution_stack.pop()
            self._publish_event("flow.finished", {"flow": flow_name}, source=flow_name)
            self.context.observability.record(
                kind="flow",
                name=flow_name,
                status=flow_status,
                trace_id=flow_trace["trace_id"],
                span_id=flow_trace["span_id"],
                parent_span_id=flow_trace.get("parent_span_id"),
                correlation_id=flow_trace["correlation_id"],
                flow=flow_name,
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
                metadata={"trigger_event": trigger_event, "node_count": len(flow_record.nodes), "error": flow_error},
            )
            self._end_trace(flow_trace)
            if flow_status == "ok":
                self._audit("flow", flow_name, "ok", {"trigger_event": trigger_event, "node_count": len(flow_record.nodes)})
            workflow_record = self.context.workflow_store.record_run(
                flow_name,
                trigger_event=trigger_event,
                status=flow_status,
                record=flow_record.to_dict(),
                metadata={"error": flow_error, "tenant": self.context.active_tenant, "namespace": self.context.active_namespace},
            )
            self.context.replication.append_record(
                "workflow",
                workflow_record,
                tenant_id=self.context.active_tenant,
                namespace=self.context.active_namespace,
                source_node=self.context.node_id,
                metadata={"category": "workflow"},
                record_id=str(workflow_record["run_id"]),
            )

        return flow_record

    def emit(self, event_name: str, payload: Any = None) -> NovaRuntimeResult:
        if self.program is None or self.context is None:
            raise RuntimeError("no Nova program is loaded")
        self._triggered_flows = []
        self._publish_event(event_name, payload, source="external")
        return NovaRuntimeResult(
            source_name=self.program.source_name,
            flows=list(self._triggered_flows),
            events=list(self.context.event_bus.history),
            context_snapshot=self.context.snapshot(),
        )

    def snapshot(self, file_path: str | Path | None = None) -> dict[str, Any]:
        if self.program is None or self.context is None:
            raise RuntimeError("no Nova program is loaded")
        payload = {
            "version": 1,
            "source_name": self.program.source_name,
            "base_path": str(self.program.base_path),
            "source": self.program.ast.source,
            "context": self.context.snapshot(),
            "events": [event.to_dict() for event in self.context.event_bus.history],
        }
        target = Path(file_path) if file_path else (self.program.base_path / ".nova" / "runtime-snapshot.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["file"] = str(target)
        return payload

    def resume(self, snapshot_or_path: dict[str, Any] | str | Path) -> dict[str, Any]:
        if isinstance(snapshot_or_path, dict):
            payload = snapshot_or_path
        else:
            path = Path(snapshot_or_path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        base_path = Path(str(payload.get("base_path") or Path.cwd()))
        source = str(payload.get("source") or "")
        source_name = str(payload.get("source_name") or "<snapshot>")
        program = self.load(source, source_name=source_name, base_path=base_path)
        self._restore_context_payload(dict(payload.get("context") or {}))
        result = {
            "source_name": program.source_name,
            "base_path": str(program.base_path),
            "restored": True,
            "context": self.context.snapshot() if self.context else {},
        }
        return result

    def register_tenant(
        self,
        tenant_id: str,
        *,
        display_name: str | None = None,
        quotas: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        if not self.context.policy.permits_tenant(tenant_id):
            raise PermissionError(f"tenant '{tenant_id}' is not permitted by runtime policy")
        payload = self.context.security.register_tenant(tenant_id, display_name=display_name, quotas=quotas, metadata=metadata)
        self.context.active_tenant = tenant_id
        self._audit("auth", "tenant.register", "ok", {"tenant_id": tenant_id})
        return payload

    def select_tenant(self, tenant_id: str) -> dict[str, Any]:
        self._require_context()
        tenant = self.context.security.get_tenant(tenant_id)
        if tenant is None:
            raise ValueError(f"unknown tenant '{tenant_id}'")
        if not self.context.policy.permits_tenant(tenant_id):
            raise PermissionError(f"tenant '{tenant_id}' is not permitted by runtime policy")
        self.context.active_tenant = tenant_id
        self._refresh_state_cache()
        self._audit("auth", "tenant.select", "ok", {"tenant_id": tenant_id})
        return {"tenant": tenant_id, "selected": True}

    def select_namespace(self, namespace: str) -> dict[str, Any]:
        self._require_context()
        if not self.context.policy.permits_namespace(namespace):
            raise PermissionError(f"namespace '{namespace}' is not permitted by runtime policy")
        self.context.active_namespace = namespace
        self._refresh_state_cache()
        self._audit("auth", "namespace.select", "ok", {"namespace": namespace})
        return {"namespace": namespace, "selected": True}

    def issue_token(
        self,
        tenant_id: str,
        subject: str,
        *,
        roles: set[str] | list[str] | tuple[str, ...] | None = None,
        ttl_seconds: int | None = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self.context.security.issue_token(tenant_id, subject, roles=roles, ttl_seconds=ttl_seconds, metadata=metadata)
        self._audit("auth", "token.issue", "ok", {"tenant_id": tenant_id, "subject": subject, "roles": payload["roles"]})
        return payload

    def verify_token(self, token: str) -> dict[str, Any]:
        self._require_context()
        principal = self.context.security.authenticate(token)
        return {"authenticated": principal is not None, "principal": principal.to_dict() if principal is not None else None}

    def login(self, token: str) -> dict[str, Any]:
        self._require_context()
        principal = self.context.security.authenticate(token)
        if principal is None:
            self._audit("auth", "login", "error", {"reason": "invalid_token"})
            raise PermissionError("invalid token")
        if not self.context.policy.permits_tenant(principal.tenant_id):
            self._audit("auth", "login", "error", {"tenant_id": principal.tenant_id, "reason": "tenant_not_permitted"})
            raise PermissionError(f"tenant '{principal.tenant_id}' is not permitted by runtime policy")
        self.context.principal = principal
        self.context.active_tenant = principal.tenant_id
        self._refresh_state_cache()
        self._audit("auth", "login", "ok", {"tenant_id": principal.tenant_id, "subject": principal.subject, "roles": sorted(principal.roles)})
        return {"authenticated": True, "principal": principal.to_dict()}

    def logout(self) -> dict[str, Any]:
        self._require_context()
        principal = self.context.principal
        self.context.principal = None
        self._audit("auth", "logout", "ok", {"previous_actor": principal.subject if isinstance(principal, AuthPrincipal) else "anonymous"})
        return {"logged_out": True}

    def whoami(self) -> dict[str, Any]:
        self._require_context()
        principal = self.context.principal
        return {
            "authenticated": isinstance(principal, AuthPrincipal),
            "principal": principal.to_dict() if isinstance(principal, AuthPrincipal) else None,
            "tenant": self.context.active_tenant,
            "namespace": self.context.active_namespace,
            "policy": self.context.policy.snapshot(),
        }

    def revoke_token(self, token_id: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.security.revoke_token(token_id)
        self._audit("auth", "token.revoke", "ok" if payload.get("revoked") else "error", {"token_id": token_id})
        return payload

    def store_secret(self, tenant_id: str, secret_name: str, secret_value: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_context()
        payload = self._commit_consensus_mutation(
            "security.secret.store",
            {
                "tenant_id": tenant_id,
                "secret_name": secret_name,
                "secret_value": secret_value,
                "metadata": dict(metadata or {}),
            },
        )
        self._audit("security", "secret.store", "ok", {"tenant_id": tenant_id, "secret_name": secret_name})
        return payload

    def resolve_secret(self, tenant_id: str, secret_name: str) -> dict[str, Any] | None:
        self._require_context()
        return self.context.security.resolve_secret(tenant_id, secret_name)

    def set_tls_profile(
        self,
        profile_name: str,
        certfile: str,
        keyfile: str,
        *,
        cafile: str | None = None,
        verify: bool = True,
        server_hostname: str | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        cert_path = str(self._resolve_path(certfile))
        key_path = str(self._resolve_path(keyfile))
        ca_path = str(self._resolve_path(cafile)) if cafile else None
        payload = self._commit_consensus_mutation(
            "security.tls.set",
            {
                "profile_name": profile_name,
                "certfile": cert_path,
                "keyfile": key_path,
                "cafile": ca_path,
                "verify": verify,
                "server_hostname": server_hostname,
            },
        )
        self._audit("security", "tls.set", "ok", {"profile_name": profile_name, "verify": verify})
        return payload

    def set_trust_policy(
        self,
        policy_name: str,
        *,
        tenant_id: str | None = None,
        namespace: str | None = None,
        require_tls: bool = False,
        labels: dict[str, str] | None = None,
        capabilities: set[str] | list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self._commit_consensus_mutation(
            "security.trust.set",
            {
                "policy_name": policy_name,
                "tenant_id": tenant_id,
                "namespace": namespace,
                "require_tls": require_tls,
                "labels": dict(labels or {}),
                "capabilities": sorted({str(item) for item in (capabilities or []) if str(item)}),
                "metadata": dict(metadata or {}),
            },
        )
        self._audit("security", "trust.set", "ok", {"policy_name": policy_name})
        return payload

    def onboard_worker(
        self,
        worker_id: str,
        tenant_id: str,
        *,
        namespace: str | None = None,
        capabilities: set[str] | list[str] | tuple[str, ...] | None = None,
        labels: dict[str, str] | None = None,
        tls_profile: str | None = None,
        certfile: str | None = None,
        keyfile: str | None = None,
        cafile: str | None = None,
        ca_name: str | None = None,
        trust_policy: str | None = None,
        rotate_after_seconds: int | None = 86400,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        self._enforce_quota("max_workers", self._tenant_worker_count() + 1)
        payload = self._commit_consensus_mutation(
            "security.worker.onboard",
            {
                "worker_id": worker_id,
                "tenant_id": tenant_id,
                "namespace": namespace or self.context.active_namespace,
                "capabilities": sorted({str(item) for item in (capabilities or []) if str(item)}),
                "labels": dict(labels or {}),
                "tls_profile": tls_profile,
                "certfile": str(self._resolve_path(certfile)) if certfile else None,
                "keyfile": str(self._resolve_path(keyfile)) if keyfile else None,
                "cafile": str(self._resolve_path(cafile)) if cafile else None,
                "ca_name": ca_name,
                "trust_policy": trust_policy,
                "rotate_after_seconds": rotate_after_seconds,
                "metadata": dict(metadata or {}),
            },
        )
        self._audit("security", "worker.onboard", "ok", {"worker_id": worker_id, "tenant_id": tenant_id})
        return payload

    def rotate_worker_certificate(
        self,
        worker_id: str,
        certfile: str,
        keyfile: str,
        *,
        cafile: str | None = None,
        rotate_after_seconds: int | None = 86400,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self.context.security.rotate_worker_certificate(
            worker_id,
            str(self._resolve_path(certfile)),
            str(self._resolve_path(keyfile)),
            cafile=str(self._resolve_path(cafile)) if cafile else None,
            rotate_after_seconds=rotate_after_seconds,
        )
        self._audit("security", "worker.rotate", "ok", {"worker_id": worker_id})
        return payload

    def create_certificate_authority(
        self,
        ca_name: str,
        *,
        common_name: str,
        validity_days: int = 3650,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self._commit_consensus_mutation(
            "security.ca.create",
            {
                "ca_name": ca_name,
                "common_name": common_name,
                "validity_days": validity_days,
                "metadata": dict(metadata or {}),
            },
        )
        self._audit("security", "ca.create", "ok", {"ca_name": ca_name})
        return payload

    def issue_certificate(
        self,
        ca_name: str,
        *,
        subject_name: str,
        common_name: str,
        profile_name: str | None = None,
        validity_days: int = 365,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        serial = uuid.uuid4().hex[:16]
        payload = self._commit_consensus_mutation(
            "security.cert.issue",
            {
                "ca_name": ca_name,
                "subject_name": subject_name,
                "common_name": common_name,
                "profile_name": profile_name,
                "validity_days": validity_days,
                "metadata": dict(metadata or {}),
                "serial": serial,
            },
        )
        self._audit("security", "cert.issue", "ok", {"ca_name": ca_name, "subject_name": subject_name, "serial": serial})
        return payload

    def revoke_certificate(self, serial: str) -> dict[str, Any]:
        self._require_context()
        payload = self._commit_consensus_mutation("security.cert.revoke", {"serial": serial})
        self._audit("security", "cert.revoke", "ok", {"serial": serial})
        return payload

    def acquire_leadership(
        self,
        cluster_name: str | None = None,
        *,
        node_id: str | None = None,
        lease_seconds: int = 30,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        target_cluster = cluster_name or self.context.cluster_name
        target_node = node_id or self.context.node_id
        payload = self.context.cluster.acquire_leadership(target_cluster, target_node, lease_seconds=lease_seconds, metadata=metadata)
        self._audit("cluster", "leader.acquire", "ok" if payload.get("acquired") else "error", {"cluster_name": target_cluster, "node_id": target_node})
        return payload

    def renew_leadership(self, cluster_name: str | None = None, *, node_id: str | None = None, lease_seconds: int = 30) -> dict[str, Any]:
        self._require_context()
        target_cluster = cluster_name or self.context.cluster_name
        target_node = node_id or self.context.node_id
        payload = self.context.cluster.renew_leadership(target_cluster, target_node, lease_seconds=lease_seconds)
        self._audit("cluster", "leader.renew", "ok", {"cluster_name": target_cluster, "node_id": target_node})
        return payload

    def release_leadership(self, cluster_name: str | None = None, *, node_id: str | None = None) -> dict[str, Any]:
        self._require_context()
        target_cluster = cluster_name or self.context.cluster_name
        target_node = node_id or self.context.node_id
        payload = self.context.cluster.release_leadership(target_cluster, target_node)
        self._audit("cluster", "leader.release", "ok" if payload.get("released") else "error", {"cluster_name": target_cluster, "node_id": target_node})
        return payload

    def leader_status(self, cluster_name: str | None = None) -> dict[str, Any] | list[dict[str, Any]] | None:
        self._require_context()
        return self.context.cluster.leader_status(cluster_name)

    def create_rollout(
        self,
        deployment_name: str,
        spec: dict[str, Any],
        *,
        strategy: str = "rolling",
        metadata: dict[str, Any] | None = None,
        auto_promote: bool = True,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self.context.cluster.create_rollout(deployment_name, spec, strategy=strategy, metadata=metadata, auto_promote=auto_promote)
        self._audit("deploy", "rollout.create", "ok", {"deployment_name": deployment_name, "revision": payload.get("revision")})
        return payload

    def promote_revision(self, deployment_name: str, revision: int) -> dict[str, Any]:
        self._require_context()
        payload = self.context.cluster.promote_revision(deployment_name, revision)
        self._audit("deploy", "rollout.promote", "ok", {"deployment_name": deployment_name, "revision": revision})
        return payload

    def rollback_deployment(self, deployment_name: str, target_revision: int | None = None) -> dict[str, Any]:
        self._require_context()
        payload = self.context.cluster.rollback(deployment_name, target_revision)
        self._audit("deploy", "rollout.rollback", "ok", {"deployment_name": deployment_name, "target_revision": payload.get("rolled_back_to")})
        return payload

    def deployment_status(self, deployment_name: str | None = None) -> dict[str, Any]:
        self._require_context()
        return self.context.cluster.deployment_status(deployment_name)

    def list_services(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.service_fabric.list_services()

    def list_packages(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.service_fabric.list_packages()

    def discover_service(
        self,
        service_name: str,
        *,
        tenant_id: str | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        return self.context.service_fabric.discover(
            service_name,
            tenant_id=tenant_id or self.context.active_tenant,
            namespace=namespace or self.context.active_namespace,
        )

    def evaluate_service_autoscaling(self, service_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
        self._require_context()
        payload = self.context.service_fabric.evaluate_autoscaling(service_name, metrics)
        service = payload.get("service")
        if isinstance(service, dict):
            self.context.services[service_name] = dict(service)
        self._audit("service", "autoscale.evaluate", "ok", {"service_name": service_name, "action": payload.get("action")})
        return payload

    def list_service_configs(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.service_fabric.list_configs()

    def list_service_volumes(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.service_fabric.list_volumes()

    def list_service_ingress(self, service_name: str | None = None) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.service_fabric.list_ingress(service_name)

    def list_traffic_routes(self, service_name: str | None = None) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.traffic_plane.list_routes(service_name)

    def list_traffic_probes(self, service_name: str | None = None) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.traffic_plane.list_probes(service_name)

    def list_secret_mounts(self, service_name: str | None = None) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.traffic_plane.list_secret_mounts(service_name)

    def probe_service_traffic(self, service_name: str) -> dict[str, Any]:
        self._require_context()
        service = self.context.service_fabric.get_service(service_name)
        if service is None:
            raise ValueError(f"unknown service '{service_name}'")
        payload = self.context.traffic_plane.probe_service(service)
        self._audit("traffic", "probe", "ok", {"service_name": service_name, "probe_count": len(payload.get("probes", []))})
        return payload

    def shift_service_traffic(self, service_name: str, weights: dict[str, float | int]) -> dict[str, Any]:
        self._require_context()
        payload = self.context.traffic_plane.set_traffic_shift(service_name, weights)
        self._audit("traffic", "shift", "ok", {"service_name": service_name, "weights": payload.get("weights")})
        return payload

    def route_service_request(
        self,
        host: str,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        self._maybe_failpoint("traffic.route")
        payload = self.context.traffic_plane.route(self.context.service_fabric, host=host, path=path, method=method, body=body, headers=headers)
        self._audit("traffic", "route", "ok", {"host": host, "path": path, "service_name": payload.get("service_name")})
        return payload

    def start_traffic_proxy(self, *, host: str = "127.0.0.1", port: int = 0, auth_token: str | None = None) -> dict[str, Any]:
        self._require_context()
        payload = self.context.traffic_plane.start_proxy(self.context.service_fabric, host=host, port=port, auth_token=auth_token)
        self._audit("traffic", "proxy.start", "ok", payload)
        return payload

    def stop_traffic_proxy(self) -> dict[str, Any]:
        self._require_context()
        payload = self.context.traffic_plane.stop_proxy()
        self._audit("traffic", "proxy.stop", "ok", payload)
        return payload

    def traffic_proxy_status(self) -> dict[str, Any]:
        self._require_context()
        return self.context.traffic_plane.proxy_status()

    def scale_service(self, service_name: str, replicas: int) -> dict[str, Any]:
        self._require_context()
        service = self.context.service_fabric.autoscale(service_name, target_replicas=replicas)
        self.context.services[service_name] = dict(service)
        self._audit("service", "scale", "ok", {"service_name": service_name, "replicas": replicas})
        return service

    def executor_status(self) -> dict[str, Any]:
        self._require_context()
        return self.context.executors.snapshot()

    def restart_executor_backend(self, backend: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.executors.restart_backend(backend)
        self._audit("executor", "restart", "ok", {"backend": backend})
        return payload

    def stop_executor_backend(self, backend: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.executors.stop_backend(backend)
        self._audit("executor", "stop", "ok", {"backend": backend})
        return payload

    def cancel_executor_request(self, backend: str, request_id: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.executors.cancel(backend, request_id)
        self._audit("executor", "cancel", "ok", {"backend": backend, "request_id": request_id})
        return payload

    def stream_executor_request(self, backend: str, request_id: str) -> dict[str, Any]:
        self._require_context()
        return self.context.executors.stream(backend, request_id)

    def list_traces(self, *, limit: int = 100, trace_id: str | None = None) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.observability.traces(limit=limit, trace_id=trace_id)

    def list_alerts(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.observability.alerts()

    def validate_snapshot_file(self, file_path: str | Path) -> dict[str, Any]:
        target = Path(file_path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        required = {"version", "source_name", "base_path", "source", "context", "events"}
        missing = sorted(required.difference(payload.keys()))
        return {
            "file": str(target),
            "valid": not missing,
            "missing": missing,
            "event_count": len(payload.get("events", [])) if isinstance(payload.get("events"), list) else 0,
            "trace_validation": self.context.observability.validate_trace_store() if self.context is not None else {"valid": True, "records": 0},
        }

    def install_package(self, package_name: str) -> dict[str, Any]:
        self._require_context()
        package = self.context.packages.get(package_name)
        if package is None:
            raise ValueError(f"unknown package '{package_name}'")
        source = package.get("source")
        resolved_source = str(self._resolve_path(source)) if isinstance(source, str) and source and not str(source).startswith(("http://", "https://")) else source
        command = {
            "package_name": package_name,
            "package": {**dict(package), "resolved_source": resolved_source},
            "tenant": self.context.active_tenant,
            "namespace": self.context.active_namespace,
        }
        installed = self._commit_consensus_mutation("package.install", command)
        self.context.packages[package_name] = dict(installed)
        self._audit("package", "install", "ok", {"package_name": package_name})
        return dict(installed)

    def deploy_service(self, service_name: str, *, auto_promote: bool | None = None) -> dict[str, Any]:
        self._require_context()
        service = self.context.services.get(service_name)
        if service is None:
            raise ValueError(f"unknown service '{service_name}'")
        package_name = str(service.get("package") or "").strip()
        if package_name:
            self.install_package(package_name)
        spec = {
            "service": service_name,
            "package": package_name or None,
            "image": service.get("image"),
            "command": service.get("command"),
            "replicas": int(service.get("replicas") or 1),
            "selector": dict(service.get("selector") or {}),
            "health": dict(service.get("health") or {}),
            "tenant": service.get("tenant"),
            "namespace": service.get("namespace"),
        }
        command = {
            "service_name": service_name,
            "spec": spec,
            "strategy": str(service.get("strategy") or "rolling"),
            "metadata": {"service": service_name, "namespace": service.get("namespace"), "tenant": service.get("tenant")},
            "auto_promote": bool(service.get("auto_promote", True) if auto_promote is None else auto_promote),
        }
        deployed = self._commit_consensus_mutation("service.deploy", command)
        self.context.services[service_name] = dict(deployed["service"])
        self._audit("service", "deploy", "ok", {"service_name": service_name, "revision": deployed["rollout"].get("revision")})
        return deployed

    def register_recovery_playbook(
        self,
        playbook_name: str,
        snapshot_path: str | Path,
        *,
        steps: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        target = str(self._resolve_path(snapshot_path))
        payload = self.context.cluster.register_playbook(playbook_name, target, steps=steps, metadata=metadata)
        self._audit("recovery", "playbook.register", "ok", {"playbook_name": playbook_name, "snapshot_path": target})
        return payload

    def list_recovery_playbooks(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.cluster.list_playbooks()

    def run_recovery_playbook(self, playbook_name: str) -> dict[str, Any]:
        self._require_context()
        cluster = self.context.cluster
        try:
            payload = cluster.run_playbook(playbook_name, self._execute_recovery_step)
            self._audit("recovery", "playbook.run", "ok", {"playbook_name": playbook_name, "run_id": payload.get("run_id")})
            return payload
        finally:
            if self.context is None or self.context.cluster is not cluster:
                cluster.close()

    def enqueue_flow(
        self,
        flow_name: str,
        *,
        payload: Any = None,
        queue_name: str = "default",
        priority: int = 100,
        not_before: float | None = None,
        max_attempts: int = 3,
        base_backoff_seconds: float = 5.0,
        backoff_multiplier: float = 2.0,
        max_backoff_seconds: float = 300.0,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        self._enforce_quota("max_queue_tasks", self._tenant_queue_depth() + 1)
        enriched_metadata = {
            "tenant": self.context.active_tenant,
            "namespace": self.context.active_namespace,
            "base_backoff_seconds": float(base_backoff_seconds),
            "backoff_multiplier": float(backoff_multiplier),
            "max_backoff_seconds": float(max_backoff_seconds),
            **dict(metadata or {}),
        }
        task = self._commit_consensus_mutation(
            "queue.enqueue",
            {
                "task_id": f"task-{int(time.time() * 1000):x}-{abs(hash((flow_name, queue_name, priority, json.dumps(payload, ensure_ascii=False, default=str)))):x}"[:16],
                "kind": "flow",
                "target": flow_name,
                "queue_name": queue_name,
                "payload": payload,
                "priority": priority,
                "not_before": not_before,
                "max_attempts": max_attempts,
                "idempotency_key": idempotency_key,
                "metadata": enriched_metadata,
            },
        )
        self._audit("control", "queue.enqueue", "ok", {"flow": flow_name, "queue_name": queue_name, "task_id": task["task_id"]})
        return task

    def schedule_flow(
        self,
        job_name: str,
        flow_name: str,
        *,
        interval_seconds: float | None = None,
        once_at: float | None = None,
        queue_name: str = "default",
        payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        self._enforce_quota("max_schedules", self._tenant_schedule_count() + 1)
        schedule = self._commit_consensus_mutation(
            "schedule.flow",
            {
                "job_name": job_name,
                "kind": "flow",
                "target": flow_name,
                "queue_name": queue_name,
                "payload": payload,
                "interval_seconds": interval_seconds,
                "once_at": once_at,
                "metadata": {"tenant": self.context.active_tenant, "namespace": self.context.active_namespace, **dict(metadata or {})},
            },
        )
        self._audit("control", "schedule.upsert", "ok", {"job_name": job_name, "flow": flow_name, "queue_name": queue_name})
        return schedule

    def schedule_event(
        self,
        job_name: str,
        event_name: str,
        *,
        interval_seconds: float | None = None,
        once_at: float | None = None,
        queue_name: str = "default",
        payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        self._enforce_quota("max_schedules", self._tenant_schedule_count() + 1)
        schedule = self._commit_consensus_mutation(
            "schedule.event",
            {
                "job_name": job_name,
                "kind": "event",
                "target": event_name,
                "queue_name": queue_name,
                "payload": payload,
                "interval_seconds": interval_seconds,
                "once_at": once_at,
                "metadata": {"tenant": self.context.active_tenant, "namespace": self.context.active_namespace, **dict(metadata or {})},
            },
        )
        self._audit("control", "schedule.upsert", "ok", {"job_name": job_name, "event": event_name, "queue_name": queue_name})
        return schedule

    def scheduler_tick(self) -> dict[str, Any]:
        self._require_context()
        payload = self.context.control_runtime.scheduler_tick(
            owner_id=self.context.node_id,
            lease_name=f"{self.context.cluster_name}:scheduler",
            lease_seconds=max(5, int(self._daemon_interval * 4)),
        )
        self._audit("control", "scheduler.tick", "ok", {"jobs_enqueued": payload.get("jobs_enqueued", 0)})
        return payload

    def run_pending_tasks(self, *, queue_name: str | None = None, limit: int = 10) -> dict[str, Any]:
        self._require_context()
        tasks = self.context.control_runtime.claim_tasks(self.context.node_id, queue_name=queue_name, limit=limit)
        processed: list[dict[str, Any]] = []
        for task in tasks:
            task_id = str(task["task_id"])
            idempotency_key = str(task.get("metadata", {}).get("idempotency_key") or "") or None
            prior_effect = self.context.control_runtime.get_task_effect(task_id)
            if prior_effect is None and idempotency_key:
                prior_effect = self.context.control_runtime.get_task_effect_by_idempotency(idempotency_key)
            if prior_effect is not None and prior_effect.get("status") == "ok":
                self.context.control_runtime.complete_task(task_id, status="ok", result=prior_effect.get("result"))
                processed.append({"task_id": task_id, "status": "ok", "result": prior_effect.get("result"), "reused": True})
                continue
            try:
                result = self._run_control_task(task)
                self.context.control_runtime.complete_task(task_id, status="ok", result=result)
                self.context.control_runtime.record_task_effect(task_id, status="ok", result=result, idempotency_key=idempotency_key)
                processed.append({"task_id": task_id, "status": "ok", "result": result})
            except Exception as exc:
                task_metadata = dict(task.get("metadata") or {})
                updated = self.context.control_runtime.fail_task(
                    task_id,
                    error=str(exc),
                    base_backoff_seconds=float(task_metadata.get("base_backoff_seconds") or 5.0),
                )
                self.context.control_runtime.record_task_effect(task_id, status="error", result={"error": str(exc)}, idempotency_key=idempotency_key)
                processed.append({"task_id": task_id, "status": str(updated.get("status") if updated else "error"), "error": str(exc)})
        self._audit("control", "queue.run", "ok", {"processed": len(processed), "queue_name": queue_name or "default"})
        return {"processed_count": len(processed), "tasks": processed}

    def list_queue_tasks(self, *, queue_name: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.control_runtime.list_tasks(queue_name=queue_name, status=status, limit=limit)

    def list_schedules(self, *, enabled: bool | None = None, limit: int = 50) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.control_runtime.list_schedules(enabled=enabled, limit=limit)

    def replay_event_log(self, *, event_name: str | None = None, since_sequence: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.control_runtime.replay_events(event_name=event_name, since_sequence=since_sequence, limit=limit)

    def record_deployment_health(
        self,
        deployment_name: str,
        revision: int,
        target_name: str,
        *,
        status: str,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self.context.cluster.record_health(deployment_name, revision, target_name, status=status, metrics=metrics)
        self._audit("deploy", "health.record", "ok", {"deployment_name": deployment_name, "revision": revision, "target_name": target_name, "status": status})
        return payload

    def evaluate_rollout(
        self,
        deployment_name: str,
        revision: int,
        *,
        minimum_healthy_targets: int = 1,
        max_error_rate: float = 0.2,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self.context.cluster.evaluate_rollout(
            deployment_name,
            revision,
            minimum_healthy_targets=minimum_healthy_targets,
            max_error_rate=max_error_rate,
        )
        self._audit("deploy", "rollout.evaluate", "ok", {"deployment_name": deployment_name, "revision": revision, "action": payload.get("evaluation", {}).get("action")})
        return payload

    def control_status(self) -> dict[str, Any]:
        self._require_context()
        payload = self.context.control_runtime.snapshot()
        payload["state_store"] = self.context.state_store.snapshot()
        payload["workflow_store"] = self.context.workflow_store.snapshot()
        payload["replication"] = self.context.replication.snapshot()
        payload["services"] = self.list_services()
        payload["packages"] = self.list_packages()
        payload["service_fabric"] = self.context.service_fabric.snapshot()
        payload["service_configs"] = self.list_service_configs()
        payload["service_volumes"] = self.list_service_volumes()
        payload["service_ingress"] = self.list_service_ingress()
        payload["traffic_plane"] = self.context.traffic_plane.snapshot()
        payload["consensus"] = self.context.consensus.snapshot()
        payload["executors"] = self.context.executors.snapshot()
        payload["toolchain"] = {
            "registry": self._package_registry.snapshot() if self._package_registry is not None else {"package_count": 0, "packages": []},
            "lockfile": dict(self.program.lockfile) if self.program is not None else {},
        }
        payload["operations"] = self.context.operations.snapshot()
        payload["api"] = self.control_api_status()
        payload["metrics"] = self.context.telemetry.collect(self)
        return payload

    def create_backup(self) -> dict[str, Any]:
        self._require_context()
        payload = self.context.operations.create_backup(snapshot=self.snapshot() if self.program is not None else None)
        self._audit("operations", "backup.create", "ok", {"backup_id": payload.get("backup_id")})
        return payload

    def list_backups(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.operations.list_backups()

    def restore_backup(self, backup_id: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.operations.restore_backup(backup_id)
        self._audit("operations", "backup.restore", "ok", {"backup_id": backup_id, "restored_files": len(payload.get("restored_files", []))})
        return payload

    def validate_migrations(self, expected: dict[str, str] | None = None) -> dict[str, Any]:
        self._require_context()
        return self.context.operations.validate_migrations(expected)

    def set_failpoint(self, name: str, action: str = "raise", *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_context()
        payload = self.context.operations.set_failpoint(name, action, metadata=metadata)
        self._audit("operations", "failpoint.set", "ok", {"name": name, "action": action})
        return payload

    def clear_failpoint(self, name: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.operations.clear_failpoint(name)
        self._audit("operations", "failpoint.clear", "ok", {"name": name, "cleared": payload.get("cleared")})
        return payload

    def list_failpoints(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.operations.list_failpoints()

    def run_load_test(self, flow_name: str, *, iterations: int = 10) -> dict[str, Any]:
        self._require_context()
        payload = self.context.operations.run_load(
            flow_name,
            int(iterations),
            lambda _index: self.execute_flow(flow_name, trigger_event="load"),
            metadata={"type": "flow"},
        )
        self._audit("operations", "load.run", "ok", {"flow_name": flow_name, "iterations": iterations})
        return payload

    def write_lockfile(self, file_path: str | Path | None = None) -> dict[str, Any]:
        if self.program is None or self._module_loader is None:
            raise RuntimeError("no Nova program is loaded")
        target = Path(file_path) if file_path else (self.program.base_path / ".nova" / "nova.lock.json")
        return self._module_loader.write_lockfile(self.program.lockfile, target)

    def publish_toolchain_package(
        self,
        name: str,
        version: str,
        entrypoint: str | Path,
        *,
        checksum: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_path = self.program.base_path if self.program is not None else Path.cwd()
        registry = self._package_registry or NovaPackageRegistry(base_path)
        self._package_registry = registry
        return registry.publish(name, version, entrypoint, checksum=checksum, metadata=metadata)

    def list_toolchain_packages(self) -> list[dict[str, Any]]:
        base_path = self.program.base_path if self.program is not None else Path.cwd()
        registry = self._package_registry or NovaPackageRegistry(base_path)
        self._package_registry = registry
        return registry.list_packages()

    def format_source(self, source: str) -> str:
        return self._formatter.format_source(source, parser=self.parser)

    def lint_source(self, source: str, *, source_name: str = "<memory>", base_path: str | Path | None = None) -> list[dict[str, Any]]:
        target_base = Path(base_path or Path.cwd()).resolve(strict=False)
        registry = self._package_registry or NovaPackageRegistry(target_base)
        loader = NovaModuleLoader(self.parser, registry)
        loaded = loader.load(source, source_name=source_name, base_path=target_base)
        return [item.to_dict() for item in self._linter.lint(loaded.ast)]

    def toolchain_symbols(self, source: str, *, source_name: str = "<memory>", base_path: str | Path | None = None) -> list[dict[str, Any]]:
        target_base = Path(base_path or Path.cwd()).resolve(strict=False)
        registry = self._package_registry or NovaPackageRegistry(target_base)
        loader = NovaModuleLoader(self.parser, registry)
        loaded = loader.load(source, source_name=source_name, base_path=target_base)
        return self._lsp.symbols(loaded.ast)

    def toolchain_hover(self, source: str, line: int, column: int = 1, *, source_name: str = "<memory>", base_path: str | Path | None = None) -> dict[str, Any] | None:
        target_base = Path(base_path or Path.cwd()).resolve(strict=False)
        registry = self._package_registry or NovaPackageRegistry(target_base)
        loader = NovaModuleLoader(self.parser, registry)
        loaded = loader.load(source, source_name=source_name, base_path=target_base)
        return self._lsp.hover(loaded.ast, line, column)

    def run_program_tests(self, source_or_path: str | Path, *, base_path: str | Path | None = None) -> dict[str, Any]:
        return self._test_runner.run(source_or_path, base_path=base_path).to_dict()

    def register_prompt_version(self, agent_name: str, version: str, prompt_text: str, *, activate: bool = False) -> dict[str, Any]:
        self._require_context()
        specification = self.context.agent_runtime.specification(agent_name)
        prompts = dict(specification.prompts)
        prompts[version] = prompt_text
        specification.prompts = prompts
        active_version = version if activate else (self.context.prompt_registry.active_version(agent_name) or specification.prompt_version or version)
        payload = self.context.prompt_registry.register_agent(agent_name, prompts, active_version=active_version, metadata=specification.governance)
        if activate:
            specification.prompt_version = version
        return payload

    def list_prompt_versions(self, agent_name: str) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.prompt_registry.list_versions(agent_name)

    def search_agent_memory(self, scope: str, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.memory_store.search(scope, query, top_k=top_k)

    def list_agent_evals(self, agent_name: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.eval_store.list_recent(agent_name, limit=limit)

    def start_control_daemon(self, *, interval_seconds: float = 1.0, task_limit: int = 4) -> dict[str, Any]:
        self._require_context()
        self._daemon_interval = max(0.1, float(interval_seconds))
        self.stop_control_daemon()
        self._daemon_stop = threading.Event()

        def runner() -> None:
            while not self._daemon_stop.wait(self._daemon_interval):
                try:
                    self.control_tick(task_limit=task_limit)
                except Exception:
                    continue

        self._daemon_thread = threading.Thread(target=runner, name="NovaControlDaemon", daemon=True)
        self._daemon_thread.start()
        payload = self.context.control_runtime.record_daemon_state(
            running=True,
            tick_interval=self._daemon_interval,
            tasks_processed=0,
            jobs_enqueued=0,
            last_tick_at=time.time(),
            metadata={"task_limit": task_limit},
        )
        self._audit("control", "daemon.start", "ok", {"interval_seconds": self._daemon_interval, "task_limit": task_limit})
        return payload

    def stop_control_daemon(self) -> dict[str, Any]:
        if self._daemon_thread is not None:
            self._daemon_stop.set()
            self._daemon_thread.join(timeout=1.0)
            self._daemon_thread = None
        if self.context is None:
            return {"running": False}
        payload = self.context.control_runtime.record_daemon_state(
            running=False,
            tick_interval=self._daemon_interval,
            tasks_processed=self.context.control_runtime.daemon_status().get("tasks_processed", 0),
            jobs_enqueued=self.context.control_runtime.daemon_status().get("jobs_enqueued", 0),
            last_tick_at=time.time(),
            metadata={"stopped": True},
        )
        self._audit("control", "daemon.stop", "ok", {"interval_seconds": self._daemon_interval})
        return payload

    def control_tick(self, *, task_limit: int = 4) -> dict[str, Any]:
        self._require_context()
        self._maybe_failpoint("control.tick.start")
        recovered = self.context.control_runtime.recover_stale_tasks(timeout_seconds=max(30.0, self._daemon_interval * 10.0))
        scheduler = self.scheduler_tick()
        self._maybe_failpoint("control.tick.after_scheduler")
        processed = self.run_pending_tasks(limit=task_limit)
        replication = self.sync_replication(limit=50)
        self._maybe_failpoint("control.tick.after_replication")
        consensus = self.sync_consensus()
        daemon_status = self.context.control_runtime.daemon_status()
        payload = self.context.control_runtime.record_daemon_state(
            running=self._daemon_thread is not None and self._daemon_thread.is_alive(),
            tick_interval=self._daemon_interval,
            tasks_processed=int(daemon_status.get("tasks_processed") or 0) + int(processed.get("processed_count") or 0),
            jobs_enqueued=int(daemon_status.get("jobs_enqueued") or 0) + int(scheduler.get("jobs_enqueued") or 0),
            last_tick_at=time.time(),
            metadata={"last_processed_count": processed.get("processed_count", 0), "recovered_stale_tasks": recovered.get("recovered", 0)},
        )
        return {"recovered": recovered, "scheduler": scheduler, "processed": processed, "replication": replication, "consensus": consensus, "daemon": payload}

    def register_replica_peer(
        self,
        peer_name: str,
        endpoint: str,
        *,
        auth_token: str | None = None,
        tls_profile: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        payload = self._commit_consensus_mutation(
            "replication.peer.register",
            {
                "peer_name": peer_name,
                "endpoint": endpoint,
                "auth_token": auth_token,
                "tls_profile": tls_profile,
                "enabled": enabled,
                "metadata": dict(metadata or {}),
            },
        )
        self._audit("replication", "peer.register", "ok", {"peer_name": peer_name, "endpoint": endpoint})
        return payload

    def list_replica_peers(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.replication.list_peers()

    def list_replicated_records(self, *, since_sequence: int = 0, record_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.replication.list_records(since_sequence=since_sequence, record_type=record_type, limit=limit)

    def replay_state_log(
        self,
        *,
        since_sequence: int = 0,
        key: str | None = None,
        tenant_id: str | None = None,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.state_store.replay(
            since_sequence=since_sequence,
            tenant_id=tenant_id,
            namespace=namespace,
            key=key,
            limit=limit,
        )

    def list_state(self, *, tenant_id: str | None = None, namespace: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.state_store.list_state(tenant_id=tenant_id, namespace=namespace, limit=limit)

    def list_workflow_runs(self, *, flow_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.workflow_store.list_runs(flow_name=flow_name, limit=limit)

    def replay_workflow_run(self, run_id: str) -> dict[str, Any]:
        self._require_context()
        record = self.context.workflow_store.get_run(run_id)
        if record is None:
            raise ValueError(f"unknown workflow run '{run_id}'")
        flow_name = str(record["flow_name"])
        replay = self.execute_flow(flow_name, trigger_event=f"replay:{run_id}")
        return {"run_id": run_id, "replayed": True, "flow": replay.to_dict()}

    def export_metrics(self, format_name: str = "json") -> dict[str, Any] | str:
        self._require_context()
        if format_name == "prometheus":
            return self.context.telemetry.export_prometheus(self)
        if format_name == "otlp":
            return self.context.telemetry.export_otlp(self)
        return self.context.telemetry.collect(self)

    def consensus_status(self) -> dict[str, Any]:
        self._require_context()
        return self.context.consensus.snapshot()

    def remove_consensus_peer(self, peer_name: str) -> dict[str, Any]:
        self._require_context()
        payload = self.context.consensus.remove_peer(peer_name)
        self._audit("consensus", "peer.remove", "ok", {"peer_name": peer_name})
        return payload

    def register_consensus_peer(
        self,
        peer_name: str,
        endpoint: str,
        *,
        auth_token: str | None = None,
        tls_profile: str | None = None,
        voter: bool = True,
        active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_context()
        return self.context.consensus.register_peer(
            peer_name,
            endpoint,
            auth_token=auth_token,
            tls_profile=tls_profile,
            voter=voter,
            active=active,
            metadata=metadata,
        )

    def list_consensus_peers(self) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.consensus.list_peers()

    def consensus_log(self, *, since_index: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        self._require_context()
        return self.context.consensus.list_log(since_index=since_index, limit=limit)

    def consensus_snapshot(self) -> dict[str, Any] | None:
        self._require_context()
        return self.context.consensus.latest_snapshot()

    def start_consensus_election(self) -> dict[str, Any]:
        self._require_context()
        payload = self.context.consensus.start_election(self._send_consensus_vote)
        self._audit("consensus", "election.start", "ok", {"term": payload.get("current_term"), "role": payload.get("role")})
        return payload

    def send_consensus_heartbeats(self) -> dict[str, Any]:
        self._require_context()
        payload = self.context.consensus.send_heartbeats(self._send_consensus_append)
        self._audit("consensus", "heartbeat", "ok", payload)
        return payload

    def compact_consensus_log(self) -> dict[str, Any]:
        self._require_context()
        snapshot_payload = {
            "control_plane": self.context.control_runtime.snapshot(limit=20),
            "state_store": self.context.state_store.snapshot(limit=20),
            "service_fabric": self.context.service_fabric.snapshot(),
        }
        up_to_index = int(self.context.consensus.status().get("last_applied") or 0)
        payload = self.context.consensus.compact_log(up_to_index, snapshot_payload)
        self._audit("consensus", "compact", "ok", {"up_to_index": up_to_index, "snapshot_id": payload.get("snapshot_id")})
        return payload

    def install_consensus_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._require_context()
        payload = self.context.consensus.install_snapshot(snapshot)
        self._audit("consensus", "snapshot.install", "ok", {"snapshot_id": payload.get("snapshot_id")})
        return payload

    def sync_consensus(self) -> dict[str, Any]:
        self._require_context()
        status = self.context.consensus.status()
        if not bool(status.get("enabled")):
            return status
        if status.get("role") == "leader":
            return self.send_consensus_heartbeats()
        if self.context.consensus.needs_election(max(5.0, self._daemon_interval * 4.0)):
            return self.start_consensus_election()
        return status

    def consensus_request_vote(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_context()
        return self.context.consensus.request_vote(
            candidate_id=str(payload.get("candidate_id") or ""),
            term=int(payload.get("term") or 0),
            last_log_index=int(payload.get("last_log_index") or 0),
            last_log_term=int(payload.get("last_log_term") or 0),
        )

    def consensus_append_entries(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_context()
        if isinstance(payload.get("snapshot"), dict):
            self.install_consensus_snapshot(dict(payload["snapshot"]))
        result = self.context.consensus.append_entries(
            leader_id=str(payload.get("leader_id") or ""),
            term=int(payload.get("term") or 0),
            prev_log_index=int(payload.get("prev_log_index") or 0),
            prev_log_term=int(payload.get("prev_log_term") or 0),
            entries=list(payload.get("entries") or []),
            leader_commit=int(payload.get("leader_commit") or 0),
        )
        self.context.consensus.apply_committed(self._apply_consensus_entry, limit=200)
        return result

    def sync_replication(self, *, limit: int = 100) -> dict[str, Any]:
        self._require_context()
        return self.context.replication.sync(self._send_replica_record, limit=limit)

    def apply_replica_record(self, record: dict[str, Any]) -> dict[str, Any]:
        self._require_context()
        record_type = str(record.get("record_type") or "")
        payload = dict(record.get("payload") or {})
        tenant_id = str(record.get("tenant_id") or self.context.active_tenant)
        namespace = str(record.get("namespace") or self.context.active_namespace)
        source_node = str(record.get("source_node") or "replica")
        metadata = dict(record.get("metadata") or {})
        record_id = str(record.get("record_id") or "")
        stored = self.context.replication.append_record(
            record_type,
            payload,
            tenant_id=tenant_id,
            namespace=namespace,
            source_node=source_node,
            metadata=metadata,
            record_id=record_id or None,
        )
        if not stored.get("inserted", True):
            return {"applied": False, "record": stored}
        match record_type:
            case "event":
                event_name = str(payload.get("event_name") or "")
                event_payload = payload.get("payload")
                event_source = str(payload.get("source") or source_node)
                event_metadata = dict(payload.get("metadata") or {})
                self.context.control_runtime.publish_event(event_name, payload=event_payload, source=event_source, metadata=event_metadata)
                self.context.event_bus.publish(event_name, event_payload, source=event_source, metadata=event_metadata)
            case "state":
                self.context.state_store.set_state(
                    tenant_id,
                    namespace,
                    str(payload.get("key") or ""),
                    payload.get("value"),
                    metadata=dict(payload.get("metadata") or {}),
                    record_id=str(payload.get("record_id") or stored["record_id"]),
                )
                if tenant_id == self.context.active_tenant and namespace == self.context.active_namespace:
                    self.context.states[str(payload.get("key") or "")] = payload.get("value")
            case "workflow":
                self.context.workflow_store.record_run(
                    str(payload.get("flow_name") or ""),
                    trigger_event=str(payload.get("trigger_event")) if payload.get("trigger_event") else None,
                    status=str(payload.get("status") or "ok"),
                    record=dict(payload.get("record") or {}),
                    metadata=dict(payload.get("metadata") or {}),
                    run_id=str(payload.get("run_id") or None) if payload.get("run_id") else None,
                )
            case _:
                raise ValueError(f"unsupported replica record type '{record_type}'")
        return {"applied": True, "record": stored}

    def _commit_consensus_mutation(self, command_type: str, command: dict[str, Any]) -> Any:
        assert self.context is not None
        proposal = self.context.consensus.propose(command_type, command, self._send_consensus_append)
        if self.context.consensus.is_enabled() and not proposal.get("committed"):
            raise RuntimeError(f"consensus quorum not reached for '{command_type}'")
        applied = self.context.consensus.apply_committed(self._apply_consensus_entry, limit=200)
        entry = dict(proposal.get("entry") or {})
        log_index = int(entry.get("log_index") or 0)
        for item in applied:
            applied_entry = dict(item.get("entry") or {})
            if int(applied_entry.get("log_index") or 0) == log_index:
                return item.get("result")
        return self._read_consensus_result(command_type, command)

    def _read_consensus_result(self, command_type: str, command: dict[str, Any]) -> Any:
        assert self.context is not None
        match command_type:
            case "queue.enqueue":
                task_id = str(command.get("task_id") or "")
                tasks = self.context.control_runtime.list_tasks(task_ids=[task_id], limit=1) if task_id else []
                return tasks[0] if tasks else None
            case "schedule.flow" | "schedule.event":
                job_name = str(command.get("job_name") or "")
                schedules = self.context.control_runtime.list_schedules(job_name=job_name, limit=1)
                return schedules[0] if schedules else None
            case "replication.peer.register":
                peer_name = str(command.get("peer_name") or "")
                return next((peer for peer in self.context.replication.list_peers() if peer.get("peer_name") == peer_name), None)
            case "package.install":
                return self.context.service_fabric.get_package(str(command.get("package_name") or ""))
            case "service.deploy":
                service_name = str(command.get("service_name") or "")
                service = self.context.service_fabric.get_service(service_name)
                return {"service": service, "rollout": service.get("rollout") if isinstance(service, dict) else None}
            case "security.secret.store":
                return self.context.security.resolve_secret(str(command.get("tenant_id") or ""), str(command.get("secret_name") or ""))
            case "security.tls.set":
                return self.context.security.get_tls_profile(str(command.get("profile_name") or ""))
            case "security.trust.set":
                return self.context.security.get_trust_policy(str(command.get("policy_name") or ""))
            case "security.worker.onboard":
                return self.context.security.get_worker_enrollment(str(command.get("worker_id") or ""))
            case "security.ca.create":
                return self.context.security.get_certificate_authority(str(command.get("ca_name") or ""))
            case "security.cert.issue":
                serial = str(command.get("serial") or "")
                return self.context.security.get_issued_certificate(serial) if serial else None
            case "security.cert.revoke":
                serial = str(command.get("serial") or "")
                return self.context.security.get_issued_certificate(serial) if serial else None
            case _:
                return None

    def _apply_consensus_entry(self, entry: dict[str, Any]) -> Any:
        assert self.context is not None
        command_type = str(entry.get("command_type") or "")
        command = dict(entry.get("command") or {})
        match command_type:
            case "queue.enqueue":
                return self.context.control_runtime.enqueue_task(
                    task_id=str(command.get("task_id") or ""),
                    kind=str(command.get("kind") or "flow"),
                    target=str(command.get("target") or ""),
                    idempotency_key=str(command.get("idempotency_key")) if command.get("idempotency_key") else None,
                    queue_name=str(command.get("queue_name") or "default"),
                    payload=command.get("payload"),
                    priority=int(command.get("priority") or 100),
                    not_before=float(command["not_before"]) if command.get("not_before") is not None else None,
                    max_attempts=int(command.get("max_attempts") or 3),
                    metadata=dict(command.get("metadata") or {}),
                )
            case "schedule.flow" | "schedule.event":
                return self.context.control_runtime.schedule_job(
                    str(command.get("job_name") or ""),
                    kind=str(command.get("kind") or "flow"),
                    target=str(command.get("target") or ""),
                    queue_name=str(command.get("queue_name") or "default"),
                    payload=command.get("payload"),
                    interval_seconds=float(command["interval_seconds"]) if command.get("interval_seconds") is not None else None,
                    once_at=float(command["once_at"]) if command.get("once_at") is not None else None,
                    metadata=dict(command.get("metadata") or {}),
                )
            case "replication.peer.register":
                return self.context.replication.register_peer(
                    str(command.get("peer_name") or ""),
                    str(command.get("endpoint") or ""),
                    auth_token=str(command.get("auth_token")) if command.get("auth_token") else None,
                    tls_profile=str(command.get("tls_profile")) if command.get("tls_profile") else None,
                    enabled=bool(command.get("enabled", True)),
                    metadata=dict(command.get("metadata") or {}),
                )
            case "package.install":
                return self._install_package_local(command)
            case "service.deploy":
                return self._deploy_service_local(command)
            case "security.secret.store":
                return self.context.security.store_secret(
                    str(command.get("tenant_id") or ""),
                    str(command.get("secret_name") or ""),
                    str(command.get("secret_value") or ""),
                    metadata=dict(command.get("metadata") or {}),
                )
            case "security.tls.set":
                return self.context.security.set_tls_profile(
                    str(command.get("profile_name") or ""),
                    str(command.get("certfile") or ""),
                    str(command.get("keyfile") or ""),
                    cafile=str(command.get("cafile")) if command.get("cafile") else None,
                    verify=bool(command.get("verify", True)),
                    server_hostname=str(command.get("server_hostname")) if command.get("server_hostname") else None,
                )
            case "security.trust.set":
                return self.context.security.set_trust_policy(
                    str(command.get("policy_name") or ""),
                    tenant_id=str(command.get("tenant_id")) if command.get("tenant_id") else None,
                    namespace=str(command.get("namespace")) if command.get("namespace") else None,
                    require_tls=bool(command.get("require_tls", False)),
                    labels=dict(command.get("labels") or {}),
                    capabilities=set(command.get("capabilities") or []),
                    metadata=dict(command.get("metadata") or {}),
                )
            case "security.worker.onboard":
                return self.context.security.onboard_worker(
                    str(command.get("worker_id") or ""),
                    str(command.get("tenant_id") or ""),
                    namespace=str(command.get("namespace") or "default"),
                    capabilities=set(command.get("capabilities") or []),
                    labels=dict(command.get("labels") or {}),
                    tls_profile=str(command.get("tls_profile")) if command.get("tls_profile") else None,
                    certfile=str(command.get("certfile")) if command.get("certfile") else None,
                    keyfile=str(command.get("keyfile")) if command.get("keyfile") else None,
                    cafile=str(command.get("cafile")) if command.get("cafile") else None,
                    ca_name=str(command.get("ca_name")) if command.get("ca_name") else None,
                    trust_policy=str(command.get("trust_policy")) if command.get("trust_policy") else None,
                    rotate_after_seconds=int(command.get("rotate_after_seconds") or 86400),
                    metadata=dict(command.get("metadata") or {}),
                )
            case "security.ca.create":
                return self.context.security.create_certificate_authority(
                    str(command.get("ca_name") or ""),
                    common_name=str(command.get("common_name") or command.get("ca_name") or ""),
                    validity_days=int(command.get("validity_days") or 3650),
                    metadata=dict(command.get("metadata") or {}),
                )
            case "security.cert.issue":
                return self.context.security.issue_certificate(
                    str(command.get("ca_name") or ""),
                    subject_name=str(command.get("subject_name") or ""),
                    common_name=str(command.get("common_name") or command.get("subject_name") or ""),
                    profile_name=str(command.get("profile_name")) if command.get("profile_name") else None,
                    validity_days=int(command.get("validity_days") or 365),
                    metadata=dict(command.get("metadata") or {}),
                    serial=str(command.get("serial")) if command.get("serial") else None,
                )
            case "security.cert.revoke":
                return self.context.security.revoke_certificate(str(command.get("serial") or ""))
            case _:
                raise ValueError(f"unsupported consensus command '{command_type}'")

    def _send_consensus_vote(self, peer: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_control_plane(peer, "/consensus/request-vote", payload)

    def _send_consensus_append(self, peer: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_control_plane(peer, "/consensus/append", payload)

    def _post_control_plane(self, peer: dict[str, Any], path: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.context is not None
        self._maybe_failpoint("control.api.request")
        headers = {"Content-Type": "application/json"}
        auth_token = peer.get("auth_token")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib.request.Request(
            str(peer["endpoint"]).rstrip("/") + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        open_kwargs: dict[str, Any] = {"timeout": 10}
        tls_profile = peer.get("tls_profile")
        if tls_profile:
            profile = self.context.security.get_tls_profile(str(tls_profile))
            if isinstance(profile, dict):
                from .security import TLSProfile

                open_kwargs["context"] = TLSProfile(
                    name=str(profile["name"]),
                    certfile=str(profile["certfile"]),
                    keyfile=str(profile["keyfile"]),
                    cafile=str(profile["cafile"]) if profile.get("cafile") else None,
                    verify=bool(profile.get("verify", True)),
                    server_hostname=str(profile["server_hostname"]) if profile.get("server_hostname") else None,
                ).create_client_context()
        with urllib.request.urlopen(request, **open_kwargs) as response:
            return json.loads(response.read().decode("utf-8"))

    def _maybe_failpoint(self, name: str) -> None:
        if self.context is None:
            return
        self.context.operations.check_failpoint(name)

    def _register_program_resources(self, program: CompiledNovaProgram) -> None:
        assert self.context is not None

        for declaration in program.ast.declarations:
            match declaration:
                case AgentDeclaration():
                    self.context.agent_runtime.register(declaration)
                case ToolDeclaration(name=name, properties=properties):
                    self.context.tool_definitions[name] = dict(properties)
                case ServiceDeclaration(name=name, properties=properties):
                    self._enforce_quota("max_services", len(self.context.services) + 1)
                    self.context.services[name] = {
                        "name": name,
                        "tenant": str(properties.get("tenant") or self.context.active_tenant),
                        "namespace": str(properties.get("namespace") or self.context.active_namespace),
                        **dict(properties),
                    }
                    self.context.service_fabric.register_service(
                        name,
                        self.context.services[name],
                        tenant_id=str(self.context.services[name]["tenant"]),
                        namespace=str(self.context.services[name]["namespace"]),
                    )
                case PackageDeclaration(name=name, properties=properties):
                    self._enforce_quota("max_packages", len(self.context.packages) + 1)
                    self.context.packages[name] = {
                        "name": name,
                        "tenant": str(properties.get("tenant") or self.context.active_tenant),
                        "namespace": str(properties.get("namespace") or self.context.active_namespace),
                        "installed": False,
                        **dict(properties),
                    }
                    self.context.service_fabric.register_package(
                        name,
                        self.context.packages[name],
                        tenant_id=str(self.context.packages[name]["tenant"]),
                        namespace=str(self.context.packages[name]["namespace"]),
                    )
                case StateDeclaration(name=name, properties=properties):
                    self.context.states[name] = dict(properties)
                case SystemDeclaration(name=name, properties=properties):
                    self.context.systems[name] = dict(properties)
                case _:
                    continue

        for dataset_name, dataset in program.ast.datasets().items():
            bootstrap_records = self._bootstrap_dataset_records(dataset.properties, base_path=program.base_path)
            self.context.datasets[dataset_name] = DatasetSnapshot(
                name=dataset_name,
                properties=dict(dataset.properties),
                records=bootstrap_records,
                metadata={"source": dataset.properties.get("source", "memory")},
            )

    def _configure_platform(self, program: CompiledNovaProgram) -> None:
        assert self.context is not None

        for declaration in program.ast.by_type(SystemDeclaration):
            properties = dict(declaration.properties)
            self.context.policy.configure(properties)
            tenant_name = properties.get("tenant")
            if isinstance(tenant_name, str) and tenant_name:
                self.context.security.register_tenant(
                    tenant_name,
                    display_name=str(properties.get("display_name") or declaration.name),
                    metadata={"system": declaration.name},
                )
                self.context.active_tenant = tenant_name

            namespace_name = properties.get("namespace") or properties.get("default_namespace")
            if isinstance(namespace_name, str) and namespace_name:
                if not self.context.policy.permits_namespace(namespace_name):
                    raise PermissionError(f"namespace '{namespace_name}' is not permitted by runtime policy")
                self.context.active_namespace = namespace_name

            cluster_name = properties.get("cluster")
            if isinstance(cluster_name, str) and cluster_name:
                self.context.cluster_name = cluster_name

            node_id = properties.get("node_id")
            if isinstance(node_id, str) and node_id:
                self.context.node_id = node_id

            consensus_enabled = bool(properties.get("consensus_enabled") or properties.get("consensus"))
            self.context.consensus.configure(
                cluster_name=self.context.cluster_name,
                node_id=self.context.node_id,
                enabled=consensus_enabled,
            )

            secrets = properties.get("secrets")
            if isinstance(secrets, dict):
                for secret_name, secret_value in secrets.items():
                    self.context.security.store_secret(
                        self.context.active_tenant,
                        str(secret_name),
                        str(secret_value),
                        metadata={"system": declaration.name},
                    )

            tls = properties.get("tls")
            if isinstance(tls, dict):
                profile_name = str(tls.get("profile") or declaration.name)
                certfile = tls.get("cert")
                keyfile = tls.get("key")
                cafile = tls.get("ca")
                if isinstance(certfile, str) and isinstance(keyfile, str):
                    self.context.security.set_tls_profile(
                        profile_name,
                        str(self._resolve_path(certfile)),
                        str(self._resolve_path(keyfile)),
                        cafile=str(self._resolve_path(cafile)) if isinstance(cafile, str) else None,
                        verify=bool(tls.get("verify", True)),
                        server_hostname=str(tls.get("server_hostname")) if tls.get("server_hostname") else None,
                    )

            certificate_authorities = properties.get("certificate_authorities")
            if isinstance(certificate_authorities, list):
                for item in certificate_authorities:
                    if not isinstance(item, dict):
                        continue
                    ca_name = str(item.get("name") or item.get("ca") or "")
                    common_name = str(item.get("common_name") or ca_name)
                    if not ca_name:
                        continue
                    self.create_certificate_authority(
                        ca_name,
                        common_name=common_name,
                        validity_days=int(item.get("validity_days") or 3650),
                        metadata=dict(item.get("metadata") or {}),
                    )

            trust_policies = properties.get("trust_policies")
            if isinstance(trust_policies, list):
                for item in trust_policies:
                    if not isinstance(item, dict):
                        continue
                    policy_name = str(item.get("name") or item.get("policy") or "")
                    if not policy_name:
                        continue
                    self.set_trust_policy(
                        policy_name,
                        tenant_id=str(item.get("tenant")) if item.get("tenant") else None,
                        namespace=str(item.get("namespace")) if item.get("namespace") else None,
                        require_tls=bool(item.get("require_tls", False)),
                        labels=dict(item.get("labels") or {}),
                        capabilities={str(cap) for cap in item.get("capabilities", [])},
                        metadata=dict(item.get("metadata") or {}),
                    )

            replicas = properties.get("replication")
            if isinstance(replicas, list):
                for item in replicas:
                    if not isinstance(item, dict):
                        continue
                    peer_name = str(item.get("name") or "")
                    endpoint = str(item.get("endpoint") or "")
                    if not peer_name or not endpoint:
                        continue
                    self.register_replica_peer(
                        peer_name,
                        endpoint,
                        auth_token=str(item.get("auth_token")) if item.get("auth_token") else None,
                        tls_profile=str(item.get("tls_profile")) if item.get("tls_profile") else None,
                        enabled=bool(item.get("enabled", True)),
                        metadata=dict(item.get("metadata") or {}),
                    )

            consensus_peers = properties.get("consensus_peers")
            if isinstance(consensus_peers, list):
                for item in consensus_peers:
                    if not isinstance(item, dict):
                        continue
                    peer_name = str(item.get("name") or "")
                    endpoint = str(item.get("endpoint") or "")
                    if not peer_name or not endpoint:
                        continue
                    self.register_consensus_peer(
                        peer_name,
                        endpoint,
                        auth_token=str(item.get("auth_token")) if item.get("auth_token") else None,
                        tls_profile=str(item.get("tls_profile")) if item.get("tls_profile") else None,
                        voter=bool(item.get("voter", True)),
                        active=bool(item.get("active", True)),
                        metadata=dict(item.get("metadata") or {}),
                    )

            if bool(properties.get("leader")):
                self.context.cluster.acquire_leadership(
                    self.context.cluster_name,
                    self.context.node_id,
                    lease_seconds=int(properties.get("lease_seconds") or 30),
                    metadata={"system": declaration.name},
                )
            schedules = properties.get("schedules")
            if isinstance(schedules, list):
                for item in schedules:
                    if not isinstance(item, dict):
                        continue
                    job_name = str(item.get("job") or item.get("name") or "")
                    if not job_name:
                        continue
                    kind = str(item.get("kind") or "flow")
                    target = str(item.get("target") or item.get("flow") or item.get("event") or "")
                    if not target:
                        continue
                    interval = float(item["interval_seconds"]) if item.get("interval_seconds") is not None else None
                    once_at = float(item["once_at"]) if item.get("once_at") is not None else None
                    if kind == "event":
                        self.schedule_event(job_name, target, interval_seconds=interval, once_at=once_at, queue_name=str(item.get("queue") or "default"), payload=item.get("payload"), metadata=dict(item.get("metadata") or {}))
                    else:
                        self.schedule_flow(job_name, target, interval_seconds=interval, once_at=once_at, queue_name=str(item.get("queue") or "default"), payload=item.get("payload"), metadata=dict(item.get("metadata") or {}))
            if bool(properties.get("daemon_autostart")):
                self.start_control_daemon(
                    interval_seconds=float(properties.get("daemon_interval_seconds") or 1.0),
                    task_limit=int(properties.get("daemon_task_limit") or 4),
                )
            if bool(properties.get("api_autostart")):
                self.start_control_api(
                    host=str(properties.get("api_host") or "127.0.0.1"),
                    port=int(properties.get("api_port") or 8781),
                    auth_token=str(properties.get("api_token")) if properties.get("api_token") else None,
                )
            alerts = properties.get("alerts")
            if isinstance(alerts, list):
                for item in alerts:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "")
                    metric = str(item.get("metric") or "")
                    if not name or not metric:
                        continue
                    self.context.observability.add_alert_rule(name, metric, float(item.get("threshold") or 0.0))
            self._audit("system", declaration.name, "ok", {"properties": to_jsonable(properties)})

        for package_name, package in list(self.context.packages.items()):
            if not package.get("tenant") or str(package.get("tenant")) == "default":
                package["tenant"] = self.context.active_tenant
            if not package.get("namespace") or str(package.get("namespace")) == "default":
                package["namespace"] = self.context.active_namespace
            self.context.service_fabric.register_package(
                package_name,
                package,
                tenant_id=str(package["tenant"]),
                namespace=str(package["namespace"]),
            )
        for service_name, service in list(self.context.services.items()):
            if not service.get("tenant") or str(service.get("tenant")) == "default":
                service["tenant"] = self.context.active_tenant
            if not service.get("namespace") or str(service.get("namespace")) == "default":
                service["namespace"] = self.context.active_namespace
            self.context.service_fabric.register_service(
                service_name,
                service,
                tenant_id=str(service["tenant"]),
                namespace=str(service["namespace"]),
            )

        for package in list(self.context.packages):
            if bool(self.context.packages[package].get("auto_install")):
                self.install_package(package)
        for service in list(self.context.services):
            if bool(self.context.services[service].get("auto_deploy")):
                self.deploy_service(service)

    def _register_event_bindings(self, program: CompiledNovaProgram) -> None:
        assert self.context is not None

        for declaration in program.ast.by_type(EventDeclaration):
            trigger = str(declaration.properties.get("on", declaration.name))
            for flow_name in self._event_flows(declaration):
                self.context.event_bus.subscribe(
                    trigger,
                    lambda event, bound_flow=flow_name: self._handle_bound_event(bound_flow, event),
                )

    def _restore_context_payload(self, payload: dict[str, Any]) -> None:
        assert self.context is not None
        datasets_payload = payload.get("datasets", {})
        if isinstance(datasets_payload, dict):
            for name, snapshot_payload in datasets_payload.items():
                if not isinstance(snapshot_payload, dict):
                    continue
                self.context.datasets[name] = DatasetSnapshot(
                    name=str(snapshot_payload.get("name") or name),
                    properties=dict(snapshot_payload.get("properties") or {}),
                    records=list(snapshot_payload.get("records") or []),
                    version=int(snapshot_payload.get("version") or 0),
                    metadata=dict(snapshot_payload.get("metadata") or {}),
                )
        states_payload = payload.get("states")
        if isinstance(states_payload, dict):
            self.context.states = dict(states_payload)
        tenant_payload = payload.get("tenant")
        if isinstance(tenant_payload, str) and tenant_payload:
            self.context.active_tenant = tenant_payload
            self.context.security.register_tenant(tenant_payload)
        namespace_payload = payload.get("namespace")
        if isinstance(namespace_payload, str) and namespace_payload:
            self.context.active_namespace = namespace_payload
        cluster_payload = payload.get("cluster_name")
        if isinstance(cluster_payload, str) and cluster_payload:
            self.context.cluster_name = cluster_payload
        node_payload = payload.get("node_id")
        if isinstance(node_payload, str) and node_payload:
            self.context.node_id = node_payload
        outputs_payload = payload.get("outputs")
        if isinstance(outputs_payload, dict):
            self.context.outputs = dict(outputs_payload)
        embeddings_payload = payload.get("embeddings")
        if isinstance(embeddings_payload, dict):
            self.context.embeddings = dict(embeddings_payload)
        memory_payload = payload.get("agent_memory")
        if isinstance(memory_payload, dict):
            self.context.agent_memory = {str(key): list(value) if isinstance(value, list) else [] for key, value in memory_payload.items()}
        services_payload = payload.get("services")
        if isinstance(services_payload, dict):
            self.context.services = {str(key): dict(value) for key, value in services_payload.items() if isinstance(value, dict)}
        packages_payload = payload.get("packages")
        if isinstance(packages_payload, dict):
            self.context.packages = {str(key): dict(value) for key, value in packages_payload.items() if isinstance(value, dict)}
        policy_payload = payload.get("policy")
        if isinstance(policy_payload, dict):
            self.context.policy.configure(policy_payload)
        principal_payload = payload.get("principal")
        if isinstance(principal_payload, dict):
            self.context.principal = AuthPrincipal(
                tenant_id=str(principal_payload.get("tenant_id") or self.context.active_tenant),
                subject=str(principal_payload.get("subject") or "snapshot"),
                roles={str(role) for role in principal_payload.get("roles", [])},
                token_id=str(principal_payload.get("token_id") or ""),
                expires_at=float(principal_payload["expires_at"]) if principal_payload.get("expires_at") is not None else None,
                metadata=dict(principal_payload.get("metadata") or {}),
                authenticated_at=float(principal_payload.get("authenticated_at") or time.time()),
            )
        self._refresh_state_cache()

    def _require_context(self) -> None:
        if self.context is None:
            raise RuntimeError("no Nova program is loaded")

    def _refresh_state_cache(self) -> None:
        if self.context is None:
            return
        for record in self.context.state_store.list_state(
            tenant_id=self.context.active_tenant,
            namespace=self.context.active_namespace,
            limit=10000,
        ):
            self.context.states[str(record["key"])] = record["value"]

    def _current_quotas(self) -> dict[str, Any]:
        assert self.context is not None
        tenant = self.context.security.get_tenant(self.context.active_tenant) or {}
        return self.context.policy.resolve_quotas(dict(tenant.get("quotas") or {}))

    def _enforce_quota(self, quota_name: str, current_value: int) -> None:
        if self.context is None:
            return
        limit = self._current_quotas().get(quota_name)
        if limit is None:
            return
        try:
            max_value = int(limit)
        except (TypeError, ValueError):
            return
        if current_value > max_value:
            self._audit("quota", quota_name, "error", {"limit": max_value, "current": current_value})
            raise PermissionError(f"quota exceeded for {quota_name}: {current_value} > {max_value}")

    def _tenant_queue_depth(self) -> int:
        assert self.context is not None
        tasks = self.context.control_runtime.list_tasks(limit=10000)
        return sum(
            1
            for task in tasks
            if str(task.get("metadata", {}).get("tenant") or self.context.active_tenant) == self.context.active_tenant
            and str(task.get("metadata", {}).get("namespace") or self.context.active_namespace) == self.context.active_namespace
        )

    def _tenant_schedule_count(self) -> int:
        assert self.context is not None
        schedules = self.context.control_runtime.list_schedules(limit=10000)
        return sum(
            1
            for item in schedules
            if str(item.get("metadata", {}).get("tenant") or self.context.active_tenant) == self.context.active_tenant
            and str(item.get("metadata", {}).get("namespace") or self.context.active_namespace) == self.context.active_namespace
        )

    def _tenant_state_count(self, *, increment_if_missing: bool = False) -> int:
        assert self.context is not None
        count = len(self.context.state_store.list_state(tenant_id=self.context.active_tenant, namespace=self.context.active_namespace, limit=10000))
        return count + (1 if increment_if_missing else 0)

    def _tenant_worker_count(self) -> int:
        assert self.context is not None
        return sum(1 for worker in self.context.mesh.list_workers() if worker.tenant in {None, self.context.active_tenant})

    def _send_replica_record(self, peer: dict[str, Any], record: dict[str, Any]) -> None:
        assert self.context is not None
        headers = {"Content-Type": "application/json"}
        auth_token = peer.get("auth_token")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib.request.Request(
            str(peer["endpoint"]).rstrip("/") + "/replication/apply",
            data=json.dumps(record, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        open_kwargs: dict[str, Any] = {"timeout": 10}
        tls_profile = peer.get("tls_profile")
        if tls_profile:
            profile = self.context.security.get_tls_profile(str(tls_profile))
            if isinstance(profile, dict):
                from .security import TLSProfile

                open_kwargs["context"] = TLSProfile(
                    name=str(profile["name"]),
                    certfile=str(profile["certfile"]),
                    keyfile=str(profile["keyfile"]),
                    cafile=str(profile["cafile"]) if profile.get("cafile") else None,
                    verify=bool(profile.get("verify", True)),
                    server_hostname=str(profile["server_hostname"]) if profile.get("server_hostname") else None,
                ).create_client_context()
        with urllib.request.urlopen(request, **open_kwargs) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("applied", False):
            raise RuntimeError(str(payload.get("error") or "replication failed"))

    def start_control_api(self, *, host: str = "127.0.0.1", port: int = 8781, auth_token: str | None = None) -> dict[str, Any]:
        self._require_context()
        from .api import NovaControlPlaneAPIServer

        if self._api_server is not None:
            self.stop_control_api()
        self._api_server = NovaControlPlaneAPIServer(self, host=host, port=port, auth_token=auth_token)
        self._api_server.start()
        payload = self._api_server.status()
        self._audit("control", "api.start", "ok", payload)
        return payload

    def stop_control_api(self) -> dict[str, Any]:
        if self._api_server is None:
            return {"running": False}
        self._api_server.stop()
        payload = self._api_server.status()
        self._api_server = None
        if self.context is not None:
            self._audit("control", "api.stop", "ok", payload)
        return payload

    def control_api_status(self) -> dict[str, Any]:
        if self._api_server is None:
            return {"running": False}
        return self._api_server.status()

    def _resolve_path(self, value: str | Path | None) -> Path:
        assert self.context is not None
        target = Path(value) if value is not None else self.context.base_path
        if not target.is_absolute():
            target = (self.context.base_path / target).resolve(strict=False)
        return target

    def _install_package_local(self, command: dict[str, Any]) -> dict[str, Any]:
        assert self.context is not None
        package_name = str(command.get("package_name") or "")
        package = dict(command.get("package") or self.context.packages.get(package_name) or {})
        package["installed"] = True
        package["installed_at"] = package.get("installed_at") or time.time()
        installed = self.context.service_fabric.install_package(
            package_name,
            package,
            tenant_id=str(command.get("tenant") or package.get("tenant") or self.context.active_tenant),
            namespace=str(command.get("namespace") or package.get("namespace") or self.context.active_namespace),
        )
        self.context.packages[package_name] = dict(installed)
        return installed

    def _deploy_service_local(self, command: dict[str, Any]) -> dict[str, Any]:
        assert self.context is not None
        service_name = str(command.get("service_name") or "")
        spec = dict(command.get("spec") or {})
        dependencies = [str(item) for item in spec.get("depends_on", []) if str(item)]
        for dependency in dependencies:
            existing = self.context.service_fabric.get_service(dependency)
            if existing is None:
                raise ValueError(f"service '{service_name}' depends on unknown service '{dependency}'")
            if not any(instance.get("status") == "running" for instance in existing.get("instances", [])):
                if dependency in self.context.services:
                    self.deploy_service(dependency)
                existing = self.context.service_fabric.get_service(dependency)
                if existing is None or not any(instance.get("status") == "running" for instance in existing.get("instances", [])):
                    raise RuntimeError(f"dependency service '{dependency}' is not ready")
        strategy = str(command.get("strategy") or "rolling")
        metadata = dict(command.get("metadata") or {})
        rollout = self.create_rollout(
            service_name,
            spec,
            strategy=strategy,
            metadata=metadata,
            auto_promote=bool(command.get("auto_promote", True)),
        )
        service = dict(self.context.services.get(service_name) or {})
        service["last_rollout"] = rollout
        service["status"] = rollout.get("status")
        service["active_revision"] = rollout.get("active_revision") or rollout.get("revision")
        fabric_service = self.context.service_fabric.deploy_service(
            service_name,
            {**service, **spec},
            tenant_id=str(spec.get("tenant") or service.get("tenant") or self.context.active_tenant),
            namespace=str(spec.get("namespace") or service.get("namespace") or self.context.active_namespace),
            rollout=rollout,
            active_revision=int(rollout.get("active_revision") or rollout.get("revision") or 0) or None,
            status=str(rollout.get("status") or "deploying"),
        )
        self.context.traffic_plane.configure_service(
            service_name,
            fabric_service,
            secret_resolver=self.context.security.resolve_secret,
        )
        service["instances"] = fabric_service.get("instances", [])
        self.context.services[service_name] = service
        return {"service": dict(service), "rollout": rollout}

    def _execute_recovery_step(self, step: dict[str, Any]) -> Any:
        action = str(step.get("action") or "")
        match action:
            case "resume_snapshot":
                snapshot_path = step.get("snapshot_path")
                if not snapshot_path:
                    raise ValueError("resume_snapshot requires snapshot_path")
                return self.resume(str(snapshot_path))
            case "replay_workflow":
                run_id = step.get("run_id")
                if not run_id:
                    raise ValueError("replay_workflow requires run_id")
                return self.replay_workflow_run(str(run_id))
            case _:
                raise ValueError(f"unsupported recovery action '{action}'")

    def _run_control_task(self, task: dict[str, Any]) -> dict[str, Any]:
        kind = str(task.get("kind") or "")
        target = str(task.get("target") or "")
        payload = task.get("payload")
        match kind:
            case "flow":
                flow_record = self.execute_flow(target, trigger_event="queue")
                return {"kind": kind, "target": target, "flow": flow_record.to_dict(), "payload": payload}
            case "event":
                result = self.emit(target, payload)
                return {"kind": kind, "target": target, "event": target, "result": result.to_dict()}
            case _:
                raise ValueError(f"unsupported queued task kind '{kind}'")

    def _handle_bound_event(self, flow_name: str, event: Event) -> None:
        if flow_name in self._execution_stack:
            return
        self._triggered_flows.append(self.execute_flow(flow_name, trigger_event=event.name))

    def _entry_flows(self, ast: NovaAST) -> list[str]:
        event_bound_flows = {flow_name for event in ast.by_type(EventDeclaration) for flow_name in self._event_flows(event)}
        flow_names = list(ast.flows())
        unbound_flows = [flow_name for flow_name in flow_names if flow_name not in event_bound_flows]
        return unbound_flows or flow_names

    def _event_flows(self, declaration: EventDeclaration) -> list[str]:
        flows_value = declaration.properties.get("flows")
        if isinstance(flows_value, list):
            return [str(item) for item in flows_value]
        if "flow" in declaration.properties:
            return [str(declaration.properties["flow"])]
        if isinstance(flows_value, str):
            return [flows_value]
        return []

    def _execute_node(self, node: DatasetNode | ToolNode | AgentNode | ServiceNode | PackageNode | FlowNode | EventNode) -> NodeExecutionRecord | None:
        assert self.context is not None
        started_at = time.perf_counter()
        self._authorize_node(node)
        parent_trace = self._current_trace()
        node_trace = self._child_trace(parent_trace, kind=getattr(node, "kind", type(node).__name__), name=node.name)

        match node:
            case FlowNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="flow", name=node.name, output=node.properties, metadata=dict(node.metadata))
            case DatasetNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="dataset", name=node.name, output=self.context.datasets[node.dataset_name].to_dict(), metadata=dict(node.metadata))
            case EventNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="event", name=node.name, output={"trigger": node.trigger, "flows": list(node.flows)}, metadata=dict(node.metadata))
            case ToolNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="tool", name=node.name, output=node.metadata, metadata=dict(node.metadata))
            case AgentNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="agent", name=node.name, output=node.metadata, metadata=dict(node.metadata))
            case ServiceNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="service", name=node.name, output=self.context.services.get(node.service_name, node.properties), metadata=dict(node.metadata))
            case PackageNode(resource=True):
                record = NodeExecutionRecord(node_id=node.node_id, kind="package", name=node.name, output=self.context.packages.get(node.package_name, node.properties), metadata=dict(node.metadata))
            case ToolNode():
                execution = self._execute_tool(node)
                output = execution.data if execution.data is not None else execution.output
                if node.alias:
                    self.context.outputs[node.alias] = output
                self.context.outputs[node.node_id] = output
                status = "error" if execution.error else "ok"
                record = NodeExecutionRecord(node_id=node.node_id, kind="tool", name=node.name, status=status, output=execution.to_dict(), metadata=dict(node.metadata))
            case AgentNode():
                task = AgentTask(
                    agent_name=node.agent_name,
                    action=node.action or "run",
                    inputs=[self.context.resolve_reference(value) for value in node.inputs],
                    metadata={**dict(node.metadata), **node_trace},
                )
                result = self.context.agent_runtime.execute(task, self.context)
                output = result.data if result.data is not None else result.output
                if node.alias:
                    self.context.outputs[node.alias] = output
                self.context.outputs[node.node_id] = output
                self._publish_event("agent.finished", {"agent": node.agent_name, "flow": node.flow, "action": task.action, "output": result.output}, source=node.agent_name)
                record = NodeExecutionRecord(node_id=node.node_id, kind="agent", name=node.name, output=result.to_dict(), metadata=dict(node.metadata))
            case _:
                return None

        duration_ms = (time.perf_counter() - started_at) * 1000.0
        record.metadata["duration_ms"] = round(duration_ms, 3)
        self.context.observability.record(
            kind="node",
            name=record.name,
            status=record.status,
            trace_id=node_trace["trace_id"],
            span_id=node_trace["span_id"],
            parent_span_id=node_trace.get("parent_span_id"),
            correlation_id=node_trace["correlation_id"],
            flow=getattr(node, "flow", None),
            node_id=record.node_id,
            duration_ms=duration_ms,
            metadata={"kind": record.kind, "output": to_jsonable(record.output)},
        )
        return record

    def _execute_tool(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if node.tool_name in {"rss.fetch", "atheria.embed", "system.log", "event.emit", "flow.run", "state.set", "state.get", "service.deploy", "service.status", "package.install", "package.status"}:
            return self._execute_tool_local(node)
        capability = str(node.metadata.get("capability", "tool") or "tool")
        remote_command = self._build_remote_command(node)
        task = {
            "kind": "tool",
            "node_id": node.node_id,
            "tool": node.tool_name,
            "arguments": list(node.arguments),
            "flow": node.flow,
            "command": remote_command,
            "pipeline_data": self.context.resolve_reference(node.arguments[-1]) if len(node.arguments) > 1 else None,
            "tenant": str(node.metadata.get("tenant") or self.context.active_tenant),
            "namespace": str(node.metadata.get("namespace") or self.context.active_namespace),
            "selector": dict(node.metadata.get("selector") or {}),
            "require_tls": bool(node.metadata.get("require_tls") or self.context.policy.mesh_tls_required),
            "metadata": {
                "tenant": str(node.metadata.get("tenant") or self.context.active_tenant),
                "namespace": str(node.metadata.get("namespace") or self.context.active_namespace),
                **(self._current_trace() or {}),
            },
        }
        result = self.context.mesh.dispatch(capability, task, lambda: self._execute_tool_local(node))
        if isinstance(result, CommandExecution):
            return result
        if isinstance(result, dict):
            return CommandExecution(
                output=str(result.get("output", "")),
                data=result.get("data"),
                error=result.get("error"),
                metadata={"remote": True, "data_type": result.get("data_type")},
            )
        return CommandExecution(data=result)

    def _build_remote_command(self, node: ToolNode) -> str | None:
        assert self.context is not None
        if node.tool_name in {"rss.fetch", "atheria.embed", "system.log", "event.emit", "flow.run", "state.set", "state.get", "service.deploy", "service.status", "package.install", "package.status"}:
            return None
        tool_definition = self.context.tool_definitions.get(node.tool_name, {})
        command_template = tool_definition.get("command") or tool_definition.get("pipeline")
        if command_template:
            command = str(command_template)
            if node.arguments:
                command = command.replace("{{dataset}}", str(node.arguments[0]))
            for index, argument in enumerate(node.arguments):
                command = command.replace(f"{{{{arg{index}}}}}", str(argument))
                resolved = self.context.resolve_reference(argument)
                replacement = json.dumps(resolved, ensure_ascii=False) if isinstance(resolved, (dict, list)) else str(resolved)
                command = command.replace(f"{{{{value{index}}}}}", replacement)
            return command
        request = BackendExecutionRequest(operation=node.tool_name, arguments=node.arguments, metadata=dict(node.metadata))
        return self.context.backend_router._build_shell_command(request, self.context)

    def _execute_tool_local(self, node: ToolNode) -> CommandExecution:
        match node.tool_name:
            case "rss.fetch":
                return self._tool_rss_fetch(node)
            case "atheria.embed":
                return self._tool_atheria_embed(node)
            case "system.log":
                return self._tool_system_log(node)
            case "event.emit":
                return self._tool_event_emit(node)
            case "flow.run":
                return self._tool_flow_run(node)
            case "state.set":
                return self._tool_state_set(node)
            case "state.get":
                return self._tool_state_get(node)
            case "service.deploy":
                return self._tool_service_deploy(node)
            case "service.status":
                return self._tool_service_status(node)
            case "package.install":
                return self._tool_package_install(node)
            case "package.status":
                return self._tool_package_status(node)
            case _:
                assert self.context is not None
                tool_definition = self.context.tool_definitions.get(node.tool_name, {})
                command_template = tool_definition.get("command") or tool_definition.get("pipeline")
                if command_template:
                    return self._run_declared_command(str(command_template), node)
                return self.context.backend_router.execute(
                    BackendExecutionRequest(operation=node.tool_name, arguments=node.arguments, metadata=dict(node.metadata)),
                    self.context,
                )

    def _tool_rss_fetch(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if not node.arguments:
            return CommandExecution(error="rss.fetch requires a dataset name")
        dataset_name = node.arguments[0]
        if dataset_name not in self.context.datasets:
            return CommandExecution(error=f"unknown dataset '{dataset_name}'")

        snapshot = self.context.datasets[dataset_name]
        records = self._bootstrap_dataset_records(snapshot.properties, base_path=self.context.base_path)
        snapshot.update(records, metadata={"source": snapshot.properties.get("source", "rss")})
        payload = {"dataset": dataset_name, "records": len(records), "version": snapshot.version, "source": snapshot.properties.get("source", "rss")}
        self.context.outputs[dataset_name] = records
        self._publish_event("dataset.updated", payload, source=dataset_name)
        return CommandExecution(output=json.dumps(payload, ensure_ascii=False), data=payload, metadata={"dataset": dataset_name})

    def _tool_atheria_embed(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if not node.arguments:
            return CommandExecution(error="atheria.embed requires a dataset name")
        dataset_name = node.arguments[0]
        if dataset_name not in self.context.datasets:
            return CommandExecution(error=f"unknown dataset '{dataset_name}'")

        snapshot = self.context.datasets[dataset_name]
        embedding_record = {"dataset": dataset_name, "vectors": len(snapshot.records), "provider": snapshot.properties.get("knowledge", "atheria"), "version": snapshot.version}
        self.context.embeddings[dataset_name] = embedding_record
        self._publish_event("knowledge.updated", embedding_record, source="atheria")
        return CommandExecution(output=json.dumps(embedding_record, ensure_ascii=False), data=embedding_record)

    def _tool_system_log(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        resolved = [self.context.resolve_reference(argument) for argument in node.arguments]
        text = " ".join(str(item) for item in resolved)
        return CommandExecution(output=text, data=text)

    def _tool_event_emit(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if not node.arguments:
            return CommandExecution(error="event.emit requires an event name")
        event_name = node.arguments[0]
        payload = self.context.resolve_reference(node.arguments[1]) if len(node.arguments) > 1 else None
        event = self._publish_event(event_name, payload, source=node.flow or "flow")
        return CommandExecution(output=json.dumps(event.to_dict(), ensure_ascii=False), data=event.to_dict())

    def _tool_flow_run(self, node: ToolNode) -> CommandExecution:
        if not node.arguments:
            return CommandExecution(error="flow.run requires a flow name")
        flow_name = node.arguments[0]
        flow_record = self.execute_flow(flow_name, trigger_event=node.flow)
        return CommandExecution(output=json.dumps(flow_record.to_dict(), ensure_ascii=False), data=flow_record.to_dict())

    def _tool_state_set(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if len(node.arguments) < 2:
            return CommandExecution(error="state.set requires <key> <value>")
        key = node.arguments[0]
        value = self.context.resolve_reference(node.arguments[1])
        self._enforce_quota("max_state_keys", self._tenant_state_count(increment_if_missing=key not in self.context.states))
        record = self.context.state_store.set_state(
            self.context.active_tenant,
            self.context.active_namespace,
            key,
            value,
            metadata={"flow": node.flow or "", "node_id": node.node_id},
        )
        self.context.states[key] = value
        self.context.replication.append_record(
            "state",
            {
                "record_id": record["record_id"],
                "key": key,
                "value": value,
                "metadata": record["metadata"],
            },
            tenant_id=self.context.active_tenant,
            namespace=self.context.active_namespace,
            source_node=self.context.node_id,
            metadata={"category": "state"},
            record_id=record["record_id"],
        )
        return CommandExecution(output=json.dumps({"key": key, "value": to_jsonable(value)}, ensure_ascii=False), data={"key": key, "value": value})

    def _tool_state_get(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if not node.arguments:
            return CommandExecution(error="state.get requires <key>")
        key = node.arguments[0]
        state_record = self.context.state_store.get_state(self.context.active_tenant, self.context.active_namespace, key)
        value = state_record["value"] if state_record is not None else self.context.states.get(key)
        if state_record is not None:
            self.context.states[key] = value
        return CommandExecution(output=json.dumps({"key": key, "value": to_jsonable(value)}, ensure_ascii=False), data=value)

    def _tool_service_deploy(self, node: ToolNode) -> CommandExecution:
        if not node.arguments:
            return CommandExecution(error="service.deploy requires <service_name>")
        payload = self.deploy_service(node.arguments[0])
        return CommandExecution(output=json.dumps(payload, ensure_ascii=False), data=payload)

    def _tool_service_status(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        service_name = node.arguments[0] if node.arguments else None
        if service_name:
            service = self.context.service_fabric.get_service(service_name) or self.context.services.get(service_name)
            if service is None:
                return CommandExecution(error=f"unknown service '{service_name}'")
            return CommandExecution(output=json.dumps(service, ensure_ascii=False), data=service)
        payload = self.list_services()
        return CommandExecution(output=json.dumps(payload, ensure_ascii=False), data=payload)

    def _tool_package_install(self, node: ToolNode) -> CommandExecution:
        if not node.arguments:
            return CommandExecution(error="package.install requires <package_name>")
        payload = self.install_package(node.arguments[0])
        return CommandExecution(output=json.dumps(payload, ensure_ascii=False), data=payload)

    def _tool_package_status(self, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        package_name = node.arguments[0] if node.arguments else None
        if package_name:
            package = self.context.service_fabric.get_package(package_name) or self.context.packages.get(package_name)
            if package is None:
                return CommandExecution(error=f"unknown package '{package_name}'")
            return CommandExecution(output=json.dumps(package, ensure_ascii=False), data=package)
        payload = self.list_packages()
        return CommandExecution(output=json.dumps(payload, ensure_ascii=False), data=payload)

    def _run_declared_command(self, template: str, node: ToolNode) -> CommandExecution:
        assert self.context is not None
        if self.context.command_executor is None:
            return CommandExecution(error=f"tool '{node.tool_name}' requires a command executor")

        command = template
        if node.arguments:
            command = command.replace("{{dataset}}", str(node.arguments[0]))
        for index, argument in enumerate(node.arguments):
            command = command.replace(f"{{{{arg{index}}}}}", str(argument))
            resolved = self.context.resolve_reference(argument)
            replacement = json.dumps(resolved, ensure_ascii=False) if isinstance(resolved, (dict, list)) else str(resolved)
            command = command.replace(f"{{{{value{index}}}}}", replacement)
        pipeline_data = self.context.resolve_reference(node.arguments[-1]) if node.arguments else None
        return self.context.command_executor.execute(command, pipeline_data=pipeline_data, cwd=self.context.base_path)

    def _bootstrap_dataset_records(self, properties: dict[str, Any], *, base_path: Path) -> list[Any]:
        if isinstance(properties.get("items"), list):
            return [self._normalize_record(item) for item in properties["items"]]

        path_value = properties.get("path")
        if isinstance(path_value, str) and path_value.strip():
            target = Path(path_value)
            if not target.is_absolute():
                target = (base_path / target).resolve(strict=False)
            if target.exists():
                if target.suffix.lower() == ".json":
                    loaded = json.loads(target.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        return [self._normalize_record(item) for item in loaded]
                    return [self._normalize_record(loaded)]
                if target.suffix.lower() == ".csv":
                    rows = [line.split(",") for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
                    if not rows:
                        return []
                    header = rows[0]
                    return [{header[index]: value for index, value in enumerate(row) if index < len(header)} for row in rows[1:]]
                return [{"text": line.strip()} for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]

        if properties.get("inline"):
            return [{"text": str(properties["inline"])}]

        if properties.get("source") == "rss":
            feed = str(properties.get("feed", properties.get("url", "local-feed")))
            return [
                {
                    "title": f"Fetched item from {feed}",
                    "source": feed,
                    "summary": "Synthetic placeholder record produced by the Nova runtime skeleton.",
                }
            ]

        return []

    def _normalize_record(self, value: Any) -> Any:
        return value if isinstance(value, dict) else {"value": value}

    def _publish_event(self, event_name: str, payload: Any, *, source: str) -> Event:
        assert self.context is not None
        actor = self.context.principal.subject if isinstance(self.context.principal, AuthPrincipal) else "system"
        created_trace = self._current_trace() is None
        trace = self._current_trace() or self._begin_trace("event", event_name)
        durable_event = self.context.control_runtime.publish_event(
            event_name,
            payload=payload,
            source=source,
            metadata={"actor": actor, "tenant": self.context.active_tenant, **trace},
        )
        self.context.replication.append_record(
            "event",
            {
                "event_name": event_name,
                "payload": payload,
                "source": source,
                "metadata": {"actor": actor, "tenant": self.context.active_tenant, "namespace": self.context.active_namespace, **trace},
            },
            tenant_id=self.context.active_tenant,
            namespace=self.context.active_namespace,
            source_node=self.context.node_id,
            metadata={"category": "event", "sequence": durable_event["sequence"]},
            record_id=f"event-{durable_event['sequence']}",
        )
        event = self.context.event_bus.publish(event_name, payload, source=source, metadata={"actor": actor, "tenant": self.context.active_tenant, **trace})
        self.context.observability.record(
            kind="event",
            name=event_name,
            status="ok",
            trace_id=trace["trace_id"],
            span_id=trace["span_id"],
            parent_span_id=trace.get("parent_span_id"),
            correlation_id=trace["correlation_id"],
            metadata={"source": source, "payload": to_jsonable(payload)},
        )
        self._audit("event", event_name, "ok", {"source": source, "payload": to_jsonable(payload), "sequence": durable_event["sequence"]})
        if self.event_bridge is not None:
            self.event_bridge(event)
        if created_trace:
            self._end_trace(trace)
        return event

    def assert_admin_access(self, action: str) -> None:
        self._require_context()
        if self.context.policy.can_admin(self.context.principal):
            return
        self._audit("policy", action, "error", {"required": "admin"})
        raise PermissionError(f"admin access required for '{action}'")

    def assert_operator_access(self, action: str) -> None:
        self._require_context()
        if self.context.policy.can_operate(self.context.principal):
            return
        self._audit("policy", action, "error", {"required": "operator"})
        raise PermissionError(f"operator access required for '{action}'")

    def _authorize_flow(self, flow_name: str) -> None:
        assert self.context is not None
        if self.program is None:
            return
        declaration = self.program.ast.flows().get(flow_name)
        if declaration is None:
            return
        flow_tenant = declaration.properties.get("tenant")
        flow_namespace = declaration.properties.get("namespace")
        required_roles = declaration.properties.get("required_roles")
        if isinstance(flow_tenant, str) and not self.context.policy.authorize_tenant(self.context.active_tenant, flow_tenant):
            self._audit("policy", f"flow:{flow_name}", "error", {"reason": "tenant_mismatch", "flow_tenant": flow_tenant})
            raise PermissionError(f"flow '{flow_name}' is bound to tenant '{flow_tenant}'")
        if isinstance(flow_namespace, str) and not self.context.policy.authorize_namespace(self.context.active_namespace, flow_namespace):
            self._audit("policy", f"flow:{flow_name}", "error", {"reason": "namespace_mismatch", "flow_namespace": flow_namespace})
            raise PermissionError(f"flow '{flow_name}' is bound to namespace '{flow_namespace}'")
        if not self.context.policy.authorize_roles(self.context.principal, required_roles):
            self._audit("policy", f"flow:{flow_name}", "error", {"reason": "missing_roles", "required_roles": to_jsonable(required_roles)})
            raise PermissionError(f"flow '{flow_name}' requires roles: {required_roles}")

    def _authorize_node(self, node: DatasetNode | ToolNode | AgentNode | ServiceNode | PackageNode | FlowNode | EventNode) -> None:
        assert self.context is not None
        resource_tenant = str(node.metadata.get("tenant")).strip() if node.metadata.get("tenant") else None
        if resource_tenant and not self.context.policy.authorize_tenant(self.context.active_tenant, resource_tenant):
            self._audit("policy", node.name, "error", {"reason": "tenant_mismatch", "resource_tenant": resource_tenant})
            raise PermissionError(f"node '{node.name}' is bound to tenant '{resource_tenant}'")
        resource_namespace = str(node.metadata.get("namespace")).strip() if node.metadata.get("namespace") else None
        if resource_namespace and not self.context.policy.authorize_namespace(self.context.active_namespace, resource_namespace):
            self._audit("policy", node.name, "error", {"reason": "namespace_mismatch", "resource_namespace": resource_namespace})
            raise PermissionError(f"node '{node.name}' is bound to namespace '{resource_namespace}'")
        required_roles = node.metadata.get("required_roles")
        if not self.context.policy.authorize_roles(self.context.principal, required_roles):
            self._audit("policy", node.name, "error", {"reason": "missing_roles", "required_roles": to_jsonable(required_roles)})
            raise PermissionError(f"node '{node.name}' requires roles: {required_roles}")

    def _audit(self, category: str, action: str, status: str, details: dict[str, Any] | None = None) -> None:
        assert self.context is not None
        principal = self.context.principal
        actor = principal.subject if isinstance(principal, AuthPrincipal) else "system"
        self.context.audit.record(category=category, action=action, status=status, actor=actor, tenant=self.context.active_tenant, details=details or {})

    def _begin_trace(self, kind: str, name: str, **metadata: Any) -> dict[str, str]:
        current = self._current_trace()
        trace = {
            "trace_id": current["trace_id"] if current is not None else uuid.uuid4().hex[:16],
            "span_id": uuid.uuid4().hex[:16],
            "parent_span_id": current["span_id"] if current is not None else "",
            "correlation_id": current["correlation_id"] if current is not None else uuid.uuid4().hex[:16],
            "trace_kind": kind,
            "trace_name": name,
        }
        for key, value in metadata.items():
            if value is not None:
                trace[f"trace_meta_{key}"] = str(value)
        self._trace_stack.append(trace)
        return trace

    def _child_trace(self, parent: dict[str, str] | None, *, kind: str, name: str) -> dict[str, str]:
        return {
            "trace_id": parent["trace_id"] if parent is not None else uuid.uuid4().hex[:16],
            "span_id": uuid.uuid4().hex[:16],
            "parent_span_id": parent["span_id"] if parent is not None else "",
            "correlation_id": parent["correlation_id"] if parent is not None else uuid.uuid4().hex[:16],
            "trace_kind": kind,
            "trace_name": name,
        }

    def _current_trace(self) -> dict[str, str] | None:
        return self._trace_stack[-1] if self._trace_stack else None

    def _end_trace(self, trace: dict[str, str]) -> None:
        if self._trace_stack and self._trace_stack[-1] == trace:
            self._trace_stack.pop()
