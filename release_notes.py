from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactEntry:
    kind: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ReleaseManifest:
    name: str
    version: str
    profile: str
    platform_system: str
    platform_machine: str
    artifacts: tuple[ArtifactEntry, ...]
    extras: tuple[str, ...]
    built_at_utc: str


def load_manifests(root: Path) -> list[ReleaseManifest]:
    manifests: list[ReleaseManifest] = []
    for path in sorted(root.rglob("*-manifest.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifests.append(
            ReleaseManifest(
                name=str(payload["name"]),
                version=str(payload["version"]),
                profile=str(payload["profile"]),
                platform_system=str(payload["platform"]["system"]),
                platform_machine=str(payload["platform"]["machine"]),
                artifacts=tuple(
                    ArtifactEntry(
                        kind=str(item["kind"]),
                        path=str(item["path"]),
                        size=int(item["size"]),
                        sha256=str(item["sha256"]),
                    )
                    for item in payload.get("artifacts", [])
                ),
                extras=tuple(str(item) for item in payload.get("extras", [])),
                built_at_utc=str(payload.get("built_at_utc", "")),
            )
        )
    return manifests


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    units = ["B", "KiB", "MiB", "GiB"]
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def render_release_notes(manifests: list[ReleaseManifest]) -> str:
    if not manifests:
        return "# Release Notes\n\nNo manifests were found.\n"

    version = manifests[0].version
    name = manifests[0].name
    grouped: dict[str, list[ReleaseManifest]] = defaultdict(list)
    for manifest in manifests:
        grouped[manifest.platform_system].append(manifest)

    lines = [
        f"# {name} {version}",
        "",
        "## Release Summary",
        "",
        f"- Version: `{version}`",
        f"- Profiles: {', '.join(sorted({manifest.profile for manifest in manifests}))}",
        f"- Platforms: {', '.join(sorted(grouped.keys()))}",
        "",
        "## Artifacts",
        "",
    ]

    for system in sorted(grouped.keys()):
        lines.append(f"### {system}")
        lines.append("")
        for manifest in sorted(grouped[system], key=lambda item: (item.profile, item.platform_machine)):
            extras = ", ".join(manifest.extras) if manifest.extras else "none"
            lines.append(f"- Profile `{manifest.profile}` on `{manifest.platform_machine}`")
            lines.append(f"  Extras: {extras}")
            lines.append(f"  Built: {manifest.built_at_utc}")
            for artifact in manifest.artifacts:
                lines.append(
                    f"  - `{artifact.path}` ({artifact.kind}, {_format_size(artifact.size)}, sha256 `{artifact.sha256[:12]}...`)"
                )
        lines.append("")

    lines.extend(
        [
            "## Verification",
            "",
            "- Verify detached signatures with `gpg --verify <file>.sig <file>`.",
            "- Verify Windows Authenticode signatures with `signtool verify /pa <file>`.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
