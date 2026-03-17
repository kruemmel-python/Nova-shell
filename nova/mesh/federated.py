from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import socket
import ssl
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any

from nova.runtime.atheria_bridge import load_aion_chronik


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_shared_memory(handle: str, *, size: int) -> bytes:
    segment = shared_memory.SharedMemory(name=handle)
    try:
        return bytes(segment.buf[: max(0, int(size))])
    finally:
        with contextlib.suppress(Exception):
            segment.close()


@dataclass(slots=True)
class FederatedInvariantUpdate:
    update_id: str
    core_id: str
    fingerprint: str
    created_at: float
    namespace: str
    project: str
    kind: str
    statement: str
    confidence: float
    effect_size: float
    samples: int
    summary: str
    zero_handle: str = ""
    zero_size: int = 0
    zero_type: str = ""
    same_host_only: bool = False
    payload_sha256: str = ""
    metadata: dict[str, Any] | None = None
    signature: str = ""

    def envelope(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "core_id": self.core_id,
            "fingerprint": self.fingerprint,
            "created_at": round(self.created_at, 6),
            "namespace": self.namespace,
            "project": self.project,
            "kind": self.kind,
            "statement": self.statement,
            "confidence": round(self.confidence, 6),
            "effect_size": round(self.effect_size, 6),
            "samples": int(self.samples),
            "summary": self.summary,
            "zero_handle": self.zero_handle,
            "zero_size": int(self.zero_size),
            "zero_type": self.zero_type,
            "same_host_only": bool(self.same_host_only),
            "payload_sha256": self.payload_sha256,
            "metadata": dict(self.metadata or {}),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.envelope()
        payload["signature"] = self.signature
        return payload


class FederatedLearningMesh:
    """Signed invariant propagation across Nova mesh workers with zero-copy same-host handles."""

    def __init__(self, storage_root: Path, *, atheria_runtime: Any | None = None) -> None:
        self.storage_root = Path(storage_root).resolve(strict=False)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.core_audit_root = self.storage_root / "core_audit"
        self.core_audit_root.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.storage_root / "federated"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.updates_path = self.state_dir / "federated-updates.jsonl"
        self.applied_path = self.state_dir / "federated-applied.jsonl"
        self.status_path = self.state_dir / "federated-status.json"
        self.atheria_runtime = atheria_runtime

    def ensure_identity(self, core_id: str = "nova-shell") -> dict[str, str]:
        target = self.core_audit_root / f"{str(core_id).lower()}_audit.key"
        if not target.exists():
            seed = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
            target.write_text(seed, encoding="utf-8")
        derived, fingerprint = self._derived_key_from_file(target)
        if derived is None:
            raise RuntimeError(f"unable to derive federated key from {target}")
        return {"core_id": str(core_id).lower(), "key_file": str(target), "fingerprint": fingerprint}

    def publish_update(
        self,
        *,
        statement: str,
        namespace: str = "default",
        project: str = "default",
        kind: str = "atheria_invariant",
        confidence: float = 0.0,
        effect_size: float = 0.0,
        samples: int = 0,
        summary: str = "",
        zero_handle: str = "",
        zero_size: int = 0,
        zero_type: str = "",
        same_host_only: bool = False,
        metadata: dict[str, Any] | None = None,
        core_id: str = "nova-shell",
    ) -> dict[str, Any]:
        identity = self.ensure_identity(core_id)
        _, key_fingerprint = self._derived_key_from_file(self.core_audit_root / f"{identity['core_id']}_audit.key")
        key = self._resolve_key(identity["core_id"], key_fingerprint)
        if key is None:
            raise RuntimeError("federated signing key unavailable")
        payload_sha256 = ""
        if zero_handle and zero_size > 0:
            payload_sha256 = hashlib.sha256(_read_shared_memory(zero_handle, size=zero_size)).hexdigest()
        update = FederatedInvariantUpdate(
            update_id=f"federated_{uuid.uuid4().hex[:12]}",
            core_id=identity["core_id"],
            fingerprint=key_fingerprint,
            created_at=time.time(),
            namespace=str(namespace or "default"),
            project=str(project or "default"),
            kind=str(kind or "atheria_invariant"),
            statement=str(statement or "").strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
            effect_size=float(effect_size),
            samples=max(0, int(samples)),
            summary=str(summary or statement or "").strip(),
            zero_handle=str(zero_handle or ""),
            zero_size=max(0, int(zero_size)),
            zero_type=str(zero_type or ""),
            same_host_only=bool(same_host_only),
            payload_sha256=payload_sha256,
            metadata=dict(metadata or {}),
        )
        update.signature = hmac.new(key, _stable_json(update.envelope()).encode("utf-8"), hashlib.sha256).hexdigest()
        self._append_jsonl(self.updates_path, update.to_dict())
        status = self.status()
        self.status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return update.to_dict()

    def publish_latest_aion_invariant(
        self,
        report_root: Path,
        *,
        namespace: str = "default",
        project: str = "default",
        broadcast: bool = False,
        workers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        module = load_aion_chronik()
        latest = module._latest_resonance_invariant(Path(report_root))
        if not latest:
            raise ValueError("no Aion-Chronik invariant available")
        statement = str(latest.get("statement") or "Inter-Core-Invariante")
        confidence = _safe_float(latest.get("confidence"), 0.0)
        effect_size = _safe_float(latest.get("effect_size"), 0.0)
        samples = int(_safe_float(latest.get("samples"), 0.0))
        summary = f"{statement} | confidence={confidence:.3f} | effect={effect_size:.3f} | samples={samples}"
        update = self.publish_update(
            statement=statement,
            namespace=namespace,
            project=project,
            kind="aion_chronik_invariant",
            confidence=confidence,
            effect_size=effect_size,
            samples=samples,
            summary=summary,
            metadata={"report_root": str(report_root), "latest": latest},
            core_id="nova-shell",
        )
        if broadcast and workers:
            broadcast_result = self.broadcast(update, workers=workers)
            update["broadcast"] = broadcast_result
        return update

    def apply_update(self, payload: dict[str, Any], *, worker_node_id: str = "") -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("invalid federated payload")
        update = FederatedInvariantUpdate(
            update_id=str(payload.get("update_id") or ""),
            core_id=str(payload.get("core_id") or ""),
            fingerprint=str(payload.get("fingerprint") or ""),
            created_at=_safe_float(payload.get("created_at"), time.time()),
            namespace=str(payload.get("namespace") or "default"),
            project=str(payload.get("project") or "default"),
            kind=str(payload.get("kind") or "atheria_invariant"),
            statement=str(payload.get("statement") or ""),
            confidence=_safe_float(payload.get("confidence"), 0.0),
            effect_size=_safe_float(payload.get("effect_size"), 0.0),
            samples=int(_safe_float(payload.get("samples"), 0.0)),
            summary=str(payload.get("summary") or payload.get("statement") or ""),
            zero_handle=str(payload.get("zero_handle") or ""),
            zero_size=int(_safe_float(payload.get("zero_size"), 0.0)),
            zero_type=str(payload.get("zero_type") or ""),
            same_host_only=bool(payload.get("same_host_only")),
            payload_sha256=str(payload.get("payload_sha256") or ""),
            metadata=dict(payload.get("metadata") or {}),
            signature=str(payload.get("signature") or ""),
        )
        verified = self._verify(update)
        duplicate = update.update_id in {dict(row.get("update") or {}).get("update_id") for row in self.applied_history(limit=500)}
        zero_preview = ""
        payload_integrity_ok = True
        if update.zero_handle and update.zero_size > 0 and self._same_host_transport_allowed(update):
            try:
                raw = _read_shared_memory(update.zero_handle, size=update.zero_size)
                if update.payload_sha256:
                    payload_integrity_ok = hashlib.sha256(raw).hexdigest() == update.payload_sha256
                zero_preview = raw[:320].decode("utf-8", errors="replace")
            except Exception:
                payload_integrity_ok = False
        training_rows = 0
        applied = bool(verified and payload_integrity_ok and not duplicate)
        if applied and self.atheria_runtime is not None:
            with contextlib.suppress(Exception):
                training_rows = int(
                    self.atheria_runtime.train_rows(
                        [
                            (
                                f"Federated invariant {update.update_id}",
                                f"{update.kind}:{update.namespace}",
                                "\n".join(
                                    part
                                    for part in [
                                        update.statement,
                                        update.summary,
                                        zero_preview,
                                    ]
                                    if str(part).strip()
                                ),
                            )
                        ]
                    )
                )
        result = {
            "applied": applied,
            "verified": bool(verified),
            "duplicate": bool(duplicate),
            "payload_integrity_ok": bool(payload_integrity_ok),
            "worker_node_id": worker_node_id,
            "training_rows": training_rows,
            "update": update.to_dict(),
            "zero_preview": zero_preview,
        }
        if verified and not duplicate:
            self._append_jsonl(self.updates_path, update.to_dict())
        if applied:
            self._append_jsonl(self.applied_path, result)
            self.status_path.write_text(json.dumps(self.status(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def broadcast(self, update: dict[str, Any], *, workers: list[dict[str, Any]]) -> dict[str, Any]:
        delivered: list[dict[str, Any]] = []
        for worker in workers:
            endpoint = str(worker.get("url") or worker.get("endpoint") or "").strip()
            if not endpoint:
                continue
            auth_token = worker.get("auth_token")
            ssl_context = self._ssl_context_for_worker(worker)
            payload = dict(update)
            if payload.get("same_host_only") and not self._is_same_host(endpoint):
                payload["zero_handle"] = ""
                payload["zero_size"] = 0
                payload["zero_type"] = ""
                payload["same_host_only"] = False
            request = urllib.request.Request(
                endpoint.rstrip("/") + "/federated/apply",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(auth_token),
                method="POST",
            )
            open_kwargs: dict[str, Any] = {"timeout": 15}
            if ssl_context is not None:
                open_kwargs["context"] = ssl_context
            try:
                with urllib.request.urlopen(request, **open_kwargs) as response:
                    delivered.append(json.loads(response.read().decode("utf-8")))
            except Exception as exc:
                delivered.append({"applied": False, "worker": endpoint, "error": str(exc)})
        return {
            "attempted": len([worker for worker in workers if str(worker.get("url") or worker.get("endpoint") or "").strip()]),
            "delivered": delivered,
            "applied_count": sum(1 for row in delivered if row.get("applied")),
        }

    def history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._tail_jsonl(self.updates_path, limit=limit)

    def applied_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._tail_jsonl(self.applied_path, limit=limit)

    def status(self) -> dict[str, Any]:
        updates = self.history(limit=200)
        applied = self.applied_history(limit=200)
        namespaces = sorted({str(row.get("namespace") or "default") for row in updates})
        last_update = updates[-1] if updates else {}
        return {
            "update_count": len(updates),
            "applied_count": len(applied),
            "namespaces": namespaces,
            "last_update": last_update,
            "last_applied": applied[-1] if applied else {},
        }

    def _verify(self, update: FederatedInvariantUpdate) -> bool:
        key = self._resolve_key(update.core_id, update.fingerprint)
        if key is None:
            return False
        digest = hmac.new(key, _stable_json(update.envelope()).encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, update.signature)

    def _same_host_transport_allowed(self, update: FederatedInvariantUpdate) -> bool:
        if not update.same_host_only:
            return True
        return True

    def _resolve_key(self, core_id: str, fingerprint: str) -> bytes | None:
        module = load_aion_chronik()
        resolver = module.SignatureResolver(self.storage_root)
        return resolver.resolve(core_id=str(core_id).lower(), fingerprint=str(fingerprint))

    def _derived_key_from_file(self, path: Path) -> tuple[bytes | None, str]:
        if not path.exists():
            return None, ""
        seed = path.read_text(encoding="utf-8").strip()
        if not seed:
            return None, ""
        derived = hashlib.sha256(seed.encode("utf-8") + b"|atheria-daemon").digest()
        fingerprint = hashlib.sha1(derived).hexdigest()[:12]
        return derived, fingerprint

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _tail_jsonl(self, path: Path, *, limit: int) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows[-max(1, int(limit)) :]

    def _headers(self, auth_token: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def _ssl_context_for_worker(self, worker: dict[str, Any]) -> ssl.SSLContext | None:
        cafile = worker.get("cafile")
        if not cafile:
            return None
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(cafile=str(cafile))
        return context

    def _is_same_host(self, endpoint: str) -> bool:
        parsed = urllib.parse.urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"}:
            return True
        with contextlib.suppress(Exception):
            local_host = socket.gethostname().lower()
            if host == local_host:
                return True
            local_fqdn = socket.getfqdn().lower()
            if host == local_fqdn:
                return True
            local_ips = set(socket.gethostbyname_ex(local_host)[2] or [])
            if host in local_ips:
                return True
        return False
