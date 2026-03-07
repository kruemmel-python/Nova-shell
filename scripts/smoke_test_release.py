from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_check(command: list[str], expected_stdout: str | None = None) -> str:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(
            f"smoke test failed for {' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if expected_stdout is not None and completed.stdout.strip() != expected_stdout:
        raise SystemExit(
            f"unexpected stdout for {' '.join(command)}\nexpected: {expected_stdout!r}\nactual: {completed.stdout.strip()!r}"
        )
    return completed.stdout


def expected_modules_for_profile(profile: str) -> dict[str, bool]:
    if profile == "enterprise":
        return {
            "psutil": True,
            "yaml": True,
            "pyarrow": True,
            "wasmtime": True,
            "numpy": True,
            "pyopencl": True,
        }
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test a standalone Nova-shell executable.")
    parser.add_argument("executable")
    parser.add_argument("--profile", choices=["core", "enterprise"], default="core")
    args = parser.parse_args(argv)

    executable = Path(args.executable).resolve()
    if not executable.exists():
        raise SystemExit(f"standalone executable not found: {executable}")

    run_check([str(executable), "--version"])
    run_check([str(executable), "--no-plugins", "-c", "py 1 + 1"], expected_stdout="2")
    doctor_stdout = run_check([str(executable), "--no-plugins", "-c", "doctor json"])
    doctor_payload = json.loads(doctor_stdout)
    if args.profile == "enterprise" and not doctor_payload.get("sandbox_default"):
        raise SystemExit("doctor sandbox_default check failed for enterprise profile")
    for module_name, expected in expected_modules_for_profile(args.profile).items():
        actual = bool(doctor_payload.get("modules", {}).get(module_name))
        if actual != expected:
            raise SystemExit(
                f"doctor module check failed for {module_name!r}: expected {expected}, actual {actual}"
            )

    print(f"smoke tests passed for {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
