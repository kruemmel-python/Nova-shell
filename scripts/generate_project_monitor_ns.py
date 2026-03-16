from __future__ import annotations

import argparse
import base64
import pathlib
import zlib


def build_ns_text(helper_source: str) -> str:
    payload = base64.b64encode(zlib.compress(helper_source.encode("utf-8"), level=9)).decode("ascii")
    chunks = [payload[index : index + 900] for index in range(0, len(payload), 900)]
    lines = [
        "# Nova-shell Live Project Monitor for the current project directory",
        "# Copy this file into a project root and run: ns.run nova_project_monitor.ns",
        "# Optional env:",
        "#   NOVA_PROJECT_MONITOR_INTERVAL=2",
        "#   NOVA_PROJECT_MONITOR_DEBOUNCE=1.0",
        "#   NOVA_PROJECT_MONITOR_OPEN=0",
        "#   NOVA_PROJECT_MONITOR_ONESHOT=1",
        "#   NOVA_PROJECT_MONITOR_WATCH_MODE=auto|watchdog|poll",
        "#   NOVA_PROJECT_MONITOR_AUTOMATION=auto|on|off",
        "#   NOVA_PROJECT_MONITOR_AUTOMATION_TIMEOUT=600",
        "#   NOVA_PROJECT_MONITOR_AI_MODE=auto|atheria|openai|openrouter|groq|lmstudio|ollama",
        "#   NOVA_PROJECT_MONITOR_AI_MODEL=<model>",
        "py import pathlib, runpy, base64, zlib",
        'project_root = py str(pathlib.Path(".").resolve())',
        'monitor_dir = py str(pathlib.Path($project_root) / ".nova_project_monitor")',
        'helper_path = py str(pathlib.Path($monitor_dir) / "project_monitor_helper.py")',
        "py pathlib.Path($monitor_dir).mkdir(parents=True, exist_ok=True)",
        'blob = py ""',
    ]
    for chunk in chunks:
        lines.append(f"blob = py $blob + {chunk!r}")
    lines.extend(
        [
            "py pathlib.Path($helper_path).write_bytes(zlib.decompress(base64.b64decode($blob)))",
            'monitor_run = py ns = runpy.run_path($helper_path, run_name="project_monitor_helper"); ns["main"]()',
            'py print("Nova-shell Projektmonitor beendet. Report: .nova_project_monitor/project_monitor_report.html")',
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a self-contained Nova-shell project monitor .ns file.")
    parser.add_argument("--helper", type=pathlib.Path, required=True, help="Path to the helper Python source.")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="Path to write the generated .ns file.")
    args = parser.parse_args()

    helper_source = args.helper.read_text(encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_ns_text(helper_source), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
