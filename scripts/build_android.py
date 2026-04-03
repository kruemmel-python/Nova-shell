from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID_DIR = ROOT / "android"
ANDROID_PYTHON_DIR = ANDROID_DIR / "app" / "src" / "main" / "python"
ANDROID_RUNTIME_MANIFEST = "android_runtime_manifest.json"
ANDROID_LEGACY_RUNTIME_DIR = "nova_mobile_runtime"
ANDROID_RUNTIME_DIRS = [
    "nova",
    "examples",
]
ANDROID_RUNTIME_FILES = [
    "nova_shell.py",
    "novascript.py",
    "mycelia_runtime.py",
    "industry_scanner.py",
    "trend_rss_sensor.py",
    "watch_the_big_players.ns",
    "watch_the_big_players_test.ns",
    "nova_project_monitor.ns",
    "morning_briefing.ns",
    "sample_news.json",
    "beispiel_rss.md",
    "morning_briefing.md",
    "README.md",
    "Dokumentation.md",
    "Whitepaper.md",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
]
ANDROID_RUNTIME_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
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
    "build",
    "dist",
    ".DS_Store",
    "Thumbs.db",
)
MOBILE_ALLOWED_COMMAND_GROUPS = [
    "ai",
    "agent",
    "atheria",
    "blob",
    "cd",
    "data",
    "doctor",
    "event",
    "events",
    "flow",
    "help",
    "memory",
    "mesh",
    "ns.check",
    "ns.emit",
    "ns.exec",
    "ns.graph",
    "ns.resume",
    "ns.run",
    "ns.snapshot",
    "ns.status",
    "open",
    "pack",
    "pulse",
    "py",
    "python",
    "rag",
    "reactive",
    "remote",
    "secure",
    "studio",
    "sync",
    "sys",
    "tool",
    "vision",
    "watch",
    "wiki",
    "zero",
]
MOBILE_BLOCKED_COMMAND_GROUPS = [
    "cpp",
    "cpp.expr",
    "cpp.expr_chain",
    "cpp.sandbox",
    "gpu",
    "jit_wasm",
    "wasm",
]


def project_version(project_root: Path = ROOT) -> str:
    source = project_root / "nova_shell.py"
    text = source.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if match is None:
        raise SystemExit(f"could not determine project version from {source}")
    return match.group(1)


def version_to_android_code(version: str) -> int:
    numbers = [int(part) for part in re.findall(r"\d+", version)]
    major, minor, patch = (numbers + [0, 0, 0])[:3]
    return major * 10_000 + minor * 100 + patch


def collect_android_runtime_dirs(project_root: Path = ROOT) -> list[Path]:
    return [project_root / name for name in ANDROID_RUNTIME_DIRS if (project_root / name).is_dir()]


def collect_android_runtime_files(project_root: Path = ROOT) -> list[Path]:
    return [project_root / name for name in ANDROID_RUNTIME_FILES if (project_root / name).is_file()]


def _should_ignore_name(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in ANDROID_RUNTIME_IGNORE_PATTERNS)


def _copytree_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if _should_ignore_name(name)}


def safe_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def clean_runtime_dir(python_root: Path) -> None:
    if not python_root.exists():
        return
    legacy_runtime_root = python_root / ANDROID_LEGACY_RUNTIME_DIR
    if legacy_runtime_root.is_dir():
        shutil.rmtree(legacy_runtime_root)
    pycache_root = python_root / "__pycache__"
    if pycache_root.is_dir():
        shutil.rmtree(pycache_root)
    for directory_name in ANDROID_RUNTIME_DIRS:
        target = python_root / directory_name
        if target.is_dir():
            shutil.rmtree(target)
    for file_name in ANDROID_RUNTIME_FILES:
        target = python_root / file_name
        if target.is_file():
            target.unlink()
    manifest_path = python_root / ANDROID_RUNTIME_MANIFEST
    if manifest_path.is_file():
        manifest_path.unlink()


