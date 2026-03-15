import hashlib
import http.server
import json
import sqlite3
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from nova import AgentNode, ExecutorTask, NovaGraphCompiler, NovaParser, NovaRuntime, ToolNode
from nova.agents.runtime import AgentTask
from nova.mesh.registry import WorkerNode
from nova_shell import NovaShell


DECLARATIVE_PROGRAM = """
state memory_store {
  backend: atheria
  namespace: test-space
}

agent researcher {
  model: llama3
  tools: [atheria.embed]
  memory: memory_store
  embeddings: atheria
}

dataset tech_rss {
  source: rss
  items: [{title: "Alpha", source: "feed-a"}, {title: "Beta", source: "feed-b"}]
}

flow radar {
  rss.fetch tech_rss -> fetched
  atheria.embed tech_rss -> embedded
  researcher summarize tech_rss -> briefing
}

event new_information {
  on: new_information
  flow: radar
}
""".strip()


BACKEND_PROGRAM_TEMPLATE = """
system edge_cluster {{
  mode: mesh
  capability: py
}}

dataset metrics {{
  path: {json_path}
}}

flow orchestrate {{
  data.load {json_path} -> loaded
  py.exec "sum(item['value'] for item in _)" loaded -> total
  state.set latest_total total
  state.get latest_total -> total_state
  event.emit new_metric total_state
}}

event schedule_tick {{
  on: schedule.tick
  flow: orchestrate
}}
""".strip()

REMOTE_PROGRAM = """
system remote_cluster {
  mode: mesh
  capability: py
}

dataset metrics {
  items: [{value: 4}, {value: 6}, {value: 10}]
}

flow remote_ops {
  py.exec "sum(item['value'] for item in _)" metrics -> total
  state.set remote_total total
}
""".strip()

PLATFORM_PROGRAM = """
system control_plane {
  tenant: platform
  cluster: edge-cluster
  node_id: node-alpha
  leader: true
  secrets: {api_key: "demo-secret"}
}

flow boot {
  system.log "boot" -> ready
}
""".strip()

AUTH_REQUIRED_PROGRAM = """
system secure_plane {
  auth_required: true
  tenant_isolation: true
  admin_roles: [admin]
  operator_roles: [ops, admin]
}

flow boot {
  system.log "ready" -> ready
}

flow tenant_job {
  tenant: alpha
  system.log "tenant-ready" -> tenant_ready
}

event tenant_job_trigger {
  on: tenant.job
  flow: tenant_job
}
""".strip()

TOKEN_REMOTE_PROGRAM = """
system secure_cluster {
  mode: mesh
  capability: py
  selector: {role: secure}
}

dataset metrics {
  items: [{value: 4}, {value: 6}]
}

flow remote_ops {
  system: secure_cluster
  py.exec "sum(item['value'] for item in _)" metrics -> total
  state.set remote_total total
}
""".strip()

TLS_REQUIRED_PROGRAM = """
system tls_cluster {
  mode: mesh
  capability: py
  selector: {role: secure}
  mesh_tls_required: true
}

dataset metrics {
  items: [{value: 2}, {value: 3}]
}

flow remote_ops {
  system: tls_cluster
  py.exec "sum(item['value'] for item in _)" metrics -> total
  state.set remote_total total
}
""".strip()

CONTROL_PROGRAM = """
system control_plane {
  daemon_autostart: false
}

flow queued_job {
  system.log "queued" -> queue_output
  state.set queue_value queue_output
}

event ping_handler {
  on: ping
  flow: queued_job
}
""".strip()

SERVICE_PROGRAM = """
system package_plane {
  namespace: prod
  quotas: {max_state_keys: 4, max_services: 4, max_packages: 4}
}

package core_sdk {
  version: 1.0.0
  source: "./core-sdk.tar"
  auto_install: true
}

service api {
  package: core_sdk
  image: nova:api
  replicas: 2
  strategy: blue_green
  auto_deploy: true
}

flow boot {
  package.status core_sdk -> pkg
  service.status api -> svc
}
""".strip()

REPLICATION_PROGRAM = """
system replica_plane {
  namespace: sync
  daemon_autostart: false
}

flow sync {
  system.log "payload" -> msg
  state.set shared_state msg
  event.emit replicated_event msg
}
""".strip()

QUOTA_PROGRAM = """
system quota_plane {
  namespace: blue
  namespace_isolation: true
  quotas: {max_state_keys: 1}
}

flow allowed {
  namespace: blue
  state.set first one
}

flow denied {
  namespace: red
  system.log "blocked" -> blocked
}

flow overflow {
  namespace: blue
  state.set first one
  state.set second two
}
""".strip()

SERVICE_FABRIC_PROGRAM_TEMPLATE = """
system fabric_core {{
  namespace: prod
  alerts: [{{name: "flow-fast", metric: "flow_p95_ms", threshold: 0}}]
}}

package base_sdk {{
  version: 1.0.0
  source: {base_path}
  checksum: {base_checksum}
  auto_install: true
}}

package api_bundle {{
  version: 1.1.0
  source: {api_path}
  checksum: {api_checksum}
  dependencies: [base_sdk]
  auto_install: true
}}

service backend {{
  package: base_sdk
  replicas: 1
  auto_deploy: true
}}

service gateway {{
  package: api_bundle
  replicas: 2
  depends_on: [backend]
  configs: {{gateway_cfg: {{mode: "prod", log_level: "info"}}}}
  volumes: {{gateway_data: {{type: "persistent", mount: "/data"}}}}
  ingress: [{{host: "gateway.local", path: "/api", target_port: 8080}}]
  autoscale: {{metric: "cpu", scale_out_threshold: 0.7, scale_in_threshold: 0.2, min_replicas: 1, max_replicas: 4, step: 1}}
  auto_deploy: true
}}

flow boot {{
  service.status gateway -> gateway_status
}}
""".strip()

AGENT_GOVERNANCE_PROGRAM = """
agent analyst {
  model: llama3
  provider: shell
  providers: [shell, atheria]
  tools: [atheria.search]
  prompts: {v1: "Summarize.", v2: "Summarize with tags."}
  prompt_version: v2
  memory: agent_mem
  memory_shards: 4
  governance: {allowed_models: [llama3], max_input_chars: 400}
}

dataset notes {
  items: [{text: "hello"}, {text: "world"}]
}

flow work {
  analyst summarize notes -> result
}
""".strip()

TOOLCHAIN_SHARED_PROGRAM = """
dataset shared_notes {
  items: [{text: "hello import"}]
}

agent helper {
  model: llama3
}
""".strip()

