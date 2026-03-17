from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


INLINE_BLOB_PREFIX = "nsblob:"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-")
    return cleaned or "blob"


def _urlsafe_b64encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _urlsafe_b64decode(payload: str) -> bytes:
    return base64.urlsafe_b64decode(payload.encode("ascii"))


@dataclass(slots=True)
class NovaBlobSeed:
    version: int
    name: str
    kind: str
    source_name: str
    entrypoint: str
    compression: str
    encoding: str
    sha256: str
    compressed_sha256: str
    original_size: int
    compressed_size: int
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    payload: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "kind": self.kind,
            "source_name": self.source_name,
            "entrypoint": self.entrypoint,
            "compression": self.compression,
            "encoding": self.encoding,
            "sha256": self.sha256,
            "compressed_sha256": self.compressed_sha256,
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "created_at": round(self.created_at, 6),
            "metadata": self.metadata,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NovaBlobSeed":
        return cls(
            version=int(payload.get("version") or 1),
            name=str(payload.get("name") or "blob"),
            kind=str(payload.get("kind") or "text"),
            source_name=str(payload.get("source_name") or ""),
            entrypoint=str(payload.get("entrypoint") or ""),
            compression=str(payload.get("compression") or "zlib"),
            encoding=str(payload.get("encoding") or "base64url"),
            sha256=str(payload.get("sha256") or ""),
            compressed_sha256=str(payload.get("compressed_sha256") or ""),
            original_size=int(payload.get("original_size") or 0),
            compressed_size=int(payload.get("compressed_size") or 0),
            created_at=float(payload.get("created_at") or time.time()),
            metadata=dict(payload.get("metadata") or {}),
            payload=str(payload.get("payload") or ""),
        )


class NovaBlobGenerator:
    """Pack, verify and rehydrate compact Nova-shell blob seeds."""

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = Path(storage_root).resolve(strict=False)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.storage_root / "ns_blobs"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def detect_kind(self, *, file_path: Path | None = None, explicit_kind: str = "", data: bytes | None = None) -> str:
        chosen = explicit_kind.strip().lower()
        if chosen and chosen != "auto":
            return chosen
        if file_path is not None:
            lowered = file_path.suffix.lower()
            if lowered == ".ns":
                return "ns"
            if lowered == ".py":
                return "py"
            if lowered in {".txt", ".md", ".json", ".yaml", ".yml", ".csv"}:
                return "text"
        payload = bytes(data or b"")
        try:
            payload.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            return "bin"

    def create_from_bytes(
        self,
        data: bytes,
        *,
        name: str = "",
        kind: str = "text",
        source_name: str = "",
        entrypoint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NovaBlobSeed:
        compressed = zlib.compress(data, level=9)
        return NovaBlobSeed(
            version=1,
            name=_safe_name(name or source_name or "blob"),
            kind=kind,
            source_name=source_name,
            entrypoint=entrypoint,
            compression="zlib",
            encoding="base64url",
            sha256=hashlib.sha256(data).hexdigest(),
            compressed_sha256=hashlib.sha256(compressed).hexdigest(),
            original_size=len(data),
            compressed_size=len(compressed),
            created_at=time.time(),
            metadata=dict(metadata or {}),
            payload=_urlsafe_b64encode(compressed),
        )

    def create_from_text(
        self,
        text: str,
        *,
        name: str = "",
        kind: str = "text",
        source_name: str = "",
        entrypoint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NovaBlobSeed:
        return self.create_from_bytes(
            text.encode("utf-8"),
            name=name,
            kind=kind,
            source_name=source_name,
            entrypoint=entrypoint,
            metadata=metadata,
        )

    def create_from_file(
        self,
        path: Path,
        *,
        kind: str = "auto",
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NovaBlobSeed:
        target = Path(path).resolve(strict=False)
        data = target.read_bytes()
        detected_kind = self.detect_kind(file_path=target, explicit_kind=kind, data=data)
        entrypoint = detected_kind if detected_kind in {"py", "ns"} else ""
        return self.create_from_bytes(
            data,
            name=name or target.stem,
            kind=detected_kind,
            source_name=str(target),
            entrypoint=entrypoint,
            metadata=metadata,
        )

    def inline_seed(self, blob: NovaBlobSeed) -> str:
        payload = json.dumps(blob.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return INLINE_BLOB_PREFIX + _urlsafe_b64encode(payload)

    def write_blob(self, blob: NovaBlobSeed, output_path: Path | None = None) -> Path:
        target = Path(output_path).resolve(strict=False) if output_path is not None else self.default_path(blob)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(blob.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def default_path(self, blob: NovaBlobSeed) -> Path:
        name = _safe_name(blob.name)
        return self.state_dir / f"{name}-{blob.sha256[:12]}.nsblob.json"

    def load_blob(self, reference: Any) -> NovaBlobSeed:
        if isinstance(reference, NovaBlobSeed):
            return reference
        if isinstance(reference, dict):
            return NovaBlobSeed.from_dict(reference)
        value = str(reference).strip()
        if not value:
            raise ValueError("blob reference is required")
        if value.startswith(INLINE_BLOB_PREFIX):
            raw = _urlsafe_b64decode(value[len(INLINE_BLOB_PREFIX) :])
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("inline blob seed must decode to an object")
            return NovaBlobSeed.from_dict(payload)
        candidate = Path(value)
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("blob file must contain an object")
            return NovaBlobSeed.from_dict(payload)
        if value.startswith("{"):
            payload = json.loads(value)
            if not isinstance(payload, dict):
                raise ValueError("blob JSON must contain an object")
            return NovaBlobSeed.from_dict(payload)
        raise FileNotFoundError(f"blob reference not found: {value}")

    def verify(self, blob: NovaBlobSeed) -> dict[str, Any]:
        compressed = _urlsafe_b64decode(blob.payload)
        compressed_sha = hashlib.sha256(compressed).hexdigest()
        integrity_ok = compressed_sha == blob.compressed_sha256
        if not integrity_ok:
            return {
                "verified": False,
                "reason": "compressed_sha256_mismatch",
                "sha256": blob.sha256,
                "compressed_sha256": blob.compressed_sha256,
            }
        raw = zlib.decompress(compressed)
        raw_sha = hashlib.sha256(raw).hexdigest()
        verified = raw_sha == blob.sha256
        return {
            "verified": verified,
            "reason": "" if verified else "sha256_mismatch",
            "sha256": blob.sha256,
            "compressed_sha256": blob.compressed_sha256,
            "original_size": blob.original_size,
            "compressed_size": blob.compressed_size,
            "compression_ratio": round(blob.compressed_size / max(1, blob.original_size), 6),
        }

    def unpack_bytes(self, blob: NovaBlobSeed) -> bytes:
        verification = self.verify(blob)
        if not verification.get("verified"):
            raise ValueError(f"blob verification failed: {verification.get('reason') or 'invalid_blob'}")
        return zlib.decompress(_urlsafe_b64decode(blob.payload))

    def unpack_text(self, blob: NovaBlobSeed) -> str:
        return self.unpack_bytes(blob).decode("utf-8")