def render_android_runtime_manifest(project_root: Path, python_root: Path) -> dict[str, object]:
    return {
        "version": project_version(project_root),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python_root": str(python_root),
        "staged_directories": [path.name for path in collect_android_runtime_dirs(project_root)],
        "staged_files": [path.name for path in collect_android_runtime_files(project_root)],
        "allowed_command_groups": MOBILE_ALLOWED_COMMAND_GROUPS,
        "blocked_command_groups": MOBILE_BLOCKED_COMMAND_GROUPS,
        "notes": [
            "This Android runtime is not wired into desktop release automation yet.",
            "Only hard local toolchain and hardware command groups such as cpp, gpu and wasm are blocked at the bridge layer.",
            "All other command groups are passed through to the runtime and may still return per-command capability errors on Android.",
        ],
    }


def write_android_runtime_manifest(project_root: Path, python_root: Path) -> Path:
    manifest_path = python_root / ANDROID_RUNTIME_MANIFEST
    payload = render_android_runtime_manifest(project_root, python_root)
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def stage_android_runtime(project_root: Path = ROOT, python_root: Path = ANDROID_PYTHON_DIR, *, clean: bool = True) -> Path:
    python_root.mkdir(parents=True, exist_ok=True)
    if clean:
        clean_runtime_dir(python_root)

    for source_dir in collect_android_runtime_dirs(project_root):
        shutil.copytree(
            source_dir,
            python_root / source_dir.name,
            dirs_exist_ok=True,
            ignore=_copytree_ignore,
        )

    for source_file in collect_android_runtime_files(project_root):
        safe_copy_file(source_file, python_root / source_file.name)

    return write_android_runtime_manifest(project_root, python_root)


def resolve_gradle_command(android_dir: Path = ANDROID_DIR) -> list[str] | None:
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.append(android_dir / "gradlew.bat")
    else:
        candidates.append(android_dir / "gradlew")
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]

    gradle_binary = shutil.which("gradle.bat" if os.name == "nt" else "gradle")
    if gradle_binary:
        return [gradle_binary]

    user_home = Path.home()
    wrapper_root = user_home / ".gradle" / "wrapper" / "dists"
    if wrapper_root.is_dir():
        pattern = "gradle.bat" if os.name == "nt" else "gradle"
        discovered: list[tuple[tuple[int, ...], Path]] = []
        for candidate in wrapper_root.rglob(pattern):
            version_match = re.search(r"gradle-(\d+(?:\.\d+)*)", str(candidate))
            if version_match is None:
                continue
            version_tuple = tuple(int(part) for part in version_match.group(1).split("."))
            discovered.append((version_tuple, candidate))
        if discovered:
            compatible = [item for item in discovered if item[0] and item[0][0] == 8]
            if compatible:
                compatible.sort(reverse=True)
                return [str(compatible[0][1])]
            discovered.sort(reverse=True)
            return [str(discovered[0][1])]
    return None


def discover_android_sdk() -> Path | None:
    env_candidates = [
        os.environ.get("ANDROID_HOME", "").strip(),
        os.environ.get("ANDROID_SDK_ROOT", "").strip(),
    ]
    for raw in env_candidates:
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve(strict=False)
        if candidate.is_dir():
            return candidate

    local_candidates = [
        Path.home() / "AppData" / "Local" / "Android" / "Sdk",
        Path.home() / "Android" / "Sdk",
    ]
    for candidate in local_candidates:
        candidate = candidate.resolve(strict=False)
        if candidate.is_dir():
            return candidate
    return None


def discover_java_home() -> Path | None:
    local_candidates = [
        Path(r"C:\Program Files\Eclipse Adoptium\jdk-21.0.9.10-hotspot"),
        Path(r"C:\Program Files\Eclipse Adoptium\jdk-17"),
        Path(r"C:\Program Files\Android\Android Studio\jbr"),
        Path(r"C:\Program Files\Android Studio\jbr"),
    ]
    for candidate in local_candidates:
        candidate = candidate.resolve(strict=False)
        if (candidate / "bin" / ("java.exe" if os.name == "nt" else "java")).is_file():
            return candidate

    env_java_home = os.environ.get("JAVA_HOME", "").strip()
    if env_java_home:
        candidate = Path(env_java_home).expanduser().resolve(strict=False)
        if (candidate / "bin" / ("java.exe" if os.name == "nt" else "java")).is_file():
            return candidate
    return None


