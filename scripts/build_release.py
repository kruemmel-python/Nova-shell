from __future__ import annotations

import argparse
import contextlib
import faulthandler
import fnmatch
import hashlib
import importlib.metadata as importlib_metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova_shell import __version__
from release_packaging import (
    load_release_metadata,
    machine_to_deb_arch,
    machine_to_winget_arch,
    machine_to_wix_arch,
    render_appstream_metadata,
    render_desktop_entry,
    render_winget_manifests,
    render_wix_source,
    installed_size_kib,
    format_deb_description,
)
from release_sbom import write_cyclonedx_sbom
from release_signing import (
    find_artifacts_for_windows_signing,
    require_signtool,
    sign_windows_artifact,
    verify_windows_artifact,
)

PROJECT_SLUG = "nova-shell"
ENTRY_MODULE = ROOT / "nova_shell.py"
PACKAGING_DIR = ROOT / "packaging"
ASSETS_DIR = PACKAGING_DIR / "assets"
LINUX_DIR = PACKAGING_DIR / "linux"
RUNTIME_CONFIG_FILE = "nova-shell-runtime.json"
PROFILE_EXTRAS = {
    "core": ["observability", "guard", "arrow", "wasm", "gpu", "atheria"],
    "enterprise": ["observability", "guard", "arrow", "wasm", "gpu", "atheria"],
}
PROFILE_NUITKA_PACKAGES = {
    "observability": ["psutil"],
    "guard": ["yaml"],
    "wasm": ["wasmtime"],
    "gpu": ["numpy", "pyopencl"],
    "atheria": ["unittest", "xml"],
}
PROFILE_NUITKA_MODULES = {
    "arrow": ["pyarrow", "pyarrow.csv", "pyarrow.flight"],
    "atheria": ["ctypes.util", "ctypes.wintypes", "pdb"],
}
PROFILE_NUITKA_NOFOLLOW = {
    "arrow": ["pyarrow.tests", "pyarrow.vendored"],
}
LOCAL_RUNTIME_DIRS = ["Atheria", "WIKI", "nova", "examples", "agent-skills-main"]
LOCAL_RUNTIME_FILES = [
    "industry_scanner.py",
    "trend_rss_sensor.py",
    "watch_the_big_players.ns",
    "watch_the_big_players_test.ns",
    "nova_project_monitor.ns",
    "morning_briefing.ns",
    "sample_news.json",
    "beispiel_rss.md",
    "morning_briefing.md",
    "THIRD_PARTY_NOTICES.md",
]
LOCAL_RUNTIME_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".nova",
    ".nova_ceo",
    ".nova_lens",
    ".nova_project_monitor",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    ".DS_Store",
    "Thumbs.db",
)
WINDOWS_INSTALLER_SUPPORT_FILES = [
    "scripts/upgrade_windows_install.ps1",
    "scripts/upgrade_windows_install.README.txt",
]
HEAVY_SIDELOAD_DISTRIBUTIONS = {"torch"}
HEARTBEAT_SECONDS = 30
TRACE_FILE_ENV = "NOVA_BUILD_TRACE_FILE"
FAULT_FILE_ENV = "NOVA_BUILD_FAULT_FILE"
_FAULT_HANDLE: object | None = None
SIDELOAD_PACKAGE_DIR = "vendor-py"
BUNDLED_TOOLCHAIN_DIR = "toolchains"
EMSDK_REPOSITORY_URL = "https://github.com/emscripten-core/emsdk.git"
EMSDK_VERSION = str(os.environ.get("NOVA_EMSDK_VERSION") or "5.0.3").strip() or "5.0.3"
EMSDK_WRAPPER_NAME = "nova-emcc.bat"
PYTHON_RUNTIME_DIR = "python"
PYTHON_STDLIB_EXCLUDES = {
    "__pycache__",
    "ensurepip",
    "idlelib",
    "site-packages",
    "test",
    "tests",
    "tkinter",
    "turtledemo",
    "venv",
}


@dataclass
class ArtifactRecord:
    kind: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BuildContext:
    source_date_epoch: int | None
    timestamp_utc: str
    env: dict[str, str]


def iso_timestamp(source_date_epoch: int | None) -> str:
    if source_date_epoch is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(source_date_epoch, tz=timezone.utc).isoformat()


def default_source_date_epoch() -> int | None:
    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid SOURCE_DATE_EPOCH value: {raw!r}") from exc


def extract_requirement_names(requirements: list[str]) -> list[str]:
    names: list[str] = []
    for requirement in requirements:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        if match:
            names.append(match.group(1))
    return names


def safe_path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def safe_path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _is_windows_runtime() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def safe_system_name() -> str:
    if _is_windows_runtime():
        return "Windows"
    if sys.platform == "darwin":
        return "Darwin"
    if sys.platform.startswith("linux"):
        return "Linux"
    value = platform.system().strip()
    return value or sys.platform


