from __future__ import annotations

import argparse
import base64
import pathlib
import zlib


def build_ns_text(helper_source: str) -> str:
    payload = base64.b64encode(zlib.compress(helper_source.encode("utf-8"), level=9)).decode("ascii")
    chunks = [payload[index : index + 900] for index in range(0, len(payload), 900)]
    lines = [
        "# Nova-shell System Guard for Windows persistence and integrity monitoring",
        "# Copy this file into a working directory and run: ns.run nova_system_guard.ns",
        "# Optional env:",
        "#   NOVA_SYSTEM_GUARD_INTERVAL=2",
        "#   NOVA_SYSTEM_GUARD_DEBOUNCE=1.0",
        "#   NOVA_SYSTEM_GUARD_OPEN=0",
        "#   NOVA_SYSTEM_GUARD_ONESHOT=1",
        "#   NOVA_SYSTEM_GUARD_WATCH_MODE=auto|watchdog|poll",
        "#   NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS=1|0",
        "#   NOVA_SYSTEM_GUARD_INCLUDE_PROJECT=auto|on|off",
        "#   NOVA_SYSTEM_GUARD_PATHS=C:/path1;C:/path2",
        "py import pathlib, runpy, base64, zlib",
        'project_root = py str(pathlib.Path(".").resolve())',
        'monitor_dir = py str(pathlib.Path($project_root) / ".nova_system_guard")',
        'helper_path = py str(pathlib.Path($monitor_dir) / "system_guard_helper.py")',
        "py pathlib.Path($monitor_dir).mkdir(parents=True, exist_ok=True)",
        'blob = py ""',
    ]
    for chunk in chunks:
        lines.append(f"blob = py $blob + {chunk!r}")
    lines.extend(
        [
            "py pathlib.Path($helper_path).write_bytes(zlib.decompress(base64.b64decode($blob)))",
            'guard_run = py ns = runpy.run_path($helper_path, run_name="system_guard_helper"); ns["main"]()',
            'py print("Nova System Guard beendet. Report: .nova_system_guard/system_guard_report.html")',
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a self-contained Nova System Guard .ns file.")
    parser.add_argument("--helper", type=pathlib.Path, required=True, help="Path to the helper Python source.")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="Path to write the generated .ns file.")
    args = parser.parse_args()

    helper_source = args.helper.read_text(encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_ns_text(helper_source), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
