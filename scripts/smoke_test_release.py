from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def smoke_runtime_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env.setdefault(key, "1")
    if extra:
        env.update(extra)
    return env


def run_check(command: list[str], *, cwd: Path, expected_stdout: str | None = None, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(cwd), env=env)
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
        modules = {
            "psutil": True,
            "yaml": True,
            "pyarrow": True,
            "wasmtime": True,
            "numpy": True,
        }
        if sys.platform.startswith("win"):
            modules["pyopencl"] = True
        return modules
    modules = {
        "psutil": True,
        "yaml": True,
        "pyarrow": True,
        "wasmtime": True,
        "numpy": True,
    }
    if sys.platform.startswith("win"):
        modules["pyopencl"] = True
    return modules


def expected_commands_for_platform() -> dict[str, bool]:
    if sys.platform.startswith("win"):
        return {
            "emcc": True,
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

    base_env = smoke_runtime_env()

    run_check([str(executable), "--version"], cwd=executable.parent, env=base_env)
    run_check([str(executable), "--no-plugins", "-c", "py 1 + 1"], cwd=executable.parent, expected_stdout="2", env=base_env)
    doctor_stdout = run_check([str(executable), "--no-plugins", "-c", "doctor json"], cwd=executable.parent, env=base_env)
    doctor_payload = json.loads(doctor_stdout)
    if args.profile == "enterprise" and not doctor_payload.get("sandbox_default"):
        raise SystemExit("doctor sandbox_default check failed for enterprise profile")
    for module_name, expected in expected_modules_for_profile(args.profile).items():
        actual = bool(doctor_payload.get("modules", {}).get(module_name))
        if actual != expected:
            raise SystemExit(
                f"doctor module check failed for {module_name!r}: expected {expected}, actual {actual}"
            )
    for command_name, expected in expected_commands_for_platform().items():
        actual = bool(doctor_payload.get("command_status", {}).get(command_name))
        if actual != expected:
            raise SystemExit(
                f"doctor command check failed for {command_name!r}: expected {expected}, actual {actual}"
            )
    atheria_payload = doctor_payload.get("atheria", {})
    if args.profile == "enterprise":
        if not bool(atheria_payload.get("available")):
            raise SystemExit("doctor atheria availability check failed for enterprise profile")
    if bool(atheria_payload.get("available")):
        run_check([str(executable), "--no-plugins", "-c", "atheria init"], cwd=executable.parent, env=base_env)
        with tempfile.TemporaryDirectory(dir=str(executable.parent)) as tmp:
            sensor_env = smoke_runtime_env()
            sensor_env["INDUSTRY_TREND_STATE"] = str(Path(tmp) / "trend-state.json")
            payload_path = Path(tmp) / "trend-payload.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "title": "AI runtime update",
                            "summary": "new agent workflow runtime release",
                            "source": "feed-a",
                            "url": "https://a",
                        },
                        {
                            "title": "Inference benchmark",
                            "summary": "research benchmark for model inference",
                            "source": "feed-b",
                            "url": "https://b",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            run_check(
                [str(executable), "--no-plugins", "-c", "atheria sensor load trend_rss_sensor.py --name trend_radar_smoke"],
                cwd=executable.parent,
                env=sensor_env,
            )
            trend_stdout = run_check(
                [
                    str(executable),
                    "--no-plugins",
                    "-c",
                    f"atheria sensor run trend_radar_smoke --file {payload_path}",
                ],
                cwd=executable.parent,
                env=sensor_env,
            )
            trend_payload = json.loads(trend_stdout)
            metadata = trend_payload.get("metadata", {})
            if metadata.get("forecast_direction") != "warming_baseline":
                raise SystemExit(
                    f"trend sensor smoke test returned unexpected forecast_direction: {metadata.get('forecast_direction')!r}"
                )
    wiki_stdout = run_check([str(executable), "--no-plugins", "-c", "wiki build"], cwd=executable.parent, env=base_env)
    wiki_payload = json.loads(wiki_stdout)
    if int(wiki_payload.get("page_count") or 0) <= 0:
        raise SystemExit("wiki build did not generate any pages")
    wiki_output_dir = Path(str(wiki_payload.get("output_dir") or ""))
    if not wiki_output_dir.is_dir():
        raise SystemExit(f"wiki output directory missing: {wiki_output_dir}")
    if not (wiki_output_dir / "Home.html").exists() and not (wiki_output_dir / "index.html").exists():
        raise SystemExit("wiki build did not produce a home page")
    if sys.platform.startswith("win"):
        sandbox_env = smoke_runtime_env()
        temp_root = executable.parent / ".smoke-temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(temp_root)) as tmp:
            sandbox_root = Path(tmp)
            sandbox_cache = sandbox_root / "emsdk-cache"
            sandbox_cache.mkdir(parents=True, exist_ok=True)
            sandbox_env["EM_CACHE"] = str(sandbox_cache)
            sandbox_env["TMP"] = str(sandbox_root)
            sandbox_env["TEMP"] = str(sandbox_root)
            sandbox_env["TMPDIR"] = str(sandbox_root)
            run_check(
                [str(executable), "--no-plugins", "-c", "cpp.sandbox int main(){ return 0; }"],
                cwd=executable.parent,
                expected_stdout="sandbox executed",
                env=sandbox_env,
            )

    print(f"smoke tests passed for {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