def safe_machine_name() -> str:
    value = ""
    if _is_windows_runtime():
        value = os.environ.get("PROCESSOR_ARCHITEW6432", "") or os.environ.get("PROCESSOR_ARCHITECTURE", "")
    if not value:
        value = platform.machine()
    normalized = value.strip().lower()
    aliases = {
        "x64": "amd64",
        "x86_64": "amd64",
        "amd64": "amd64",
        "x86": "x86",
        "i386": "x86",
        "i686": "x86",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    return aliases.get(normalized, normalized or "unknown")


def safe_platform_string() -> str:
    if _is_windows_runtime():
        version = sys.getwindowsversion()
        return f"Windows-{version.major}.{version.minor}.{version.build}-{safe_machine_name()}"
    if sys.platform.startswith("linux"):
        return f"Linux-{safe_machine_name()}"
    if sys.platform == "darwin":
        return f"Darwin-{safe_machine_name()}"
    return platform.platform()


def load_profile_dependencies(profile: str) -> list[str]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        payload = tomllib.load(handle)
    project = payload.get("project", {})
    requirements = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extra in PROFILE_EXTRAS[profile]:
        requirements.extend(optional.get(extra, []))
    return extract_requirement_names(requirements)


def collect_nuitka_packages(profile: str) -> list[str]:
    packages: list[str] = []
    for extra in PROFILE_EXTRAS[profile]:
        packages.extend(PROFILE_NUITKA_PACKAGES.get(extra, []))
    unique_packages = sorted(dict.fromkeys(packages))
    sideload = set(collect_sideload_packages(profile))
    if sideload:
        unique_packages = [package_name for package_name in unique_packages if package_name not in sideload]
    return unique_packages


def collect_nuitka_modules(profile: str) -> list[str]:
    modules: list[str] = []
    for extra in PROFILE_EXTRAS[profile]:
        modules.extend(PROFILE_NUITKA_MODULES.get(extra, []))
    sideload = set(collect_sideload_packages(profile))
    unique_modules = sorted(dict.fromkeys(modules))
    if sideload:
        unique_modules = [
            module_name
            for module_name in unique_modules
            if module_name.split(".", 1)[0] not in sideload
        ]
    return unique_modules


def collect_nuitka_nofollow(profile: str) -> list[str]:
    modules: list[str] = []
    for extra in PROFILE_EXTRAS[profile]:
        modules.extend(PROFILE_NUITKA_NOFOLLOW.get(extra, []))
    modules.extend(collect_sideload_packages(profile))
    if _is_windows_runtime() and profile in {"core", "enterprise"}:
        modules.append("nova")
    return sorted(dict.fromkeys(modules))


def collect_nuitka_compile_flags(profile: str) -> list[str]:
    flags: list[str] = []
    if _is_windows_runtime() and profile in {"core", "enterprise"}:
        flags.extend(
            [
                "--disable-ccache",
                "--low-memory",
                "--jobs=1",
                "--lto=no",
            ]
        )
    return flags


def collect_sideload_packages(profile: str) -> list[str]:
    packages: list[str] = []
    if profile == "core" and "observability" in PROFILE_EXTRAS[profile]:
        packages.append("psutil")
    if profile == "core" and "guard" in PROFILE_EXTRAS[profile]:
        packages.append("yaml")
    if "arrow" in PROFILE_EXTRAS[profile]:
        packages.append("pyarrow")
    if "wasm" in PROFILE_EXTRAS[profile]:
        packages.append("wasmtime")
    if "gpu" in PROFILE_EXTRAS[profile]:
        packages.append("numpy")
    if "atheria" in PROFILE_EXTRAS[profile]:
        packages.append("torch")
    if "gpu" in PROFILE_EXTRAS[profile] and _is_windows_runtime():
        packages.append("pyopencl")
    return list(dict.fromkeys(packages))


def collect_local_runtime_directories() -> list[Path]:
    directories: list[Path] = []
    for relative_name in LOCAL_RUNTIME_DIRS:
        candidate = (ROOT / relative_name).resolve()
        if candidate.exists() and candidate.is_dir():
            directories.append(candidate)
    return directories


def collect_local_runtime_files() -> list[Path]:
    files: list[Path] = []
    for relative_name in LOCAL_RUNTIME_FILES:
        candidate = (ROOT / relative_name).resolve()
        if candidate.exists() and candidate.is_file():
            files.append(candidate)
    return files


def collect_nuitka_deployment_flags(profile: str) -> list[str]:
    flags = ["self-execution"]
    if collect_sideload_packages(profile):
        flags.append("excluded-module-usage")
    return flags


def build_nuitka_command(profile: str, python_exe: str, out_dir: Path) -> list[str]:
    command = [python_exe, "-m", "nuitka"]
    command.extend(
        [
            "--standalone",
            "--assume-yes-for-downloads",
            "--follow-imports",
        ]
    )
    for deployment_flag in collect_nuitka_deployment_flags(profile):
        command.append(f"--no-deployment-flag={deployment_flag}")
    command.extend(collect_nuitka_compile_flags(profile))
    for package_name in collect_nuitka_packages(profile):
        command.append(f"--include-package={package_name}")
    for module_name in collect_nuitka_modules(profile):
        command.append(f"--include-module={module_name}")
    for module_name in collect_nuitka_nofollow(profile):
        command.append(f"--nofollow-import-to={module_name}")
    command.extend(
        [
            f"--output-dir={out_dir}",
            str(ENTRY_MODULE),
        ]
    )
    return command


def create_build_context(source_date_epoch: int | None) -> BuildContext:
    env = os.environ.copy()
    env.setdefault("PYTHONHASHSEED", "0")
    env.setdefault("TZ", "UTC")
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")
    if _is_windows_runtime():
        env.setdefault("CFLAGS", "/Zm2000 /Od")
    if source_date_epoch is not None:
        env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    return BuildContext(
        source_date_epoch=source_date_epoch,
        timestamp_utc=iso_timestamp(source_date_epoch),
        env=env,
    )


def ensure_windows_msvc_environment() -> None:
    if os.name != "nt":
        return

    include_value = os.environ.get("INCLUDE", "").strip()
    include_paths = [Path(entry) for entry in include_value.split(os.pathsep) if entry]
    if any((path / "excpt.h").exists() for path in include_paths):
        return

    hints: list[str] = [
        "Windows native build environment is not initialized correctly.",
        "The MSVC header 'excpt.h' is not reachable via INCLUDE.",
    ]
    if not include_value:
        hints.append("INCLUDE is currently empty.")

    visual_studio_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio"
    if visual_studio_root.exists():
        located_header = next(visual_studio_root.rglob("excpt.h"), None)
        if located_header is not None:
            hints.append(f"Build Tools appear to be installed at '{located_header.parent}', but the developer environment was not loaded.")

    hints.append("Use 'scripts/build_windows.ps1', which bootstraps VsDevCmd automatically, or run the build from 'x64 Native Tools PowerShell/Command Prompt for VS 2022'.")
    raise SystemExit(" ".join(hints))


def step(message: str) -> None:
    trace(message)
    print(f"==> {message}", flush=True)


def format_duration(seconds: float) -> str:
    total = int(seconds)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def trace(message: str) -> None:
    target = os.environ.get(TRACE_FILE_ENV, "").strip()
    if not target:
        return
    try:
        trace_path = Path(target)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except Exception:
        pass


def enable_fault_dumps() -> None:
    global _FAULT_HANDLE
    target = os.environ.get(FAULT_FILE_ENV, "").strip()
    if not target:
        return
    try:
        fault_path = Path(target)
        fault_path.parent.mkdir(parents=True, exist_ok=True)
        _FAULT_HANDLE = fault_path.open("a", encoding="utf-8")
        timestamp = datetime.now(timezone.utc).isoformat()
        _FAULT_HANDLE.write(f"{timestamp} faulthandler enabled\n")
        _FAULT_HANDLE.flush()
        faulthandler.enable(file=_FAULT_HANDLE, all_threads=True)
        # Periodic faulthandler dumps have triggered native access violations
        # on Windows during large filesystem staging operations.
        if periodic_fault_dumps_enabled():
            faulthandler.dump_traceback_later(30, repeat=True, file=_FAULT_HANDLE)
    except Exception:
        _FAULT_HANDLE = None


def periodic_fault_dumps_enabled() -> bool:
    return os.name != "nt"


def run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    label: str | None = None,
    heartbeat_seconds: int = HEARTBEAT_SECONDS,
) -> None:
    if label:
        step(label)
    trace("run command: " + " ".join(cmd))
    print("+", " ".join(cmd), flush=True)
    started = time.monotonic()
    next_heartbeat = started + heartbeat_seconds
    process = subprocess.Popen(cmd, cwd=cwd, env=env)
    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                if returncode != 0:
                    raise SystemExit(returncode)
                return
            now = time.monotonic()
            if now >= next_heartbeat:
                description = label or Path(cmd[0]).name
                step(f"{description} still running ({format_duration(now - started)})")
                next_heartbeat += heartbeat_seconds
            time.sleep(1)
    except KeyboardInterrupt:
        with contextlib.suppress(Exception):
            process.terminate()
        raise


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def record(kind: str, path: Path) -> ArtifactRecord:
    return ArtifactRecord(
        kind=kind,
        path=display_path(path),
        size=path.stat().st_size,
        sha256=sha256sum(path),
    )


def discover_python_artifacts(out_dir: Path) -> list[Path]:
    return sorted(path for path in out_dir.iterdir() if path.is_file())


def find_bundle_dir(output_dir: Path) -> Path:
    dist_dirs = sorted(path for path in output_dir.rglob("*.dist") if path.is_dir())
    if not dist_dirs:
        raise FileNotFoundError(f"no standalone bundle directory found in {output_dir}")
    return dist_dirs[0]


