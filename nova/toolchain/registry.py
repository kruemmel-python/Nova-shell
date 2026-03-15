from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any


class NovaPackageRegistry:
    """Local registry for Nova modules and packages."""

    def __init__(self, base_path: Path) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = state_dir / "toolchain-registry.json"
        self._lock = threading.RLock()
        if not self.registry_path.exists():
            self.registry_path.write_text(json.dumps({"version": 1, "packages": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

    def publish(
        self,
        name: str,
        version: str,
        entrypoint: str | Path,
        *,
        checksum: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = Path(entrypoint).resolve(strict=False)
        package = {
            "name": name,
            "version": version,
            "entrypoint": str(target),
            "checksum": checksum or self._checksum(target),
            "metadata": dict(metadata or {}),
        }
        payload = self._load()
        payload.setdefault("packages", {}).setdefault(name, {})[version] = package
        self._store(payload)
        return package

    def resolve(self, target: str) -> dict[str, Any] | None:
        name, version = self._split_target(target)
        payload = self._load()
        versions = dict(payload.get("packages", {}).get(name) or {})
        if not versions:
            return None
        if version:
            package = versions.get(version)
            return dict(package) if isinstance(package, dict) else None
        selected = versions[sorted(versions)[-1]]
        return dict(selected) if isinstance(selected, dict) else None

    def list_packages(self) -> list[dict[str, Any]]:
        payload = self._load()
        packages: list[dict[str, Any]] = []
        for versions in payload.get("packages", {}).values():
            if not isinstance(versions, dict):
                continue
            for package in versions.values():
                if isinstance(package, dict):
                    packages.append(dict(package))
        return sorted(packages, key=lambda item: (str(item.get("name")), str(item.get("version"))))

    def snapshot(self) -> dict[str, Any]:
        payload = self._load()
        return {
            "package_count": sum(len(versions) for versions in payload.get("packages", {}).values() if isinstance(versions, dict)),
            "packages": self.list_packages(),
        }

    def _split_target(self, target: str) -> tuple[str, str | None]:
        if "@" not in target:
            return target, None
        name, version = target.rsplit("@", 1)
        return name, version or None

    def _checksum(self, path: Path) -> str:
        if not path.exists():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _load(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _store(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
