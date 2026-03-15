from __future__ import annotations

import http.server
import json
import threading
import urllib.parse
from typing import Any


class NovaControlPlaneAPIServer:
    """Small HTTP control-plane API for Nova runtime administration."""

    def __init__(self, runtime: Any, *, host: str, port: int, auth_token: str | None = None) -> None:
        self.runtime = runtime
        self.host = host
        self.port = int(port)
        self.auth_token = auth_token
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        runtime = self.runtime
        auth_token = self.auth_token

        class Handler(http.server.BaseHTTPRequestHandler):
            def _write_json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _write_text(self, text: str, status: int = 200, content_type: str = "text/plain; version=0.0.4") -> None:
                body = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                if not auth_token:
                    return True
                return str(self.headers.get("Authorization") or "") == f"Bearer {auth_token}"

            def _json_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(body.decode("utf-8"))
                    return payload if isinstance(payload, dict) else {}
                except Exception:
                    return {}

            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._write_json({"error": "unauthorized"}, status=401)
                    return
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                try:
                    if parsed.path in {"/", "/health"}:
                        self._write_json({"status": "ok", "api": runtime.control_api_status()})
                        return
                    if parsed.path == "/status":
                        self._write_json(runtime.control_status())
                        return
                    if parsed.path == "/metrics/prometheus":
                        self._write_text(str(runtime.export_metrics("prometheus")))
                        return
                    if parsed.path == "/metrics/otlp":
                        self._write_json(runtime.export_metrics("otlp"))
                        return
                    if parsed.path == "/traces":
                        trace_id = params.get("trace_id", [None])[0]
                        limit = int(params.get("limit", ["100"])[0])
                        self._write_json({"traces": runtime.list_traces(limit=limit, trace_id=trace_id)})
                        return
                    if parsed.path == "/alerts":
                        self._write_json({"alerts": runtime.list_alerts()})
                        return
                    if parsed.path == "/queue":
                        queue_name = params.get("queue", [None])[0]
                        status = params.get("status", [None])[0]
                        limit = int(params.get("limit", ["50"])[0])
                        self._write_json({"tasks": runtime.list_queue_tasks(queue_name=queue_name, status=status, limit=limit)})
                        return
                    if parsed.path == "/schedules":
                        limit = int(params.get("limit", ["50"])[0])
                        self._write_json({"schedules": runtime.list_schedules(limit=limit)})
                        return
                    if parsed.path == "/events":
                        event_name = params.get("event_name", [None])[0]
                        since = int(params.get("since_sequence", ["0"])[0])
                        limit = int(params.get("limit", ["100"])[0])
                        self._write_json({"events": runtime.replay_event_log(event_name=event_name, since_sequence=since, limit=limit)})
                        return
                    if parsed.path == "/state":
                        tenant_id = params.get("tenant", [None])[0]
                        namespace = params.get("namespace", [None])[0]
                        key = params.get("key", [None])[0]
                        if key:
                            rows = runtime.list_state(tenant_id=tenant_id, namespace=namespace, limit=1000)
                            row = next((item for item in rows if item.get("key") == key), None)
                            self._write_json({"state": row})
                            return
                        limit = int(params.get("limit", ["200"])[0])
                        self._write_json({"states": runtime.list_state(tenant_id=tenant_id, namespace=namespace, limit=limit)})
                        return
                    if parsed.path == "/workflows":
                        flow_name = params.get("flow", [None])[0]
                        limit = int(params.get("limit", ["100"])[0])
                        self._write_json({"runs": runtime.list_workflow_runs(flow_name=flow_name, limit=limit)})
                        return
                    if parsed.path == "/replication/peers":
                        self._write_json({"peers": runtime.list_replica_peers()})
                        return
                    if parsed.path == "/replication/records":
                        since = int(params.get("since_sequence", ["0"])[0])
                        limit = int(params.get("limit", ["100"])[0])
                        record_type = params.get("record_type", [None])[0]
                        self._write_json({"records": runtime.list_replicated_records(since_sequence=since, record_type=record_type, limit=limit)})
                        return
                    if parsed.path == "/consensus/status":
                        self._write_json(runtime.consensus_status())
                        return
                    if parsed.path == "/consensus/peers":
                        self._write_json({"peers": runtime.list_consensus_peers()})
                        return
                    if parsed.path == "/consensus/log":
                        since = int(params.get("since_index", ["0"])[0])
                        limit = int(params.get("limit", ["100"])[0])
                        self._write_json({"entries": runtime.consensus_log(since_index=since, limit=limit)})
                        return
                    if parsed.path == "/consensus/snapshot":
                        self._write_json({"snapshot": runtime.consensus_snapshot()})
                        return
                    if parsed.path == "/services":
                        self._write_json({"services": runtime.list_services()})
                        return
                    if parsed.path == "/services/discover":
                        service_name = str(params.get("service", [""])[0])
                        tenant_id = params.get("tenant", [None])[0]
                        namespace = params.get("namespace", [None])[0]
                        self._write_json(runtime.discover_service(service_name, tenant_id=tenant_id, namespace=namespace))
                        return
                    if parsed.path == "/services/ingress":
                        service_name = params.get("service", [None])[0]
                        self._write_json({"ingress": runtime.list_service_ingress(service_name)})
                        return
                    if parsed.path == "/services/configs":
                        self._write_json({"configs": runtime.list_service_configs()})
                        return
                    if parsed.path == "/services/volumes":
                        self._write_json({"volumes": runtime.list_service_volumes()})
                        return
                    if parsed.path == "/traffic/routes":
                        service_name = params.get("service", [None])[0]
                        self._write_json({"routes": runtime.list_traffic_routes(service_name)})
                        return
                    if parsed.path == "/traffic/probes":
                        service_name = params.get("service", [None])[0]
                        self._write_json({"probes": runtime.list_traffic_probes(service_name)})
                        return
                    if parsed.path == "/traffic/mounts":
                        service_name = params.get("service", [None])[0]
                        self._write_json({"mounts": runtime.list_secret_mounts(service_name)})
                        return
                    if parsed.path == "/traffic/proxy":
                        self._write_json(runtime.traffic_proxy_status())
                        return
                    if parsed.path == "/toolchain/packages":
                        self._write_json({"packages": runtime.list_toolchain_packages()})
                        return
                    if parsed.path == "/agents/prompts":
                        agent_name = str(params.get("agent", [""])[0])
                        self._write_json({"prompts": runtime.list_prompt_versions(agent_name)})
                        return
                    if parsed.path == "/agents/evals":
                        agent_name = params.get("agent", [None])[0]
                        limit = int(params.get("limit", ["20"])[0])
                        self._write_json({"evaluations": runtime.list_agent_evals(agent_name, limit=limit)})
                        return
                    if parsed.path == "/agents/memory":
                        scope = str(params.get("scope", [""])[0])
                        query = str(params.get("query", [""])[0])
                        limit = int(params.get("limit", ["5"])[0])
                        self._write_json({"matches": runtime.search_agent_memory(scope, query, top_k=limit)})
                        return
                    if parsed.path == "/operations/backups":
                        self._write_json({"backups": runtime.list_backups()})
                        return
                    if parsed.path == "/operations/failpoints":
                        self._write_json({"failpoints": runtime.list_failpoints()})
                        return
                    if parsed.path == "/packages":
                        self._write_json({"packages": runtime.list_packages()})
                        return
                    if parsed.path == "/executors":
                        self._write_json(runtime.executor_status())
                        return
                    if parsed.path == "/executors/stream":
                        backend = str(params.get("backend", [""])[0])
                        request_id = str(params.get("request_id", [""])[0])
                        self._write_json(runtime.stream_executor_request(backend, request_id))
                        return
                except Exception as exc:
                    self._write_json({"error": str(exc)}, status=500)
                    return
                self._write_json({"error": "not found"}, status=404)

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._write_json({"error": "unauthorized"}, status=401)
                    return
                parsed = urllib.parse.urlparse(self.path)
                payload = self._json_body()
                try:
                    if parsed.path == "/queue/enqueue":
                        self._write_json(
                            runtime.enqueue_flow(
                                str(payload.get("flow") or ""),
                                payload=payload.get("payload"),
                                queue_name=str(payload.get("queue_name") or "default"),
                                priority=int(payload.get("priority") or 100),
                                max_attempts=int(payload.get("max_attempts") or 3),
                                base_backoff_seconds=float(payload.get("base_backoff_seconds") or 5.0),
                                backoff_multiplier=float(payload.get("backoff_multiplier") or 2.0),
                                max_backoff_seconds=float(payload.get("max_backoff_seconds") or 300.0),
                            )
                        )
                        return
                    if parsed.path == "/queue/run":
                        self._write_json(runtime.run_pending_tasks(queue_name=payload.get("queue_name"), limit=int(payload.get("limit") or 10)))
                        return
                    if parsed.path == "/schedules/flow":
                        self._write_json(
                            runtime.schedule_flow(
                                str(payload.get("job_name") or ""),
                                str(payload.get("flow") or ""),
                                interval_seconds=float(payload["interval_seconds"]) if payload.get("interval_seconds") is not None else None,
                                once_at=float(payload["once_at"]) if payload.get("once_at") is not None else None,
                                queue_name=str(payload.get("queue_name") or "default"),
                                payload=payload.get("payload"),
                            )
                        )
                        return
                    if parsed.path == "/schedules/event":
                        self._write_json(
                            runtime.schedule_event(
                                str(payload.get("job_name") or ""),
                                str(payload.get("event") or ""),
                                interval_seconds=float(payload["interval_seconds"]) if payload.get("interval_seconds") is not None else None,
                                once_at=float(payload["once_at"]) if payload.get("once_at") is not None else None,
                                queue_name=str(payload.get("queue_name") or "default"),
                                payload=payload.get("payload"),
                            )
                        )
                        return
                    if parsed.path == "/replication/peers":
                        self._write_json(
                            runtime.register_replica_peer(
                                str(payload.get("peer_name") or ""),
                                str(payload.get("endpoint") or ""),
                                auth_token=str(payload.get("auth_token")) if payload.get("auth_token") else None,
                                tls_profile=str(payload.get("tls_profile")) if payload.get("tls_profile") else None,
                                enabled=bool(payload.get("enabled", True)),
                                metadata=dict(payload.get("metadata") or {}),
                            )
                        )
                        return
                    if parsed.path == "/replication/apply":
                        self._write_json(runtime.apply_replica_record(payload))
                        return
                    if parsed.path == "/consensus/request-vote":
                        self._write_json(runtime.consensus_request_vote(payload))
                        return
                    if parsed.path == "/consensus/append":
                        self._write_json(runtime.consensus_append_entries(payload))
                        return
                    if parsed.path == "/consensus/election":
                        self._write_json(runtime.start_consensus_election())
                        return
                    if parsed.path == "/consensus/heartbeat":
                        self._write_json(runtime.send_consensus_heartbeats())
                        return
                    if parsed.path == "/consensus/compact":
                        self._write_json(runtime.compact_consensus_log())
                        return
                    if parsed.path == "/consensus/snapshot":
                        self._write_json(runtime.install_consensus_snapshot(dict(payload.get("snapshot") or payload)))
                        return
                    if parsed.path == "/consensus/peers":
                        self._write_json(
                            runtime.register_consensus_peer(
                                str(payload.get("peer_name") or ""),
                                str(payload.get("endpoint") or ""),
                                auth_token=str(payload.get("auth_token")) if payload.get("auth_token") else None,
                                tls_profile=str(payload.get("tls_profile")) if payload.get("tls_profile") else None,
                                voter=bool(payload.get("voter", True)),
                                active=bool(payload.get("active", True)),
                                metadata=dict(payload.get("metadata") or {}),
                            )
                        )
                        return
                    if parsed.path == "/consensus/peers/remove":
                        self._write_json(runtime.remove_consensus_peer(str(payload.get("peer_name") or "")))
                        return
                    if parsed.path == "/services/deploy":
                        self._write_json(runtime.deploy_service(str(payload.get("service") or "")))
                        return
                    if parsed.path == "/services/scale":
                        self._write_json(runtime.scale_service(str(payload.get("service") or ""), int(payload.get("replicas") or 1)))
                        return
                    if parsed.path == "/services/autoscale":
                        self._write_json(runtime.evaluate_service_autoscaling(str(payload.get("service") or ""), dict(payload.get("metrics") or {})))
                        return
                    if parsed.path == "/traffic/probe":
                        self._write_json(runtime.probe_service_traffic(str(payload.get("service") or "")))
                        return
                    if parsed.path == "/traffic/shift":
                        self._write_json(runtime.shift_service_traffic(str(payload.get("service") or ""), dict(payload.get("weights") or {})))
                        return
                    if parsed.path == "/traffic/route":
                        body = payload.get("body")
                        body_bytes = body.encode("utf-8") if isinstance(body, str) else None
                        self._write_json(
                            runtime.route_service_request(
                                str(payload.get("host") or ""),
                                str(payload.get("path") or "/"),
                                method=str(payload.get("method") or "GET"),
                                body=body_bytes,
                                headers=dict(payload.get("headers") or {}),
                            )
                        )
                        return
                    if parsed.path == "/traffic/proxy/start":
                        self._write_json(
                            runtime.start_traffic_proxy(
                                host=str(payload.get("host") or "127.0.0.1"),
                                port=int(payload.get("port") or 0),
                                auth_token=str(payload.get("auth_token")) if payload.get("auth_token") else None,
                            )
                        )
                        return
                    if parsed.path == "/traffic/proxy/stop":
                        self._write_json(runtime.stop_traffic_proxy())
                        return
                    if parsed.path == "/toolchain/packages/publish":
                        self._write_json(
                            runtime.publish_toolchain_package(
                                str(payload.get("name") or ""),
                                str(payload.get("version") or ""),
                                str(payload.get("entrypoint") or ""),
                                checksum=str(payload.get("checksum")) if payload.get("checksum") else None,
                                metadata=dict(payload.get("metadata") or {}),
                            )
                        )
                        return
                    if parsed.path == "/agents/prompts":
                        self._write_json(
                            runtime.register_prompt_version(
                                str(payload.get("agent") or ""),
                                str(payload.get("version") or ""),
                                str(payload.get("prompt") or ""),
                                activate=bool(payload.get("activate", False)),
                            )
                        )
                        return
                    if parsed.path == "/operations/backup":
                        self._write_json(runtime.create_backup())
                        return
                    if parsed.path == "/operations/restore":
                        self._write_json(runtime.restore_backup(str(payload.get("backup_id") or "")))
                        return
                    if parsed.path == "/operations/failpoints":
                        self._write_json(
                            runtime.set_failpoint(
                                str(payload.get("name") or ""),
                                str(payload.get("action") or "raise"),
                                metadata=dict(payload.get("metadata") or {}),
                            )
                        )
                        return
                    if parsed.path == "/operations/failpoints/clear":
                        self._write_json(runtime.clear_failpoint(str(payload.get("name") or "")))
                        return
                    if parsed.path == "/operations/load":
                        self._write_json(runtime.run_load_test(str(payload.get("flow") or ""), iterations=int(payload.get("iterations") or 10)))
                        return
                    if parsed.path == "/operations/migrations":
                        self._write_json(runtime.validate_migrations(dict(payload.get("expected") or {})))
                        return
                    if parsed.path == "/packages/install":
                        self._write_json(runtime.install_package(str(payload.get("package") or "")))
                        return
                    if parsed.path == "/executors/restart":
                        self._write_json(runtime.restart_executor_backend(str(payload.get("backend") or "")))
                        return
                    if parsed.path == "/executors/stop":
                        self._write_json(runtime.stop_executor_backend(str(payload.get("backend") or "")))
                        return
                    if parsed.path == "/executors/cancel":
                        self._write_json(runtime.cancel_executor_request(str(payload.get("backend") or ""), str(payload.get("request_id") or "")))
                        return
                    if parsed.path == "/workflows/replay":
                        self._write_json(runtime.replay_workflow_run(str(payload.get("run_id") or "")))
                        return
                    if parsed.path == "/snapshot/validate":
                        self._write_json(runtime.validate_snapshot_file(str(payload.get("file") or "")))
                        return
                except Exception as exc:
                    self._write_json({"error": str(exc)}, status=500)
                    return
                self._write_json({"error": "not found"}, status=404)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._server = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="NovaControlAPI", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._server = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._server is not None and self._thread is not None and self._thread.is_alive(),
            "host": self.host,
            "port": self.port,
            "auth_required": self.auth_token is not None,
        }
