from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import ssl
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuthPrincipal:
    tenant_id: str
    subject: str
    roles: set[str] = field(default_factory=set)
    token_id: str = ""
    expires_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    authenticated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "subject": self.subject,
            "roles": sorted(self.roles),
            "token_id": self.token_id,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "authenticated_at": self.authenticated_at,
        }


@dataclass(slots=True)
class TLSProfile:
    name: str
    certfile: str
    keyfile: str
    cafile: str | None = None
    verify: bool = True
    server_hostname: str | None = None
    updated_at: float = field(default_factory=time.time)

    def create_server_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
        if self.cafile:
            context.load_verify_locations(cafile=self.cafile)
        context.verify_mode = ssl.CERT_REQUIRED if self.verify else ssl.CERT_NONE
        return context

    def create_client_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
        if self.cafile:
            context.load_verify_locations(cafile=self.cafile)
        if not self.verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "certfile": self.certfile,
            "keyfile": self.keyfile,
            "cafile": self.cafile,
            "verify": self.verify,
            "server_hostname": self.server_hostname,
            "updated_at": self.updated_at,
        }


class SecurityPlane:
    """SQLite-backed tenant, token, secret, and TLS registry."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = state_dir
        self.pki_path = state_dir / "pki"
        self.pki_path.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "security-plane.db"
        self.master_key_path = state_dir / "security-master.key"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._master_key = self._load_master_key()
        self._open_connection()
        self._init_schema()
        self.register_tenant("default", display_name="Default Tenant")

    def _open_connection(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._open_connection()
        return self._conn

    def _init_schema(self) -> None:
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    quotas_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    token_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    last_used_at REAL,
                    revoked_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    tenant_id TEXT NOT NULL,
                    secret_name TEXT NOT NULL,
                    secret_value TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (tenant_id, secret_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tls_profiles (
                    profile_name TEXT PRIMARY KEY,
                    certfile TEXT NOT NULL,
                    keyfile TEXT NOT NULL,
                    cafile TEXT,
                    verify INTEGER NOT NULL,
                    server_hostname TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trust_policies (
                    policy_name TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    namespace TEXT,
                    require_tls INTEGER NOT NULL,
                    labels_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_enrollments (
                    worker_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    tls_profile TEXT,
                    trust_policy TEXT,
                    metadata_json TEXT NOT NULL,
                    next_rotation_at REAL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS certificate_authorities (
                    ca_name TEXT PRIMARY KEY,
                    common_name TEXT NOT NULL,
                    certfile TEXT NOT NULL,
                    keyfile TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS issued_certificates (
                    serial TEXT PRIMARY KEY,
                    ca_name TEXT NOT NULL,
                    subject_name TEXT NOT NULL,
                    common_name TEXT NOT NULL,
                    profile_name TEXT,
                    certfile TEXT NOT NULL,
                    keyfile TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    issued_at REAL NOT NULL,
                    expires_at REAL,
                    revoked_at REAL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _load_master_key(self) -> bytes:
        if self.master_key_path.exists():
            return base64.urlsafe_b64decode(self.master_key_path.read_text(encoding="utf-8").strip().encode("ascii"))
        key = os.urandom(32)
        self.master_key_path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")
        return key

    def _encrypt_secret_value(self, value: str) -> str:
        nonce = os.urandom(16)
        plaintext = value.encode("utf-8")
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(plaintext):
            block = hmac.new(self._master_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            keystream.extend(block)
            counter += 1
        ciphertext = bytes(byte ^ keystream[index] for index, byte in enumerate(plaintext))
        tag = hmac.new(self._master_key, nonce + ciphertext, hashlib.sha256).digest()
        payload = {"v": 1, "nonce": base64.b64encode(nonce).decode("ascii"), "ciphertext": base64.b64encode(ciphertext).decode("ascii"), "tag": base64.b64encode(tag).decode("ascii")}
        return "enc:" + json.dumps(payload, ensure_ascii=False)

    def _decrypt_secret_value(self, value: str) -> str:
        if not value.startswith("enc:"):
            return value
        payload = json.loads(value[4:])
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        tag = base64.b64decode(payload["tag"])
        expected = hmac.new(self._master_key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("secret integrity verification failed")
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(ciphertext):
            block = hmac.new(self._master_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            keystream.extend(block)
            counter += 1
        plaintext = bytes(byte ^ keystream[index] for index, byte in enumerate(ciphertext))
        return plaintext.decode("utf-8")

    def _openssl_available(self) -> bool:
        return shutil.which("openssl") is not None

    def _synthetic_pem(self, label: str, content: str) -> str:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return f"-----BEGIN {label}-----\n{encoded}\n-----END {label}-----\n"

    def register_tenant(
        self,
        tenant_id: str,
        *,
        display_name: str | None = None,
        quotas: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        payload = {
            "tenant_id": tenant_id,
            "display_name": display_name or tenant_id,
            "quotas": quotas or {},
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO tenants(tenant_id, display_name, quotas_json, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    quotas_json=excluded.quotas_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    tenant_id,
                    payload["display_name"],
                    json.dumps(payload["quotas"], ensure_ascii=False),
                    json.dumps(payload["metadata"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_tenant(tenant_id) or payload

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT tenant_id, display_name, quotas_json, metadata_json, created_at, updated_at
                FROM tenants
                WHERE tenant_id=?
                """,
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "tenant_id": row[0],
            "display_name": row[1],
            "quotas": json.loads(row[2]),
            "metadata": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }

    def list_tenants(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT tenant_id, display_name, quotas_json, metadata_json, created_at, updated_at
                FROM tenants
                ORDER BY tenant_id
                """
            ).fetchall()
        return [
            {
                "tenant_id": row[0],
                "display_name": row[1],
                "quotas": json.loads(row[2]),
                "metadata": json.loads(row[3]),
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    def issue_token(
        self,
        tenant_id: str,
        subject: str,
        *,
        roles: set[str] | list[str] | tuple[str, ...] | None = None,
        ttl_seconds: int | None = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"unknown tenant '{tenant_id}'")

        now = time.time()
        token_id = uuid.uuid4().hex[:16]
        token_value = f"nova_{token_id}_{secrets.token_urlsafe(24)}"
        token_hash = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
        roles_payload = sorted({str(role) for role in (roles or []) if str(role)})
        expires_at = now + max(1, ttl_seconds) if ttl_seconds else None
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO tokens(token_id, tenant_id, subject, roles_json, token_hash, metadata_json, created_at, expires_at, last_used_at, revoked_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    tenant_id,
                    subject,
                    json.dumps(roles_payload, ensure_ascii=False),
                    token_hash,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    expires_at,
                    None,
                    None,
                ),
            )
        return {
            "token_id": token_id,
            "tenant_id": tenant_id,
            "subject": subject,
            "roles": roles_payload,
            "expires_at": expires_at,
            "token": token_value,
        }

    def authenticate(self, token: str) -> AuthPrincipal | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT token_id, tenant_id, subject, roles_json, metadata_json, expires_at, revoked_at
                FROM tokens
                WHERE token_hash=?
                """,
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        token_id, tenant_id, subject, roles_json, metadata_json, expires_at, revoked_at = row
        if revoked_at is not None:
            return None
        if expires_at is not None and float(expires_at) < now:
            return None
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute("UPDATE tokens SET last_used_at=? WHERE token_id=?", (now, token_id))
        return AuthPrincipal(
            tenant_id=str(tenant_id),
            subject=str(subject),
            roles=set(json.loads(roles_json)),
            token_id=str(token_id),
            expires_at=float(expires_at) if expires_at is not None else None,
            metadata=json.loads(metadata_json),
        )

    def authorize(self, principal: AuthPrincipal | None, required_roles: set[str] | list[str] | tuple[str, ...]) -> bool:
        if principal is None:
            return False
        roles = {str(role) for role in required_roles}
        return roles.issubset(principal.roles)

    def revoke_token(self, token_id: str) -> dict[str, Any]:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            cursor = conn.execute("UPDATE tokens SET revoked_at=? WHERE token_id=?", (now, token_id))
        return {"token_id": token_id, "revoked": cursor.rowcount > 0, "revoked_at": now if cursor.rowcount > 0 else None}

    def store_secret(self, tenant_id: str, secret_name: str, secret_value: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"unknown tenant '{tenant_id}'")
        now = time.time()
        encrypted_value = self._encrypt_secret_value(secret_value)
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO secrets(tenant_id, secret_name, secret_value, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, secret_name) DO UPDATE SET
                    secret_value=excluded.secret_value,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (tenant_id, secret_name, encrypted_value, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return {"tenant_id": tenant_id, "secret_name": secret_name, "updated_at": now}

    def resolve_secret(self, tenant_id: str, secret_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT tenant_id, secret_name, secret_value, metadata_json, created_at, updated_at
                FROM secrets
                WHERE tenant_id=? AND secret_name=?
                """,
                (tenant_id, secret_name),
            ).fetchone()
        if row is None:
            return None
        return {
            "tenant_id": row[0],
            "secret_name": row[1],
            "secret_value": self._decrypt_secret_value(row[2]),
            "metadata": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }

    def list_secrets(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT tenant_id, secret_name, metadata_json, created_at, updated_at
            FROM secrets
        """
        params: tuple[Any, ...] = ()
        if tenant_id:
            query += " WHERE tenant_id=?"
            params = (tenant_id,)
        query += " ORDER BY tenant_id, secret_name"
        with self._lock:
            rows = self._ensure_connection().execute(query, params).fetchall()
        return [
            {
                "tenant_id": row[0],
                "secret_name": row[1],
                "metadata": json.loads(row[2]),
                "created_at": row[3],
                "updated_at": row[4],
                "has_value": True,
            }
            for row in rows
        ]

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
        updated_at = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO tls_profiles(profile_name, certfile, keyfile, cafile, verify, server_hostname, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_name) DO UPDATE SET
                    certfile=excluded.certfile,
                    keyfile=excluded.keyfile,
                    cafile=excluded.cafile,
                    verify=excluded.verify,
                    server_hostname=excluded.server_hostname,
                    updated_at=excluded.updated_at
                """,
                (profile_name, certfile, keyfile, cafile, int(bool(verify)), server_hostname, updated_at),
            )
        return self.get_tls_profile(profile_name) or {"name": profile_name}

    def get_tls_profile(self, profile_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT profile_name, certfile, keyfile, cafile, verify, server_hostname, updated_at
                FROM tls_profiles
                WHERE profile_name=?
                """,
                (profile_name,),
            ).fetchone()
        if row is None:
            return None
        profile = TLSProfile(
            name=row[0],
            certfile=row[1],
            keyfile=row[2],
            cafile=row[3],
            verify=bool(row[4]),
            server_hostname=row[5],
            updated_at=row[6],
        )
        return profile.to_dict()

    def list_tls_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT profile_name, certfile, keyfile, cafile, verify, server_hostname, updated_at
                FROM tls_profiles
                ORDER BY profile_name
                """
            ).fetchall()
        return [
            TLSProfile(
                name=row[0],
                certfile=row[1],
                keyfile=row[2],
                cafile=row[3],
                verify=bool(row[4]),
                server_hostname=row[5],
                updated_at=row[6],
            ).to_dict()
            for row in rows
        ]

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
        updated_at = time.time()
        payload = {
            "policy_name": policy_name,
            "tenant_id": tenant_id,
            "namespace": namespace,
            "require_tls": bool(require_tls),
            "labels": {str(key): str(value) for key, value in dict(labels or {}).items()},
            "capabilities": sorted({str(item) for item in (capabilities or []) if str(item)}),
            "metadata": metadata or {},
            "updated_at": updated_at,
        }
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO trust_policies(policy_name, tenant_id, namespace, require_tls, labels_json, capabilities_json, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    require_tls=excluded.require_tls,
                    labels_json=excluded.labels_json,
                    capabilities_json=excluded.capabilities_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    policy_name,
                    tenant_id,
                    namespace,
                    int(bool(require_tls)),
                    json.dumps(payload["labels"], ensure_ascii=False),
                    json.dumps(payload["capabilities"], ensure_ascii=False),
                    json.dumps(payload["metadata"], ensure_ascii=False),
                    updated_at,
                ),
            )
        return self.get_trust_policy(policy_name) or payload

    def get_trust_policy(self, policy_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT policy_name, tenant_id, namespace, require_tls, labels_json, capabilities_json, metadata_json, updated_at
                FROM trust_policies
                WHERE policy_name=?
                """,
                (policy_name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "policy_name": row[0],
            "tenant_id": row[1],
            "namespace": row[2],
            "require_tls": bool(row[3]),
            "labels": json.loads(row[4]),
            "capabilities": json.loads(row[5]),
            "metadata": json.loads(row[6]),
            "updated_at": row[7],
        }

    def list_trust_policies(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                """
                SELECT policy_name, tenant_id, namespace, require_tls, labels_json, capabilities_json, metadata_json, updated_at
                FROM trust_policies
                ORDER BY policy_name
                """
            ).fetchall()
        return [
            {
                "policy_name": row[0],
                "tenant_id": row[1],
                "namespace": row[2],
                "require_tls": bool(row[3]),
                "labels": json.loads(row[4]),
                "capabilities": json.loads(row[5]),
                "metadata": json.loads(row[6]),
                "updated_at": row[7],
            }
            for row in rows
        ]

    def authorize_worker(
        self,
        *,
        worker_id: str,
        tenant_id: str | None,
        namespace: str | None,
        capabilities: set[str] | list[str] | tuple[str, ...],
        labels: dict[str, str] | None,
        tls_profile: str | None,
    ) -> bool:
        policies = self.list_trust_policies()
        if not policies:
            return True
        normalized_capabilities = {str(item) for item in capabilities}
        normalized_labels = {str(key): str(value) for key, value in dict(labels or {}).items()}
        for policy in policies:
            policy_tenant = policy.get("tenant_id")
            policy_namespace = policy.get("namespace")
            if policy_tenant and policy_tenant != tenant_id:
                continue
            if policy_namespace and policy_namespace != namespace:
                continue
            if policy.get("require_tls") and not tls_profile:
                continue
            required_labels = dict(policy.get("labels") or {})
            if any(normalized_labels.get(key) != str(value) for key, value in required_labels.items()):
                continue
            required_capabilities = {str(item) for item in policy.get("capabilities", [])}
            if not required_capabilities.issubset(normalized_capabilities):
                continue
            return True
        enrollment = self.get_worker_enrollment(worker_id)
        return enrollment is not None

    def onboard_worker(
        self,
        worker_id: str,
        tenant_id: str,
        *,
        namespace: str = "default",
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
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"unknown tenant '{tenant_id}'")
        profile_name = tls_profile
        if ca_name and not (certfile and keyfile):
            issued = self.issue_certificate(
                ca_name,
                subject_name=worker_id,
                common_name=worker_id,
                profile_name=profile_name or f"worker-{worker_id}",
                validity_days=max(1, int((rotate_after_seconds or 86400) / 86400)),
                metadata={"worker_id": worker_id, **dict(metadata or {})},
            )
            certfile = str(issued["certfile"])
            keyfile = str(issued["keyfile"])
            cafile = str(self.get_certificate_authority(ca_name)["certfile"]) if self.get_certificate_authority(ca_name) else cafile
            profile_name = str(issued.get("profile_name") or profile_name or f"worker-{worker_id}")
        if certfile and keyfile:
            profile_name = profile_name or f"worker-{worker_id}"
            self.set_tls_profile(profile_name, certfile, keyfile, cafile=cafile, verify=bool(cafile))
        if not self.authorize_worker(
            worker_id=worker_id,
            tenant_id=tenant_id,
            namespace=namespace,
            capabilities=capabilities or (),
            labels=labels or {},
            tls_profile=profile_name,
        ):
            raise PermissionError(f"worker '{worker_id}' does not satisfy configured trust policies")
        now = time.time()
        next_rotation_at = now + max(60, int(rotate_after_seconds)) if rotate_after_seconds else None
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO worker_enrollments(worker_id, tenant_id, namespace, capabilities_json, labels_json, tls_profile, trust_policy, metadata_json, next_rotation_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    namespace=excluded.namespace,
                    capabilities_json=excluded.capabilities_json,
                    labels_json=excluded.labels_json,
                    tls_profile=excluded.tls_profile,
                    trust_policy=excluded.trust_policy,
                    metadata_json=excluded.metadata_json,
                    next_rotation_at=excluded.next_rotation_at,
                    updated_at=excluded.updated_at
                """,
                (
                    worker_id,
                    tenant_id,
                    namespace,
                    json.dumps(sorted({str(item) for item in (capabilities or []) if str(item)}), ensure_ascii=False),
                    json.dumps({str(key): str(value) for key, value in dict(labels or {}).items()}, ensure_ascii=False),
                    profile_name,
                    trust_policy,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    next_rotation_at,
                    now,
                ),
            )
        return self.get_worker_enrollment(worker_id) or {"worker_id": worker_id}

    def get_worker_enrollment(self, worker_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT worker_id, tenant_id, namespace, capabilities_json, labels_json, tls_profile, trust_policy, metadata_json, next_rotation_at, updated_at
                FROM worker_enrollments
                WHERE worker_id=?
                """,
                (worker_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "worker_id": row[0],
            "tenant_id": row[1],
            "namespace": row[2],
            "capabilities": json.loads(row[3]),
            "labels": json.loads(row[4]),
            "tls_profile": row[5],
            "trust_policy": row[6],
            "metadata": json.loads(row[7]),
            "next_rotation_at": row[8],
            "updated_at": row[9],
        }

    def list_worker_enrollments(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT worker_id, tenant_id, namespace, capabilities_json, labels_json, tls_profile, trust_policy, metadata_json, next_rotation_at, updated_at
            FROM worker_enrollments
        """
        params: tuple[Any, ...] = ()
        if tenant_id:
            query += " WHERE tenant_id=?"
            params = (tenant_id,)
        query += " ORDER BY worker_id"
        with self._lock:
            rows = self._ensure_connection().execute(query, params).fetchall()
        return [
            {
                "worker_id": row[0],
                "tenant_id": row[1],
                "namespace": row[2],
                "capabilities": json.loads(row[3]),
                "labels": json.loads(row[4]),
                "tls_profile": row[5],
                "trust_policy": row[6],
                "metadata": json.loads(row[7]),
                "next_rotation_at": row[8],
                "updated_at": row[9],
            }
            for row in rows
        ]

    def create_certificate_authority(
        self,
        ca_name: str,
        *,
        common_name: str,
        validity_days: int = 3650,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_dir = self.pki_path / ca_name
        target_dir.mkdir(parents=True, exist_ok=True)
        certfile = target_dir / "ca.crt"
        keyfile = target_dir / "ca.key"
        provider = "openssl" if self._openssl_available() else "synthetic"
        if provider == "openssl":
            subprocess.run(
                [
                    shutil.which("openssl") or "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(keyfile),
                    "-out",
                    str(certfile),
                    "-days",
                    str(max(1, int(validity_days))),
                    "-nodes",
                    "-subj",
                    f"/CN={common_name}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        if not certfile.exists() or not keyfile.exists():
            keyfile.write_text(self._synthetic_pem("PRIVATE KEY", f"{ca_name}:{common_name}:key"), encoding="utf-8")
            certfile.write_text(self._synthetic_pem("CERTIFICATE", f"{ca_name}:{common_name}:cert"), encoding="utf-8")
            provider = "synthetic"
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO certificate_authorities(ca_name, common_name, certfile, keyfile, provider, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ca_name) DO UPDATE SET
                    common_name=excluded.common_name,
                    certfile=excluded.certfile,
                    keyfile=excluded.keyfile,
                    provider=excluded.provider,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    ca_name,
                    common_name,
                    str(certfile),
                    str(keyfile),
                    provider,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_certificate_authority(ca_name) or {"ca_name": ca_name}

    def get_certificate_authority(self, ca_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT ca_name, common_name, certfile, keyfile, provider, metadata_json, created_at, updated_at
                FROM certificate_authorities
                WHERE ca_name=?
                """,
                (ca_name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "ca_name": row[0],
            "common_name": row[1],
            "certfile": row[2],
            "keyfile": row[3],
            "provider": row[4],
            "metadata": json.loads(row[5]),
            "created_at": row[6],
            "updated_at": row[7],
        }

    def list_certificate_authorities(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._ensure_connection().execute(
                "SELECT ca_name FROM certificate_authorities ORDER BY ca_name"
            ).fetchall()
        return [self.get_certificate_authority(str(row[0])) for row in rows if self.get_certificate_authority(str(row[0])) is not None]

    def issue_certificate(
        self,
        ca_name: str,
        *,
        subject_name: str,
        common_name: str,
        profile_name: str | None = None,
        validity_days: int = 365,
        metadata: dict[str, Any] | None = None,
        serial: str | None = None,
    ) -> dict[str, Any]:
        ca = self.get_certificate_authority(ca_name)
        if ca is None:
            raise ValueError(f"unknown certificate authority '{ca_name}'")
        serial_value = serial or uuid.uuid4().hex[:16]
        existing = self.get_issued_certificate(serial_value)
        if existing is not None:
            return existing
        target_dir = self.pki_path / ca_name / subject_name
        target_dir.mkdir(parents=True, exist_ok=True)
        certfile = target_dir / f"{serial_value}.crt"
        keyfile = target_dir / f"{serial_value}.key"
        provider = str(ca.get("provider") or "synthetic")
        if provider == "openssl" and self._openssl_available():
            csrfile = target_dir / f"{serial_value}.csr"
            subprocess.run(
                [shutil.which("openssl") or "openssl", "genrsa", "-out", str(keyfile), "2048"],
                capture_output=True,
                text=True,
                check=False,
            )
            subprocess.run(
                [
                    shutil.which("openssl") or "openssl",
                    "req",
                    "-new",
                    "-key",
                    str(keyfile),
                    "-out",
                    str(csrfile),
                    "-subj",
                    f"/CN={common_name}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            subprocess.run(
                [
                    shutil.which("openssl") or "openssl",
                    "x509",
                    "-req",
                    "-in",
                    str(csrfile),
                    "-CA",
                    str(ca["certfile"]),
                    "-CAkey",
                    str(ca["keyfile"]),
                    "-CAcreateserial",
                    "-out",
                    str(certfile),
                    "-days",
                    str(max(1, int(validity_days))),
                    "-sha256",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        if not certfile.exists() or not keyfile.exists():
            keyfile.write_text(self._synthetic_pem("PRIVATE KEY", f"{serial_value}:{subject_name}:key"), encoding="utf-8")
            certfile.write_text(self._synthetic_pem("CERTIFICATE", f"{serial_value}:{subject_name}:cert"), encoding="utf-8")
            provider = "synthetic"
        tls_profile_name = profile_name or f"{ca_name}-{subject_name}"
        self.set_tls_profile(tls_profile_name, str(certfile), str(keyfile), cafile=str(ca["certfile"]), verify=provider == "openssl")
        issued_at = time.time()
        expires_at = issued_at + (max(1, int(validity_days)) * 86400)
        conn = self._ensure_connection()
        with self._lock, conn:
            conn.execute(
                """
                INSERT INTO issued_certificates(serial, ca_name, subject_name, common_name, profile_name, certfile, keyfile, metadata_json, issued_at, expires_at, revoked_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    serial_value,
                    ca_name,
                    subject_name,
                    common_name,
                    tls_profile_name,
                    str(certfile),
                    str(keyfile),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    issued_at,
                    expires_at,
                    None,
                ),
            )
        return self.get_issued_certificate(serial_value) or {"serial": serial_value}

    def get_issued_certificate(self, serial: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._ensure_connection().execute(
                """
                SELECT serial, ca_name, subject_name, common_name, profile_name, certfile, keyfile, metadata_json, issued_at, expires_at, revoked_at
                FROM issued_certificates
                WHERE serial=?
                """,
                (serial,),
            ).fetchone()
        if row is None:
            return None
        return {
            "serial": row[0],
            "ca_name": row[1],
            "subject_name": row[2],
            "common_name": row[3],
            "profile_name": row[4],
            "certfile": row[5],
            "keyfile": row[6],
            "metadata": json.loads(row[7]),
            "issued_at": row[8],
            "expires_at": row[9],
            "revoked_at": row[10],
        }

    def list_issued_certificates(self, ca_name: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT serial FROM issued_certificates"
        params: tuple[Any, ...] = ()
        if ca_name:
            query += " WHERE ca_name=?"
            params = (ca_name,)
        query += " ORDER BY issued_at DESC"
        with self._lock:
            rows = self._ensure_connection().execute(query, params).fetchall()
        return [self.get_issued_certificate(str(row[0])) for row in rows if self.get_issued_certificate(str(row[0])) is not None]

    def revoke_certificate(self, serial: str) -> dict[str, Any]:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock, conn:
            cursor = conn.execute("UPDATE issued_certificates SET revoked_at=? WHERE serial=?", (now, serial))
        certificate = self.get_issued_certificate(serial)
        return {"serial": serial, "revoked": cursor.rowcount > 0, "revoked_at": now if cursor.rowcount > 0 else None, "certificate": certificate}

    def rotate_worker_certificate(
        self,
        worker_id: str,
        certfile: str,
        keyfile: str,
        *,
        cafile: str | None = None,
        rotate_after_seconds: int | None = 86400,
    ) -> dict[str, Any]:
        enrollment = self.get_worker_enrollment(worker_id)
        if enrollment is None:
            raise ValueError(f"worker '{worker_id}' is not enrolled")
        profile_name = str(enrollment.get("tls_profile") or f"worker-{worker_id}")
        self.set_tls_profile(profile_name, certfile, keyfile, cafile=cafile, verify=bool(cafile))
        return self.onboard_worker(
            worker_id,
            str(enrollment["tenant_id"]),
            namespace=str(enrollment.get("namespace") or "default"),
            capabilities=set(enrollment.get("capabilities") or []),
            labels=dict(enrollment.get("labels") or {}),
            tls_profile=profile_name,
            trust_policy=str(enrollment.get("trust_policy") or "") or None,
            rotate_after_seconds=rotate_after_seconds,
            metadata=dict(enrollment.get("metadata") or {}),
        )

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        conn = self._ensure_connection()
        with self._lock:
            token_count = int(conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0])
            active_token_count = int(conn.execute("SELECT COUNT(*) FROM tokens WHERE revoked_at IS NULL").fetchone()[0])
            secret_count = int(conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0])
            trust_policy_count = int(conn.execute("SELECT COUNT(*) FROM trust_policies").fetchone()[0])
            worker_enrollment_count = int(conn.execute("SELECT COUNT(*) FROM worker_enrollments").fetchone()[0])
            ca_count = int(conn.execute("SELECT COUNT(*) FROM certificate_authorities").fetchone()[0])
            certificate_count = int(conn.execute("SELECT COUNT(*) FROM issued_certificates").fetchone()[0])
            recent_rows = conn.execute(
                """
                SELECT token_id, tenant_id, subject, roles_json, created_at, expires_at, last_used_at, revoked_at
                FROM tokens
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        recent_tokens = [
            {
                "token_id": row[0],
                "tenant_id": row[1],
                "subject": row[2],
                "roles": json.loads(row[3]),
                "created_at": row[4],
                "expires_at": row[5],
                "last_used_at": row[6],
                "revoked_at": row[7],
            }
            for row in recent_rows
        ]
        return {
            "db_path": str(self.db_path),
            "tenant_count": len(self.list_tenants()),
            "token_count": token_count,
            "active_token_count": active_token_count,
            "secret_count": secret_count,
            "tenants": self.list_tenants(),
            "recent_tokens": recent_tokens,
            "secrets": self.list_secrets(),
            "tls_profiles": self.list_tls_profiles(),
            "trust_policy_count": trust_policy_count,
            "trust_policies": self.list_trust_policies(),
            "worker_enrollment_count": worker_enrollment_count,
            "workers": self.list_worker_enrollments(),
            "certificate_authority_count": ca_count,
            "certificate_authorities": self.list_certificate_authorities(),
            "certificate_count": certificate_count,
            "certificates": self.list_issued_certificates(),
        }
