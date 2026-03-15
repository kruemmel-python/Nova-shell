from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .security import AuthPrincipal


@dataclass(slots=True)
class AuditRecord:
    category: str
    action: str
    status: str
    actor: str = "anonymous"
    tenant: str = "default"
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "action": self.action,
            "status": self.status,
            "actor": self.actor,
            "tenant": self.tenant,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class RuntimeAuditLog:
    """Append-only runtime audit trail stored as JSONL."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "runtime-audit.jsonl"
        self._lock = threading.RLock()
        self._records: list[AuditRecord] = []

    def record(
        self,
        *,
        category: str,
        action: str,
        status: str,
        actor: str,
        tenant: str,
        details: dict[str, Any] | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            category=category,
            action=action,
            status=status,
            actor=actor,
            tenant=tenant,
            details=details or {},
        )
        with self._lock:
            self._records.append(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        with self._lock:
            recent = [record.to_dict() for record in self._records[-max(1, limit) :]]
            error_count = sum(1 for record in self._records if record.status == "error")
        return {
            "path": str(self.path),
            "count": len(self._records),
            "error_count": error_count,
            "records": recent,
        }


class RuntimePolicy:
    """Runtime policy and RBAC evaluator for Nova control-plane actions."""

    def __init__(self) -> None:
        self.auth_required = False
        self.tenant_isolation = False
        self.namespace_isolation = False
        self.mesh_tls_required = False
        self.admin_roles: set[str] = {"admin"}
        self.operator_roles: set[str] = {"admin", "ops"}
        self.allowed_tenants: set[str] = set()
        self.allowed_namespaces: set[str] = set()
        self.default_namespace = "default"
        self.quotas: dict[str, Any] = {}
        self.defaults: dict[str, Any] = {}

    def configure(self, properties: dict[str, Any]) -> None:
        if "auth_required" in properties:
            self.auth_required = bool(properties["auth_required"])
        if "tenant_isolation" in properties:
            self.tenant_isolation = bool(properties["tenant_isolation"])
        if "namespace_isolation" in properties:
            self.namespace_isolation = bool(properties["namespace_isolation"])
        if "mesh_tls_required" in properties:
            self.mesh_tls_required = bool(properties["mesh_tls_required"])
        if "admin_roles" in properties:
            self.admin_roles = self._normalize_roles(properties["admin_roles"]) or {"admin"}
        if "operator_roles" in properties:
            self.operator_roles = self._normalize_roles(properties["operator_roles"]) or {"admin", "ops"}
        if "allowed_tenants" in properties:
            self.allowed_tenants = self._normalize_roles(properties["allowed_tenants"])
        if "allowed_namespaces" in properties:
            self.allowed_namespaces = self._normalize_roles(properties["allowed_namespaces"])
        if "default_namespace" in properties and str(properties["default_namespace"]).strip():
            self.default_namespace = str(properties["default_namespace"]).strip()
        if "namespace" in properties and str(properties["namespace"]).strip():
            self.default_namespace = str(properties["namespace"]).strip()
        if isinstance(properties.get("quotas"), dict):
            self.quotas.update(dict(properties["quotas"]))
        self.defaults.update(properties)

    def can_admin(self, principal: AuthPrincipal | None) -> bool:
        if not self.auth_required:
            return True
        if principal is None:
            return False
        return bool(principal.roles.intersection(self.admin_roles))

    def can_operate(self, principal: AuthPrincipal | None) -> bool:
        if not self.auth_required:
            return True
        if principal is None:
            return False
        return bool(principal.roles.intersection(self.operator_roles))

    def authorize_roles(self, principal: AuthPrincipal | None, required_roles: set[str] | list[str] | tuple[str, ...] | None) -> bool:
        normalized = self._normalize_roles(required_roles)
        if not normalized:
            return True
        if principal is None:
            return False
        return normalized.issubset(principal.roles)

    def authorize_tenant(self, active_tenant: str, resource_tenant: str | None) -> bool:
        if resource_tenant is None or not self.tenant_isolation:
            return True
        return active_tenant == resource_tenant

    def permits_tenant(self, tenant_id: str) -> bool:
        if not self.allowed_tenants:
            return True
        return tenant_id in self.allowed_tenants

    def authorize_namespace(self, active_namespace: str, resource_namespace: str | None) -> bool:
        if resource_namespace is None or not self.namespace_isolation:
            return True
        return active_namespace == resource_namespace

    def permits_namespace(self, namespace: str) -> bool:
        if not self.allowed_namespaces:
            return True
        return namespace in self.allowed_namespaces

    def resolve_quotas(self, tenant_quotas: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(self.quotas)
        if isinstance(tenant_quotas, dict):
            merged.update(tenant_quotas)
        return merged

    def snapshot(self) -> dict[str, Any]:
        return {
            "auth_required": self.auth_required,
            "tenant_isolation": self.tenant_isolation,
            "namespace_isolation": self.namespace_isolation,
            "mesh_tls_required": self.mesh_tls_required,
            "admin_roles": sorted(self.admin_roles),
            "operator_roles": sorted(self.operator_roles),
            "allowed_tenants": sorted(self.allowed_tenants),
            "allowed_namespaces": sorted(self.allowed_namespaces),
            "default_namespace": self.default_namespace,
            "quotas": self.quotas,
            "defaults": self.defaults,
        }

    def _normalize_roles(self, value: Any) -> set[str]:
        match value:
            case None:
                return set()
            case str():
                return {item.strip() for item in value.split(",") if item.strip()}
            case list() | tuple() | set():
                return {str(item).strip() for item in value if str(item).strip()}
            case _:
                return {str(value).strip()} if str(value).strip() else set()
