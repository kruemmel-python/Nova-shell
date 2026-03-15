from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
METADATA_FILE = ROOT / "packaging" / "release.json"
WIX_NAMESPACE = uuid.UUID("2d0f7b29-2d0e-4a44-8b2f-d1e6d0fdba7e")


@dataclass(frozen=True)
class ReleaseMetadata:
    package_name: str
    package_slug: str
    package_identifier: str
    publisher: str
    description: str
    long_description: str
    maintainer_name: str
    maintainer_email: str
    license: str
    upgrade_code: str
    app_id: str
    homepage: str
    publisher_url: str
    publisher_support_url: str
    moniker: str
    tags: tuple[str, ...]
    linux_categories: tuple[str, ...]
    linux_section: str
    install_scope: str


def load_release_metadata(path: Path | None = None) -> ReleaseMetadata:
    source = path or METADATA_FILE
    defaults = {
        "package_name": "Nova-shell",
        "package_slug": "nova-shell",
        "package_identifier": "NovaShell.NovaShell",
        "publisher": "Nova-shell Team",
        "description": "Unified compute and data orchestration runtime.",
        "long_description": (
            "Nova-shell is a unified compute and data orchestration runtime for "
            "polyglot pipelines, observability, distributed workflows and secure execution."
        ),
        "maintainer_name": "Nova-shell Team",
        "maintainer_email": "packages@nova-shell.invalid",
        "license": "LicenseRef-Proprietary",
        "upgrade_code": "65BF3F20-6FC0-4A8E-84F6-9F6C6953EF2D",
        "app_id": "nova-shell",
        "homepage": "",
        "publisher_url": "",
        "publisher_support_url": "",
        "moniker": "nova-shell",
        "tags": ["cli", "runtime", "orchestration"],
        "linux_categories": ["Development", "Utility"],
        "linux_section": "utils",
        "install_scope": "machine",
    }
    if source.exists():
        loaded = json.loads(source.read_text(encoding="utf-8"))
        defaults.update(loaded)
    return ReleaseMetadata(
        package_name=str(defaults["package_name"]),
        package_slug=str(defaults["package_slug"]),
        package_identifier=str(defaults["package_identifier"]),
        publisher=str(defaults["publisher"]),
        description=str(defaults["description"]),
        long_description=str(defaults["long_description"]),
        maintainer_name=str(defaults["maintainer_name"]),
        maintainer_email=str(defaults["maintainer_email"]),
        license=str(defaults["license"]),
        upgrade_code=str(defaults["upgrade_code"]).upper(),
        app_id=str(defaults["app_id"]),
        homepage=str(defaults.get("homepage", "")),
        publisher_url=str(defaults.get("publisher_url", "")),
        publisher_support_url=str(defaults.get("publisher_support_url", "")),
        moniker=str(defaults.get("moniker", "")),
        tags=tuple(str(tag) for tag in defaults.get("tags", [])),
        linux_categories=tuple(str(item) for item in defaults.get("linux_categories", [])),
        linux_section=str(defaults.get("linux_section", "utils")),
        install_scope=str(defaults.get("install_scope", "machine")),
    )


def to_msi_version(version: str) -> str:
    parts = [int(part) for part in re.findall(r"\d+", version)]
    while len(parts) < 3:
        parts.append(0)
    major = min(parts[0], 255)
    minor = min(parts[1], 255)
    patch = min(parts[2], 65535)
    return f"{major}.{minor}.{patch}"


