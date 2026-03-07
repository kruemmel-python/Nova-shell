from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_check(command: list[str], expected_stdout: str | None = None) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(
            f"smoke test failed for {' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if expected_stdout is not None and completed.stdout.strip() != expected_stdout:
        raise SystemExit(
            f"unexpected stdout for {' '.join(command)}\nexpected: {expected_stdout!r}\nactual: {completed.stdout.strip()!r}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test a standalone Nova-shell executable.")
    parser.add_argument("executable")
    args = parser.parse_args(argv)

    executable = Path(args.executable).resolve()
    if not executable.exists():
        raise SystemExit(f"standalone executable not found: {executable}")

    run_check([str(executable), "--version"])
    run_check([str(executable), "--no-plugins", "-c", "py 1 + 1"], expected_stdout="2")
    run_check([str(executable), "--no-plugins", "-c", "doctor json"])

    print(f"smoke tests passed for {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
