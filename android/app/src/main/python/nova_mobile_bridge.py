from __future__ import annotations

import json
import os
import shlex
import sys
import threading
from pathlib import Path
from typing import Any


MOBILE_BLOCKED_COMMAND_GROUPS = {
    "cpp",
    "cpp.expr",
    "cpp.expr_chain",
    "cpp.sandbox",
    "gpu",
    "jit_wasm",
    "wasm",
}
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
_SHELL_LOCK = threading.RLock()
_SHELL = None


def _runtime_root() -> Path:
    return Path(__file__).resolve().parent


def _runtime_manifest_path() -> Path:
    return _runtime_root() / "android_runtime_manifest.json"


def _bootstrap_runtime() -> Path:
    runtime_root = _runtime_root()
    runtime_text = str(runtime_root)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    os.environ.setdefault("NOVA_MOBILE_PROFILE", "android")
    os.environ.setdefault("NOVA_DISABLE_BROWSER", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("HOME", runtime_text)
    return runtime_root


def _runtime_ready() -> bool:
    runtime_root = _runtime_root()
    return (runtime_root / "nova_shell.py").is_file() and (runtime_root / "nova").is_dir()


def _runtime_manifest() -> dict[str, Any]:
    manifest_path = _runtime_manifest_path()
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _split_pipeline_stages(command: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escape = False
    for char in command:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\" and quote:
            current.append(char)
            escape = True
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = ""
            elif not quote:
                quote = char
            current.append(char)
            continue
        if char == "|" and not quote:
            stage = "".join(current).strip()
            if stage:
                parts.append(stage)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _command_tokens(command: str) -> list[str]:
    tokens: list[str] = []
    for stage in _split_pipeline_stages(command):
        try:
            parts = shlex.split(stage)
        except ValueError:
            parts = stage.split()
        if parts:
            tokens.append(parts[0])
    return tokens


def _blocked_command(command: str) -> str | None:
    for token in _command_tokens(command):
        if token in MOBILE_BLOCKED_COMMAND_GROUPS:
            return token
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(getattr(value, "value"))
    return str(value)


def _normalize_cwd(raw_cwd: str | None) -> Path:
    runtime_root = _runtime_root()
    if not raw_cwd:
        return runtime_root
    candidate = Path(raw_cwd)
    if not candidate.is_absolute():
        candidate = runtime_root / candidate
    return candidate.resolve(strict=False)


def _shell_instance():
    global _SHELL
    with _SHELL_LOCK:
        if _SHELL is not None:
            return _SHELL
        runtime_root = _bootstrap_runtime()
        previous_cwd = Path.cwd()
        try:
            os.chdir(runtime_root)
            from nova_shell import NovaShell

            shell = NovaShell()
            shell.cwd = runtime_root
            _SHELL = shell
            return shell
        finally:
            os.chdir(previous_cwd)


def bootstrap_summary() -> dict[str, Any]:
    runtime_root = _bootstrap_runtime()
    manifest = _runtime_manifest()
    return {
        "ok": _runtime_ready(),
        "runtime_root": str(runtime_root),
        "runtime_ready": _runtime_ready(),
        "allowed_command_groups": manifest.get("allowed_command_groups", MOBILE_ALLOWED_COMMAND_GROUPS),
        "blocked_command_groups": manifest.get("blocked_command_groups", sorted(MOBILE_BLOCKED_COMMAND_GROUPS)),
        "notes": manifest.get("notes", []),
        "examples": [
            "doctor",
            "remote http://10.0.2.2:8765 doctor",
            "pulse status",
            "help",
            "ns.graph examples/CEO_ns/CEO_Lifecycle.ns",
            "ns.run examples/CEO_ns/StrategyAgent.ns",
        ],
    }


def bootstrap_summary_json() -> str:
    return json.dumps(bootstrap_summary(), indent=2, ensure_ascii=False)


def run_single_command(command: str, cwd: str | None = None) -> dict[str, Any]:
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "empty command"}
    if not _runtime_ready():
        return {
            "ok": False,
            "error": "Android runtime is not staged yet. Run `python scripts/build_android.py prepare` from the repository root first.",
        }
    blocked = _blocked_command(command)
    if blocked is not None:
        return {
            "ok": False,
            "error": f"command group `{blocked}` is blocked in the Android preview",
            "blocked_command_group": blocked,
        }

    with _SHELL_LOCK:
        shell = _shell_instance()
        shell.cwd = _normalize_cwd(cwd)
        result = shell.route(command)
    return {
        "ok": result.error is None,
        "command": command,
        "cwd": str(shell.cwd),
        "output": result.output,
        "error": result.error,
        "data": _json_safe(result.data),
        "data_type": getattr(result.data_type, "value", str(result.data_type)),
    }


def run_single_command_json(command: str, cwd: str | None = None) -> str:
    return json.dumps(run_single_command(command, cwd=cwd), indent=2, ensure_ascii=False)