def resolve_apk_output_path(android_dir: Path, variant: str) -> Path:
    output_dir = android_dir / "app" / "build" / "outputs" / "apk" / variant
    metadata_path = output_dir / "output-metadata.json"
    if metadata_path.is_file():
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        elements = payload.get("elements", []) if isinstance(payload, dict) else []
        if isinstance(elements, list):
            for element in elements:
                if not isinstance(element, dict):
                    continue
                output_file = element.get("outputFile")
                if isinstance(output_file, str) and output_file.strip():
                    return output_dir / output_file

    fallback_names = [f"app-{variant}.apk", f"app-{variant}-unsigned.apk"]
    for name in fallback_names:
        candidate = output_dir / name
        if candidate.is_file():
            return candidate
    return output_dir / fallback_names[0]


def assemble_android(
    *,
    project_root: Path = ROOT,
    android_dir: Path = ANDROID_DIR,
    python_root: Path = ANDROID_PYTHON_DIR,
    variant: str = "debug",
    clean: bool = True,
) -> Path:
    stage_android_runtime(project_root, python_root, clean=clean)
    gradle_command = resolve_gradle_command(android_dir)
    if gradle_command is None:
        raise SystemExit(
            "Gradle was not found. Open the android project in Android Studio or install Gradle and retry."
        )

    normalized_variant = variant.strip().lower() or "debug"
    if normalized_variant not in {"debug", "release"}:
        raise SystemExit(f"unsupported Android build variant: {variant!r}")

    version = project_version(project_root)
    env = os.environ.copy()
    env.setdefault("NOVA_SHELL_VERSION", version)
    env.setdefault("NOVA_ANDROID_VERSION_CODE", str(version_to_android_code(version)))
    sdk_root = discover_android_sdk()
    if sdk_root is not None:
        env.setdefault("ANDROID_HOME", str(sdk_root))
        env.setdefault("ANDROID_SDK_ROOT", str(sdk_root))
    java_home = discover_java_home()
    if java_home is not None:
        env["JAVA_HOME"] = str(java_home)

    command = gradle_command + ["--no-daemon", f"assemble{normalized_variant.capitalize()}"]
    subprocess.run(command, cwd=str(android_dir), env=env, check=True)
    return resolve_apk_output_path(android_dir, normalized_variant)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare or assemble the Android preview build.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="stage the mobile-safe runtime into android/app/src/main/python")
    prepare_parser.add_argument("--android-dir", type=Path, default=ANDROID_DIR)
    prepare_parser.add_argument("--project-root", type=Path, default=ROOT)
    prepare_parser.add_argument("--no-clean", action="store_true", help="preserve existing staged files before copying")

    clean_parser = subparsers.add_parser("clean", help="remove generated staged runtime files")
    clean_parser.add_argument("--android-dir", type=Path, default=ANDROID_DIR)

    assemble_parser = subparsers.add_parser("assemble", help="stage the runtime and run Gradle assembleDebug/assembleRelease")
    assemble_parser.add_argument("--android-dir", type=Path, default=ANDROID_DIR)
    assemble_parser.add_argument("--project-root", type=Path, default=ROOT)
    assemble_parser.add_argument("--variant", choices=["debug", "release"], default="debug")
    assemble_parser.add_argument("--no-clean", action="store_true", help="preserve existing staged files before copying")

    manifest_parser = subparsers.add_parser("manifest", help="print the generated Android runtime manifest to stdout")
    manifest_parser.add_argument("--android-dir", type=Path, default=ANDROID_DIR)
    manifest_parser.add_argument("--project-root", type=Path, default=ROOT)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    android_dir = args.android_dir.resolve(strict=False)
    python_root = android_dir / "app" / "src" / "main" / "python"

    if args.command == "prepare":
        manifest_path = stage_android_runtime(args.project_root.resolve(strict=False), python_root, clean=not args.no_clean)
        print(manifest_path)
        return 0

    if args.command == "clean":
        clean_runtime_dir(python_root)
        print(python_root)
        return 0

    if args.command == "assemble":
        apk_path = assemble_android(
            project_root=args.project_root.resolve(strict=False),
            android_dir=android_dir,
            python_root=python_root,
            variant=args.variant,
            clean=not args.no_clean,
        )
        print(apk_path)
        return 0

    if args.command == "manifest":
        payload = render_android_runtime_manifest(args.project_root.resolve(strict=False), python_root)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    raise SystemExit(f"unsupported command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
