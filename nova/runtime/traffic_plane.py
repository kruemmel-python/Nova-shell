from __future__ import annotations

import http.server
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .service_fabric import ServiceFabric


class ServiceTrafficPlane:
    """Traffic-plane services for ingress routing, health probing and rollouts."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "traffic-plane.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._proxy_server: http.server.ThreadingHTTPServer | None = None
        self._proxy_thread: threading.Thread | None = None
        self._proxy_token: str | None = None
        self._round_robin: dict[str, int] = {}
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traffic_routes (
                    service_name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    path TEXT NOT NULL,
                    target_port INTEGER,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (service_name, host, path)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traffic_probes (
                    service_name TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    latency_ms REAL,
                    error TEXT,
                    checked_at REAL NOT NULL,
                    PRIMARY KEY (service_name, instance_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traffic_shifts (
                    service_name TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    weight REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (service_name, revision)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secret_mounts (
                    service_name TEXT NOT NULL,
                    mount_path TEXT NOT NULL,
                    secret_name TEXT NOT NULL,
                    available INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (service_name, mount_path)
                )
                """
            )

    def close(self) -> None:
        self.stop_proxy()
        with self._lock:
            self._conn.close()

    def configure_service(
        self,
        service_name: str,
        service: dict[str, Any],
        *,
        secret_resolver: Any | None = None,
    ) -> dict[str, Any]:
        tenant_id = str(service.get("tenant") or "default")
        ingress = service.get("ingress") or []
        if isinstance(ingress, list):
            for item in ingress:
                if not isinstance(item, dict):
                    continue
                self.register_route(
                    service_name,
                    host=str(item.get("host") or ""),
                    path=str(item.get("path") or "/"),
                    target_port=int(item["target_port"]) if item.get("target_port") is not None else None,
                    metadata=dict(item.get("metadata") or {}),
                )
        mounts = service.get("secret_mounts") or {}
        if isinstance(mounts, dict):
            mount_items = [{"mount_path": key, "secret_name": value} for key, value in mounts.items()]
        elif isinstance(mounts, list):
            mount_items = [item for item in mounts if isinstance(item, dict)]
        else:
            mount_items = []
        for item in mount_items:
            secret_name = str(item.get("secret_name") or item.get("secret") or "")
            mount_path = str(item.get("mount_path") or item.get("mount") or "")
            if not secret_name or not mount_path:
                continue
            resolved = secret_resolver(tenant_id, secret_name) if callable(secret_resolver) else None
            self.register_secret_mount(
                service_name,
                mount_path=mount_path,
                secret_name=secret_name,
                available=resolved is not None,
                metadata={"tenant": tenant_id, **dict(item.get("metadata") or {})},
            )
        revisions = {str(item.get("revision")) for item in service.get("instances", []) if item.get("revision") is not None}
        if revisions and not self.traffic_weights(service_name):
            weight = round(100.0 / max(len(revisions), 1), 4)
            self.set_traffic_shift(service_name, {revision: weight for revision in revisions})
        return {"service_name": service_name, "routes": self.list_routes(service_name), "secret_mounts": self.list_secret_mounts(service_name)}

    def register_route(
        self,
        service_name: str,
        *,
        host: str,
        path: str = "/",
        target_port: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO traffic_routes(service_name, host, path, target_port, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name, host, path) DO UPDATE SET
                    target_port=excluded.target_port,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (service_name, host, path, target_port, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return {"service_name": service_name, "host": host, "path": path, "target_port": target_port, "metadata": metadata or {}}

    def register_secret_mount(
        self,
        service_name: str,
        *,
        mount_path: str,
        secret_name: str,
        available: bool,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO secret_mounts(service_name, mount_path, secret_name, available, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name, mount_path) DO UPDATE SET
                    secret_name=excluded.secret_name,
                    available=excluded.available,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (service_name, mount_path, secret_name, 1 if available else 0, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
        return {"service_name": service_name, "mount_path": mount_path, "secret_name": secret_name, "available": available, "metadata": metadata or {}}

    def list_routes(self, service_name: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT service_name, host, path, target_port, metadata_json, created_at, updated_at FROM traffic_routes"
        params: tuple[Any, ...] = ()
        if service_name:
            query += " WHERE service_name=?"
            params = (service_name,)
        query += " ORDER BY service_name, host, path"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "service_name": row[0],
                "host": row[1],
                "path": row[2],
                "target_port": row[3],
                "metadata": json.loads(row[4]),
                "created_at": row[5],
                "updated_at": row[6],
            }
            for row in rows
        ]

    def list_probes(self, service_name: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT service_name, instance_id, endpoint, status, http_status, latency_ms, error, checked_at FROM traffic_probes"
        params: tuple[Any, ...] = ()
        if service_name:
            query += " WHERE service_name=?"
            params = (service_name,)
        query += " ORDER BY service_name, checked_at DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "service_name": row[0],
                "instance_id": row[1],
                "endpoint": row[2],
                "status": row[3],
                "http_status": row[4],
                "latency_ms": row[5],
                "error": row[6],
                "checked_at": row[7],
            }
            for row in rows
        ]

    def list_secret_mounts(self, service_name: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT service_name, mount_path, secret_name, available, metadata_json, updated_at FROM secret_mounts"
        params: tuple[Any, ...] = ()
        if service_name:
            query += " WHERE service_name=?"
            params = (service_name,)
        query += " ORDER BY service_name, mount_path"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "service_name": row[0],
                "mount_path": row[1],
                "secret_name": row[2],
                "available": bool(row[3]),
                "metadata": json.loads(row[4]),
                "updated_at": row[5],
            }
            for row in rows
        ]

    def set_traffic_shift(self, service_name: str, weights: dict[str, float | int]) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM traffic_shifts WHERE service_name=?", (service_name,))
            for revision, weight in weights.items():
                self._conn.execute(
                    "INSERT INTO traffic_shifts(service_name, revision, weight, updated_at) VALUES(?, ?, ?, ?)",
                    (service_name, str(revision), float(weight), now),
                )
        return {"service_name": service_name, "weights": self.traffic_weights(service_name)}

    def traffic_weights(self, service_name: str) -> dict[str, float]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT revision, weight FROM traffic_shifts WHERE service_name=? ORDER BY revision",
                (service_name,),
            ).fetchall()
        return {str(row[0]): float(row[1]) for row in rows}

    def probe_service(self, service: dict[str, Any], *, timeout_seconds: float = 2.0) -> dict[str, Any]:
        service_name = str(service.get("name") or service.get("service_name") or "")
        results: list[dict[str, Any]] = []
        path = str(service.get("health_path") or "/")
        for instance in service.get("instances", []):
            endpoint = str(instance.get("endpoint") or "")
            started = time.perf_counter()
            status = "healthy"
            http_status = 200
            error: str | None = None
            if endpoint.startswith("http://") or endpoint.startswith("https://"):
                request = urllib.request.Request(endpoint.rstrip("/") + path, headers={"User-Agent": "nova-traffic-plane"})
                try:
                    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                        http_status = int(response.status)
                        status = "healthy" if response.status < 500 else "unhealthy"
                except urllib.error.HTTPError as exc:
                    http_status = int(exc.code)
                    status = "unhealthy"
                    error = str(exc)
                except Exception as exc:
                    http_status = 0
                    status = "unhealthy"
                    error = str(exc)
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._record_probe(service_name, str(instance.get("instance_id") or ""), endpoint, status, http_status=http_status, latency_ms=latency_ms, error=error)
            results.append(
                {
                    "service_name": service_name,
                    "instance_id": instance.get("instance_id"),
                    "endpoint": endpoint,
                    "status": status,
                    "http_status": http_status,
                    "latency_ms": latency_ms,
                    "error": error,
                }
            )
        return {"service_name": service_name, "probes": results}

    def route(
        self,
        service_fabric: ServiceFabric,
        *,
        host: str,
        path: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        route = self._match_route(host, path)
        if route is None:
            raise ValueError(f"no route for host={host!r} path={path!r}")
        service = service_fabric.get_service(str(route["service_name"]))
        if service is None:
            raise ValueError(f"unknown service '{route['service_name']}'")
        instance = self._select_instance(service)
        if instance is None:
            raise RuntimeError(f"no healthy instances for service '{route['service_name']}'")
        endpoint = str(instance.get("endpoint") or "")
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            target = endpoint.rstrip("/") + path
            request = urllib.request.Request(
                target,
                data=body,
                method=method,
                headers={**(headers or {}), "Host": host, "User-Agent": "nova-traffic-proxy"},
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
                return {
                    "service_name": route["service_name"],
                    "instance_id": instance["instance_id"],
                    "endpoint": endpoint,
                    "status_code": int(response.status),
                    "headers": dict(response.headers.items()),
                    "body": payload.decode("utf-8", errors="replace"),
                }
        payload = {
            "service_name": route["service_name"],
            "instance_id": instance["instance_id"],
            "endpoint": endpoint,
            "path": path,
            "message": "fabric endpoint routed without external upstream",
        }
        return {"service_name": route["service_name"], "instance_id": instance["instance_id"], "endpoint": endpoint, "status_code": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(payload, ensure_ascii=False)}

    def start_proxy(self, service_fabric: ServiceFabric, *, host: str = "127.0.0.1", port: int = 0, auth_token: str | None = None) -> dict[str, Any]:
        self.stop_proxy()
        plane = self
        self._proxy_token = auth_token

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self._proxy()

            def do_POST(self) -> None:  # noqa: N802
                self._proxy()

            def _proxy(self) -> None:
                if plane._proxy_token is not None and self.headers.get("Authorization") != f"Bearer {plane._proxy_token}":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b"unauthorized")
                    return
                body = None
                content_length = self.headers.get("Content-Length")
                if content_length:
                    body = self.rfile.read(int(content_length))
                try:
                    payload = plane.route(
                        service_fabric,
                        host=self.headers.get("Host", ""),
                        path=self.path,
                        method=self.command,
                        body=body,
                        headers={key: value for key, value in self.headers.items()},
                    )
                except Exception as exc:
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"))
                    return
                self.send_response(int(payload.get("status_code") or 200))
                for key, value in dict(payload.get("headers") or {}).items():
                    if key.lower() in {"content-length", "transfer-encoding", "connection"}:
                        continue
                    self.send_header(str(key), str(value))
                self.end_headers()
                self.wfile.write(str(payload.get("body") or "").encode("utf-8"))

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._proxy_server = http.server.ThreadingHTTPServer((host, port), _Handler)
        self._proxy_thread = threading.Thread(target=self._proxy_server.serve_forever, name="nova-traffic-proxy", daemon=True)
        self._proxy_thread.start()
        return self.proxy_status()

    def stop_proxy(self) -> dict[str, Any]:
        if self._proxy_server is not None:
            self._proxy_server.shutdown()
            self._proxy_server.server_close()
            self._proxy_server = None
        if self._proxy_thread is not None:
            self._proxy_thread.join(timeout=2.0)
            self._proxy_thread = None
        self._proxy_token = None
        return self.proxy_status()

    def proxy_status(self) -> dict[str, Any]:
        if self._proxy_server is None:
            return {"running": False}
        host, port = self._proxy_server.server_address[:2]
        return {"running": True, "host": host, "port": int(port), "auth": self._proxy_token is not None}

    def snapshot(self) -> dict[str, Any]:
        return {
            "route_count": len(self.list_routes()),
            "probe_count": len(self.list_probes()),
            "secret_mount_count": len(self.list_secret_mounts()),
            "routes": self.list_routes(),
            "probes": self.list_probes(),
            "secret_mounts": self.list_secret_mounts(),
            "proxy": self.proxy_status(),
        }

    def _record_probe(
        self,
        service_name: str,
        instance_id: str,
        endpoint: str,
        status: str,
        *,
        http_status: int | None,
        latency_ms: float | None,
        error: str | None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO traffic_probes(service_name, instance_id, endpoint, status, http_status, latency_ms, error, checked_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name, instance_id) DO UPDATE SET
                    endpoint=excluded.endpoint,
                    status=excluded.status,
                    http_status=excluded.http_status,
                    latency_ms=excluded.latency_ms,
                    error=excluded.error,
                    checked_at=excluded.checked_at
                """,
                (service_name, instance_id, endpoint, status, http_status, latency_ms, error, time.time()),
            )

    def _match_route(self, host: str, path: str) -> dict[str, Any] | None:
        candidates = [item for item in self.list_routes() if item["host"] == host and path.startswith(str(item.get("path") or "/"))]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: len(str(item.get("path") or "/")), reverse=True)[0]

    def _select_instance(self, service: dict[str, Any]) -> dict[str, Any] | None:
        service_name = str(service.get("name") or service.get("service_name") or "")
        healthy = self._healthy_instances(service)
        if not healthy:
            healthy = [item for item in service.get("instances", []) if item.get("status") == "running"]
        if not healthy:
            return None
        weighted = self._apply_weights(service_name, healthy)
        index = self._round_robin.get(service_name, 0) % len(weighted)
        self._round_robin[service_name] = index + 1
        return weighted[index]

    def _healthy_instances(self, service: dict[str, Any]) -> list[dict[str, Any]]:
        probes = {(item["service_name"], item["instance_id"]): item for item in self.list_probes(str(service.get("name") or service.get("service_name") or ""))}
        instances: list[dict[str, Any]] = []
        for instance in service.get("instances", []):
            key = (str(service.get("name") or service.get("service_name") or ""), str(instance.get("instance_id") or ""))
            probe = probes.get(key)
            if (probe is None or probe.get("status") == "healthy") and instance.get("status") == "running":
                instances.append(instance)
        return instances

    def _apply_weights(self, service_name: str, instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
        weights = self.traffic_weights(service_name)
        if not weights:
            return list(instances)
        weighted: list[dict[str, Any]] = []
        for instance in instances:
            revision = str(instance.get("revision") or "")
            configured = float(weights.get(revision, 0.0))
            if configured <= 0.0:
                continue
            weight = max(1, int(round(configured)))
            weighted.extend([instance] * weight)
        return weighted or list(instances)