TOOLCHAIN_MAIN_PROGRAM = """
import "./shared.ns"

system dev_core {
  namespace: dev
}

flow test_imports {
  test: true
  assert_state: {done: "ok"}
  assert_outputs: [summary, marker]
  assert_events: [tested]
  helper summarize shared_notes -> summary
  system.log "ok" -> marker
  state.set done marker
  event.emit tested marker
}
""".strip()

TRAFFIC_PROGRAM = """
system traffic_plane {
  tenant: default
  namespace: prod
  secrets: {db_password: "super-secret"}
}

service gateway {
  image: nova:gateway
  replicas: 2
  ingress: [{host: "gateway.local", path: "/api"}]
  secret_mounts: {"/etc/secrets/db": db_password}
  auto_deploy: true
}
""".strip()


class _FakeCommandExecutor:
    def execute(self, command: str, *, pipeline_data: object = None, cwd: Path | None = None) -> object:
        class _Result:
            def __init__(self) -> None:
                self.output = f"provider:{command}"
                self.data = {"command": command, "pipeline": pipeline_data}
                self.error = None
                self.metadata = {"cwd": str(cwd) if cwd else None}

        return _Result()


class _TextHandler(http.server.BaseHTTPRequestHandler):
    body_text = "ok"

    def do_GET(self) -> None:  # noqa: N802
        payload = self.body_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class NovaLanguageTests(unittest.TestCase):
    def test_parser_builds_typed_ast(self) -> None:
        parser = NovaParser()
        ast = parser.parse(DECLARATIVE_PROGRAM)

        self.assertEqual(len(ast.declarations), 5)
        self.assertEqual(ast.agents()["researcher"].properties["model"], "llama3")
        self.assertEqual(ast.datasets()["tech_rss"].properties["source"], "rss")
        self.assertEqual(ast.flows()["radar"].steps[0].operation, "rss.fetch")
        self.assertEqual(ast.flows()["radar"].steps[2].alias, "briefing")

    def test_graph_compiler_creates_dag(self) -> None:
        ast = NovaParser().parse(DECLARATIVE_PROGRAM)
        graph = NovaGraphCompiler().compile(ast)
        order = graph.topological_order()

        self.assertGreaterEqual(len(graph.nodes), 7)
        self.assertTrue(any(isinstance(node, AgentNode) and not node.resource for node in graph.nodes.values()))
        self.assertTrue(any(isinstance(node, ToolNode) and not node.resource for node in graph.nodes.values()))
        self.assertIn("flow::radar", order)

    def test_runtime_executes_flow_and_mesh_dispatch(self) -> None:
        runtime = NovaRuntime()
        runtime.load(DECLARATIVE_PROGRAM)
        assert runtime.context is not None
        assert runtime.program is not None
        runtime.context.mesh.register(
            WorkerNode(
                worker_id="embed-worker",
                capabilities={"tool"},
                executor=lambda task: runtime._execute_tool_local(runtime.program.graph.nodes[task["node_id"]]),
            )
        )

        flow_record = runtime.execute_flow("radar")

        self.assertEqual(flow_record.flow, "radar")
        self.assertIn("briefing", runtime.context.outputs)
        self.assertTrue(any(event.name == "dataset.updated" for event in runtime.context.event_bus.history))

    def test_runtime_event_trigger_updates_context(self) -> None:
        runtime = NovaRuntime()
        runtime.load(DECLARATIVE_PROGRAM)
        result = runtime.emit("new_information", {"source": "test"})

        assert runtime.context is not None
        self.assertEqual(result.flows[0].flow, "radar")
        self.assertIn("briefing", runtime.context.outputs)
        self.assertTrue(any(event.name == "flow.finished" for event in runtime.context.event_bus.history))

    def test_runtime_backend_execution_and_observability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "metrics.json"
            json_path.write_text(json.dumps([{"value": 2}, {"value": 5}, {"value": 8}]), encoding="utf-8")
            program = BACKEND_PROGRAM_TEMPLATE.format(json_path=json.dumps(str(json_path)))

            with NovaRuntime() as runtime:
                runtime.load(program, base_path=tmp)
                assert runtime.context is not None
                assert runtime.program is not None
                runtime.context.mesh.register(
                    WorkerNode(
                        worker_id="py-worker",
                        capabilities={"py"},
                        executor=lambda task: runtime._execute_tool_local(runtime.program.graph.nodes[task["node_id"]]),
                    )
                )

                result = runtime.emit("schedule.tick", {"manual": True})
                snapshot = runtime.context.snapshot()

                self.assertEqual(result.flows[0].flow, "orchestrate")
                self.assertEqual(runtime.context.states["latest_total"], 15)
                self.assertGreaterEqual(snapshot["mesh"]["task_count"], 1)
                self.assertGreaterEqual(snapshot["observability"]["node_count"], 1)
                self.assertTrue(any(event.name == "new_metric" for event in runtime.context.event_bus.history))

    def test_runtime_native_executor_manager_handles_python_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "metrics.json"
            json_path.write_text(json.dumps([{"value": 1}, {"value": 2}, {"value": 3}]), encoding="utf-8")
            program = BACKEND_PROGRAM_TEMPLATE.format(json_path=json.dumps(str(json_path)))

            with NovaRuntime() as runtime:
                runtime.load(program, base_path=tmp)
                result = runtime.execute_flow("orchestrate")
                assert runtime.context is not None

                self.assertEqual(result.flow, "orchestrate")
                self.assertEqual(runtime.context.states["latest_total"], 6)
                executors = runtime.executor_status()["executors"]
                self.assertTrue(any(item["backend"] == "py" for item in executors))

    def test_runtime_isolated_executor_supports_timeout_cancel_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with NovaRuntime() as runtime:
                runtime.load(DECLARATIVE_PROGRAM, base_path=tmp)
                assert runtime.context is not None

                timeout_result = runtime.context.executors.execute(
                    "py",
                    ExecutorTask(
                        request_id="timeout-job",
                        capability="py",
                        kind="backend",
                        operation="py.exec",
                        arguments=["import time\ntime.sleep(1)\n_ = 1"],
                        command="import time\ntime.sleep(1)\n_ = 1",
                        metadata={"timeout_seconds": 0.2},
                    ),
                )
                self.assertIsNotNone(timeout_result.error)

                async_result = runtime.context.executors.execute_async(
                    "py",
                    ExecutorTask(
                        request_id="cancel-job",
                        capability="py",
                        kind="backend",
                        operation="py.exec",
                        arguments=['import time\nprint("hello")\ntime.sleep(5)\nprint("done")'],
                        command='import time\nprint("hello")\ntime.sleep(5)\nprint("done")',
                    ),
                )
                self.assertEqual(async_result["status"], "running")
                time.sleep(0.2)
                stream = runtime.context.executors.stream("py", "cancel-job")
                self.assertEqual(stream["request_id"], "cancel-job")
                canceled = runtime.context.executors.cancel("py", "cancel-job")
                self.assertTrue(canceled["canceled"])

                restarted = runtime.context.executors.restart_backend("py")
                self.assertEqual(restarted["backend"], "py")
                recovered = runtime.context.executors.execute(
                    "py",
                    ExecutorTask(
                        request_id="recover-job",
                        capability="py",
                        kind="backend",
                        operation="py.exec",
                        arguments=["41 + 1"],
                        command="41 + 1",
                    ),
                )
                self.assertEqual(recovered.data, 42)

    def test_runtime_system_declaration_bootstraps_platform_services(self) -> None:
        with NovaRuntime() as runtime:
            runtime.load(PLATFORM_PROGRAM)
            assert runtime.context is not None

            self.assertEqual(runtime.context.active_tenant, "platform")
            self.assertEqual(runtime.context.cluster_name, "edge-cluster")
            self.assertEqual(runtime.context.node_id, "node-alpha")
            self.assertEqual(runtime.resolve_secret("platform", "api_key")["secret_value"], "demo-secret")

            leader = runtime.leader_status("edge-cluster")
            self.assertIsNotNone(leader)
            self.assertEqual(leader["leader_id"], "node-alpha")

    def test_runtime_enforces_tenant_isolation_on_flow_execution(self) -> None:
        with NovaRuntime() as runtime:
            runtime.load(AUTH_REQUIRED_PROGRAM)
            runtime.register_tenant("alpha")
            runtime.select_tenant("default")

            with self.assertRaises(PermissionError):
                runtime.execute_flow("tenant_job")

            runtime.select_tenant("alpha")
            flow_record = runtime.execute_flow("tenant_job")
            self.assertEqual(flow_record.flow, "tenant_job")
            self.assertEqual(runtime.context.outputs["tenant_ready"], "tenant-ready")

    def test_runtime_control_plane_queue_scheduler_and_durable_event_log(self) -> None:
        with NovaRuntime() as runtime:
            runtime.load(CONTROL_PROGRAM)
            assert runtime.context is not None

            task = runtime.enqueue_flow("queued_job")
            self.assertEqual(task["status"], "queued")

            processed = runtime.run_pending_tasks()
            self.assertEqual(processed["processed_count"], 1)
            self.assertEqual(runtime.context.states["queue_value"], "queued")

            runtime.schedule_flow("job1", "queued_job", interval_seconds=0.0)
            tick = runtime.scheduler_tick()
            self.assertGreaterEqual(tick["jobs_enqueued"], 1)

            daemon_tick = runtime.control_tick(task_limit=4)
            self.assertGreaterEqual(daemon_tick["processed"]["processed_count"], 1)

            runtime.emit("ping", {"source": "test"})
            replay = runtime.replay_event_log(event_name="ping", limit=10)
            self.assertEqual(replay[-1]["event_name"], "ping")
            self.assertGreaterEqual(runtime.control_status()["event_count"], 1)

    def test_runtime_canary_rollout_evaluation_promotes_healthy_revision(self) -> None:
        with NovaRuntime() as runtime:
            runtime.load(DECLARATIVE_PROGRAM)
            runtime.create_rollout("svc", {"image": "nova:v1"}, strategy="rolling", auto_promote=True)
            runtime.create_rollout("svc", {"image": "nova:v2"}, strategy="canary", auto_promote=False)
            runtime.record_deployment_health("svc", 2, "canary-a", status="healthy", metrics={"error_rate": 0.01})
            evaluation = runtime.evaluate_rollout("svc", 2)

            self.assertEqual(evaluation["evaluation"]["action"], "promote")
            self.assertEqual(evaluation["active_revision"], 2)

    def test_parser_and_runtime_support_service_and_package_resources(self) -> None:
        parser = NovaParser()
        ast = parser.parse(SERVICE_PROGRAM)
        self.assertIn("core_sdk", ast.packages())
        self.assertIn("api", ast.services())

        graph = NovaGraphCompiler().compile(ast)
        graph_kinds = {node["kind"] for node in graph.to_dict()["nodes"]}
        self.assertIn("service", graph_kinds)
        self.assertIn("package", graph_kinds)

        with NovaRuntime() as runtime:
            runtime.load(SERVICE_PROGRAM)
            assert runtime.context is not None
            self.assertTrue(runtime.context.packages["core_sdk"]["installed"])
            self.assertEqual(runtime.context.services["api"]["last_rollout"]["strategy"], "blue_green")

            flow_record = runtime.execute_flow("boot")
            self.assertEqual(flow_record.flow, "boot")
            self.assertIn("pkg", runtime.context.outputs)
            self.assertIn("svc", runtime.context.outputs)

    def test_runtime_replication_api_and_state_log_sync_between_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_target, tempfile.TemporaryDirectory() as tmp_source:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            with NovaRuntime() as target, NovaRuntime() as source:
                target.load(REPLICATION_PROGRAM, base_path=tmp_target)
                api_status = target.start_control_api(host="127.0.0.1", port=port, auth_token="replica-secret")
                self.assertTrue(api_status["running"])

                source.load(REPLICATION_PROGRAM, base_path=tmp_source)
                source.register_replica_peer("target", f"http://127.0.0.1:{port}", auth_token="replica-secret")
                source.execute_flow("sync")
                sync_result = source.sync_replication(limit=50)
                self.assertEqual(sync_result["peer_count"], 1)

                replicated_state = target.list_state(tenant_id="default", namespace="sync")
                self.assertTrue(any(item["key"] == "shared_state" for item in replicated_state))
                replicated_events = target.replay_event_log(event_name="replicated_event", limit=20)
                self.assertTrue(any(item["event_name"] == "replicated_event" for item in replicated_events))

                status_request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/status",
                    headers={"Authorization": "Bearer replica-secret"},
                )
                with urllib.request.urlopen(status_request, timeout=10) as response:
                    status_payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("replication", status_payload)

                metrics_request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/metrics/prometheus",
                    headers={"Authorization": "Bearer replica-secret"},
                )
                with urllib.request.urlopen(metrics_request, timeout=10) as response:
                    metrics_text = response.read().decode("utf-8")
                self.assertIn("nova_runtime_metric", metrics_text)
                target.stop_control_api()

    def test_runtime_consensus_replicates_control_plane_queue_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_leader, tempfile.TemporaryDirectory() as tmp_follower:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            with NovaRuntime() as leader, NovaRuntime() as follower:
                leader.load(CONTROL_PROGRAM, base_path=tmp_leader)
                follower.load(CONTROL_PROGRAM, base_path=tmp_follower)
                assert leader.context is not None
                assert follower.context is not None

                leader.context.cluster_name = "raft"
                leader.context.node_id = "leader-node"
                follower.context.cluster_name = "raft"
                follower.context.node_id = "follower-node"
                leader.context.consensus.configure(cluster_name="raft", node_id="leader-node", enabled=True)
                follower.context.consensus.configure(cluster_name="raft", node_id="follower-node", enabled=True)

                follower.start_control_api(host="127.0.0.1", port=port, auth_token="raft-secret")
                leader.register_consensus_peer("follower", f"http://127.0.0.1:{port}", auth_token="raft-secret")
                election = leader.start_consensus_election()
                self.assertEqual(election["role"], "leader")

                task = leader.enqueue_flow("queued_job", priority=5)
                follower_tasks = follower.list_queue_tasks(limit=10)
                self.assertTrue(any(item["task_id"] == task["task_id"] for item in follower_tasks))
                heartbeats = leader.send_consensus_heartbeats()
                self.assertGreaterEqual(heartbeats["sent"], 1)
                snapshot = leader.compact_consensus_log()
                installed = follower.install_consensus_snapshot(snapshot)
                self.assertGreaterEqual(installed["last_included_index"], snapshot["last_included_index"])
                follower.stop_control_api()

    def test_runtime_scheduler_lease_and_idempotent_queueing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with NovaRuntime() as runtime_a, NovaRuntime() as runtime_b:
                runtime_a.load(CONTROL_PROGRAM, base_path=tmp)
                runtime_b.load(CONTROL_PROGRAM, base_path=tmp)
                assert runtime_a.context is not None
                assert runtime_b.context is not None
                runtime_a.context.node_id = "node-a"
                runtime_b.context.node_id = "node-b"
                runtime_a.context.cluster_name = "shared"
                runtime_b.context.cluster_name = "shared"

                runtime_a.schedule_flow("job", "queued_job", interval_seconds=0.0)
                tick_a = runtime_a.scheduler_tick()
                tick_b = runtime_b.scheduler_tick()

                self.assertGreaterEqual(tick_a["jobs_enqueued"], 1)
                self.assertEqual(tick_b["jobs_enqueued"], 0)

                task_a = runtime_a.enqueue_flow("queued_job", idempotency_key="dup-task")
                task_b = runtime_b.enqueue_flow("queued_job", idempotency_key="dup-task")
                self.assertEqual(task_a["task_id"], task_b["task_id"])

                processed = runtime_a.run_pending_tasks(limit=10)
                effect = runtime_a.context.control_runtime.get_task_effect(task_a["task_id"])
                self.assertGreaterEqual(processed["processed_count"], 1)
                self.assertIsNotNone(effect)
                self.assertEqual(effect["status"], "ok")

    def test_runtime_enforces_namespace_isolation_and_state_quotas(self) -> None:
        with NovaRuntime() as runtime:
            runtime.load(QUOTA_PROGRAM)
            runtime.select_namespace("blue")

            allowed = runtime.execute_flow("allowed")
            self.assertEqual(allowed.flow, "allowed")

            with self.assertRaises(PermissionError):
                runtime.execute_flow("denied")

            with self.assertRaises(PermissionError):
                runtime.execute_flow("overflow")

    def test_runtime_trust_policies_gate_worker_onboarding_and_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "worker-cert.pem"
            key_path = Path(tmp) / "worker-key.pem"
            ca_path = Path(tmp) / "worker-ca.pem"
            cert_path.write_text("cert", encoding="utf-8")
            key_path.write_text("key", encoding="utf-8")
            ca_path.write_text("ca", encoding="utf-8")

            with NovaRuntime() as runtime:
                runtime.load(DECLARATIVE_PROGRAM, base_path=tmp)
                runtime.register_tenant("platform")
                runtime.select_tenant("platform")
                runtime.select_namespace("secure")
                runtime.set_trust_policy(
                    "secure-workers",
                    tenant_id="platform",
                    namespace="secure",
                    require_tls=True,
                    labels={"role": "secure"},
                    capabilities={"py"},
                )

                onboarded = runtime.onboard_worker(
                    "worker-secure",
                    "platform",
                    namespace="secure",
                    capabilities={"py"},
                    labels={"role": "secure", "namespace": "secure"},
                    certfile=str(cert_path),
                    keyfile=str(key_path),
                    cafile=str(ca_path),
                    trust_policy="secure-workers",
                )
                self.assertEqual(onboarded["worker_id"], "worker-secure")

                runtime.context.mesh.register(
                    WorkerNode(
                        worker_id="worker-secure",
                        capabilities={"py"},
                        endpoint="https://127.0.0.1:9443",
                        labels={"role": "secure", "namespace": "secure"},
                        tenant="platform",
                        tls_profile=str(onboarded["tls_profile"]),
                    )
                )

                with self.assertRaises(PermissionError):
                    runtime.context.mesh.register(
                        WorkerNode(
                            worker_id="worker-insecure",
                            capabilities={"py"},
                            endpoint="http://127.0.0.1:9555",
                            labels={"role": "open", "namespace": "secure"},
                            tenant="platform",
                        )
                    )

    def test_runtime_pki_service_fabric_and_encrypted_secret_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with NovaRuntime() as runtime:
                runtime.load(SERVICE_PROGRAM, base_path=tmp)
                assert runtime.context is not None

                runtime.create_certificate_authority("mesh-root", common_name="Nova Mesh Root")
                issued = runtime.issue_certificate("mesh-root", subject_name="worker-a", common_name="worker-a")
                onboarded = runtime.onboard_worker(
                    "worker-a",
                    "default",
                    namespace="prod",
                    capabilities={"py"},
                    labels={"namespace": "prod", "role": "worker"},
                    ca_name="mesh-root",
                    trust_policy=None,
                )
                runtime.store_secret("default", "db_password", "s3cr3t")
                runtime.scale_service("api", 3)
                discovery = runtime.discover_service("api")

                self.assertTrue(Path(issued["certfile"]).exists())
                self.assertEqual(onboarded["worker_id"], "worker-a")
                self.assertEqual(len(discovery["endpoints"]), 3)

                conn = sqlite3.connect(Path(tmp) / ".nova" / "security-plane.db")
                try:
                    row = conn.execute(
                        "SELECT secret_value FROM secrets WHERE tenant_id='default' AND secret_name='db_password'"
                    ).fetchone()
                finally:
                    conn.close()
                assert row is not None
                self.assertTrue(str(row[0]).startswith("enc:"))

    def test_runtime_service_fabric_dependencies_ingress_and_autoscaling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_pkg = Path(tmp) / "base.tar"
            api_pkg = Path(tmp) / "api.tar"
            base_pkg.write_text("base-sdk", encoding="utf-8")
            api_pkg.write_text("api-bundle", encoding="utf-8")
            program = SERVICE_FABRIC_PROGRAM_TEMPLATE.format(
                base_path=json.dumps(str(base_pkg)),
                api_path=json.dumps(str(api_pkg)),
                base_checksum=hashlib.sha256(base_pkg.read_bytes()).hexdigest(),
                api_checksum=hashlib.sha256(api_pkg.read_bytes()).hexdigest(),
            )

            with NovaRuntime() as runtime:
                runtime.load(program, base_path=tmp)
                assert runtime.context is not None

                runtime.execute_flow("boot")
                discovery = runtime.discover_service("gateway")
                autoscaled = runtime.evaluate_service_autoscaling("gateway", {"cpu": 0.95})
                traces = runtime.list_traces(limit=50)
                alerts = runtime.list_alerts()

                self.assertTrue(runtime.context.packages["base_sdk"]["installed"])
                self.assertTrue(runtime.context.packages["api_bundle"]["installed"])
                self.assertEqual(len(runtime.list_service_configs()), 1)
                self.assertEqual(len(runtime.list_service_volumes()), 1)
                self.assertEqual(len(runtime.list_service_ingress("gateway")), 1)
                self.assertIn("gateway.prod.svc.nova", discovery["dns"])
                self.assertEqual(len(discovery["ingress"]), 1)
                self.assertEqual(autoscaled["action"], "scale_out")
                self.assertEqual(autoscaled["target_replicas"], 3)
                self.assertTrue(any(trace.get("trace_id") and trace.get("correlation_id") for trace in traces))
                self.assertTrue(any(alert["name"] == "flow-fast" for alert in alerts))

    def test_agent_runtime_provider_prompt_versioning_and_governance(self) -> None:
        with NovaRuntime(command_executor=_FakeCommandExecutor()) as runtime:
            runtime.load(AGENT_GOVERNANCE_PROGRAM)
            assert runtime.context is not None

            flow_record = runtime.execute_flow("work")
            result = runtime.context.outputs["result"]

            self.assertEqual(flow_record.flow, "work")
            self.assertEqual(result["provider"], "shell")
            self.assertEqual(result["prompt_version"], "v2")
            self.assertIn(":shard:", result["memory"])

            with self.assertRaises(PermissionError):
                runtime.context.agent_runtime.execute(
                    AgentTask(agent_name="analyst", action="summarize", inputs=["x" * 1000], metadata={}),
                    runtime.context,
                )

    def test_toolchain_supports_imports_lockfiles_registry_and_ns_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shared_path = Path(tmp) / "shared.ns"
            main_path = Path(tmp) / "main.ns"
            lock_path = Path(tmp) / "nova.lock.json"
            shared_path.write_text(TOOLCHAIN_SHARED_PROGRAM, encoding="utf-8")
            main_path.write_text(TOOLCHAIN_MAIN_PROGRAM, encoding="utf-8")

            with NovaRuntime() as runtime:
                program = runtime.load(main_path.read_text(encoding="utf-8"), source_name=str(main_path), base_path=tmp)
                formatted = runtime.format_source(main_path.read_text(encoding="utf-8"))
                diagnostics = runtime.lint_source(main_path.read_text(encoding="utf-8"), source_name=str(main_path), base_path=tmp)
                symbols = runtime.toolchain_symbols(main_path.read_text(encoding="utf-8"), source_name=str(main_path), base_path=tmp)
                hover = runtime.toolchain_hover(main_path.read_text(encoding="utf-8"), 7, source_name=str(main_path), base_path=tmp)
                lock_payload = runtime.write_lockfile(lock_path)
                test_payload = runtime.run_program_tests(main_path)

                runtime.publish_toolchain_package("shared_mod", "1.0.0", shared_path)
                registry_program = """
import shared_mod@1.0.0

flow inspect {
  helper summarize shared_notes -> summary
}
""".strip()
                compiled = runtime.compile(registry_program, base_path=tmp)

                self.assertGreaterEqual(len(program.modules), 2)
                self.assertEqual(lock_payload["modules"], 2)
                self.assertTrue(lock_path.exists())
                self.assertEqual(diagnostics, [])
                self.assertTrue(any(symbol["name"] == "helper" for symbol in symbols))
                self.assertEqual(hover["kind"], "flow")
                self.assertEqual(test_payload["passed"], 1)
                self.assertTrue(any(item["name"] == "shared_mod" for item in runtime.list_toolchain_packages()))
                self.assertGreaterEqual(len(compiled.modules), 1)
                self.assertIn('import "./shared.ns"', formatted)

    def test_service_traffic_plane_supports_proxy_probes_secret_mounts_and_traffic_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with NovaRuntime() as runtime:
                runtime.load(TRAFFIC_PROGRAM, base_path=tmp)
                assert runtime.context is not None

                servers: list[http.server.ThreadingHTTPServer] = []
                threads: list[threading.Thread] = []
                try:
                    endpoints: list[str] = []
                    for body_text in ("upstream-a", "upstream-b"):
                        handler = type(f"_Handler_{body_text.replace('-', '_')}", (_TextHandler,), {"body_text": body_text})
                        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
                        thread = threading.Thread(target=server.serve_forever, daemon=True)
                        thread.start()
                        servers.append(server)
                        threads.append(thread)
                        host, port = server.server_address[:2]
                        endpoints.append(f"http://{host}:{port}")

                    service = runtime.context.service_fabric.get_service("gateway")
                    assert service is not None
                    instances = list(service["instances"])
                    runtime.context.service_fabric.update_instance(
                        "gateway",
                        instance_id=str(instances[0]["instance_id"]),
                        revision=1,
                        endpoint=endpoints[0],
                        status="running",
                        metadata=dict(instances[0]["metadata"]),
                    )
                    runtime.context.service_fabric.update_instance(
                        "gateway",
                        instance_id=str(instances[1]["instance_id"]),
                        revision=2,
                        endpoint=endpoints[1],
                        status="running",
                        metadata=dict(instances[1]["metadata"]),
                    )
                    service = runtime.context.service_fabric.get_service("gateway")
                    assert service is not None
                    runtime.context.traffic_plane.configure_service("gateway", service, secret_resolver=runtime.context.security.resolve_secret)

                    probes = runtime.probe_service_traffic("gateway")
                    shift = runtime.shift_service_traffic("gateway", {"2": 100})
                    routed = runtime.route_service_request("gateway.local", "/api")
                    proxy = runtime.start_traffic_proxy(auth_token="traffic-secret")
                    request = urllib.request.Request(
                        f'http://{proxy["host"]}:{proxy["port"]}/api',
                        headers={"Host": "gateway.local", "Authorization": "Bearer traffic-secret"},
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        proxy_body = response.read().decode("utf-8")
                    mounts = runtime.list_secret_mounts("gateway")

                    self.assertEqual(len(probes["probes"]), 2)
                    self.assertEqual(shift["weights"]["2"], 100.0)
                    self.assertIn("upstream-b", routed["body"])
                    self.assertIn("upstream-b", proxy_body)
                    self.assertEqual(len(runtime.list_traffic_routes("gateway")), 1)
                    self.assertEqual(len(runtime.list_traffic_probes("gateway")), 2)
                    self.assertEqual(len(mounts), 1)
                    self.assertTrue(mounts[0]["available"])
                finally:
                    runtime.stop_traffic_proxy()
                    for server in servers:
                        server.shutdown()
                        server.server_close()
                    for thread in threads:
                        thread.join(timeout=1.0)

    def test_ai_runtime_exposes_prompt_registry_memory_search_eval_and_tool_sandbox(self) -> None:
        with NovaRuntime(command_executor=_FakeCommandExecutor()) as runtime:
            runtime.load(AGENT_GOVERNANCE_PROGRAM)
            assert runtime.context is not None

            runtime.register_prompt_version("analyst", "v3", "Summarize with audit trail.", activate=True)
            result = runtime.context.agent_runtime.execute(
                AgentTask(agent_name="analyst", action="summarize", inputs=["hello world"], metadata={"requested_tools": ["atheria.search"]}),
                runtime.context,
            )
            prompts = runtime.list_prompt_versions("analyst")
            memory_hits = runtime.search_agent_memory("agent_mem", "provider")
            evals = runtime.list_agent_evals("analyst")

            self.assertEqual(result.data["prompt_version"], "v3")
            self.assertTrue(any(item["version"] == "v3" for item in prompts))
            self.assertGreaterEqual(len(memory_hits), 1)
            self.assertGreaterEqual(len(evals), 1)
            self.assertEqual(evals[0]["verdict"], "pass")

            with self.assertRaises(PermissionError):
                runtime.context.agent_runtime.execute(
                    AgentTask(agent_name="analyst", action="summarize", inputs=["hello"], metadata={"requested_tools": ["danger.exec"]}),
                    runtime.context,
                )

    def test_operations_support_backup_restore_failpoints_load_and_migration_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with NovaRuntime() as runtime:
                runtime.load(CONTROL_PROGRAM, base_path=tmp)
                runtime.execute_flow("queued_job")

                migrations = runtime.validate_migrations({"service_fabric": "2", "operations": "1"})
                backup = runtime.create_backup()
                runtime.set_failpoint("control.tick.after_scheduler", metadata={"message": "forced failure"})
                with self.assertRaises(RuntimeError):
                    runtime.control_tick()
                runtime.clear_failpoint("control.tick.after_scheduler")
                load_run = runtime.run_load_test("queued_job", iterations=3)
                backups = runtime.list_backups()
                restored = runtime.restore_backup(str(backup["backup_id"]))

                self.assertTrue(migrations["ok"])
                self.assertTrue(Path(backup["path"]).exists())
                self.assertGreaterEqual(load_run["throughput"], 1.0)
                self.assertGreaterEqual(len(backups), 1)
                self.assertGreaterEqual(len(restored["restored_files"]), 1)

    def test_shell_exposes_api_metrics_and_worker_trust_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                program_path = Path(tmp) / "control.ns"
                cert_path = Path(tmp) / "worker-cert.pem"
                key_path = Path(tmp) / "worker-key.pem"
                ca_path = Path(tmp) / "worker-ca.pem"
                labels_path = Path(tmp) / "labels.json"
                program_path.write_text(REPLICATION_PROGRAM, encoding="utf-8")
                cert_path.write_text("cert", encoding="utf-8")
                key_path.write_text("key", encoding="utf-8")
                ca_path.write_text("ca", encoding="utf-8")
                labels_path.write_text(json.dumps({"role": "secure", "namespace": "secure"}), encoding="utf-8")

                self.assertIsNone(shell.route(f'ns.run "{program_path}"').error)
                self.assertIsNone(shell.route("ns.auth tenant create platform Platform").error)
                self.assertIsNone(shell.route("ns.auth tenant select platform").error)
                self.assertIsNone(shell.route("ns.auth namespace select secure").error)
                self.assertIsNone(shell.route(f'ns.auth trust set secure-workers platform secure true "{labels_path}" py').error)
                self.assertIsNone(
                    shell.route(
                        f'ns.auth worker onboard worker-secure platform secure py "{labels_path}" "{cert_path}" "{key_path}" "{ca_path}" secure-workers'
                    ).error
                )

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]

                api_result = shell.route(f"ns.control api start 127.0.0.1 {port} api-secret")
                self.assertIsNone(api_result.error)
                api_payload = json.loads(api_result.output)
                self.assertTrue(api_payload["running"])

                metrics_result = shell.route("ns.control metrics prometheus")
                self.assertIsNone(metrics_result.error)
                self.assertIn("nova_runtime_metric", metrics_result.output)

                trust_result = shell.route("ns.auth trust list")
                self.assertIsNone(trust_result.error)
                self.assertIn("secure-workers", trust_result.output)

                worker_result = shell.route("ns.auth worker list platform")
                self.assertIsNone(worker_result.error)
                self.assertIn("worker-secure", worker_result.output)

                stop_result = shell.route("ns.control api stop")
                self.assertIsNone(stop_result.error)
            finally:
                shell._close_loop()

    def test_shell_runs_declarative_ns_program_and_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                path = Path(tmp) / "program.ns"
                path.write_text(DECLARATIVE_PROGRAM, encoding="utf-8")

                run_result = shell.route(f'ns.run "{path}"')
                self.assertIsNone(run_result.error)
                run_payload = json.loads(run_result.output)
                self.assertEqual(run_payload["flows"][0]["flow"], "radar")
                self.assertIn("briefing", run_payload["context"]["outputs"])

                graph_result = shell.route(f'ns.graph "{path}"')
                self.assertIsNone(graph_result.error)
                graph_payload = json.loads(graph_result.output)
                self.assertIn("graph", graph_payload)
                self.assertGreaterEqual(len(graph_payload["graph"]["nodes"]), 7)

                status_result = shell.route("ns.status")
                self.assertIsNone(status_result.error)
                status_payload = json.loads(status_result.output)
                self.assertIn("observability", status_payload["context"])
            finally:
                shell._close_loop()

    def test_shell_event_emit_reaches_loaded_declarative_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                path = Path(tmp) / "program.ns"
                path.write_text(DECLARATIVE_PROGRAM, encoding="utf-8")

                load_result = shell.route(f'ns.run "{path}"')
                self.assertIsNone(load_result.error)

                emit_result = shell.route("event emit new_information ping")
                self.assertIsNone(emit_result.error)
                self.assertIsNotNone(shell._declarative_nova)
                self.assertIn("briefing", shell._declarative_nova.context.outputs)
            finally:
                shell._close_loop()

    def test_shell_snapshot_and_resume_restore_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                path = Path(tmp) / "program.ns"
                snapshot = Path(tmp) / "runtime-snapshot.json"
                path.write_text(DECLARATIVE_PROGRAM, encoding="utf-8")

                run_result = shell.route(f'ns.run "{path}"')
                self.assertIsNone(run_result.error)

                snapshot_result = shell.route(f'ns.snapshot "{snapshot}"')
                self.assertIsNone(snapshot_result.error)
                self.assertTrue(snapshot.exists())

                resume_result = shell.route(f'ns.resume "{snapshot}"')
                self.assertIsNone(resume_result.error)
                status_result = shell.route("ns.status")
                self.assertIsNone(status_result.error)
                status_payload = json.loads(status_result.output)
                self.assertIn("briefing", status_payload["context"]["outputs"])
            finally:
                shell._close_loop()

    def test_shell_remote_mesh_worker_executes_declarative_python_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            worker_id = ""
            try:
                worker_result = shell.route("mesh start-worker --caps py")
                self.assertIsNone(worker_result.error)
                worker_payload = json.loads(worker_result.output)
                worker_id = worker_payload["worker_id"]

                path = Path(tmp) / "remote.ns"
                path.write_text(REMOTE_PROGRAM, encoding="utf-8")

                run_result = shell.route(f'ns.run "{path}"')
                self.assertIsNone(run_result.error)
                self.assertIsNotNone(shell._declarative_nova)
                self.assertEqual(shell._declarative_nova.context.states["remote_total"], 20)
                mesh_snapshot = shell._declarative_nova.context.mesh.snapshot()
                self.assertGreaterEqual(mesh_snapshot["task_count"], 1)
            finally:
                if worker_id:
                    shell.route(f"mesh stop-worker {worker_id}")
                shell._close_loop()

    def test_shell_platform_commands_manage_auth_cluster_deployments_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                program_path = Path(tmp) / "program.ns"
                program_path.write_text(DECLARATIVE_PROGRAM, encoding="utf-8")
                deploy_v1 = Path(tmp) / "deploy-v1.json"
                deploy_v2 = Path(tmp) / "deploy-v2.json"
                cert_path = Path(tmp) / "cert.pem"
                key_path = Path(tmp) / "key.pem"
                ca_path = Path(tmp) / "ca.pem"
                snapshot_path = Path(tmp) / "runtime-snapshot.json"
                deploy_v1.write_text(json.dumps({"image": "nova:v1", "replicas": 2}), encoding="utf-8")
                deploy_v2.write_text(json.dumps({"image": "nova:v2", "replicas": 3}), encoding="utf-8")
                cert_path.write_text("cert", encoding="utf-8")
                key_path.write_text("key", encoding="utf-8")
                ca_path.write_text("ca", encoding="utf-8")

                self.assertIsNone(shell.route(f'ns.run "{program_path}"').error)

                tenant_result = shell.route("ns.auth tenant create platform Platform")
                self.assertIsNone(tenant_result.error)
                token_result = shell.route("ns.auth token issue platform operator admin,ops 600")
                self.assertIsNone(token_result.error)
                token_payload = json.loads(token_result.output)
                verify_result = shell.route(f'ns.auth token verify "{token_payload["token"]}"')
                self.assertIsNone(verify_result.error)
                verify_payload = json.loads(verify_result.output)
                self.assertTrue(verify_payload["authenticated"])
                self.assertEqual(verify_payload["principal"]["tenant_id"], "platform")

                self.assertIsNone(shell.route("ns.auth secret set platform api_key super-secret").error)
                self.assertIsNone(shell.route(f'ns.auth tls set edge "{cert_path}" "{key_path}" "{ca_path}"').error)

                leader_result = shell.route("ns.cluster leader acquire edge-cluster node-a 45")
                self.assertIsNone(leader_result.error)
                leader_payload = json.loads(leader_result.output)
                self.assertTrue(leader_payload["acquired"])
                self.assertEqual(leader_payload["leader_id"], "node-a")

                self.assertIsNone(shell.route(f'ns.deploy rollout nova-app "{deploy_v1}" rolling false').error)
                self.assertIsNone(shell.route("ns.deploy promote nova-app 1").error)
                self.assertIsNone(shell.route(f'ns.deploy rollout nova-app "{deploy_v2}" rolling false').error)
                self.assertIsNone(shell.route("ns.deploy promote nova-app 2").error)
                rollback_result = shell.route("ns.deploy rollback nova-app")
                self.assertIsNone(rollback_result.error)
                rollback_payload = json.loads(rollback_result.output)
                self.assertEqual(rollback_payload["rolled_back_to"], 1)

                self.assertIsNone(shell.route(f'ns.snapshot "{snapshot_path}"').error)
                plan_result = shell.route(f'ns.recover plan restore "{snapshot_path}"')
                self.assertIsNone(plan_result.error)
                recover_result = shell.route("ns.recover run restore")
                self.assertIsNone(recover_result.error)
                recover_payload = json.loads(recover_result.output)
                self.assertEqual(recover_payload["status"], "ok")

                status_result = shell.route("ns.status")
                self.assertIsNone(status_result.error)
                status_payload = json.loads(status_result.output)
                self.assertGreaterEqual(status_payload["context"]["security"]["tenant_count"], 2)
                self.assertGreaterEqual(status_payload["context"]["cluster"]["run_count"], 1)
                self.assertIn("tls_profiles", status_payload["context"]["security"])
                self.assertIn("deployments", status_payload["context"]["cluster"])
                self.assertIn("briefing", status_payload["context"]["outputs"])
            finally:
                shell._close_loop()

    def test_shell_auth_policy_requires_login_for_operator_and_admin_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                program_path = Path(tmp) / "secure.ns"
                spec_path = Path(tmp) / "deploy.json"
                program_path.write_text(AUTH_REQUIRED_PROGRAM, encoding="utf-8")
                spec_path.write_text(json.dumps({"image": "nova:v1"}), encoding="utf-8")

                self.assertIsNone(shell.route(f'ns.run "{program_path}"').error)

                denied = shell.route("ns.deploy status")
                self.assertIsNotNone(denied.error)
                self.assertIn("operator access required", denied.error)

                admin_issue = shell.route("ns.auth token issue default bootstrap admin 600")
                self.assertIsNone(admin_issue.error)
                admin_token = json.loads(admin_issue.output)["token"]

                login_admin = shell.route(f'ns.auth login "{admin_token}"')
                self.assertIsNone(login_admin.error)

                ops_issue = shell.route("ns.auth token issue default operator ops 600")
                self.assertIsNone(ops_issue.error)
                ops_token = json.loads(ops_issue.output)["token"]

                self.assertIsNone(shell.route("ns.auth logout").error)
                login_ops = shell.route(f'ns.auth login "{ops_token}"')
                self.assertIsNone(login_ops.error)

                operator_status = shell.route("ns.deploy status")
                self.assertIsNone(operator_status.error)

                rollout_denied = shell.route(f'ns.deploy rollout nova-app "{spec_path}"')
                self.assertIsNotNone(rollout_denied.error)
                self.assertIn("admin access required", rollout_denied.error)

                self.assertIsNone(shell.route(f'ns.auth login "{admin_token}"').error)
                rollout_allowed = shell.route(f'ns.deploy rollout nova-app "{spec_path}"')
                self.assertIsNone(rollout_allowed.error)

                whoami = shell.route("ns.auth whoami")
                self.assertIsNone(whoami.error)
                whoami_payload = json.loads(whoami.output)
                self.assertTrue(whoami_payload["authenticated"])
                self.assertEqual(whoami_payload["principal"]["subject"], "bootstrap")
            finally:
                shell._close_loop()

    def test_shell_remote_mesh_worker_uses_auth_token_for_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            worker_id = ""
            try:
                worker_result = shell.route('mesh start-worker --caps py --labels role=secure --token dispatch-secret')
                self.assertIsNone(worker_result.error)
                worker_id = json.loads(worker_result.output)["worker_id"]

                path = Path(tmp) / "token-remote.ns"
                path.write_text(TOKEN_REMOTE_PROGRAM, encoding="utf-8")

                run_result = shell.route(f'ns.run "{path}"')
                self.assertIsNone(run_result.error)
                self.assertIsNotNone(shell._declarative_nova)
                self.assertEqual(shell._declarative_nova.context.states["remote_total"], 10)
                mesh_snapshot = shell._declarative_nova.context.mesh.snapshot()
                self.assertGreaterEqual(mesh_snapshot["task_count"], 1)
            finally:
                if worker_id:
                    shell.route(f"mesh stop-worker {worker_id}")
                shell._close_loop()

    def test_shell_mesh_tls_policy_filters_non_tls_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            worker_id = ""
            try:
                worker_result = shell.route('mesh start-worker --caps py --labels role=secure')
                self.assertIsNone(worker_result.error)
                worker_id = json.loads(worker_result.output)["worker_id"]

                path = Path(tmp) / "tls-remote.ns"
                path.write_text(TLS_REQUIRED_PROGRAM, encoding="utf-8")

                run_result = shell.route(f'ns.run "{path}"')
                self.assertIsNone(run_result.error)
                self.assertIsNotNone(shell._declarative_nova)
                self.assertEqual(shell._declarative_nova.context.states["remote_total"], 5)
                mesh_snapshot = shell._declarative_nova.context.mesh.snapshot()
                self.assertEqual(mesh_snapshot["task_count"], 0)
            finally:
                if worker_id:
                    shell.route(f"mesh stop-worker {worker_id}")
                shell._close_loop()

    def test_shell_control_commands_manage_queue_scheduler_and_event_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                path = Path(tmp) / "control.ns"
                path.write_text(CONTROL_PROGRAM, encoding="utf-8")

                self.assertIsNone(shell.route(f'ns.run "{path}"').error)

                enqueue_result = shell.route("ns.control queue enqueue queued_job")
                self.assertIsNone(enqueue_result.error)

                run_result = shell.route("ns.control queue run")
                self.assertIsNone(run_result.error)
                run_payload = json.loads(run_result.output)
                self.assertEqual(run_payload["processed_count"], 1)

                schedule_result = shell.route("ns.control schedule add-flow job1 queued_job 0")
                self.assertIsNone(schedule_result.error)

                tick_result = shell.route("ns.control daemon tick 4")
                self.assertIsNone(tick_result.error)
                tick_payload = json.loads(tick_result.output)
                self.assertGreaterEqual(tick_payload["scheduler"]["jobs_enqueued"], 1)

                self.assertIsNone(shell.route("event emit ping now").error)
                events_result = shell.route("ns.control events ping 0 10")
                self.assertIsNone(events_result.error)
                events_payload = json.loads(events_result.output)
                self.assertTrue(any(item["event_name"] == "ping" for item in events_payload["events"]))

                status_result = shell.route("ns.control status")
                self.assertIsNone(status_result.error)
                status_payload = json.loads(status_result.output)
                self.assertGreaterEqual(status_payload["event_count"], 1)
                self.assertGreaterEqual(status_payload["schedule_count"], 1)
            finally:
                shell._close_loop()

    def test_shell_blue_green_rollout_health_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = NovaShell()
            try:
                program_path = Path(tmp) / "program.ns"
                metrics_path = Path(tmp) / "health.json"
                deploy_v1 = Path(tmp) / "deploy-v1.json"
                deploy_v2 = Path(tmp) / "deploy-v2.json"
                program_path.write_text(DECLARATIVE_PROGRAM, encoding="utf-8")
                metrics_path.write_text(json.dumps({"error_rate": 0.01}), encoding="utf-8")
                deploy_v1.write_text(json.dumps({"image": "nova:v1"}), encoding="utf-8")
                deploy_v2.write_text(json.dumps({"image": "nova:v2"}), encoding="utf-8")

                self.assertIsNone(shell.route(f'ns.run "{program_path}"').error)
                self.assertIsNone(shell.route(f'ns.deploy rollout svc "{deploy_v1}" rolling true').error)
                self.assertIsNone(shell.route(f'ns.deploy rollout svc "{deploy_v2}" blue_green false').error)
                self.assertIsNone(shell.route(f'ns.deploy health svc 2 green healthy "{metrics_path}"').error)

                evaluate_result = shell.route("ns.deploy evaluate svc 2")
                self.assertIsNone(evaluate_result.error)
                evaluate_payload = json.loads(evaluate_result.output)
                self.assertEqual(evaluate_payload["evaluation"]["action"], "promote")
                self.assertEqual(evaluate_payload["active_revision"], 2)
            finally:
                shell._close_loop()


if __name__ == "__main__":
    unittest.main()
