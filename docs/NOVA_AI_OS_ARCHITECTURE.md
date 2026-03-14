# Nova AI Operating System Architecture

Nova-shell now has a second execution path beside the legacy line-oriented NovaScript runtime:

- `novascript.py`: imperative shell-style scripting for existing workflows
- `nova/`: declarative Nova Language compiler and AI operating system runtime

The declarative stack is designed around a small number of stable abstractions:

1. `NovaParser`
   Turns `.ns` source into a typed AST with `agent`, `dataset`, `flow`, `state`, `event`, `tool`, `service`, `package`, and `system` declarations.
2. `NovaGraphCompiler`
   Compiles the AST into a DAG of `AgentNode`, `DatasetNode`, `ToolNode`, `ServiceNode`, `PackageNode`, `FlowNode`, and `EventNode`.
3. `NovaRuntime`
   Executes graph closures per flow, hosts the agent runtime, routes runtime events, and can dispatch work into the mesh registry.
4. `EventBus`
   Delivers runtime events such as `dataset.updated`, `agent.finished`, and custom external signals.
5. `MeshRegistry`
   Provides worker registration and capability-based dispatch for local or remote execution backends.

## Directory Structure

```text
nova/
  __init__.py
  parser/
    ast.py
    errors.py
    parser.py
  graph/
    model.py
    compiler.py
  runtime/
    consensus.py
    backends.py
    cluster.py
    control_plane.py
    context.py
    executor_daemon.py
    executor_job.py
    executors.py
    observability.py
    api.py
    replication.py
    runtime.py
    security.py
    service_fabric.py
    state_store.py
    telemetry.py
    workflows.py
  agents/
    runtime.py
  events/
    bus.py
  mesh/
    control_plane.py
    registry.py
examples/
  ai_os_cluster.ns
  advanced_agent_fabric.ns
  control_plane_runtime.ns
  market_radar.ns
  distributed_pipeline.ns
  consensus_fabric_cluster.ns
  replicated_control_plane.ns
  secure_multi_tenant.ns
  service_package_platform.ns
```

## Execution Model

- Declarations define resources and policy, not execution order.
- `flow` blocks define ordered steps which are compiled into graph edges.
- Graph nodes are executed in topological order for the selected flow closure.
- Tool nodes can run built-ins such as `rss.fetch`, `atheria.embed`, and `system.log`, or execute declared commands through the existing shell runtime.
- Agent nodes resolve model, tools, memory, and embeddings from their declarations and execute inside the runtime context.
- Event declarations bind named runtime events to one or more flows.
- Systems and mesh capabilities remain data-driven so future backends can be plugged in without changing the language front-end.

## Runtime Capabilities

The current declarative runtime now supports these execution classes directly:

- local graph execution with persistent state and dataset snapshots
- capability-based mesh dispatch with SQLite-backed worker/task history
- remote worker dispatch over HTTP with failover across registered mesh workers
- runtime observability persisted as JSONL traces under `.nova/`
- tenant-aware security services with token issuance, secret storage, and TLS profile registry
- lease-based cluster leadership, rolling deployment revisions, and persisted recovery playbooks
- runtime policy enforcement for RBAC, tenant isolation, and secure-mesh transport requirements
- append-only audit logging for flows, events, auth actions, cluster operations, and deployment actions
- durable control-plane queue with retries/backoff, periodic schedules, and a local daemon tick loop
- durable event log replay for event-driven automation recovery and audit correlation
- persistent state log with replay per tenant and namespace
- replicated event/state/workflow transport across API-connected peers
- HTTP control-plane API for queueing, schedules, metrics, workflow replay, and replication ingress
- health-aware rollout evaluation for `rolling`, `canary`, and `blue_green` deployment strategies
- backend operations such as `py.exec`, `sys.exec`, `data.load`, `cpp.exec`, `gpu.run`, `wasm.run`
- native backend executor daemons for `py`, `cpp`, `gpu`, `wasm`, and `ai` routed through a standardized executor protocol
- isolated executor subprocesses with restart, cancellation, timeout handling, and per-request job streaming/status
- event-native steps such as `event.emit`, `flow.run`, `state.set`, and `state.get`
- agent execution with provider-aware fallback through the existing Nova-shell AI runtime
- declarative `package` installation metadata and `service` deployment metadata with rollout integration
- persistent service-fabric state with package registry, service discovery, and replica reconciliation
- control-plane consensus log with peer election, vote RPCs, append RPCs, and commit/apply replay
- encrypted secrets at rest plus built-in certificate authorities, certificate issuance, and revocation state
- scheduler lease ownership, stale-task recovery, and idempotent queue effects for replay-safe orchestration
- heartbeat-driven consensus sync, peer removal, snapshot install, and consensus log compaction
- configs, volumes, ingress mappings, package dependency resolution, signature verification, and autoscaling policies
- correlated traces with `trace_id`/`correlation_id`, latency histograms, alert evaluation, and snapshot validation
- provider-aware agent runtime with prompt versions, governance checks, tool sandboxing, and sharded memory scopes
- Prometheus and OTLP-style runtime metrics export
- snapshot and resume of declarative runtime state

Operational inspection from the shell:

- `ns.run file.ns`
- `ns.graph file.ns`
- `ns.status`
- `ns.cluster`
- `ns.auth`
- `ns.deploy`
- `ns.recover`
- `ns.control`
- `ns.snapshot [file]`
- `ns.resume <file>`

## Platform Control Plane

The declarative runtime now carries a persisted platform layer under `.nova/`:

- `mesh-control-plane.db`
  Stores worker registration and task history for capability-based execution.
- `security-plane.db`
  Stores tenants, issued API tokens, secret metadata and values, and TLS profiles for local runtime integration.