def find_executable(bundle_dir: Path) -> Path:
    preferred = {"nova-shell", "nova_shell"}
    candidates: list[Path] = []
    for path in bundle_dir.rglob("*"):
        if not path.is_file():
            continue
        stem = path.stem.lower()
        name = path.name.lower()
        if stem in preferred or name in {f"{item}.exe" for item in preferred}:
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"no executable found in {bundle_dir}")
    candidates.sort(key=lambda item: (len(item.parts), len(item.name)))
    return candidates[0]


def normalize_tree_timestamps(root: Path, source_date_epoch: int | None) -> None:
    if source_date_epoch is None:
        return
    for path in sorted(root.rglob("*")):
        with contextlib.suppress(FileNotFoundError):
            os.utime(path, (source_date_epoch, source_date_epoch), follow_symlinks=False)
    with contextlib.suppress(FileNotFoundError):
        os.utime(root, (source_date_epoch, source_date_epoch), follow_symlinks=False)


def normalize_file_timestamp(path: Path, source_date_epoch: int | None) -> None:
    if source_date_epoch is None:
        return
    with contextlib.suppress(FileNotFoundError, NotImplementedError):
        os.utime(path, (source_date_epoch, source_date_epoch), follow_symlinks=False)


def _relative_archive_name(path: Path, root: Path) -> str:
    return os.path.relpath(os.fspath(path), os.fspath(root)).replace("\\", "/")


def archive_bundle(bundle_dir: Path, archive_base: Path, *, source_date_epoch: int | None) -> Path:
    members = sorted(path for path in bundle_dir.rglob("*"))
    if os.name == "nt":
        archive_path = archive_base.parent / f"{archive_base.name}.zip"
        tar_executable = shutil.which("tar.exe") or shutil.which("tar")
        if tar_executable:
            with contextlib.suppress(FileNotFoundError):
                archive_path.unlink()
            subprocess.run(
                [
                    tar_executable,
                    "-a",
                    "-c",
                    "-f",
                    os.fspath(archive_path),
                    "-C",
                    os.fspath(bundle_dir.parent),
                    bundle_dir.name,
                ],
                check=True,
            )
            normalize_file_timestamp(archive_path, source_date_epoch)
            return archive_path
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in members:
                if path.is_dir():
                    continue
                rel_name = _relative_archive_name(path, bundle_dir.parent)
                info = zipfile.ZipInfo(rel_name)
                dt = (
                    datetime.fromtimestamp(max(source_date_epoch, 315532800), tz=timezone.utc)
                    if source_date_epoch is not None
                    else datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                )
                info.date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                with path.open("rb") as handle:
                    with zf.open(info, "w") as archive_handle:
                        shutil.copyfileobj(handle, archive_handle, length=1024 * 1024)
        return archive_path

    archive_path = archive_base.parent / f"{archive_base.name}.tar.gz"
    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        for path in members:
            rel_name = _relative_archive_name(path, bundle_dir.parent)
            info = tf.gettarinfo(str(path), arcname=rel_name)
            if source_date_epoch is not None:
                info.mtime = source_date_epoch
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
            if info.isfile():
                with path.open("rb") as handle:
                    tf.addfile(info, handle)
            else:
                tf.addfile(info)
    return archive_path


def remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path)
        return
    except PermissionError as exc:
        raise SystemExit(
            f"failed to clean build root '{path}'. Close any running nova_shell.exe instances or processes holding files in that directory, then retry."
        ) from exc


def write_manifest(target_dir: Path, profile: str, artifacts: list[ArtifactRecord], *, build_context: BuildContext) -> Path:
    manifest = {
        "name": PROJECT_SLUG,
        "version": __version__,
        "profile": profile,
        "platform": {
            "system": safe_system_name(),
            "machine": safe_machine_name(),
            "platform": safe_platform_string(),
        },
        "built_at_utc": build_context.timestamp_utc,
        "artifacts": [artifact.__dict__ for artifact in artifacts],
        "extras": PROFILE_EXTRAS[profile],
    }
    manifest_path = target_dir / f"{PROJECT_SLUG}-{__version__}-{profile}-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def write_checksums(target_dir: Path, artifacts: list[ArtifactRecord], manifest_path: Path) -> Path:
    checksums_path = target_dir / f"{PROJECT_SLUG}-{__version__}-SHA256SUMS.txt"
    lines = [f"{artifact.sha256}  {artifact.path}" for artifact in artifacts]
    lines.append(f"{sha256sum(manifest_path)}  {display_path(manifest_path)}")
    checksums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksums_path


def write_subject_checksums(target_dir: Path, profile: str, artifacts: list[ArtifactRecord]) -> Path:
    checksums_path = target_dir / f"{PROJECT_SLUG}-{__version__}-{profile}-subjects.checksums.txt"
    lines = [f"{artifact.sha256}  {artifact.path}" for artifact in artifacts]
    checksums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksums_path


def build_python_artifacts(python_exe: str, out_dir: Path, *, build_context: BuildContext) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run(
        [python_exe, "-m", "build", "--sdist", "--wheel", "--outdir", str(out_dir)],
        env=build_context.env,
        label="Building Python source and wheel artifacts",
    )
    return discover_python_artifacts(out_dir)


def build_standalone(python_exe: str, out_dir: Path, profile: str, *, build_context: BuildContext) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_windows_msvc_environment()
    run(
        build_nuitka_command(profile, python_exe, out_dir),
        env=build_context.env,
        label=f"Building standalone {profile} binary with Nuitka",
    )
    try:
        bundle_dir = find_bundle_dir(out_dir)
        executable = find_executable(bundle_dir)
    except FileNotFoundError as exc:
        guidance = [
            "standalone build did not produce a runnable executable.",
            "Verify the local C toolchain and platform SDK are complete.",
        ]
        if os.name == "nt":
            guidance.append("On Windows, install Visual Studio Build Tools with the C++ workload and Windows SDK headers.")
        else:
            guidance.append("On Linux, install a supported C compiler plus patchelf.")
        raise SystemExit(" ".join(guidance)) from exc
    normalize_tree_timestamps(bundle_dir, build_context.source_date_epoch)
    return bundle_dir, executable


def smoke_test_executable(python_exe: str, executable: Path, profile: str) -> None:
    run(
        [python_exe, str(ROOT / "scripts" / "smoke_test_release.py"), "--profile", profile, str(executable)],
        label="Running standalone smoke tests",
    )


def prune_bundle_runtime_state(bundle_dir: Path) -> None:
    for relative in (".nova_lens", "toolchains/emsdk-cache"):
        target = bundle_dir / relative
        if target.exists():
            remove_tree(target)


def ensure_bundle(build_root: Path, python_exe: str, profile: str, *, rebuild: bool, build_context: BuildContext) -> tuple[Path, Path]:
    standalone_dir = build_root / "standalone"
    if rebuild or not standalone_dir.exists():
        return build_standalone(python_exe, standalone_dir, profile, build_context=build_context)
    bundle_dir = find_bundle_dir(standalone_dir)
    executable = find_executable(bundle_dir)
    normalize_tree_timestamps(bundle_dir, build_context.source_date_epoch)
    return bundle_dir, executable


def require_tool(name: str, guidance: str) -> str:
    tool = shutil.which(name)
    if not tool:
        raise SystemExit(guidance)
    return tool


def copytree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    safe_copytree(src, dst)