def machine_to_wix_arch(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"amd64", "x86_64", "x64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return "x86"


def machine_to_winget_arch(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"amd64", "x86_64", "x64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return "x86"


def machine_to_deb_arch(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"amd64", "x86_64", "x64"}:
        return "amd64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    if normalized in {"armv7l", "armhf"}:
        return "armhf"
    return normalized


def installed_size_kib(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            total += path.lstat().st_size
        else:
            total += 1024
    return max(1, (total + 1023) // 1024)


def format_deb_description(summary: str, details: str) -> str:
    lines = [summary]
    for paragraph in details.splitlines():
        if paragraph.strip():
            lines.append(f" {paragraph}")
        else:
            lines.append(" .")
    return "\n".join(lines)


def stable_wix_id(prefix: str, value: str) -> str:
    digest = uuid.uuid5(WIX_NAMESPACE, value).hex[:16]
    return f"{prefix}_{digest}"


def stable_guid(value: str) -> str:
    return str(uuid.uuid5(WIX_NAMESPACE, value)).upper()


def render_wix_source(metadata: ReleaseMetadata, version: str, bundle_dir: Path, executable_name: str) -> str:
    files = sorted(path for path in bundle_dir.rglob("*") if path.is_file())
    rel_dir_set = {Path(".")}
    for file_path in files:
        parent = file_path.relative_to(bundle_dir).parent
        while True:
            rel_dir_set.add(parent)
            if parent == Path("."):
                break
            parent = parent.parent
    rel_dirs = sorted(rel_dir_set, key=lambda item: (len(item.parts), item.as_posix()))
    dir_ids = {Path("."): "INSTALLFOLDER"}
    for rel_dir in rel_dirs:
        if rel_dir == Path("."):
            continue
        dir_ids[rel_dir] = stable_wix_id("DIR", rel_dir.as_posix())

    children: dict[Path, list[Path]] = {}
    for rel_dir in rel_dirs:
        parent = rel_dir.parent if rel_dir != Path(".") else None
        if parent is not None:
            children.setdefault(parent, []).append(rel_dir)

    def render_dir(parent: Path) -> str:
        chunks: list[str] = []
        for child in sorted(children.get(parent, []), key=lambda item: item.name.lower()):
            chunks.append(f'          <Directory Id="{dir_ids[child]}" Name="{escape(child.name)}">')
            nested = render_dir(child)
            if nested:
                chunks.append(nested)
            chunks.append("          </Directory>")
        return "\n".join(chunks)

    directory_markup = render_dir(Path("."))
    component_refs: list[str] = []
    component_fragments: list[str] = []
    files_by_dir: dict[Path, list[Path]] = {}
    for file_path in files:
        rel_path = file_path.relative_to(bundle_dir)
        files_by_dir.setdefault(rel_path.parent, []).append(rel_path)

    for rel_dir, rel_files in sorted(files_by_dir.items(), key=lambda item: item[0].as_posix()):
        lines = [f'  <Fragment>', f'    <DirectoryRef Id="{dir_ids[rel_dir]}">']
        for rel_file in sorted(rel_files, key=lambda item: item.as_posix()):
            comp_id = stable_wix_id("CMP", rel_file.as_posix())
            file_id = stable_wix_id("FIL", rel_file.as_posix())
            component_refs.append(f'      <ComponentRef Id="{comp_id}" />')
            source = escape(str((bundle_dir / rel_file).resolve()))
            lines.extend(
                [
                    f'      <Component Id="{comp_id}" Guid="{stable_guid(rel_file.as_posix())}">',
                    f'        <File Id="{file_id}" Source="{source}" KeyPath="yes" />',
                    "      </Component>",
                ]
            )
        lines.extend(["    </DirectoryRef>", "  </Fragment>"])
        component_fragments.append("\n".join(lines))

    shortcut_target = f"[INSTALLFOLDER]{executable_name}"
    shortcut_fragment = f"""
  <Fragment>
    <DirectoryRef Id="ApplicationProgramsFolder">
      <Component Id="ApplicationShortcut" Guid="{stable_guid('application-shortcut')}">
        <Shortcut Id="ApplicationStartMenuShortcut" Name="{escape(metadata.package_name)}" Target="{escape(shortcut_target)}" WorkingDirectory="INSTALLFOLDER" />
        <RemoveFolder Id="ApplicationProgramsFolderRemove" On="uninstall" />
        <RegistryValue Root="HKCU" Key="Software\\{escape(metadata.publisher)}\\{escape(metadata.package_name)}" Name="installed" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </DirectoryRef>
  </Fragment>""".strip()

    wix_source = f"""
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">
  <Package Name="{escape(metadata.package_name)}"
           Manufacturer="{escape(metadata.publisher)}"
           Version="{to_msi_version(version)}"
           UpgradeCode="{metadata.upgrade_code}"
           Scope="perMachine"
           InstallerVersion="500"
           Compressed="yes">
    <MajorUpgrade AllowSameVersionUpgrades="yes" DowngradeErrorMessage="A newer version of {escape(metadata.package_name)} is already installed." />
    <MediaTemplate EmbedCab="yes" />
    <SummaryInformation Description="{escape(metadata.description)}" Manufacturer="{escape(metadata.publisher)}" />

    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="INSTALLFOLDER" Name="{escape(metadata.package_name)}">
{directory_markup}
      </Directory>
    </StandardDirectory>

    <StandardDirectory Id="ProgramMenuFolder">
      <Directory Id="ApplicationProgramsFolder" Name="{escape(metadata.package_name)}" />
    </StandardDirectory>

    <Feature Id="MainFeature" Title="{escape(metadata.package_name)}" Level="1">
{chr(10).join(component_refs)}
      <ComponentRef Id="ApplicationShortcut" />
    </Feature>
  </Package>

{chr(10).join(component_fragments)}
{shortcut_fragment}
</Wix>
""".strip()
    return wix_source + "\n"


def render_desktop_entry(metadata: ReleaseMetadata) -> str:
    categories = ";".join(metadata.linux_categories) + ";"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={metadata.package_name}\n"
        f"Comment={metadata.description}\n"
        "Exec=nova-shell\n"
        f"Icon={metadata.app_id}\n"
        f"Categories={categories}\n"
        "Terminal=true\n"
    )


def render_appstream_metadata(metadata: ReleaseMetadata) -> str:
    homepage = f'    <url type="homepage">{escape(metadata.homepage)}</url>\n' if metadata.homepage else ""
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<component type=\"desktop-application\">\n"
        f"  <id>{metadata.app_id}.desktop</id>\n"
        f"  <name>{escape(metadata.package_name)}</name>\n"
        f"  <summary>{escape(metadata.description)}</summary>\n"
        "  <metadata_license>CC0-1.0</metadata_license>\n"
        f"  <project_license>{escape(metadata.license)}</project_license>\n"
        "  <description>\n"
        f"    <p>{escape(metadata.long_description)}</p>\n"
        "  </description>\n"
        f"{homepage}"
        "</component>\n"
    )


def render_winget_manifests(
    metadata: ReleaseMetadata,
    version: str,
    installer_url: str,
    installer_sha256: str,
    architecture: str,
) -> dict[str, str]:
    def optional_line(key: str, value: str) -> str:
        return f'{key}: "{value}"\n' if value else ""

    tags_block = "".join(f"  - {tag}\n" for tag in metadata.tags)
    version_manifest = (
        f'PackageIdentifier: "{metadata.package_identifier}"\n'
        f'PackageVersion: "{version}"\n'
        'DefaultLocale: "en-US"\n'
        'ManifestType: "version"\n'
        'ManifestVersion: "1.6.0"\n'
    )
    locale_manifest = (
        f'PackageIdentifier: "{metadata.package_identifier}"\n'
        f'PackageVersion: "{version}"\n'
        'PackageLocale: "en-US"\n'
        f'Publisher: "{metadata.publisher}"\n'
        f'PackageName: "{metadata.package_name}"\n'
        f'License: "{metadata.license}"\n'
        f'ShortDescription: "{metadata.description}"\n'
        f'Description: "{metadata.long_description}"\n'
        f'{optional_line("Moniker", metadata.moniker)}'
        f'{optional_line("PublisherUrl", metadata.publisher_url)}'
        f'{optional_line("PublisherSupportUrl", metadata.publisher_support_url)}'
        f'{optional_line("PackageUrl", metadata.homepage)}'
        + ("Tags:\n" + tags_block if tags_block else "")
        + 'ManifestType: "defaultLocale"\n'
        + 'ManifestVersion: "1.6.0"\n'
    )
    installer_manifest = (
        f'PackageIdentifier: "{metadata.package_identifier}"\n'
        f'PackageVersion: "{version}"\n'
        'InstallerType: "wix"\n'
        f'Scope: "{metadata.install_scope}"\n'
        'Installers:\n'
        f'  - Architecture: "{architecture}"\n'
        f'    InstallerUrl: "{installer_url}"\n'
        f'    InstallerSha256: "{installer_sha256}"\n'
        'ManifestType: "installer"\n'
        'ManifestVersion: "1.6.0"\n'
    )
    return {
        "version": version_manifest,
        "defaultLocale": locale_manifest,
        "installer": installer_manifest,
    }