- `cluster-plane.db`
  Stores leader leases, deployment revisions, recovery playbooks, and recovery run history.
- `runtime-control-plane.db`
  Stores queued tasks, schedules, daemon state, and the durable event log used by the local control plane.
- `runtime-state.db`
  Stores current state values and an append-only state change log for replay and namespace recovery.
- `runtime-workflows.db`
  Stores durable workflow run history used for replay and recovery orchestration.
- `runtime-replication.db`
  Stores replication peers and the replicated event/state/workflow log.
- `runtime-consensus.db`
  Stores consensus peers, the persistent control-plane log, commit index, and leader election state.
- `runtime-executors.db`
  Stores native executor daemon endpoints and runtime request counters.
- `service-fabric.db`
  Stores packages, services, desired replica state, service instances/endpoints, configs, volumes, and ingress mappings.
- `runtime-observability.jsonl`
  Stores append-only node, flow, and event traces including correlation metadata for inspection and replay correlation.
- `runtime-audit.jsonl`
  Stores append-only audit records for authentication, policy decisions, recovery actions, and deployment operations.

Operationally, this gives the declarative `.ns` path its own control plane instead of relying on the legacy shell runtime as the only source of truth.

## Secure Operations

The runtime can now enforce policy directly at execution time:

- `auth_required: true`
  Requires authenticated principals for operator and admin control-plane commands.
- `tenant_isolation: true`
  Prevents tenant-bound flows and nodes from executing under the wrong tenant context.
- `namespace_isolation: true`
  Prevents namespace-bound flows and nodes from executing outside the selected namespace.
- `admin_roles` and `operator_roles`
  Control which token roles may mutate cluster, deployment, recovery, and secret state.
- `quotas: {...}`
  Enforces queue, schedule, state, service, package, and worker limits at runtime.
- `selector: {...}`
  Constrains a flow/tool/agent to workers with matching mesh labels.
- `require_tls: true` or `mesh_tls_required: true`
  Filters remote worker placement to HTTPS endpoints only.
- `trust_policies: [...]`
  Declares mTLS/label/capability admission rules for worker onboarding and mesh registration.
- `certificate_authorities: [...]`
  Declares runtime-managed CAs used to issue and rotate worker certificates.

For local worker processes, Nova-shell now supports secured worker startup:

- `mesh start-worker --caps py --labels role=secure --token <bearer>`
- `mesh start-worker --caps py --tls-cert cert.pem --tls-key key.pem [--tls-ca ca.pem]`

## Local Control Plane

The declarative runtime now includes a local control-plane loop for durable orchestration:

- `ns.control queue enqueue <flow>`
  Adds a durable queued task persisted in SQLite.
- `ns.control queue run`
  Claims and executes queued tasks immediately through the active runtime.
- `ns.control schedule add-flow <job> <flow> <interval>`
  Adds a periodic schedule that enqueues flow tasks.
- `ns.control daemon start`
  Starts a background thread that ticks the scheduler and drains queued tasks.
- `ns.control api start`
  Starts an HTTP control-plane API for remote queueing, metrics, replication ingress, and replay.
- `ns.control metrics <json|prometheus|otlp>`
  Exports runtime metrics for external observability systems.
- `ns.control replica ...`
  Manages replication peers and forces replication syncs.
- `ns.control workflow ...`
  Lists and replays durable workflow runs.
- `ns.control events [name] [since_sequence] [limit]`
  Replays the durable event log for recovery and replay inspection.

This is still process-local, but it closes a major gap between a compiler/runtime skeleton and an actual operating control plane.

## New Control-Plane Primitives

The latest runtime layer adds three major product-OS primitives:

- `ControlPlaneConsensus`
  A persistent, Raft-like log for queue, schedule, service, package, security, and replication mutations.
- `NativeExecutorManager`
  A local daemon manager for `py`, `cpp`, `gpu`, `wasm`, and `ai` executor endpoints, replacing shell-only execution as the primary backend path.
- `executor_daemon.py` + `executor_job.py`
  The isolation boundary for backend execution: one persistent daemon per backend and one subprocess per request for timeout/cancel/restart safety.
- `ServiceFabric`
  A persistent package/service registry with instance tracking, discovery, and replica reconciliation.

Example program:

- [examples/consensus_fabric_cluster.ns](H:/Nova-shell-main/examples/consensus_fabric_cluster.ns)

## Current Product Gaps Closed

The latest repo iteration closes several previously open platform gaps:

- Global scheduler ownership:
  The runtime now acquires a persisted scheduler lease with a fencing token before enqueueing schedule-derived tasks.
- Replay-safe queueing:
  Queue tasks now support idempotency keys plus task-effect persistence so retries can reuse completed results.
- Service platform features:
  Services now persist configs, volumes, ingress definitions, autoscaling policies, and dependency metadata.
- Deeper diagnostics:
  Traces now carry `trace_id`, `span_id`, and `correlation_id`, and telemetry exports latency histograms and alert state.
- Agent governance:
  Agents now support prompt revisions, provider preference lists, memory sharding, and input/tool governance checks.

Reference example:

- [examples/advanced_agent_fabric.ns](H:/Nova-shell-main/examples/advanced_agent_fabric.ns)

## Design Decisions

- Keep the parser line-based and explicit so syntax errors can point to exact lines with minimal ambiguity.
- Compile flows into a DAG early so orchestration, observability, and distributed placement all operate on one shared graph representation.
- Reuse the existing `NovaShell.route()` command path through a small command-executor adapter instead of duplicating shell semantics inside the new runtime.
- Preserve backward compatibility by routing only brace-based declarative `.ns` programs into the new stack; legacy NovaScript continues to use the existing interpreter.
- Persist mesh and observability state under `.nova/` so long-running orchestration becomes inspectable and resumable at the runtime boundary.