def ignored_names(names: list[str], patterns: tuple[str, ...]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
            ignored.add(name)
    return ignored


def native_fs_path(path: Path) -> str:
    resolved = os.fspath(path)
    if os.name != "nt":
        return resolved
    absolute = os.path.abspath(resolved)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute.lstrip("\\")
    return "\\\\?\\" + absolute


def safe_copy2_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(native_fs_path(src), "rb") as source_handle, open(native_fs_path(dst), "wb") as target_handle:
        while True:
            chunk = source_handle.read(256 * 1024)
            if not chunk:
                break
            target_handle.write(chunk)
    with contextlib.suppress(OSError):
        stat_result = os.stat(native_fs_path(src))
        os.chmod(native_fs_path(dst), stat.S_IMODE(stat_result.st_mode))
        os.utime(native_fs_path(dst), (stat_result.st_atime, stat_result.st_mtime))


def safe_copytree(
    src: Path,
    dst: Path,
    *,
    ignore_patterns: tuple[str, ...] = (),
    prefer_robocopy: bool = True,
) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    src = src.resolve()
    dst.mkdir(parents=True, exist_ok=True)
    if os.name == "nt" and prefer_robocopy:
        command = [
            "robocopy",
            str(src),
            str(dst),
            "/E",
            "/COPY:DAT",
            "/DCOPY:DAT",
            "/R:2",
            "/W:1",
            "/XJ",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ]
        exclude_dirs = [pattern for pattern in ignore_patterns if "*" not in pattern and "?" not in pattern and not pattern.startswith("*.")]
        exclude_files = [pattern for pattern in ignore_patterns if pattern not in exclude_dirs]
        if exclude_dirs:
            command.append("/XD")
            command.extend(exclude_dirs)
        if exclude_files:
            command.append("/XF")
            command.extend(exclude_files)
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if completed.returncode > 7:
            raise SystemExit(
                f"robocopy failed while copying '{src}' to '{dst}' with exit code {completed.returncode}.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return
    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        relative_root = root_path.relative_to(src)
        target_root = dst / relative_root
        target_root.mkdir(parents=True, exist_ok=True)

        ignored_dirs = ignored_names(dirs, ignore_patterns)
        dirs[:] = [name for name in dirs if name not in ignored_dirs]
        ignored_files = ignored_names(files, ignore_patterns)

        for directory_name in list(dirs):
            source_dir = root_path / directory_name
            target_dir = target_root / directory_name
            if source_dir.is_symlink():
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.symlink(os.readlink(source_dir), target_dir, target_is_directory=True)
                    dirs.remove(directory_name)
                    continue
                except OSError:
                    pass
            target_dir.mkdir(parents=True, exist_ok=True)

        for file_name in files:
            if file_name in ignored_files:
                continue
            source_file = root_path / file_name
            target_file = target_root / file_name
            target_file.parent.mkdir(parents=True, exist_ok=True)
            if source_file.is_symlink():
                try:
                    os.symlink(os.readlink(source_file), target_file)
                    continue
                except OSError:
                    pass
            safe_copy2_file(source_file, target_file)


def copytree_filtered(src: Path, dst: Path) -> None:
    safe_copytree(src, dst, ignore_patterns=("__pycache__", "*.pyc", "*.pyo"))


def copy_file_filtered(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    safe_copy2_file(src, dst)


def resolve_distribution_names(package_name: str) -> list[str]:
    mapping = importlib_metadata.packages_distributions()
    return sorted(dict.fromkeys(mapping.get(package_name, [package_name])))


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        make_executable(path)


def collect_sideload_distributions(package_names: list[str]) -> list[importlib_metadata.Distribution]:
    queue: list[str] = []
    for package_name in package_names:
        queue.extend(resolve_distribution_names(package_name))
    seen: set[str] = set()
    distributions: list[importlib_metadata.Distribution] = []
    while queue:
        distribution_name = queue.pop(0)
        normalized = distribution_name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            distribution = importlib_metadata.distribution(distribution_name)
        except importlib_metadata.PackageNotFoundError:
            continue
        distributions.append(distribution)
        for requirement_name in extract_requirement_names(list(distribution.requires or [])):
            queue.append(requirement_name)
    return distributions


def distribution_name(distribution: importlib_metadata.Distribution) -> str:
    with contextlib.suppress(Exception):
        value = str(distribution.metadata.get("Name", "")).strip().lower()
        if value:
            return value
    distribution_path = Path(distribution._path)
    return distribution_path.name.split("-", 1)[0].strip().lower()


def read_top_level_entries(distribution: importlib_metadata.Distribution) -> list[str]:
    return [
        entry.strip()
        for entry in (distribution.read_text("top_level.txt") or "").splitlines()
        if entry.strip()
    ]


def stage_sideload_top_level_entries(
    distribution: importlib_metadata.Distribution,
    sideload_root: Path,
    copied: set[str],
    *,
    top_level_entries: list[str] | None = None,
) -> None:
    try:
        distribution_path = Path(distribution._path).resolve()
    except OSError:
        return
    site_packages = distribution_path.parent
    if safe_path_exists(distribution_path):
        target = sideload_root / distribution_path.name
        if safe_path_is_dir(distribution_path):
            copytree_filtered(distribution_path, target)
        else:
            copy_file_filtered(distribution_path, target)

    for entry in top_level_entries or read_top_level_entries(distribution):
        root_candidates = [
            site_packages / entry,
            site_packages / f"{entry}.py",
            site_packages / f"{entry}.pyd",
            site_packages / f"{entry}.dll",
        ]
        for candidate in root_candidates:
            if not safe_path_exists(candidate):
                continue
            if safe_path_is_dir(candidate):
                copytree_filtered(candidate, sideload_root / candidate.name)
            else:
                copy_file_filtered(candidate, sideload_root / candidate.name)
            copied.add(entry)
            break


def stage_sideload_distribution(distribution: importlib_metadata.Distribution, sideload_root: Path, copied: set[str]) -> None:
    top_level_entries = read_top_level_entries(distribution)
    if distribution_name(distribution) in HEAVY_SIDELOAD_DISTRIBUTIONS or top_level_entries:
        stage_sideload_top_level_entries(distribution, sideload_root, copied, top_level_entries=top_level_entries)
        return

    try:
        distribution_path = Path(distribution._path).resolve()
    except OSError:
        return
    site_packages = distribution_path.parent
    copied_any = False

    for record_path in list(distribution.files or []):
        try:
            source = Path(distribution.locate_file(record_path)).resolve()
        except OSError:
            continue
        if not safe_path_exists(source) or safe_path_is_dir(source):
            continue
        try:
            relative_path = source.relative_to(site_packages)
        except ValueError:
            continue
        relative_key = relative_path.as_posix()
        if relative_key in copied:
            continue
        copy_file_filtered(source, sideload_root / relative_path)
        copied.add(relative_key)
        copied_any = True

    if not copied_any and safe_path_exists(distribution_path):
        target = sideload_root / distribution_path.name
        if safe_path_is_dir(distribution_path):
            copytree_filtered(distribution_path, target)
        else:
            copy_file_filtered(distribution_path, target)

    top_level_entries = [
        entry.strip()
        for entry in (distribution.read_text("top_level.txt") or "").splitlines()
        if entry.strip()
    ]
    for entry in top_level_entries:
        if entry in copied:
            continue
        root_candidates = [
            site_packages / entry,
            site_packages / f"{entry}.py",
            site_packages / f"{entry}.pyd",
            site_packages / f"{entry}.dll",
        ]
        entry_copied = False
        for candidate in root_candidates:
            if not safe_path_exists(candidate):
                continue
            if safe_path_is_dir(candidate):
                for source in candidate.rglob("*"):
                    if not source.is_file():
                        continue
                    relative_path = source.relative_to(site_packages)
                    relative_key = relative_path.as_posix()
                    if relative_key in copied:
                        continue
                    copy_file_filtered(source, sideload_root / relative_path)
                    copied.add(relative_key)
                entry_copied = True
                continue
            relative_path = candidate.relative_to(site_packages)
            relative_key = relative_path.as_posix()
            if relative_key in copied:
                continue
            copy_file_filtered(candidate, sideload_root / relative_path)
            copied.add(relative_key)
            entry_copied = True
        if entry_copied:
            copied.add(entry)


def stage_sideload_packages(bundle_dir: Path, profile: str, *, build_context: BuildContext) -> None:
    packages = collect_sideload_packages(profile)
    if not packages:
        return
    step("Staging sideload runtime packages")
    sideload_root = bundle_dir / SIDELOAD_PACKAGE_DIR
    sideload_root.mkdir(parents=True, exist_ok=True)
    copied: set[str] = set()
    for distribution in collect_sideload_distributions(packages):
        stage_sideload_distribution(distribution, sideload_root, copied)
    normalize_tree_timestamps(bundle_dir / SIDELOAD_PACKAGE_DIR, build_context.source_date_epoch)


def stage_local_runtime_directories(bundle_dir: Path, *, build_context: BuildContext) -> None:
    runtime_dirs = collect_local_runtime_directories()
    runtime_files = collect_local_runtime_files()
    if not runtime_dirs and not runtime_files:
        return
    step("Staging local runtime directories")
    for source_dir in runtime_dirs:
        target_dir = bundle_dir / source_dir.name
        safe_copytree(source_dir, target_dir, ignore_patterns=LOCAL_RUNTIME_IGNORE_PATTERNS)
        normalize_tree_timestamps(target_dir, build_context.source_date_epoch)
    for source_file in runtime_files:
        target_file = bundle_dir / source_file.name
        copy_file_filtered(source_file, target_file)
        normalize_file_timestamp(target_file, build_context.source_date_epoch)


def should_bundle_emsdk(profile: str) -> bool:
    return _is_windows_runtime() and "wasm" in PROFILE_EXTRAS[profile]


def emsdk_cache_dir() -> Path:
    normalized_version = re.sub(r"[^A-Za-z0-9._-]+", "_", EMSDK_VERSION)
    return ROOT / ".tools" / f"emsdk-{normalized_version}-{safe_machine_name()}"


def first_existing_path(root: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        for candidate in matches:
            if candidate.exists():
                return candidate.resolve()
    return None


def validate_emsdk_root(path: Path) -> bool:
    required = [
        path / "upstream" / "emscripten" / "emcc.py",
        path / "upstream" / "bin" / ("clang.exe" if _is_windows_runtime() else "clang"),
    ]
    if not all(candidate.exists() for candidate in required):
        return False
    python_exe = first_existing_path(path, ["python/*/python.exe", "python/*/bin/python3", "python/*/bin/python"])
    node_exe = first_existing_path(path, ["node/*/bin/node.exe", "node/*/node.exe", "node/*/bin/node", "node/*/node"])
    return python_exe is not None and node_exe is not None


def ensure_emsdk_cache(*, build_context: BuildContext) -> Path:
    cache_dir = emsdk_cache_dir()
    if validate_emsdk_root(cache_dir):
        return cache_dir

    step(f"Bootstrapping bundled Emscripten SDK {EMSDK_VERSION}")
    temp_dir = cache_dir.parent / f"{cache_dir.name}.tmp"
    if temp_dir.exists():
        remove_tree(temp_dir)
    temp_dir.parent.mkdir(parents=True, exist_ok=True)

    run(
        ["git", "clone", "--depth", "1", "--branch", EMSDK_VERSION, EMSDK_REPOSITORY_URL, str(temp_dir)],
        env=build_context.env,
        label="Downloading Emscripten SDK",
        heartbeat_seconds=60,
    )
    emsdk_bat = temp_dir / "emsdk.bat"
    if not emsdk_bat.exists():
        raise SystemExit(f"emsdk bootstrap failed: missing {emsdk_bat}")

    run(
        ["cmd.exe", "/c", str(emsdk_bat), "install", EMSDK_VERSION],
        cwd=temp_dir,
        env=build_context.env,
        label=f"Installing Emscripten SDK {EMSDK_VERSION}",
        heartbeat_seconds=60,
    )
    run(
        ["cmd.exe", "/c", str(emsdk_bat), "activate", EMSDK_VERSION],
        cwd=temp_dir,
        env=build_context.env,
        label=f"Activating Emscripten SDK {EMSDK_VERSION}",
        heartbeat_seconds=60,
    )

    if cache_dir.exists():
        remove_tree(cache_dir)
    temp_dir.rename(cache_dir)
    if not validate_emsdk_root(cache_dir):
        raise SystemExit(f"emsdk bootstrap produced an incomplete toolchain at {cache_dir}")
    return cache_dir


def write_relocatable_emscripten_config(emsdk_root: Path) -> None:
    config = """import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _first(*patterns: str) -> str:
    for pattern in patterns:
        matches = sorted(ROOT.glob(pattern))
        for candidate in matches:
            if candidate.exists():
                return str(candidate.resolve())
    raise RuntimeError(f"Missing bundled Emscripten runtime asset for patterns: {patterns!r}")

_local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("TMP") or str(ROOT)
_nova_cache_root = Path(_local_app_data) / "Nova-shell" / "emscripten"
_nova_cache_root.mkdir(parents=True, exist_ok=True)

EMSDK = str(ROOT)
EMSCRIPTEN_ROOT = str((ROOT / "upstream" / "emscripten").resolve())
LLVM_ROOT = str((ROOT / "upstream" / "bin").resolve())
BINARYEN_ROOT = str((ROOT / "upstream").resolve())
NODE_JS = _first("node/*/bin/node.exe", "node/*/node.exe", "node/*/bin/node", "node/*/node")
PYTHON = _first("python/python.exe", "python/*/python.exe", "python/*/bin/python3", "python/*/bin/python")
JAVA = os.environ.get("JAVA", "java")
JS_ENGINES = [NODE_JS]
WASM_ENGINES = [NODE_JS]
TEMP_DIR = str((_nova_cache_root / "tmp").resolve())
CACHE = str((_nova_cache_root / "cache").resolve())
PORTS = str((Path(CACHE) / "ports").resolve())
"""
    write_text(emsdk_root / ".emscripten", config)


def write_bundled_emcc_wrapper(bundle_dir: Path) -> None:
    wrapper = """@echo off
setlocal
set "NOVA_EMSDK_ROOT=%~dp0emsdk"
if not exist "%NOVA_EMSDK_ROOT%\\upstream\\emscripten\\emcc.py" (
  echo Missing bundled emcc runtime: %NOVA_EMSDK_ROOT%\\upstream\\emscripten\\emcc.py 1>&2
  exit /b 1
)
set "EMSDK=%NOVA_EMSDK_ROOT%"
set "EM_CONFIG=%NOVA_EMSDK_ROOT%\\.emscripten"
if not defined LOCALAPPDATA (
  set "LOCALAPPDATA=%TEMP%"
)
if not defined EM_CACHE (
  set "EM_CACHE=%LOCALAPPDATA%\\Nova-shell\\emscripten\\cache"
)
set "NOVA_EMSDK_PYTHON=%NOVA_EMSDK_ROOT%\\python\\python.exe"
if not exist "%NOVA_EMSDK_PYTHON%" set "NOVA_EMSDK_PYTHON="
if not defined NOVA_EMSDK_PYTHON (
  for /D %%D in ("%NOVA_EMSDK_ROOT%\\python\\*") do (
    if exist "%%~fD\\python.exe" set "NOVA_EMSDK_PYTHON=%%~fD\\python.exe"
  )
)
if not defined NOVA_EMSDK_PYTHON (
  echo Missing bundled Emscripten Python runtime. 1>&2
  exit /b 1
)
"%NOVA_EMSDK_PYTHON%" "%NOVA_EMSDK_ROOT%\\upstream\\emscripten\\emcc.py" %*
exit /b %ERRORLEVEL%
"""
    write_text(bundle_dir / BUNDLED_TOOLCHAIN_DIR / EMSDK_WRAPPER_NAME, wrapper, executable=True)


def current_python_root() -> Path:
    candidate = Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    if _is_windows_runtime() and (candidate / "python.exe").exists():
        return candidate
    return Path(sys.executable).resolve().parent


def should_include_python_stdlib(path: Path, lib_root: Path) -> bool:
    parts = path.relative_to(lib_root).parts
    if any(part in PYTHON_STDLIB_EXCLUDES for part in parts):
        return False
    return path.suffix not in {".pyc", ".pyo"}


def stage_minimal_python_runtime(target_root: Path) -> None:
    python_root = current_python_root()
    target_root.mkdir(parents=True, exist_ok=True)

    version_tag = f"python{sys.version_info.major}{sys.version_info.minor}"
    runtime_files = [
        "python.exe",
        "python3.dll",
        f"{version_tag}.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ]
    for name in runtime_files:
        source = python_root / name
        if source.exists():
            safe_copy2_file(source, target_root / source.name)

    dll_source = python_root / "DLLs"
    dll_target = target_root / "DLLs"
    if dll_source.exists():
        safe_copytree(dll_source, dll_target, ignore_patterns=("__pycache__", "*.pyc", "*.pyo"))

    lib_root = python_root / "Lib"
    stdlib_zip = target_root / f"{version_tag}.zip"
    with zipfile.ZipFile(stdlib_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in lib_root.rglob("*"):
            if not source.is_file() or not should_include_python_stdlib(source, lib_root):
                continue
            archive.write(source, arcname=str(source.relative_to(lib_root)).replace("\\", "/"))

    pth = target_root / f"{version_tag}._pth"
    pth.write_text(f"{version_tag}.zip\nDLLs\n.\n..\\upstream\\emscripten\n", encoding="utf-8")


def stage_minimal_node_runtime(cache_dir: Path, target_root: Path) -> None:
    node_exe = first_existing_path(cache_dir, ["node/*/bin/node.exe", "node/*/node.exe", "node/*/bin/node", "node/*/node"])
    if node_exe is None:
        return
    version_root = node_exe.parent.parent if node_exe.parent.name == "bin" else node_exe.parent
    target_version_root = target_root / version_root.name
    target_bin = target_version_root / ("bin" if node_exe.parent.name == "bin" else "")
    target_bin.mkdir(parents=True, exist_ok=True)
    safe_copy2_file(node_exe, target_bin / node_exe.name)
    version_marker = version_root / ".emsdk_version"
    if version_marker.exists():
        safe_copy2_file(version_marker, target_version_root / version_marker.name)


def stage_emsdk_runtime_subset(cache_dir: Path, target_root: Path) -> None:
    subset_dirs = [
        ("upstream/bin", ("__pycache__", "*.pyc", "*.pyo", ".git", ".github")),
        ("upstream/lib", ("__pycache__", "*.pyc", "*.pyo", ".git", ".github")),
        (
            "upstream/emscripten",
            (
                "__pycache__",
                "*.pyc",
                "*.pyo",
                ".git",
                ".github",
                "cache",
                "docs",
                "media",
                "node_modules",
                "test",
                "tests",
                "cmake",
            ),
        ),
    ]
    for relative_path, ignore_patterns in subset_dirs:
        source = cache_dir / relative_path
        if not source.exists():
            continue
        # The Python walker has shown access violations on large Emscripten trees
        # on some Windows hosts. Prefer robocopy here and keep the ignore list
        # explicit so the subset remains stable.
        safe_copytree(
            source,
            target_root / relative_path,
            ignore_patterns=ignore_patterns,
            prefer_robocopy=True,
        )
    stage_minimal_node_runtime(cache_dir, target_root / "node")
    stage_minimal_python_runtime(target_root / PYTHON_RUNTIME_DIR)


def stage_bundled_emsdk(bundle_dir: Path, profile: str, *, build_context: BuildContext) -> None:
    if not should_bundle_emsdk(profile):
        return
    cache_dir = ensure_emsdk_cache(build_context=build_context)
    target_root = bundle_dir / BUNDLED_TOOLCHAIN_DIR / "emsdk"
    step("Staging bundled Emscripten SDK")
    if target_root.exists():
        remove_tree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    stage_emsdk_runtime_subset(cache_dir, target_root)
    write_relocatable_emscripten_config(target_root)
    write_bundled_emcc_wrapper(bundle_dir)
    normalize_tree_timestamps(bundle_dir / BUNDLED_TOOLCHAIN_DIR, build_context.source_date_epoch)


def write_runtime_config(bundle_dir: Path, profile: str) -> None:
    payload = {
        "profile": profile,
        "sandbox_default": profile == "enterprise",
        "sideload_packages": collect_sideload_packages(profile),
    }
    if should_bundle_emsdk(profile):
        payload["toolchains"] = {
            "emscripten": {
                "version": EMSDK_VERSION,
                "root": f"{BUNDLED_TOOLCHAIN_DIR}/emsdk",
                "emcc_wrapper": f"{BUNDLED_TOOLCHAIN_DIR}/{EMSDK_WRAPPER_NAME}",
            }
        }
    write_text(bundle_dir / RUNTIME_CONFIG_FILE, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def build_windows_installers(
    build_root: Path,
    profile: str,
    bundle_dir: Path,
    executable: Path,
    *,
    base_download_url: str,
    signing_config: dict[str, str] | None,
    build_context: BuildContext,
) -> list[Path]:
    metadata = load_release_metadata()
    installer_root = build_root / "installers"
    installer_root.mkdir(parents=True, exist_ok=True)

    wix_exe = require_tool("wix", "WiX Toolset v4 is required for MSI packaging. Install it with 'dotnet tool install --global wix --version 4.*'.")
    arch = machine_to_wix_arch(safe_machine_name())
    wix_source = installer_root / "nova-shell.wxs"
    wix_source.write_text(render_wix_source(metadata, __version__, bundle_dir, executable.name), encoding="utf-8")

    msi_name = f"{metadata.package_slug}-{__version__}-windows-{arch}-{profile}.msi"
    msi_path = installer_root / msi_name
    run(
        [wix_exe, "build", "-arch", arch, "-o", str(msi_path), str(wix_source)],
        label="Building Windows MSI installer",
    )
    with contextlib.suppress(FileNotFoundError):
        os.utime(msi_path, (build_context.source_date_epoch or msi_path.stat().st_mtime, build_context.source_date_epoch or msi_path.stat().st_mtime))
    if signing_config:
        sign_windows_artifact(
            msi_path,
            signtool=signing_config["signtool"],
            timestamp_url=signing_config["timestamp_url"],
            certificate_file=signing_config.get("certificate_file"),
            certificate_password=signing_config.get("certificate_password"),
            subject_name=signing_config.get("subject_name"),
        )
        verify_windows_artifact(msi_path, signtool=signing_config["signtool"])

    artifacts = [msi_path]
    artifacts.extend(stage_windows_installer_support_files(installer_root, build_context=build_context))
    if base_download_url:
        installer_url = base_download_url.rstrip("/") + "/" + msi_name
        winget_manifests = render_winget_manifests(
            metadata,
            __version__,
            installer_url,
            sha256sum(msi_path),
            machine_to_winget_arch(safe_machine_name()),
        )
        identifier_parts = metadata.package_identifier.split(".")
        manifest_dir = build_root / "winget" / "manifests" / identifier_parts[0][0].lower()
        manifest_dir = manifest_dir.joinpath(*identifier_parts, __version__)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        stem = metadata.package_identifier
        manifest_paths = {
            "version": manifest_dir / f"{stem}.yaml",
            "installer": manifest_dir / f"{stem}.installer.yaml",
            "defaultLocale": manifest_dir / f"{stem}.locale.en-US.yaml",
        }
        for key, path in manifest_paths.items():
            path.write_text(winget_manifests[key], encoding="utf-8")
            artifacts.append(path)

    return artifacts


def stage_windows_installer_support_files(installer_root: Path, *, build_context: BuildContext) -> list[Path]:
    staged: list[Path] = []
    for relative_name in WINDOWS_INSTALLER_SUPPORT_FILES:
        source = (ROOT / relative_name).resolve()
        if not source.exists() or not source.is_file():
            continue
        target = installer_root / source.name
        safe_copy2_file(source, target)
        with contextlib.suppress(FileNotFoundError):
            os.utime(
                target,
                (
                    build_context.source_date_epoch or target.stat().st_mtime,
                    build_context.source_date_epoch or target.stat().st_mtime,
                ),
            )
        staged.append(target)
    return staged


def prepare_linux_appdir(bundle_dir: Path, executable: Path, work_root: Path, *, build_context: BuildContext) -> Path:
    metadata = load_release_metadata()
    appdir = work_root / f"{metadata.package_slug}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    app_bundle_dir = appdir / "usr" / "lib" / metadata.package_slug
    copytree_clean(bundle_dir, app_bundle_dir)

    launcher = appdir / "usr" / "bin" / metadata.package_slug
    launcher_content = (
        "#!/bin/sh\n"
        'HERE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"\n'
        f'exec "$HERE/lib/{metadata.package_slug}/{executable.name}" "$@"\n'
    )
    write_text(launcher, launcher_content, executable=True)

    desktop_entry = render_desktop_entry(metadata)
    appstream = render_appstream_metadata(metadata)
    icon_source = ASSETS_DIR / f"{metadata.app_id}.svg"
    icon_root = appdir / f"{metadata.app_id}.svg"
    safe_copy2_file(icon_source, icon_root)
    safe_copy2_file(icon_source, appdir / ".DirIcon")

    write_text(appdir / "AppRun", "#!/bin/sh\nexec \"$APPDIR/usr/bin/nova-shell\" \"$@\"\n", executable=True)
    write_text(appdir / f"{metadata.app_id}.desktop", desktop_entry)
    write_text(appdir / "usr" / "share" / "applications" / f"{metadata.app_id}.desktop", desktop_entry)
    write_text(appdir / "usr" / "share" / "metainfo" / f"{metadata.app_id}.appdata.xml", appstream)
    icon_target = appdir / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{metadata.app_id}.svg"
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    safe_copy2_file(icon_source, icon_target)
    normalize_tree_timestamps(appdir, build_context.source_date_epoch)
    return appdir


def build_appimage(build_root: Path, bundle_dir: Path, executable: Path, profile: str, *, build_context: BuildContext) -> Path:
    tool = require_tool("appimagetool", "appimagetool is required for AppImage packaging. Install it or place it on PATH.")
    metadata = load_release_metadata()
    work_root = build_root / "installers" / "appimage-work"
    appdir = prepare_linux_appdir(bundle_dir, executable, work_root, build_context=build_context)
    machine = safe_machine_name().lower()
    output_path = build_root / "installers" / f"{metadata.package_slug}-{__version__}-{machine}-{profile}.AppImage"
    env = build_context.env.copy()
    env["ARCH"] = machine
    run([tool, str(appdir), str(output_path)], env=env, label="Building AppImage installer")
    return output_path


def build_deb(build_root: Path, bundle_dir: Path, executable: Path, profile: str, *, build_context: BuildContext) -> Path:
    require_tool("dpkg-deb", "dpkg-deb is required for Debian packaging. Install the dpkg package toolchain.")
    metadata = load_release_metadata()
    arch = machine_to_deb_arch(safe_machine_name())
    package_root = build_root / "installers" / "deb-root"
    if package_root.exists():
        shutil.rmtree(package_root)

    app_root = package_root / "opt" / metadata.package_slug
    copytree_clean(bundle_dir, app_root)
    bin_dir = package_root / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / metadata.package_slug).symlink_to(Path("/") / "opt" / metadata.package_slug / executable.name)

    desktop_entry = render_desktop_entry(metadata)
    appstream = render_appstream_metadata(metadata)
    write_text(package_root / "usr" / "share" / "applications" / f"{metadata.app_id}.desktop", desktop_entry)
    write_text(package_root / "usr" / "share" / "metainfo" / f"{metadata.app_id}.appdata.xml", appstream)
    deb_icon_target = package_root / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{metadata.app_id}.svg"
    deb_icon_target.parent.mkdir(parents=True, exist_ok=True)
    safe_copy2_file(ASSETS_DIR / f"{metadata.app_id}.svg", deb_icon_target)

    control_dir = package_root / "DEBIAN"
    control_dir.mkdir(parents=True, exist_ok=True)
    installed_size = installed_size_kib(package_root)
    control_lines = [
        f"Package: {metadata.package_slug}",
        f"Version: {__version__}",
        f"Section: {metadata.linux_section}",
        "Priority: optional",
        f"Architecture: {arch}",
        f"Maintainer: {metadata.maintainer_name} <{metadata.maintainer_email}>",
        f"Installed-Size: {installed_size}",
        f"Description: {format_deb_description(metadata.description, metadata.long_description)}",
    ]
    if metadata.homepage:
        control_lines.insert(7, f"Homepage: {metadata.homepage}")
    write_text(control_dir / "control", "\n".join(control_lines) + "\n")

    for script_name in ("postinst", "prerm"):
        src = LINUX_DIR / script_name
        dst = control_dir / script_name
        safe_copy2_file(src, dst)
        make_executable(dst)

    normalize_tree_timestamps(package_root, build_context.source_date_epoch)
    deb_name = f"{metadata.package_slug}_{__version__}_{arch}_{profile}.deb"
    output_path = build_root / "installers" / deb_name
    run(
        ["dpkg-deb", "--build", "--root-owner-group", str(package_root), str(output_path)],
        env=build_context.env,
        label="Building Debian package",
    )
    return output_path


def build_linux_installers(build_root: Path, bundle_dir: Path, executable: Path, profile: str, *, build_context: BuildContext) -> list[Path]:
    return [
        build_appimage(build_root, bundle_dir, executable, profile, build_context=build_context),
        build_deb(build_root, bundle_dir, executable, profile, build_context=build_context),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build releasable Nova-shell artifacts.")
    parser.add_argument("--profile", choices=sorted(PROFILE_EXTRAS.keys()), default="core")
    parser.add_argument("--mode", choices=["python", "standalone", "installers", "all"], default="all")
    parser.add_argument("--output-dir", default=str(ROOT / "dist" / "release"))
    parser.add_argument("--python", default=sys.executable, help="Python executable used for the build.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--base-download-url", default="", help="Base URL used for generated winget manifests.")
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        default=default_source_date_epoch(),
        help="Fixed UNIX timestamp used for more reproducible build metadata and archives. Defaults to SOURCE_DATE_EPOCH when set.",
    )
    parser.add_argument("--windows-sign", action="store_true", help="Sign Windows executables and MSI files with signtool.")
    parser.add_argument("--windows-cert-file", default="", help="PFX file used for signtool signing.")
    parser.add_argument("--windows-cert-password", default="", help="Password for the PFX certificate.")
    parser.add_argument("--windows-subject-name", default="", help="Certificate subject name if using the Windows certificate store.")
    parser.add_argument("--timestamp-url", default="http://timestamp.digicert.com", help="RFC3161 timestamp URL used by signtool.")
    return parser.parse_args()


def main() -> int:
    enable_fault_dumps()
    trace("main entry")
    args = parse_args()
    trace(f"parsed args: profile={args.profile} mode={args.mode} skip_tests={args.skip_tests} clean={args.clean}")
    trace("resolving output root")
    output_root = Path(args.output_dir).resolve()
    trace(f"resolved output root: {output_root}")
    system_name = safe_system_name()
    machine_name = safe_machine_name()
    build_root = output_root / f"{system_name.lower()}-{machine_name.lower()}" / args.profile
    trace(f"computed build root: {build_root}")
    trace("creating build context")
    build_context = create_build_context(args.source_date_epoch)
    trace("created build context")

    trace("about to emit preparing step")
    step(f"Preparing release build for profile '{args.profile}' in {display_path(build_root)}")
    trace("preparing step emitted")
    if args.clean and build_root.exists():
        step(f"Removing previous build root {display_path(build_root)}")
        remove_tree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)

    if not args.skip_tests:
        run(
            [args.python, "-m", "unittest", "discover", "-s", "tests", "-v"],
            env=build_context.env,
            label="Running test suite",
        )

    artifacts: list[ArtifactRecord] = []
    bundle_dir: Path | None = None
    executable: Path | None = None
    signing_config: dict[str, str] | None = None

    if args.windows_sign:
        if os.name != "nt":
            raise SystemExit("--windows-sign is only supported on Windows")
        signtool = require_signtool()
        if not args.windows_cert_file and not args.windows_subject_name:
            raise SystemExit("provide --windows-cert-file or --windows-subject-name when using --windows-sign")
        signing_config = {
            "signtool": signtool,
            "timestamp_url": args.timestamp_url,
        }
        if args.windows_cert_file:
            signing_config["certificate_file"] = args.windows_cert_file
        if args.windows_cert_password:
            signing_config["certificate_password"] = args.windows_cert_password
        if args.windows_subject_name:
            signing_config["subject_name"] = args.windows_subject_name

    if args.mode in {"python", "all"}:
        python_artifacts = build_python_artifacts(args.python, build_root / "python", build_context=build_context)
        artifacts.extend(record("python", path) for path in python_artifacts)

    if args.mode in {"standalone", "installers", "all"}:
        step("Resolving standalone bundle")
        bundle_dir, executable = ensure_bundle(
            build_root,
            args.python,
            args.profile,
            rebuild=args.mode in {"standalone", "all"},
            build_context=build_context,
        )
        stage_bundled_emsdk(bundle_dir, args.profile, build_context=build_context)
        write_runtime_config(bundle_dir, args.profile)
        stage_sideload_packages(bundle_dir, args.profile, build_context=build_context)
        stage_local_runtime_directories(bundle_dir, build_context=build_context)
        if signing_config and bundle_dir is not None:
            for signable in find_artifacts_for_windows_signing(bundle_dir):
                sign_windows_artifact(
                    signable,
                    signtool=signing_config["signtool"],
                    timestamp_url=signing_config["timestamp_url"],
                    certificate_file=signing_config.get("certificate_file"),
                    certificate_password=signing_config.get("certificate_password"),
                    subject_name=signing_config.get("subject_name"),
                )
                verify_windows_artifact(signable, signtool=signing_config["signtool"])
        smoke_test_executable(args.python, executable, args.profile)
        prune_bundle_runtime_state(bundle_dir)

    if args.mode in {"standalone", "all"} and bundle_dir is not None:
        step("Archiving standalone bundle")
        archive_name = f"{PROJECT_SLUG}-{__version__}-{system_name.lower()}-{machine_name.lower()}-{args.profile}"
        archive_path = archive_bundle(bundle_dir, build_root / archive_name, source_date_epoch=build_context.source_date_epoch)
        artifacts.append(record("standalone-archive", archive_path))

    if args.mode in {"installers", "all"}:
        step("Building installer artifacts")
        assert bundle_dir is not None and executable is not None
        if os.name == "nt":
            installer_paths = build_windows_installers(
                build_root,
                args.profile,
                bundle_dir,
                executable,
                base_download_url=args.base_download_url,
                signing_config=signing_config,
                build_context=build_context,
            )
        else:
            installer_paths = build_linux_installers(build_root, bundle_dir, executable, args.profile, build_context=build_context)
        artifacts.extend(record("installer", path) for path in installer_paths)

    step("Writing manifest and SBOM metadata")
    subject_artifacts = list(artifacts)
    subject_checksums_path = write_subject_checksums(build_root, args.profile, subject_artifacts)
    manifest_path = write_manifest(build_root, args.profile, artifacts, build_context=build_context)
    sbom_path = write_cyclonedx_sbom(
        build_root / f"{PROJECT_SLUG}-{__version__}-{args.profile}.sbom.cyclonedx.json",
        package_name=PROJECT_SLUG,
        version=__version__,
        description=load_release_metadata().description,
        license_id=load_release_metadata().license,
        artifact_paths=[
            (artifact.path, Path(ROOT / artifact.path), artifact.kind)
            for artifact in subject_artifacts
            if (ROOT / artifact.path).exists()
        ],
        dependency_names=load_profile_dependencies(args.profile),
        source_date_epoch=build_context.source_date_epoch,
    )
    artifacts.append(record("sbom", sbom_path))
    manifest_path = write_manifest(build_root, args.profile, artifacts, build_context=build_context)
    checksums_path = write_checksums(build_root, artifacts, manifest_path)

    step("Release build completed")
    print(
        json.dumps(
            {
                "manifest": display_path(manifest_path),
                "checksums": display_path(checksums_path),
                "sbom": display_path(sbom_path),
                "subjects": display_path(subject_checksums_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
