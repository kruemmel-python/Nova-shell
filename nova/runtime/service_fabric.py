from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class ServiceFabric:
    """Persistent package, service, and instance registry for Nova OS resources."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "service-fabric.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS packages (
                    package_name TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    installed INTEGER NOT NULL,
                    installed_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS services (
                    service_name TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    desired_replicas INTEGER NOT NULL,
                    active_revision INTEGER,
                    rollout_json TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_instances (
                    instance_id TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    revision INTEGER,
                    endpoint TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fabric_configs (
                    config_name TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fabric_volumes (
                    volume_name TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_ingress (
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

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def register_config(self, config_name: str, data: dict[str, Any], *, tenant_id: str, namespace: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO fabric_configs(config_name, tenant_id, namespace, data_json, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(config_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    data_json=excluded.data_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (config_name, tenant_id, namespace, json.dumps(data, ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return self.get_config(config_name) or {"name": config_name}

    def get_config(self, config_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT config_name, tenant_id, namespace, data_json, metadata_json, created_at, updated_at
                FROM fabric_configs
                WHERE config_name=?
                """,
                (config_name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "name": row[0],
            "tenant": row[1],
            "namespace": row[2],
            "data": json.loads(row[3]),
            "metadata": json.loads(row[4]),
            "created_at": row[5],
            "updated_at": row[6],
        }

    def list_configs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT config_name FROM fabric_configs ORDER BY config_name").fetchall()
        return [self.get_config(str(row[0])) for row in rows if self.get_config(str(row[0])) is not None]

    def register_volume(self, volume_name: str, spec: dict[str, Any], *, tenant_id: str, namespace: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO fabric_volumes(volume_name, tenant_id, namespace, spec_json, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(volume_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    spec_json=excluded.spec_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (volume_name, tenant_id, namespace, json.dumps(spec, ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return self.get_volume(volume_name) or {"name": volume_name}

    def get_volume(self, volume_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT volume_name, tenant_id, namespace, spec_json, metadata_json, created_at, updated_at
                FROM fabric_volumes
                WHERE volume_name=?
                """,
                (volume_name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "name": row[0],
            "tenant": row[1],
            "namespace": row[2],
            "spec": json.loads(row[3]),
            "metadata": json.loads(row[4]),
            "created_at": row[5],
            "updated_at": row[6],
        }

    def list_volumes(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT volume_name FROM fabric_volumes ORDER BY volume_name").fetchall()
        return [self.get_volume(str(row[0])) for row in rows if self.get_volume(str(row[0])) is not None]

    def register_ingress(
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
                INSERT INTO service_ingress(service_name, host, path, target_port, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name, host, path) DO UPDATE SET
                    target_port=excluded.target_port,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (service_name, host, path, target_port, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return {"service_name": service_name, "host": host, "path": path, "target_port": target_port, "metadata": metadata or {}, "updated_at": now}

    def list_ingress(self, service_name: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT service_name, host, path, target_port, metadata_json, created_at, updated_at
            FROM service_ingress
        """
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

    def resolve_package_dependencies(self, package_name: str, *, _seen: set[str] | None = None) -> list[str]:
        package = self.get_package(package_name)
        if package is None:
            raise ValueError(f"unknown package '{package_name}'")
        seen = _seen or set()
        if package_name in seen:
            return []
        seen.add(package_name)
        dependencies = [str(item) for item in package.get("dependencies", []) if str(item)]
        ordered: list[str] = []
        for dependency in dependencies:
            ordered.extend(self.resolve_package_dependencies(dependency, _seen=seen))
            ordered.append(dependency)
        deduped: list[str] = []
        for item in ordered:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def verify_package_signature(self, package_name: str) -> dict[str, Any]:
        package = self.get_package(package_name)
        if package is None:
            raise ValueError(f"unknown package '{package_name}'")
        resolved_source = package.get("resolved_source") or package.get("source")
        actual_hash: str | None = None
        if isinstance(resolved_source, str):
            target = Path(resolved_source)
            if target.exists() and target.is_file():
                actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        expected = str(package.get("signature") or package.get("checksum") or "").strip() or None
        verified = actual_hash is not None and (expected is None or actual_hash == expected)
        return {
            "package_name": package_name,
            "resolved_source": resolved_source,
            "actual_hash": actual_hash,
            "expected_hash": expected,
            "verified": verified,
        }

    def register_package(self, package_name: str, spec: dict[str, Any], *, tenant_id: str, namespace: str) -> dict[str, Any]:
        now = time.time()
        existing = self.get_package(package_name)
        installed = bool(spec.get("installed")) if "installed" in spec else (bool(existing.get("installed")) if isinstance(existing, dict) else False)
        installed_at = spec.get("installed_at") if "installed_at" in spec else (existing.get("installed_at") if isinstance(existing, dict) else None)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO packages(package_name, tenant_id, namespace, spec_json, installed, installed_at, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(package_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    spec_json=excluded.spec_json,
                    installed=excluded.installed,
                    installed_at=excluded.installed_at,
                    updated_at=excluded.updated_at
                """,
                (package_name, tenant_id, namespace, json.dumps(spec, ensure_ascii=False), int(installed), installed_at, now, now),
            )
        return self.get_package(package_name) or {"name": package_name}

    def install_package(self, package_name: str, spec: dict[str, Any], *, tenant_id: str, namespace: str) -> dict[str, Any]:
        spec = dict(spec)
        for dependency in self.resolve_package_dependencies(package_name):
            dependency_spec = self.get_package(dependency)
            if dependency_spec is not None and not bool(dependency_spec.get("installed")):
                self.install_package(dependency, dependency_spec, tenant_id=str(dependency_spec["tenant"]), namespace=str(dependency_spec["namespace"]))
        signature = self.verify_package_signature(package_name)
        if signature.get("expected_hash") and not bool(signature.get("verified")):
            raise ValueError(f"package '{package_name}' failed signature verification")
        spec["installed"] = True
        spec["installed_at"] = time.time()
        spec["signature_verified"] = bool(signature.get("verified"))
        spec["resolved_hash"] = signature.get("actual_hash")
        return self.register_package(package_name, spec, tenant_id=tenant_id, namespace=namespace)

    def get_package(self, package_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT package_name, tenant_id, namespace, spec_json, installed, installed_at, created_at, updated_at
                FROM packages
                WHERE package_name=?
                """,
                (package_name,),
            ).fetchone()
        if row is None:
            return None
        spec = json.loads(row[3])
        spec.update(
            {
                "name": row[0],
                "tenant": row[1],
                "namespace": row[2],
                "installed": bool(row[4]),
                "installed_at": row[5],
                "created_at": row[6],
                "updated_at": row[7],
            }
        )
        return spec

    def list_packages(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT package_name FROM packages ORDER BY package_name").fetchall()
        return [self.get_package(str(row[0])) for row in rows if self.get_package(str(row[0])) is not None]

    def register_service(self, service_name: str, spec: dict[str, Any], *, tenant_id: str, namespace: str) -> dict[str, Any]:
        now = time.time()
        desired_replicas = max(1, int(spec.get("replicas") or 1))
        existing = self.get_service(service_name)
        active_revision = existing.get("active_revision") if isinstance(existing, dict) else spec.get("active_revision")
        rollout = existing.get("rollout") if isinstance(existing, dict) else spec.get("rollout")
        status = str(existing.get("status") if isinstance(existing, dict) else spec.get("status") or "registered")
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO services(service_name, tenant_id, namespace, spec_json, desired_replicas, active_revision, rollout_json, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    spec_json=excluded.spec_json,
                    desired_replicas=excluded.desired_replicas,
                    active_revision=excluded.active_revision,
                    rollout_json=excluded.rollout_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    service_name,
                    tenant_id,
                    namespace,
                    json.dumps(spec, ensure_ascii=False),
                    desired_replicas,
                    active_revision,
                    json.dumps(rollout, ensure_ascii=False) if rollout is not None else None,
                    status,
                    now,
                    now,
                ),
            )
        self._register_embedded_resources(service_name, spec, tenant_id=tenant_id, namespace=namespace)
        return self.get_service(service_name) or {"name": service_name}

    def deploy_service(
        self,
        service_name: str,
        spec: dict[str, Any],
        *,
        tenant_id: str,
        namespace: str,
        rollout: dict[str, Any] | None = None,
        active_revision: int | None = None,
        status: str = "deploying",
    ) -> dict[str, Any]:
        now = time.time()
        desired_replicas = max(1, int(spec.get("replicas") or 1))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO services(service_name, tenant_id, namespace, spec_json, desired_replicas, active_revision, rollout_json, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    spec_json=excluded.spec_json,
                    desired_replicas=excluded.desired_replicas,
                    active_revision=excluded.active_revision,
                    rollout_json=excluded.rollout_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    service_name,
                    tenant_id,
                    namespace,
                    json.dumps(spec, ensure_ascii=False),
                    desired_replicas,
                    active_revision,
                    json.dumps(rollout, ensure_ascii=False) if rollout is not None else None,
                    status,
                    now,
                    now,
                ),
            )
        self._register_embedded_resources(service_name, spec, tenant_id=tenant_id, namespace=namespace)
        return self.reconcile(service_name, desired_replicas=desired_replicas, revision=active_revision)

    def get_service(self, service_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT service_name, tenant_id, namespace, spec_json, desired_replicas, active_revision, rollout_json, status, created_at, updated_at
                FROM services
                WHERE service_name=?
                """,
                (service_name,),
            ).fetchone()
        if row is None:
            return None
        spec = json.loads(row[3])
        spec.update(
            {
                "name": row[0],
                "tenant": row[1],
                "namespace": row[2],
                "replicas": int(row[4]),
                "desired_replicas": int(row[4]),
                "active_revision": row[5],
                "rollout": json.loads(row[6]) if row[6] else None,
                "status": row[7],
                "instances": self.list_instances(row[0]),
                "ingress": self.list_ingress(row[0]),
                "created_at": row[8],
                "updated_at": row[9],
            }
        )
        return spec

    def list_services(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT service_name FROM services ORDER BY service_name").fetchall()
        return [self.get_service(str(row[0])) for row in rows if self.get_service(str(row[0])) is not None]

    def update_instance(
        self,
        service_name: str,
        *,
        instance_id: str | None = None,
        revision: int | None = None,
        endpoint: str | None = None,
        status: str = "running",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        target_instance_id = instance_id or uuid.uuid4().hex[:16]
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO service_instances(instance_id, service_name, revision, endpoint, status, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET
                    service_name=excluded.service_name,
                    revision=excluded.revision,
                    endpoint=excluded.endpoint,
                    status=excluded.status,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    target_instance_id,
                    service_name,
                    revision,
                    endpoint,
                    status,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return next(item for item in self.list_instances(service_name) if item["instance_id"] == target_instance_id)

    def list_instances(self, service_name: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT instance_id, service_name, revision, endpoint, status, metadata_json, created_at, updated_at
            FROM service_instances
        """
        params: tuple[Any, ...] = ()
        if service_name:
            query += " WHERE service_name=?"
            params = (service_name,)
        query += " ORDER BY created_at ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "instance_id": row[0],
                "service_name": row[1],
                "revision": row[2],
                "endpoint": row[3],
                "status": row[4],
                "metadata": json.loads(row[5]),
                "created_at": row[6],
                "updated_at": row[7],
            }
            for row in rows
        ]

    def reconcile(self, service_name: str, *, desired_replicas: int, revision: int | None = None) -> dict[str, Any]:
        service = self.get_service(service_name)
        if service is None:
            raise ValueError(f"unknown service '{service_name}'")
        instances = self.list_instances(service_name)
        running = [instance for instance in instances if instance["status"] != "terminated"]
        while len(running) < desired_replicas:
            running.append(
                self.update_instance(
                    service_name,
                    revision=revision,
                    endpoint=f"fabric://{service_name}/{uuid.uuid4().hex[:8]}",
                    status="running",
                    metadata={"provisioned_by": "service_fabric"},
                )
            )
        while len(running) > desired_replicas:
            instance = running.pop()
            self.update_instance(
                service_name,
                instance_id=str(instance["instance_id"]),
                revision=revision,
                endpoint=instance.get("endpoint"),
                status="terminated",
                metadata={**dict(instance.get("metadata") or {}), "terminated_by": "service_fabric"},
            )
        updated = self.get_service(service_name) or service
        return updated

    def discover(self, service_name: str, *, tenant_id: str | None = None, namespace: str | None = None) -> dict[str, Any]:
        service = self.get_service(service_name)
        if service is None:
            raise ValueError(f"unknown service '{service_name}'")
        if tenant_id and str(service.get("tenant")) != tenant_id:
            raise PermissionError(f"service '{service_name}' is not visible to tenant '{tenant_id}'")
        if namespace and str(service.get("namespace")) != namespace:
            raise PermissionError(f"service '{service_name}' is not visible in namespace '{namespace}'")
        endpoints = [item["endpoint"] for item in service["instances"] if item["status"] == "running"]
        dns = f"{service_name}.{service['namespace']}.svc.nova"
        ingress = [
            f"https://{item['host']}{item['path']}"
            for item in self.list_ingress(service_name)
        ]
        return {"service": service, "dns": dns, "endpoints": endpoints, "ingress": ingress}

    def autoscale(self, service_name: str, *, target_replicas: int) -> dict[str, Any]:
        service = self.get_service(service_name)
        if service is None:
            raise ValueError(f"unknown service '{service_name}'")
        spec = dict(service)
        spec["replicas"] = max(1, int(target_replicas))
        self.register_service(service_name, spec, tenant_id=str(service["tenant"]), namespace=str(service["namespace"]))
        return self.reconcile(service_name, desired_replicas=max(1, int(target_replicas)), revision=service.get("active_revision"))

    def evaluate_autoscaling(self, service_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
        service = self.get_service(service_name)
        if service is None:
            raise ValueError(f"unknown service '{service_name}'")
        policy = dict(service.get("autoscale") or {})
        current = int(service.get("desired_replicas") or service.get("replicas") or 1)
        min_replicas = max(1, int(policy.get("min_replicas") or 1))
        max_replicas = max(min_replicas, int(policy.get("max_replicas") or max(current, 1)))
        step = max(1, int(policy.get("step") or 1))
        metric_name = str(policy.get("metric") or "cpu")
        observed = float(metrics.get(metric_name) or 0.0)
        scale_out_threshold = float(policy.get("scale_out_threshold") or 0.75)
        scale_in_threshold = float(policy.get("scale_in_threshold") or 0.25)
        target = current
        action = "hold"
        if observed >= scale_out_threshold and current < max_replicas:
            target = min(max_replicas, current + step)
            action = "scale_out"
        elif observed <= scale_in_threshold and current > min_replicas:
            target = max(min_replicas, current - step)
            action = "scale_in"
        if target != current:
            service = self.autoscale(service_name, target_replicas=target)
        return {
            "service_name": service_name,
            "metric": metric_name,
            "observed": observed,
            "current_replicas": current,
            "target_replicas": target,
            "action": action,
            "service": service if target != current else self.get_service(service_name),
        }

    def _register_embedded_resources(self, service_name: str, spec: dict[str, Any], *, tenant_id: str, namespace: str) -> None:
        configs = spec.get("configs")
        if isinstance(configs, dict):
            for config_name, data in configs.items():
                if isinstance(data, dict):
                    self.register_config(str(config_name), data, tenant_id=tenant_id, namespace=namespace, metadata={"service": service_name})
        volumes = spec.get("volumes")
        if isinstance(volumes, dict):
            for volume_name, volume_spec in volumes.items():
                if isinstance(volume_spec, dict):
                    self.register_volume(str(volume_name), volume_spec, tenant_id=tenant_id, namespace=namespace, metadata={"service": service_name})
        ingress = spec.get("ingress")
        if isinstance(ingress, list):
            for item in ingress:
                if not isinstance(item, dict) or not item.get("host"):
                    continue
                self.register_ingress(
                    service_name,
                    host=str(item["host"]),
                    path=str(item.get("path") or "/"),
                    target_port=int(item["target_port"]) if item.get("target_port") is not None else None,
                    metadata={"service": service_name, **dict(item.get("metadata") or {})},
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            package_count = int(self._conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0])
            service_count = int(self._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0])
            instance_count = int(self._conn.execute("SELECT COUNT(*) FROM service_instances").fetchone()[0])
            config_count = int(self._conn.execute("SELECT COUNT(*) FROM fabric_configs").fetchone()[0])
            volume_count = int(self._conn.execute("SELECT COUNT(*) FROM fabric_volumes").fetchone()[0])
            ingress_count = int(self._conn.execute("SELECT COUNT(*) FROM service_ingress").fetchone()[0])
        return {
            "db_path": str(self.db_path),
            "package_count": package_count,
            "service_count": service_count,
            "instance_count": instance_count,
            "config_count": config_count,
            "volume_count": volume_count,
            "ingress_count": ingress_count,
            "packages": self.list_packages(),
            "services": self.list_services(),
            "instances": self.list_instances(),
            "configs": self.list_configs(),
            "volumes": self.list_volumes(),
            "ingress": self.list_ingress(),
        }
