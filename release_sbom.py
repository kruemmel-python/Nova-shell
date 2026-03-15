from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SbomArtifact:
    path: str
    sha256: str
    size: int
    kind: str


def _timestamp_from_epoch(source_date_epoch: int | None) -> str:
    if source_date_epoch is None:
        dt = datetime.now(timezone.utc)
    else:
        dt = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_license(value: str) -> dict[str, Any]:
    if not value:
        return {"license": {"name": "NOASSERTION"}}
    return {"license": {"id": value}} if "-" in value or value.startswith("LicenseRef-") else {"license": {"name": value}}


def _normalize_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _extract_requirement_name(requirement: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return match.group(1) if match else None


def collect_environment_components(dependency_names: list[str]) -> list[dict[str, Any]]:
    if not dependency_names:
        return []

    installed = {
        _normalize_dist_name(dist.metadata.get("Name", "")): dist
        for dist in metadata.distributions()
        if dist.metadata.get("Name")
    }
    queue = [_normalize_dist_name(name) for name in dependency_names]
    seen: set[str] = set()
    components: list[dict[str, Any]] = []

    while queue:
        normalized_name = queue.pop(0)
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        dist = installed.get(normalized_name)
        if dist is None:
            continue
        name = dist.metadata.get("Name")
        version = dist.version
        if not name or not version:
            continue
        licenses: list[dict[str, Any]] = []
        license_value = dist.metadata.get("License", "").strip()
        if license_value:
            licenses.append(_normalize_license(license_value))
        components.append(
            {
                "type": "library",
                "bom-ref": f"pkg:pypi/{name}@{version}",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
                **({"licenses": licenses} if licenses else {}),
            }
        )

        for requirement in dist.requires or []:
            requirement_name = _extract_requirement_name(requirement)
            if requirement_name:
                queue.append(_normalize_dist_name(requirement_name))

    return sorted(components, key=lambda item: item["name"].lower())


def build_cyclonedx_sbom(
    *,
    package_name: str,
    version: str,
    description: str,
    license_id: str,
    artifacts: list[SbomArtifact],
    dependency_names: list[str],
    source_date_epoch: int | None = None,
) -> dict[str, Any]:
    serial = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, package_name + ':' + version)}"
    properties = [
        {"name": "nova-shell:artifact-count", "value": str(len(artifacts))},
    ]
    for artifact in artifacts:
        properties.extend(
            [
                {"name": f"nova-shell:artifact:{artifact.path}:kind", "value": artifact.kind},
                {"name": f"nova-shell:artifact:{artifact.path}:sha256", "value": artifact.sha256},
                {"name": f"nova-shell:artifact:{artifact.path}:size", "value": str(artifact.size)},
            ]
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": serial,
        "version": 1,
        "metadata": {
            "timestamp": _timestamp_from_epoch(source_date_epoch),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "nova-shell-release-tooling",
                        "version": version,
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": f"pkg:generic/{package_name}@{version}",
                "name": package_name,
                "version": version,
                "description": description,
                "licenses": [_normalize_license(license_id)],
            },
            "properties": properties,
        },
        "components": collect_environment_components(dependency_names),
    }


def write_cyclonedx_sbom(
    output_path: Path,
    *,
    package_name: str,
    version: str,
    description: str,
    license_id: str,
    artifact_paths: list[tuple[str, Path, str]],
    dependency_names: list[str],
    source_date_epoch: int | None = None,
) -> Path:
    normalized_artifacts = [
        SbomArtifact(
            path=logical_path,
            sha256=_hash_file(path),
            size=path.stat().st_size,
            kind=kind,
        )
        for logical_path, path, kind in artifact_paths
    ]
    payload = build_cyclonedx_sbom(
        package_name=package_name,
        version=version,
        description=description,
        license_id=license_id,
        artifacts=normalized_artifacts,
        dependency_names=dependency_names,
        source_date_epoch=source_date_epoch,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path
