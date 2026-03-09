from __future__ import annotations

import argparse
import atexit
import asyncio
import codeop
import contextlib
import copy
import csv
import inspect
import importlib
import importlib.util
import io
import http.server
import threading
import time
import json
import math
import os
import glob
import fnmatch
import re
import socket
import shlex
import shutil
import subprocess
import tempfile
import zipfile
import uuid
import sqlite3
import hashlib
import base64
import platform
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Callable, Iterable

from novascript import Assignment as NSAssignment, Command as NSCommand, NovaInterpreter, NovaJITCompiler, NovaParser, WatchHook as NSWatchHook

try:
    import readline
except ImportError:  # pragma: no cover - platform dependent
    readline = None


__version__ = "0.8.1"
SIDELOAD_PACKAGE_DIR = "vendor-py"
RUNTIME_CONFIG_FILE = "nova-shell-runtime.json"


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


def configure_sideload_paths() -> None:
    candidates = [
        Path(sys.executable).resolve().parent / SIDELOAD_PACKAGE_DIR,
        Path(__file__).resolve().parent / SIDELOAD_PACKAGE_DIR,
    ]
    for candidate in candidates:
        candidate_text = str(candidate)
        if candidate.is_dir() and candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)


def module_available(module_name: str) -> bool:
    with contextlib.suppress(Exception):
        return importlib.util.find_spec(module_name) is not None
    return False


def load_runtime_config() -> dict[str, Any]:
    candidates = [
        Path(sys.executable).resolve().parent / RUNTIME_CONFIG_FILE,
        Path(__file__).resolve().parent / RUNTIME_CONFIG_FILE,
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
        except Exception:
            continue
    return {}


def parse_dotenv_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv_files(candidates: Iterable[Path], *, override: bool = False) -> list[str]:
    loaded: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.resolve(strict=False)
        candidate_text = str(candidate)
        if candidate_text in seen or not candidate.is_file():
            continue
        seen.add(candidate_text)
        try:
            values = parse_dotenv_text(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key, value in values.items():
            if override or key not in os.environ:
                os.environ[key] = value
        loaded.append(candidate_text)
    return loaded


def _resolve_vswhere_path() -> Path | None:
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidate = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    return candidate if candidate.exists() else None


def _run_vswhere(args: list[str]) -> list[str]:
    vswhere = _resolve_vswhere_path()
    if vswhere is None:
        return []
    try:
        completed = subprocess.run(
            [str(vswhere), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def resolve_gxx_command() -> str:
    path = shutil.which("g++")
    if path:
        return path
    if _is_windows_runtime():
        for candidate in (
            r"C:\msys64\ucrt64\bin\g++.exe",
            r"C:\msys64\mingw64\bin\g++.exe",
        ):
            if Path(candidate).exists():
                return candidate
    return ""


def resolve_cl_command() -> str:
    path = shutil.which("cl")
    if path:
        return path
    if not _is_windows_runtime():
        return ""

    install_paths = _run_vswhere(
        [
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ]
    )
    for install_path in install_paths:
        tools_root = Path(install_path) / "VC" / "Tools" / "MSVC"
        if not tools_root.exists():
            continue
        versions = sorted([path for path in tools_root.iterdir() if path.is_dir()], reverse=True)
        for version_path in versions:
            candidate = version_path / "bin" / "Hostx64" / "x64" / "cl.exe"
            if candidate.exists():
                return str(candidate)
    return ""


def resolve_emcc_command(runtime_config: dict[str, Any], modules: dict[str, bool]) -> str:
    path = shutil.which("emcc")
    if path:
        return path
    if _is_windows_runtime():
        for candidate in (
            r"C:\emsdk\upstream\emscripten\emcc.bat",
            str(Path.home() / "emsdk" / "upstream" / "emscripten" / "emcc.bat"),
        ):
            if Path(candidate).exists():
                return candidate
    if runtime_config.get("profile") == "enterprise" and modules.get("wasmtime"):
        return "bundled-wasm-runtime"
    return ""


def build_tool_subprocess_env(executable_path: str) -> dict[str, str]:
    env = os.environ.copy()
    tool_dir = str(Path(executable_path).resolve().parent)
    current = env.get("PATH", "")
    entries = [entry for entry in current.split(os.pathsep) if entry]
    normalized_entries = {os.path.normcase(os.path.normpath(entry)) for entry in entries}
    normalized_tool_dir = os.path.normcase(os.path.normpath(tool_dir))
    if normalized_tool_dir not in normalized_entries:
        env["PATH"] = tool_dir + (os.pathsep + current if current else "")
    return env


configure_sideload_paths()


class PipelineType(str, Enum):
    TEXT = "text"
    OBJECT = "object"
    ARRAY = "array"
    TEXT_STREAM = "text_stream"
    OBJECT_STREAM = "object_stream"
    ARRAY_STREAM = "array_stream"
    GENERATOR = "generator"
    ARROW_TABLE = "arrow_table"
    SHARED_MEMORY = "shared_memory"


@dataclass
class CommandResult:
    output: str
    data: Any = None
    error: str | None = None
    data_type: PipelineType = PipelineType.TEXT


@dataclass
class PipelineNode:
    name: str
    stages: list[str] = field(default_factory=list)
    parallel: bool = False


@dataclass
class PipelineGraph:
    nodes: list[PipelineNode] = field(default_factory=list)

    def add(self, node: PipelineNode) -> None:
        self.nodes.append(node)


@dataclass(frozen=True)
class AIProviderSpec:
    name: str
    kind: str
    env_keys: tuple[str, ...]
    base_url: str
    base_url_env: str
    default_model: str
    default_model_env: str
    fallback_models: tuple[str, ...] = ()
    requires_api_key: bool = True
    openai_compat: bool = False


@dataclass
class AIAgentDefinition:
    name: str
    prompt_template: str
    provider: str
    model: str
    system_prompt: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class VectorMemoryEntry:
    entry_id: str
    namespace: str
    project: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class ToolSchemaDefinition:
    name: str
    description: str
    schema: dict[str, Any]
    pipeline_template: str
    builtin: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentRuntimeInstance:
    name: str
    provider: str
    model: str
    system_prompt: str
    prompt_template: str
    source_agent: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentGraphDefinition:
    name: str
    nodes: list[str]
    edges: list[tuple[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class AtheriaSensorPluginSpec:
    name: str
    path: str
    mapping: dict[str, str] = field(default_factory=dict)
    description: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class LensForkArtifact:
    fork_id: str
    snapshot_id: str
    inject_payload: dict[str, Any]
    diff: list[dict[str, Any]] = field(default_factory=list)
    simulation: dict[str, Any] = field(default_factory=dict)
    namespace: str = "default"
    project: str = "default"
    created_at: float = field(default_factory=time.time)


@dataclass
class AutoRAGWatcherSpec:
    watcher_id: str
    pattern: str
    namespace: str
    project: str
    chunk_size: int
    chunk_overlap: int
    publish_topic: str
    summarize: bool = True
    train_atheria: bool = True
    reactive_trigger_id: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class LocalManagedWorker:
    worker_id: str
    url: str
    caps: set[str]
    process: subprocess.Popen[Any]
    log_path: Path
    started_at: float = field(default_factory=time.time)


@dataclass
class GPUTaskGraphArtifact:
    graph_id: str
    kernels: list[str]
    input_payload: str
    final_output: str = ""
    final_data: Any = None


def split_command(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    return list(lexer)


class PythonEngine:
    """Execute Python snippets with optional pipeline input and persistent globals."""

    def __init__(self) -> None:
        self.globals: dict[str, Any] = {"os": os}
        self._execution_lock = threading.RLock()

    @contextlib.contextmanager
    def _push_cwd(self, cwd: Path | None) -> Iterable[None]:
        if cwd is None:
            yield
            return
        previous_cwd = Path.cwd()
        os.chdir(cwd)
        try:
            yield
        finally:
            os.chdir(previous_cwd)

    def execute(
        self,
        code: str,
        pipeline_input: str = "",
        pipeline_data: Any = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        stdout_buffer = io.StringIO()

        try:
            with self._execution_lock:
                self.globals["_"] = pipeline_data if pipeline_data is not None else pipeline_input
                with self._push_cwd(cwd), contextlib.redirect_stdout(stdout_buffer):
                    try:
                        value = eval(code, self.globals, self.globals)
                        if value is not None:
                            self.globals["_"] = value
                            print(value)
                    except SyntaxError:
                        exec(code, self.globals, self.globals)

            output = stdout_buffer.getvalue()
            data = self.globals.get("_")
            if isinstance(data, list):
                data_type = PipelineType.OBJECT_STREAM
            elif isinstance(data, dict):
                data_type = PipelineType.OBJECT
            else:
                data_type = PipelineType.TEXT
            return CommandResult(output=output, data=data, data_type=data_type)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))


class CppEngine:
    """Compile and run C++ code snippets via g++."""

    def compile_and_run(self, code: str, pipeline_input: str = "") -> CommandResult:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "program.cpp"
            binary = Path(tmp) / ("program.exe" if _is_windows_runtime() else "program")

            source.write_text(code, encoding="utf-8")
            compiler = resolve_gxx_command()
            if not compiler:
                return CommandResult(output="", error="g++ is required for cpp commands")
            compiler_env = build_tool_subprocess_env(compiler)

            try:
                compile_proc = subprocess.run(
                    [compiler, "-std=c++20", "-O2", str(source), "-o", str(binary)],
                    capture_output=True,
                    text=True,
                    env=compiler_env,
                )
            except FileNotFoundError:
                return CommandResult(output="", error="g++ is required for cpp commands")
            if compile_proc.returncode != 0:
                return CommandResult(output="", error=compile_proc.stderr)

            try:
                run_proc = subprocess.run(
                    [str(binary)],
                    capture_output=True,
                    text=True,
                    input=pipeline_input,
                    env=compiler_env,
                )
            except FileNotFoundError:
                return CommandResult(output="", error="compiled cpp binary could not be executed")
            return CommandResult(
                output=run_proc.stdout,
                error=run_proc.stderr if run_proc.stderr else None,
            )

    def compile_to_wasm_and_run(self, code: str, pipeline_input: str = "") -> CommandResult:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "program.cpp"
            wasm = Path(tmp) / "program.wasm"
            source.write_text(code, encoding="utf-8")
            has_wasmtime = False
            with contextlib.suppress(Exception):
                import wasmtime  # noqa: F401
                has_wasmtime = True
            emcc_command = resolve_emcc_command(load_runtime_config(), {"wasmtime": has_wasmtime})
            if not emcc_command:
                return CommandResult(output="", error="emcc is required for cpp sandbox mode")
            if emcc_command == "bundled-wasm-runtime":
                return CommandResult(output="", error="enterprise runtime includes wasmtime, but cpp sandbox mode still requires an emcc compiler")
            compiler_env = build_tool_subprocess_env(emcc_command)

            try:
                compile_proc = subprocess.run(
                    [emcc_command, str(source), "-O2", "-s", "STANDALONE_WASM=1", "-s", "EXPORTED_FUNCTIONS=['_main']", "-o", str(wasm)],
                    capture_output=True,
                    text=True,
                    env=compiler_env,
                )
            except FileNotFoundError:
                return CommandResult(output="", error="emcc is required for cpp sandbox mode")
            if compile_proc.returncode != 0:
                return CommandResult(output="", error=f"sandbox compile failed: {compile_proc.stderr.strip()}")

            try:
                import wasmtime
            except ImportError:
                return CommandResult(output="", error="wasmtime is required for cpp sandbox mode")

            try:
                store = wasmtime.Store()
                module = wasmtime.Module.from_file(store.engine, str(wasm))
                linker = wasmtime.Linker(store.engine)
                instance = linker.instantiate(store, module)
                run = instance.exports(store).get("_start")
                if run is None:
                    return CommandResult(output="", error="sandbox wasm module missing _start")
                run(store)
                return CommandResult(output="sandbox executed\n")
            except Exception as exc:
                return CommandResult(output="", error=f"sandbox runtime error: {exc}")


class GPUEngine:
    """Run OpenCL kernels when pyopencl is available."""

    def run_kernel(self, kernel_file: str, pipeline_input: str = "") -> CommandResult:
        try:
            import pyopencl as cl
            import numpy as np
        except ImportError:
            return CommandResult(output="", error="pyopencl and numpy are required for gpu commands")

        try:
            kernel_path = Path(kernel_file)
            source = kernel_path.read_text(encoding="utf-8")
            platform = cl.get_platforms()[0]
            device = platform.get_devices()[0]
            context = cl.Context([device])
            queue = cl.CommandQueue(context)

            program = cl.Program(context, source).build()
            data = np.arange(10, dtype=np.float32)
            if pipeline_input.strip():
                parsed = [float(x) for x in pipeline_input.split()]
                data = np.array(parsed, dtype=np.float32)

            buffer = cl.Buffer(
                context,
                cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,
                hostbuf=data,
            )
            program.compute(queue, data.shape, None, buffer)
            cl.enqueue_copy(queue, data, buffer)
            return CommandResult(
                output=" ".join(map(str, data.tolist())) + "\n",
                data=data.tolist(),
                data_type=PipelineType.ARRAY_STREAM,
            )
        except Exception as exc:
            return CommandResult(output="", error=str(exc))


class DataEngine:
    """Load and emit structured data for pipelines."""

    def load_csv(self, file_path: str) -> CommandResult:
        try:
            rows: list[dict[str, str]] = []
            with Path(file_path).open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows.extend(reader)
            return CommandResult(output=json.dumps(rows, ensure_ascii=False) + "\n", data=rows, data_type=PipelineType.OBJECT_STREAM)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def load_csv_arrow(self, file_path: str) -> CommandResult:
        try:
            import pyarrow.csv as pacsv
        except ImportError:
            return CommandResult(output="", error="pyarrow is required for arrow mode")

        try:
            table = pacsv.read_csv(file_path)
            return CommandResult(
                output=f"ArrowTable rows={table.num_rows} cols={table.num_columns}\n",
                data=table,
                data_type=PipelineType.ARROW_TABLE,
            )
        except Exception as exc:
            return CommandResult(output="", error=str(exc))


class SystemEngine:
    """Run host shell commands."""

    def execute(self, command: str, pipeline_input: str = "", cwd: Path | None = None) -> CommandResult:
        parts = split_command(command)
        if parts and parts[0] == "printf":
            payload = " ".join(parts[1:])
            try:
                payload = payload.encode("utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                pass
            return CommandResult(
                output=payload,
                data=payload,
                data_type=PipelineType.TEXT,
            )
        if parts and parts[0] == "sleep":
            seconds = 0.0
            if len(parts) > 1:
                with contextlib.suppress(Exception):
                    seconds = max(0.0, float(parts[1]))
            time.sleep(seconds)
            return CommandResult(output="", data="", data_type=PipelineType.TEXT)

        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            input=pipeline_input,
            cwd=str(cwd) if cwd is not None else None,
        )
        return CommandResult(
            output=proc.stdout,
            data=proc.stdout,
            error=proc.stderr if proc.stderr else None,
            data_type=PipelineType.TEXT,
        )


class EventBus:
    def __init__(self) -> None:
        self.subscribers: list[Callable[[dict[str, str]], None]] = []
        self.events: list[dict[str, str]] = []

    def subscribe(self, callback: Callable[[dict[str, str]], None]) -> None:
        self.subscribers.append(callback)

    def emit(self, data: dict[str, str]) -> None:
        self.events.append(data)
        for subscriber in self.subscribers:
            subscriber(data)

    def last(self) -> dict[str, str] | None:
        return self.events[-1] if self.events else None


class NovaFabric:
    """Local shared-memory bridge used as a zero-copy-like handoff primitive."""

    def __init__(self) -> None:
        self._segments: dict[str, shared_memory.SharedMemory] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def put_bytes(self, payload: bytes, data_type: str) -> CommandResult:
        segment = shared_memory.SharedMemory(create=True, size=max(1, len(payload)))
        if payload:
            segment.buf[: len(payload)] = payload
        handle = segment.name
        self._segments[handle] = segment
        self._metadata[handle] = {"size": len(payload), "type": data_type}
        return CommandResult(
            output=f"{handle}\n",
            data={"handle": handle, "size": len(payload), "type": data_type},
            data_type=PipelineType.SHARED_MEMORY,
        )

    def put(self, value: str) -> CommandResult:
        return self.put_bytes(value.encode("utf-8"), "text")

    def put_arrow_table(self, table: Any) -> CommandResult:
        try:
            import pyarrow as pa

            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            payload = sink.getvalue().to_pybytes()
            result = self.put_bytes(payload, "arrow_table")
            if result.data:
                result.data["format"] = "arrow_ipc_stream"
            return result
        except Exception as exc:
            return CommandResult(output="", error=f"arrow fabric store failed: {exc}")

    def put_arrow_from_csv(self, csv_path: str) -> CommandResult:
        try:
            import pyarrow.csv as pacsv
        except ImportError:
            return CommandResult(output="", error="pyarrow is required for fabric put-arrow")
        try:
            table = pacsv.read_csv(csv_path)
            return self.put_arrow_table(table)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _format_arrow_payload(self, data: bytes) -> CommandResult | None:
        with contextlib.suppress(Exception):
            import pyarrow as pa

            reader = pa.ipc.open_stream(pa.BufferReader(data))
            table = reader.read_all()
            preview = table.slice(0, min(10, table.num_rows)).to_pylist()
            payload = {
                "type": "arrow_table",
                "rows": table.num_rows,
                "columns": table.column_names,
                "preview": preview,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        return None

    def get(self, handle: str) -> CommandResult:
        segment = self._segments.get(handle)
        needs_close = False
        if segment is None:
            try:
                segment = shared_memory.SharedMemory(name=handle)
            except FileNotFoundError:
                return CommandResult(output="", error=f"shared memory handle not found: {handle}")
            needs_close = True

        metadata = self._metadata.get(handle, {})
        size = int(metadata.get("size") or segment.size)
        data = bytes(segment.buf[:size])
        try:
            text = data.decode("utf-8", errors="strict")
            return CommandResult(output=f"{text}\n", data=text, data_type=PipelineType.TEXT)
        except UnicodeDecodeError:
            arrow_result = self._format_arrow_payload(data)
            if arrow_result is not None:
                return arrow_result
            payload = {
                "type": str(metadata.get("type") or "binary"),
                "size": len(data),
                "base64": base64.b64encode(data).decode("ascii"),
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        finally:
            if needs_close:
                with contextlib.suppress(Exception):
                    segment.close()

    def cleanup(self) -> None:
        for handle, segment in list(self._segments.items()):
            with contextlib.suppress(Exception):
                segment.close()
            with contextlib.suppress(Exception):
                segment.unlink()
            self._segments.pop(handle, None)
            self._metadata.pop(handle, None)


class PolicyEngine:
    """Simple policy-as-code style guard for stage permissions."""

    def __init__(self) -> None:
        self.policies: dict[str, set[str]] = {
            "open": set(),
            "minimal": {"sys", "remote", "gpu", "wasm"},
            "offline": {"remote"},
        }

    def is_allowed(self, policy: str, stage: str) -> tuple[bool, str | None]:
        denied = self.policies.get(policy)
        if denied is None:
            return False, f"unknown policy: {policy}"

        parts = split_command(stage)
        if not parts:
            return True, None
        cmd = parts[0]
        if cmd in denied:
            return False, f"policy '{policy}' blocks command '{cmd}'"
        return True, None


class MeshScheduler:
    """Topology-aware worker registry and latency/data-locality-aware scheduling."""

    def __init__(self) -> None:
        self.workers: list[dict[str, Any]] = []

    def add_worker(self, url: str, caps: set[str]) -> None:
        self.workers = [w for w in self.workers if w["url"] != url]
        self.workers.append(
            {
                "url": url,
                "caps": caps,
                "load": 0,
                "latency_ms": 15.0,
                "data_handles": set(),
                "last_seen": time.time(),
            }
        )

    def get_worker(self, url: str) -> dict[str, Any] | None:
        return next((w for w in self.workers if w["url"] == url), None)

    def remove_worker(self, url: str) -> bool:
        before = len(self.workers)
        self.workers = [w for w in self.workers if w["url"] != url]
        return len(self.workers) != before

    def heartbeat(self, url: str, *, latency_ms: float | None = None, data_handles: Iterable[str] | None = None) -> bool:
        worker = next((w for w in self.workers if w["url"] == url), None)
        if worker is None:
            return False
        worker["last_seen"] = time.time()
        if latency_ms is not None:
            worker["latency_ms"] = max(0.1, float(latency_ms))
        if data_handles is not None:
            worker["data_handles"] = set(data_handles)
        return True

    def list_workers(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for w in sorted(self.workers, key=lambda item: (item["load"], item["url"])):
            row = {
                "url": w["url"],
                "caps": sorted(w["caps"]),
                "load": w["load"],
                "latency_ms": w.get("latency_ms", 0.0),
                "data_handles": sorted(w.get("data_handles", set())),
                "last_seen": w.get("last_seen", 0.0),
            }
            for key in ("managed_local", "worker_id", "pid", "log_path"):
                if key in w:
                    row[key] = w[key]
            rows.append(row)
        return rows

    def select_worker(self, capability: str) -> dict[str, Any] | None:
        candidates = [w for w in self.workers if capability in w["caps"]]
        if not candidates:
            return None
        chosen = min(candidates, key=lambda item: item["load"])
        chosen["load"] += 1
        return chosen

    def intelligent_select(self, capability: str, data_handle: str | None = None) -> dict[str, Any] | None:
        candidates = [w for w in self.workers if capability in w["caps"]]
        if not candidates:
            return None

        def score(worker: dict[str, Any]) -> float:
            locality_bonus = 25.0 if data_handle and data_handle in worker.get("data_handles", set()) else 0.0
            latency_penalty = worker.get("latency_ms", 15.0) / 10.0
            load_penalty = worker.get("load", 0) * 3.0
            staleness_penalty = max(0.0, (time.time() - worker.get("last_seen", time.time())) / 30.0)
            return locality_bonus - latency_penalty - load_penalty - staleness_penalty

        chosen = max(candidates, key=score)
        chosen["load"] += 1
        return chosen

class NovaZeroPool:
    """Unified zero-copy memory manager for text/arrow payload handoff."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def put_bytes(self, payload: bytes, data_type: str) -> CommandResult:
        segment = shared_memory.SharedMemory(create=True, size=max(1, len(payload)))
        if payload:
            segment.buf[: len(payload)] = payload
        handle = segment.name
        self.objects[handle] = {
            "segment": segment,
            "size": len(payload),
            "type": data_type,
            "refs": 1,
            "created_at": time.time(),
        }
        data = {"handle": handle, "size": len(payload), "type": data_type, "refs": 1}
        return CommandResult(output=json.dumps(data, ensure_ascii=False) + "\n", data=data, data_type=PipelineType.SHARED_MEMORY)

    def put_text(self, text: str) -> CommandResult:
        return self.put_bytes(text.encode("utf-8"), "text")

    def put_arrow_table(self, table: Any) -> CommandResult:
        try:
            import pyarrow as pa
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            payload = sink.getvalue().to_pybytes()
            result = self.put_bytes(payload, "arrow_table")
            if result.data:
                result.data["format"] = "arrow_ipc_stream"
                result.output = json.dumps(result.data, ensure_ascii=False) + "\n"
            return result
        except Exception as exc:
            return CommandResult(output="", error=f"arrow zero-copy store failed: {exc}")

    def put_arrow_from_csv(self, csv_path: str) -> CommandResult:
        try:
            import pyarrow.csv as pacsv
        except ImportError:
            return CommandResult(output="", error="pyarrow is required for zero put-arrow")
        try:
            table = pacsv.read_csv(csv_path)
            return self.put_arrow_table(table)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def get(self, handle: str) -> CommandResult:
        obj = self.objects.get(handle)
        if obj is None:
            return CommandResult(output="", error=f"zero handle not found: {handle}")
        data = bytes(obj["segment"].buf[: obj["size"]])
        if obj["type"] == "text":
            text = data.decode("utf-8", errors="replace")
            return CommandResult(output=text + ("\n" if not text.endswith("\n") else ""), data=text, data_type=PipelineType.TEXT)
        encoded = base64.b64encode(data).decode("ascii")
        payload = {"handle": handle, "type": obj["type"], "size": obj["size"], "refs": obj["refs"], "base64": encoded}
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.SHARED_MEMORY)

    def list(self) -> list[dict[str, Any]]:
        return [
            {"handle": h, "size": o["size"], "type": o["type"], "refs": o["refs"], "created_at": o["created_at"]}
            for h, o in sorted(self.objects.items())
        ]

    def release(self, handle: str) -> CommandResult:
        obj = self.objects.get(handle)
        if obj is None:
            return CommandResult(output="", error=f"zero handle not found: {handle}")
        obj["refs"] -= 1
        if obj["refs"] <= 0:
            with contextlib.suppress(Exception):
                obj["segment"].close()
            with contextlib.suppress(Exception):
                obj["segment"].unlink()
            self.objects.pop(handle, None)
            return CommandResult(output="released\n")
        return CommandResult(output=f"refs={obj['refs']}\n")

    def cleanup(self) -> None:
        for handle, obj in list(self.objects.items()):
            with contextlib.suppress(Exception):
                obj["segment"].close()
            with contextlib.suppress(Exception):
                obj["segment"].unlink()
            self.objects.pop(handle, None)


class FlowStateStore:
    """State backend for event/window-aware streaming decisions."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_events (
                ts REAL NOT NULL,
                event TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def add_event(self, event: str) -> None:
        self.conn.execute("INSERT INTO flow_events(ts, event) VALUES(?, ?)", (time.time(), event))
        self.conn.commit()

    def count_last(self, seconds: float, pattern: str = "*") -> int:
        cutoff = time.time() - seconds
        cur = self.conn.execute("SELECT event FROM flow_events WHERE ts >= ?", (cutoff,))
        return sum(1 for (event,) in cur.fetchall() if fnmatch.fnmatch(event, pattern))

    def set(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO flow_state(key, value) VALUES(?, ?)", (key, value))
        self.conn.commit()

    def get(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT value FROM flow_state WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()


class GCounterCRDT:
    """Grow-only counter CRDT for decentralized approximate synchronization."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.counts: dict[str, int] = {node_id: 0}

    def increment(self, amount: int = 1) -> int:
        self.counts[self.node_id] = self.counts.get(self.node_id, 0) + max(0, amount)
        return self.value

    @property
    def value(self) -> int:
        return sum(self.counts.values())

    def merge(self, remote_counts: dict[str, int]) -> int:
        for node, value in remote_counts.items():
            self.counts[node] = max(self.counts.get(node, 0), int(value))
        return self.value


class LWWMapCRDT:
    """Last-write-wins map CRDT for decentralized key synchronization."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.values: dict[str, tuple[float, str, str]] = {}

    def set(self, key: str, value: str) -> None:
        self.values[key] = (time.time(), self.node_id, value)

    def get(self, key: str) -> str | None:
        row = self.values.get(key)
        return row[2] if row else None

    def merge(self, remote_values: dict[str, list[Any] | tuple[Any, ...]]) -> None:
        for key, payload in remote_values.items():
            ts, node, value = payload
            current = self.values.get(key)
            candidate = (float(ts), str(node), str(value))
            if current is None or candidate[:2] >= current[:2]:
                self.values[key] = candidate


class NovaLensStore:
    """Persistent lineage store with content-addressable payload snapshots."""

    def __init__(self, base_dir: str | Path = ".nova_lens") -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.cas_dir = self.base / "cas"
        self.cas_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base / "lineage.db"
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                trace_id TEXT,
                stage TEXT NOT NULL,
                error TEXT,
                data_type TEXT,
                output_hash TEXT,
                data_hash TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forks (
                id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                ts REAL NOT NULL,
                namespace TEXT NOT NULL,
                project TEXT NOT NULL,
                inject_json TEXT NOT NULL,
                diff_hash TEXT,
                simulation_hash TEXT,
                fork_output_hash TEXT,
                fork_data_hash TEXT
            )
            """
        )
        self.conn.commit()

    def _store_blob(self, value: str) -> str:
        payload = value.encode("utf-8", errors="replace")
        digest = hashlib.sha256(payload).hexdigest()
        self.cas_dir.mkdir(parents=True, exist_ok=True)
        blob_path = self.cas_dir / digest
        if not blob_path.exists():
            blob_path.write_bytes(payload)
        return digest

    def _load_blob(self, digest: str | None) -> str:
        if not digest:
            return ""
        path = self.cas_dir / digest
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def record(self, stage: str, result: CommandResult, trace_id: str, data_preview: str) -> str:
        snap_id = uuid.uuid4().hex[:12]
        output_hash = self._store_blob(result.output or "")
        data_hash = self._store_blob(data_preview or "")
        self.conn.execute(
            "INSERT INTO snapshots(id, ts, trace_id, stage, error, data_type, output_hash, data_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snap_id,
                time.time(),
                trace_id,
                stage,
                result.error or "",
                result.data_type.value,
                output_hash,
                data_hash,
            ),
        )
        self.conn.commit()
        return snap_id

    def list(self, limit: int = 10) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT id, ts, trace_id, stage, error, data_type, output_hash, data_hash FROM snapshots ORDER BY ts DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "trace_id": r[2],
                "stage": r[3],
                "error": r[4],
                "data_type": r[5],
                "output_hash": r[6],
                "data_hash": r[7],
            }
            for r in rows
        ]

    def get(self, snap_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT id, ts, trace_id, stage, error, data_type, output_hash, data_hash FROM snapshots WHERE id = ?",
            (snap_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "ts": row[1],
            "trace_id": row[2],
            "stage": row[3],
            "error": row[4],
            "data_type": row[5],
            "output_hash": row[6],
            "data_hash": row[7],
            "output": self._load_blob(row[6]),
            "data_preview": self._load_blob(row[7]),
        }

    def replay(self, snap_id: str) -> CommandResult:
        data = self.get(snap_id)
        if data is None:
            return CommandResult(output="", error="snapshot not found")
        return CommandResult(output=data.get("output", ""), data=data, data_type=PipelineType.OBJECT)

    def record_fork(
        self,
        *,
        snapshot_id: str,
        namespace: str,
        project: str,
        inject_payload: dict[str, Any],
        diff: list[dict[str, Any]],
        simulation: dict[str, Any],
        fork_output: str,
        fork_data_preview: str,
    ) -> LensForkArtifact:
        fork_id = "fork_" + uuid.uuid4().hex[:10]
        diff_hash = self._store_blob(json.dumps(diff, ensure_ascii=False, indent=2))
        simulation_hash = self._store_blob(json.dumps(simulation, ensure_ascii=False, indent=2))
        fork_output_hash = self._store_blob(fork_output or "")
        fork_data_hash = self._store_blob(fork_data_preview or "")
        payload = LensForkArtifact(
            fork_id=fork_id,
            snapshot_id=snapshot_id,
            inject_payload=dict(inject_payload),
            diff=list(diff),
            simulation=dict(simulation),
            namespace=namespace,
            project=project,
        )
        self.conn.execute(
            """
            INSERT INTO forks(id, snapshot_id, ts, namespace, project, inject_json, diff_hash, simulation_hash, fork_output_hash, fork_data_hash)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.fork_id,
                snapshot_id,
                payload.created_at,
                namespace,
                project,
                json.dumps(inject_payload, ensure_ascii=False),
                diff_hash,
                simulation_hash,
                fork_output_hash,
                fork_data_hash,
            ),
        )
        self.conn.commit()
        return payload

    def list_forks(self, limit: int = 10) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT id, snapshot_id, ts, namespace, project, inject_json
            FROM forks
            ORDER BY ts DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "snapshot_id": row[1],
                "ts": row[2],
                "namespace": row[3],
                "project": row[4],
                "inject": json.loads(str(row[5])),
            }
            for row in rows
        ]

    def get_fork(self, fork_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            """
            SELECT id, snapshot_id, ts, namespace, project, inject_json, diff_hash, simulation_hash, fork_output_hash, fork_data_hash
            FROM forks
            WHERE id = ?
            """,
            (fork_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        diff_text = self._load_blob(row[6])
        simulation_text = self._load_blob(row[7])
        return {
            "id": row[0],
            "snapshot_id": row[1],
            "ts": row[2],
            "namespace": row[3],
            "project": row[4],
            "inject": json.loads(str(row[5])),
            "diff": json.loads(diff_text) if diff_text else [],
            "simulation": json.loads(simulation_text) if simulation_text else {},
            "fork_output": self._load_blob(row[8]),
            "fork_data_preview": self._load_blob(row[9]),
        }

    def close(self) -> None:
        self.conn.close()


class BaseAtheriaSensorPlugin:
    """Base contract for dynamically loaded Atheria sensors."""

    def analyze(self, payload: Any) -> dict[str, Any]:
        raise NotImplementedError


class AtheriaSensorRegistry:
    """Dynamic sensor registry for Atheria-compatible structured events."""

    FEATURE_KEYS = [
        "trauma_pressure",
        "signal_strength",
        "system_temperature",
        "resource_pressure",
        "entropic_index",
        "structural_tension",
        "guardian_score",
        "holographic_energy",
        "cpu_usage",
        "memory_usage",
        "network_latency",
        "error_rate",
        "queue_depth",
        "anomaly_score",
    ]

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.storage_root / "atheria_sensors.json"
        self.plugins: dict[str, AtheriaSensorPluginSpec] = {}
        self._loaded_plugins: dict[str, Any] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        if not self.registry_path.exists():
            return
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, dict):
                continue
            spec = AtheriaSensorPluginSpec(
                name=str(item.get("name") or ""),
                path=str(item.get("path") or ""),
                mapping={str(key): str(value) for key, value in dict(item.get("mapping") or {}).items()},
                description=str(item.get("description") or ""),
                created_at=float(item.get("created_at") or time.time()),
            )
            if spec.name and spec.path:
                self.plugins[spec.name] = spec

    def _save_registry(self) -> None:
        rows = [
            {
                "name": spec.name,
                "path": spec.path,
                "mapping": spec.mapping,
                "description": spec.description,
                "created_at": spec.created_at,
            }
            for spec in sorted(self.plugins.values(), key=lambda item: item.name)
        ]
        self.registry_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def register(self, path: Path, *, name: str | None = None, mapping: dict[str, str] | None = None) -> AtheriaSensorPluginSpec:
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"sensor plugin not found: {path}")
        chosen_name = (name or resolved.stem).strip()
        if not chosen_name:
            raise ValueError("sensor plugin name must not be empty")
        description = ""
        with contextlib.suppress(Exception):
            module = self._load_plugin_from_path(chosen_name, resolved)
            description = str(getattr(module, "__doc__", "") or "").strip().splitlines()[0] if getattr(module, "__doc__", None) else ""
        spec = AtheriaSensorPluginSpec(
            name=chosen_name,
            path=str(resolved),
            mapping=dict(mapping or {}),
            description=description,
        )
        self.plugins[chosen_name] = spec
        self._save_registry()
        return spec

    def set_mapping(self, name: str, mapping: dict[str, str]) -> AtheriaSensorPluginSpec:
        spec = self.plugins.get(name)
        if spec is None:
            raise KeyError(name)
        spec.mapping = {str(key): str(value) for key, value in mapping.items()}
        self._save_registry()
        return spec

    def list_plugins(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "path": spec.path,
                "mapping": spec.mapping,
                "description": spec.description,
                "created_at": spec.created_at,
            }
            for spec in sorted(self.plugins.values(), key=lambda item: item.name)
        ]

    def _load_plugin_from_path(self, name: str, path: Path) -> Any:
        cache_key = str(path.resolve())
        if cache_key in self._loaded_plugins:
            return self._loaded_plugins[cache_key]
        module_name = f"nova_atheria_sensor_{name}_{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()[:10]}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"failed to load sensor plugin: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._loaded_plugins[cache_key] = module
        return module

    def _resolve_analyzer(self, name: str) -> tuple[AtheriaSensorPluginSpec, Callable[[Any], dict[str, Any]]]:
        plugin = self.plugins.get(name)
        if plugin is None:
            raise KeyError(name)
        module = self._load_plugin_from_path(name, Path(plugin.path))
        sensor_obj = getattr(module, "sensor", None)
        if sensor_obj is not None and hasattr(sensor_obj, "analyze"):
            return plugin, sensor_obj.analyze
        for member_name in dir(module):
            candidate = getattr(module, member_name)
            if inspect.isclass(candidate) and issubclass(candidate, BaseAtheriaSensorPlugin) and candidate is not BaseAtheriaSensorPlugin:
                instance = candidate()
                return plugin, instance.analyze
        analyze_fn = getattr(module, "analyze", None)
        if callable(analyze_fn):
            return plugin, analyze_fn
        raise ValueError("sensor plugin must expose analyze(payload) or a BaseAtheriaSensorPlugin subclass")

    def _extract_json_path(self, payload: Any, path_text: str) -> Any:
        normalized = str(path_text).strip()
        if normalized.startswith("$."):
            normalized = normalized[2:]
        if normalized.startswith("$"):
            normalized = normalized[1:]
        if not normalized:
            return payload
        current = payload
        for token in [item for item in normalized.split(".") if item]:
            if isinstance(current, dict):
                current = current.get(token)
                continue
            if isinstance(current, list):
                with contextlib.suppress(Exception):
                    current = current[int(token)]
                    continue
            return None
        return current

    def _coerce_float(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def run(self, name: str, payload: Any) -> dict[str, Any]:
        plugin, analyze = self._resolve_analyzer(name)
        raw = analyze(payload)
        if not isinstance(raw, dict):
            raise ValueError("sensor analyze(payload) must return an object")
        features = {key: 0.0 for key in self.FEATURE_KEYS}
        for key in self.FEATURE_KEYS:
            value = raw.get(key)
            coerced = self._coerce_float(value)
            if coerced is not None:
                features[key] = coerced
        feature_map = raw.get("features")
        if isinstance(feature_map, dict):
            for key, value in feature_map.items():
                if key in features:
                    coerced = self._coerce_float(value)
                    if coerced is not None:
                        features[key] = coerced
        if plugin.mapping and payload is not None:
            for key, path_text in plugin.mapping.items():
                if key not in features:
                    continue
                extracted = self._extract_json_path(payload, path_text)
                coerced = self._coerce_float(extracted)
                if coerced is not None:
                    features[key] = coerced
        vector_payload = raw.get("vector")
        if isinstance(vector_payload, list) and len(vector_payload) == len(self.FEATURE_KEYS):
            vector = [float(item) for item in vector_payload]
            features = {key: vector[index] for index, key in enumerate(self.FEATURE_KEYS)}
        else:
            vector = [float(features[key]) for key in self.FEATURE_KEYS]
        metadata = dict(raw.get("metadata") or {})
        metadata.setdefault("plugin", name)
        metadata.setdefault("source_path", plugin.path)
        summary = str(raw.get("summary") or f"sensor {name} produced {len(self.FEATURE_KEYS)} features").strip()
        return {
            "name": name,
            "event_id": str(raw.get("event_id") or f"{name}_{uuid.uuid4().hex[:8]}"),
            "timestamp": float(raw.get("timestamp") or time.time()),
            "dimensions": len(vector),
            "feature_keys": list(self.FEATURE_KEYS),
            "features": {key: round(float(features[key]), 6) for key in self.FEATURE_KEYS},
            "vector": [round(float(item), 6) for item in vector],
            "metadata": metadata,
            "summary": summary,
            "mapping": plugin.mapping,
        }


class NovaComputeJIT:
    """JIT-like execution path: transpile arithmetic NovaScript snippets to Wasm."""

    def __init__(self) -> None:
        self.compiler = NovaJITCompiler()

    def execute_expression(self, expression: str) -> CommandResult:
        if not expression.strip():
            return CommandResult(output='', error='usage: jit_wasm <arithmetic_expression>')

        try:
            wat = self.compiler.compile_expr_to_wat(expression)
        except Exception as exc:
            return CommandResult(output='', error=f'jit compile error: {exc}')

        try:
            import wasmtime
        except ImportError:
            return CommandResult(output='', error='wasmtime is required for jit_wasm')

        try:
            engine = wasmtime.Engine()
            module = wasmtime.Module(engine, wasmtime.wat2wasm(wat))
            store = wasmtime.Store(engine)
            linker = wasmtime.Linker(engine)
            instance = linker.instantiate(store, module)
            run = instance.exports(store)['run']
            value = float(run(store))
            payload = {'expression': expression, 'wat': wat, 'value': value}
            return CommandResult(output=f'{value}\n', data=payload, data_type=PipelineType.OBJECT)
        except Exception as exc:
            return CommandResult(output='', error=f'jit runtime error: {exc}')


class RemoteEngine:
    """Minimal remote execution client for NovaMesh-like workers."""

    def execute(self, worker_url: str, command: str) -> CommandResult:
        payload = json.dumps({"command": command}).encode("utf-8")
        request = urllib.request.Request(
            worker_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
            return CommandResult(
                output=body.get("output", ""),
                data=body.get("data"),
                error=body.get("error"),
                data_type=PipelineType(body.get("data_type", PipelineType.TEXT.value)),
            )
        except urllib.error.URLError as exc:
            return CommandResult(output="", error=f"remote worker error: {exc}")
        except Exception as exc:
            return CommandResult(output="", error=str(exc))


class WasmEngine:
    """Execute WebAssembly modules via wasmtime when available."""

    def execute(self, wasm_file: str) -> CommandResult:
        try:
            import wasmtime
        except ImportError:
            return CommandResult(output="", error="wasmtime is required for wasm commands")

        try:
            store = wasmtime.Store()
            module = wasmtime.Module.from_file(store.engine, wasm_file)
            linker = wasmtime.Linker(store.engine)
            instance = linker.instantiate(store, module)
            run = instance.exports(store).get("run")
            if run is None:
                return CommandResult(output="", error="wasm module must export function 'run'")
            value = run(store)
            return CommandResult(output=f"{value}\n", data=value, data_type=PipelineType.OBJECT)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))


class NovaOptimizer:
    """Predictive steering across engines using telemetry + lightweight heuristics."""

    def __init__(self, shell: "NovaShell") -> None:
        self.shell = shell

    def _recent_duration(self, engine: str, limit: int = 50) -> float | None:
        durations: list[float] = []
        for event in reversed(self.shell.events.events[-limit:]):
            stage = str(event.get("stage", ""))
            if stage.startswith(engine + " ") or stage == engine:
                with contextlib.suppress(Exception):
                    durations.append(float(event.get("duration_ms", 0.0)))
        if not durations:
            return None
        return sum(durations) / len(durations)

    def suggest_engine(self, task: str, payload: str = "") -> dict[str, Any]:
        task_name = task.lower().strip()
        size = len(payload)
        cpu_percent, _ = self.shell._sample_resources()

        scores: dict[str, float] = {"py": 1.0, "cpp": 1.0, "gpu": 1.0, "mesh": 1.0}
        reasons: list[str] = []

        if size > 50000:
            scores["cpp"] += 2.5
            scores["gpu"] += 2.0
            reasons.append("large payload favors compiled engines")
        elif size < 5000:
            scores["py"] += 1.5
            reasons.append("small payload favors low-overhead python")

        if any(keyword in task_name for keyword in ["matrix", "vector", "tensor", "fft"]):
            scores["gpu"] += 2.5
            scores["cpp"] += 1.5
            reasons.append("numeric keyword match boosts gpu/cpp")

        if cpu_percent > 75 and self.shell.mesh.workers:
            scores["mesh"] += 3.0
            reasons.append("high local CPU and mesh workers available")

        for engine in ["py", "cpp", "gpu"]:
            recent = self._recent_duration(engine)
            if recent is not None:
                scores[engine] += max(0.0, 8.0 - min(recent / 25.0, 8.0))

        chosen = max(scores, key=scores.get)
        return {
            "task": task,
            "payload_size": size,
            "cpu_percent": round(cpu_percent, 2),
            "scores": scores,
            "engine": chosen,
            "reasons": reasons,
        }


@dataclass
class ReactiveTrigger:
    trigger_id: str
    kind: str
    target: str
    pipeline: str
    threshold: int = 0
    once: bool = True
    created_at: float = field(default_factory=time.time)
    active: bool = True


class ReactiveFlowEngine:
    """Event-driven trigger manager for file and sync-based pipelines."""

    def __init__(self, shell: "NovaShell") -> None:
        self.shell = shell
        self.triggers: dict[str, ReactiveTrigger] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_flags: dict[str, threading.Event] = {}

    def register_file_trigger(self, pattern: str, pipeline: str, once: bool = True) -> ReactiveTrigger:
        trigger = ReactiveTrigger(trigger_id=uuid.uuid4().hex[:10], kind="file", target=pattern, pipeline=pipeline, once=once)
        self._start_trigger(trigger)
        return trigger

    def register_sync_trigger(self, counter: str, threshold: int, pipeline: str, once: bool = True) -> ReactiveTrigger:
        trigger = ReactiveTrigger(trigger_id=uuid.uuid4().hex[:10], kind="sync", target=counter, threshold=threshold, pipeline=pipeline, once=once)
        self._start_trigger(trigger)
        return trigger

    def _start_trigger(self, trigger: ReactiveTrigger) -> None:
        stop_flag = threading.Event()
        self.triggers[trigger.trigger_id] = trigger
        self._stop_flags[trigger.trigger_id] = stop_flag
        thread = threading.Thread(target=self._run_trigger, args=(trigger, stop_flag), daemon=True)
        self._threads[trigger.trigger_id] = thread
        thread.start()

    def _run_trigger(self, trigger: ReactiveTrigger, stop_flag: threading.Event) -> None:
        seen: set[str] = set()
        while not stop_flag.is_set() and trigger.active:
            try:
                if trigger.kind == "file":
                    matches = sorted(glob.glob(trigger.target))
                    for path in matches:
                        if path in seen:
                            continue
                        seen.add(path)
                        if "{{path}}" in trigger.pipeline:
                            command = trigger.pipeline.replace("{{path}}", shlex.quote(path))
                        else:
                            command = trigger.pipeline.replace("_", shlex.quote(path))
                        self.shell.route(command)
                        if trigger.once:
                            trigger.active = False
                            return
                elif trigger.kind == "sync":
                    counter = self.shell.sync_counters.get(trigger.target)
                    value = counter.value if counter else 0
                    if value >= trigger.threshold:
                        self.shell.route(trigger.pipeline)
                        if trigger.once:
                            trigger.active = False
                            return
                time.sleep(0.2)
            except Exception:
                time.sleep(0.2)

    def stop(self, trigger_id: str) -> bool:
        flag = self._stop_flags.get(trigger_id)
        trigger = self.triggers.get(trigger_id)
        if flag is None or trigger is None:
            return False
        trigger.active = False
        flag.set()
        return True

    def clear(self) -> None:
        for trigger_id in list(self.triggers.keys()):
            self.stop(trigger_id)

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": t.trigger_id,
                "kind": t.kind,
                "target": t.target,
                "pipeline": t.pipeline,
                "threshold": t.threshold,
                "once": t.once,
                "active": t.active,
            }
            for t in self.triggers.values()
        ]


class GuardPolicyStore:
    """Policy loader with optional eBPF metadata for hardened deployments."""

    def __init__(self) -> None:
        self.loaded_policies: dict[str, dict[str, Any]] = {}
        self.builtin_policies: dict[str, dict[str, Any]] = {
            "strict-ebpf": {
                "name": "strict-ebpf",
                "ebpf_enforce": True,
                "blocked_terms": ["curl"],
                "block_commands": [],
            }
        }
        self.ebpf_available = self._check_ebpf()
        self.enforced_policy: str | None = None

    def _check_ebpf(self) -> bool:
        with contextlib.suppress(Exception):
            import bcc  # noqa: F401
            return True
        return False

    def load(self, path: str) -> dict[str, Any]:
        raw = Path(path).read_text(encoding="utf-8")
        data: dict[str, Any]
        try:
            import yaml  # type: ignore

            parsed = yaml.safe_load(raw)
            data = parsed if isinstance(parsed, dict) else {}
        except Exception:
            data = json.loads(raw)
        name = str(data.get("name") or Path(path).stem)
        self.loaded_policies[name] = data
        return data

    def get_policy(self, policy_name: str) -> dict[str, Any] | None:
        return self.loaded_policies.get(policy_name) or self.builtin_policies.get(policy_name)

    def ensure_policy_loaded(self, policy_name: str) -> dict[str, Any] | None:
        policy = self.loaded_policies.get(policy_name)
        if policy is not None:
            return policy
        builtin = self.builtin_policies.get(policy_name)
        if builtin is None:
            return None
        policy = copy.deepcopy(builtin)
        self.loaded_policies[policy_name] = policy
        return policy

    def compile_ebpf_profile(self, policy_name: str) -> CommandResult:
        policy = self.ensure_policy_loaded(policy_name)
        if policy is None:
            return CommandResult(output="", error="policy not loaded")

        blocked_terms = [str(v) for v in policy.get("blocked_terms", [])]
        c_code = [
            "// Generated eBPF-like policy stub for NovaGuard",
            "int nova_guard_filter(void *ctx) {",
            "    // syscall-level checks would be inserted here",
            "    return 0;",
            "}",
            "// blocked_terms: " + ",".join(blocked_terms),
        ]
        payload = {"policy": policy_name, "ebpf_stub_c": "\n".join(c_code), "blocked_terms": blocked_terms}
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def enforce(self, policy_name: str) -> CommandResult:
        if self.ensure_policy_loaded(policy_name) is None:
            return CommandResult(output="", error="policy not loaded")
        self.enforced_policy = policy_name
        mode = "kernel-ebpf" if self.ebpf_available else "userspace-ebpf-emulation"
        payload = {"policy": policy_name, "mode": mode}
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def evaluate(self, policy_name: str, stage: str) -> tuple[bool, str | None]:
        policy = self.loaded_policies.get(policy_name)
        if policy is None:
            return True, None

        blocked_cmds = set(policy.get("block_commands", []))
        blocked_prefixes = [str(v) for v in policy.get("block_prefixes", [])]
        parts = split_command(stage)
        if not parts:
            return True, None
        cmd = parts[0]
        if cmd in blocked_cmds:
            return False, f"policy '{policy_name}' blocks command '{cmd}'"
        if any(stage.startswith(prefix) for prefix in blocked_prefixes):
            return False, f"policy '{policy_name}' blocks stage prefix"
        return True, None


class FabricRemoteBridge:
    """Remote transfer abstraction with 'rdma' command semantics and graceful fallback."""

    def __init__(self) -> None:
        self.arrow_flight_available = self._check_arrow_flight()

    def _check_arrow_flight(self) -> bool:
        with contextlib.suppress(Exception):
            import pyarrow.flight  # noqa: F401
            return True
        return False

    def put_file(self, url: str, file_path: str) -> CommandResult:
        path = Path(file_path)
        if not path.exists():
            return CommandResult(output="", error=f"file not found: {file_path}")
        payload = path.read_bytes()
        request = urllib.request.Request(
            url.rstrip("/") + "/fabric/put-bytes",
            data=payload,
            headers={"Content-Type": "application/octet-stream", "X-Nova-Fabric-Mode": "rdma-compatible"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
            body["transport"] = "arrow-flight" if self.arrow_flight_available else "http-binary"
            return CommandResult(output=json.dumps(body, ensure_ascii=False) + "\n", data=body, data_type=PipelineType.OBJECT)
        except Exception as exc:
            return CommandResult(output="", error=f"fabric rdma-put error: {exc}")

    def get_file(self, url: str, handle: str, out_file: str) -> CommandResult:
        target = Path(out_file)
        endpoint = url.rstrip("/") + "/fabric/get-bytes?handle=" + urllib.parse.quote(handle)
        try:
            with urllib.request.urlopen(endpoint, timeout=15) as response:
                data = response.read()
            target.write_bytes(data)
            payload = {"handle": handle, "output": str(target), "bytes": len(data)}
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        except Exception as exc:
            return CommandResult(output="", error=f"fabric rdma-get error: {exc}")


@dataclass
class GraphArtifact:
    graph_id: str
    original_pipeline: str
    optimized_stages: list[str]
    fused_cpp_count: int
    generated_cpp: str | None = None


class NovaGraphCompiler:
    """AOT-style pipeline optimizer with cross-stage fusion metadata."""

    def __init__(self) -> None:
        self.artifacts: dict[str, GraphArtifact] = {}

    def optimize(self, pipeline: str, stages: list[str]) -> GraphArtifact:
        optimized: list[str] = []
        fused_cpp_count = 0
        i = 0
        while i < len(stages):
            stage = stages[i]
            if stage.startswith("cpp.expr "):
                exprs = [stage[len("cpp.expr ") :].strip()]
                i += 1
                while i < len(stages) and stages[i].startswith("cpp.expr "):
                    exprs.append(stages[i][len("cpp.expr ") :].strip())
                    i += 1
                fused_cpp_count += max(0, len(exprs) - 1)
                optimized.append("cpp.expr_chain " + " ; ".join(exprs))
                continue
            optimized.append(stage)
            i += 1

        graph_id = uuid.uuid4().hex[:12]
        generated_cpp = None
        for stage in optimized:
            if stage.startswith("cpp.expr_chain "):
                generated_cpp = self._build_cpp_chain(stage[len("cpp.expr_chain ") :])
                break

        artifact = GraphArtifact(
            graph_id=graph_id,
            original_pipeline=pipeline,
            optimized_stages=optimized,
            fused_cpp_count=fused_cpp_count,
            generated_cpp=generated_cpp,
        )
        self.artifacts[graph_id] = artifact
        return artifact

    def get(self, graph_id: str) -> GraphArtifact | None:
        return self.artifacts.get(graph_id)

    def _build_cpp_chain(self, exprs_text: str) -> str:
        exprs = [x.strip() for x in exprs_text.split(";") if x.strip()]
        lines = [
            "#include <iostream>",
            "#include <string>",
            "int main(){",
            "  std::string line;",
            "  while(std::getline(std::cin, line)){",
            "    double x = std::stod(line);",
        ]
        for expr in exprs:
            lines.append(f"    x = ({expr});")
        lines.extend(['    std::cout << x << "\\n";', "  }", "  return 0;", "}"])
        return "\n".join(lines)


class NovaSynth:
    """AI-native (heuristic/telemetry) engine selector and autotuner."""

    def __init__(self, shell: "NovaShell") -> None:
        self.shell = shell

    def suggest(self, code: str) -> dict[str, Any]:
        text = code.strip()
        lower = text.lower()
        engine = "py"
        reason = "default python path"

        if any(k in lower for k in ["matrix", "tensor", "vector", "fft"]):
            engine = "gpu"
            reason = "numeric workload pattern"
        elif "for " in lower or "while " in lower:
            engine = "cpp"
            reason = "loop-heavy pattern"

        # telemetry bias from optimizer if available
        opt = self.shell.optimizer.suggest_engine("synth", text)
        if opt.get("engine") in {"py", "cpp", "gpu", "mesh"}:
            if engine == "py" and opt["engine"] != "py":
                engine = opt["engine"]
                reason += "; telemetry override"

        return {"engine": engine, "reason": reason, "input": code}

    def autotune(self, code: str) -> CommandResult:
        suggestion = self.suggest(code)
        engine = suggestion["engine"]
        payload = code.strip()

        if engine == "cpp" and payload.startswith("py "):
            payload = payload[len("py ") :].strip()
            if payload:
                return self.shell.route(f"cpp.expr {payload}")
        if engine == "gpu":
            return CommandResult(output="", error="autotune selected gpu; provide kernel file for gpu execution")
        if engine == "mesh" and self.shell.mesh.workers:
            return self.shell.route(f"mesh intelligent-run cpu py {payload or '0'}")
        return self.shell.route(code if code.strip().startswith(("py ", "cpp ", "gpu ", "sys ")) else f"py {payload}")


class NovaVectorMemory:
    """Persistent local vector memory using deterministic hashed embeddings."""

    def __init__(self, dimensions: int = 64, db_path: str | Path | None = None) -> None:
        self.dimensions = dimensions
        self.db_path = Path(db_path or (Path.home() / ".nova_shell_memory" / "vector_memory.db")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.entries: dict[str, VectorMemoryEntry] = {}
        self._init_schema()
        self._load_entries()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_memory (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                project TEXT NOT NULL,
                text TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    def _load_entries(self) -> None:
        cur = self.conn.execute(
            "SELECT id, namespace, project, text, vector_json, metadata_json, created_at FROM vector_memory"
        )
        self.entries.clear()
        for row in cur.fetchall():
            self.entries[str(row[0])] = VectorMemoryEntry(
                entry_id=str(row[0]),
                namespace=str(row[1]),
                project=str(row[2]),
                text=str(row[3]),
                vector=list(json.loads(str(row[4]))),
                metadata=dict(json.loads(str(row[5]))),
                created_at=float(row[6]),
            )

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in re.findall(r"[A-Za-z0-9_\-\u00C0-\u024F]+", text.lower()) if token]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return vector
        return [value / norm for value in vector]

    def embed(
        self,
        text: str,
        *,
        entry_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        namespace: str = "default",
        project: str = "default",
    ) -> VectorMemoryEntry:
        chosen_id = (entry_id or f"mem_{uuid.uuid4().hex[:8]}").strip()
        entry = VectorMemoryEntry(
            entry_id=chosen_id,
            namespace=namespace.strip() or "default",
            project=project.strip() or "default",
            text=text,
            vector=self._embed(text),
            metadata=dict(metadata or {}),
        )
        self.entries[chosen_id] = entry
        self.conn.execute(
            "INSERT OR REPLACE INTO vector_memory(id, namespace, project, text, vector_json, metadata_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                entry.entry_id,
                entry.namespace,
                entry.project,
                entry.text,
                json.dumps(entry.vector),
                json.dumps(entry.metadata, ensure_ascii=False),
                entry.created_at,
            ),
        )
        self.conn.commit()
        return entry

    def search(self, query: str, *, limit: int = 5, namespace: str | None = None, project: str | None = None) -> list[dict[str, Any]]:
        query_vector = self._embed(query)
        scored: list[dict[str, Any]] = []
        for entry in self.entries.values():
            if namespace and entry.namespace != namespace:
                continue
            if project and entry.project != project:
                continue
            score = sum(a * b for a, b in zip(query_vector, entry.vector))
            scored.append(
                {
                    "id": entry.entry_id,
                    "namespace": entry.namespace,
                    "project": entry.project,
                    "score": round(float(score), 6),
                    "text": entry.text,
                    "metadata": entry.metadata,
                    "created_at": entry.created_at,
                }
            )
        scored.sort(key=lambda item: float(item["score"]), reverse=True)
        return scored[: max(1, limit)]

    def list_entries(self, *, namespace: str | None = None, project: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for entry in self.entries.values():
            if namespace and entry.namespace != namespace:
                continue
            if project and entry.project != project:
                continue
            rows.append(
                {
                    "id": entry.entry_id,
                    "namespace": entry.namespace,
                    "project": entry.project,
                    "text_preview": entry.text[:160],
                    "metadata": entry.metadata,
                    "created_at": entry.created_at,
                }
            )
        return rows

    def count(self, *, namespace: str | None = None, project: str | None = None) -> int:
        return len(self.list_entries(namespace=namespace, project=project))

    def get_entry(self, entry_id: str) -> VectorMemoryEntry | None:
        return self.entries.get(entry_id)

    def close(self) -> None:
        self.conn.close()


class NovaAtheriaRuntime:
    """Optional local Atheria integration with persistent training records."""

    def __init__(self, runtime_config: dict[str, Any], cwd: Path) -> None:
        self.runtime_config = runtime_config
        self.cwd = cwd
        self.storage_root = (Path.home() / ".nova_shell_memory").resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.training_store_path = self.storage_root / "atheria_training.json"
        self._module: Any = None
        self._core: Any = None
        self._embedding_model = "atheria-poincare-memory-v1"
        self._loaded_training: list[dict[str, Any]] = self._load_training_rows()

    def _discover_source_dir(self) -> Path | None:
        candidates = [
            self.cwd / "Atheria",
            Path(__file__).resolve().parent / "Atheria",
            Path(sys.executable).resolve().parent / "Atheria",
        ]
        env_home = str(os.environ.get("ATHERIA_HOME") or "").strip()
        if env_home:
            candidates.insert(0, Path(os.path.expanduser(env_home)))
        for candidate in candidates:
            candidate = candidate.resolve(strict=False)
            if candidate.is_dir() and (candidate / "atheria_core.py").is_file():
                return candidate
        return None

    def is_available(self) -> bool:
        return self._discover_source_dir() is not None

    def _poincare_dims(self) -> int:
        raw = self.runtime_config.get("atheria_poincare_dims")
        with contextlib.suppress(Exception):
            dims = int(raw)
            if dims >= 3:
                return dims
        if self._module is not None:
            with contextlib.suppress(Exception):
                dims = int(getattr(self._module, "POINCARE_DIMS", 0) or 0)
                if dims >= 3:
                    return dims
        return 6

    def _project_to_poincare_ball(self, values: Iterable[float], *, max_norm: float = 0.999) -> list[float]:
        vector = [float(item) for item in values]
        norm = math.sqrt(sum(item * item for item in vector))
        if norm >= max_norm:
            scale = max_norm / (norm + 1e-8)
            vector = [item * scale for item in vector]
        return vector

    def _normalize_embedding(self, embedding: Any, *, dims: int) -> list[float] | None:
        if not isinstance(embedding, list) or len(embedding) != dims:
            return None
        try:
            vector = [float(item) for item in embedding]
        except (TypeError, ValueError):
            return None
        return self._project_to_poincare_ball(vector)

    def _embedding_features(self, text: str) -> list[str]:
        tokens = self._tokenize(text)
        features: list[str] = []
        for token in tokens:
            features.append(token)
            if len(token) >= 4:
                features.append(f"prefix:{token[:3]}")
                features.append(f"suffix:{token[-3:]}")
                max_window = min(len(token) - 2, 5)
                for start in range(max_window):
                    features.append(f"gram:{token[start:start + 3]}")
        for index in range(len(tokens) - 1):
            features.append(f"pair:{tokens[index]}::{tokens[index + 1]}")
        return features[:256]

    def _embed_text_hyperbolic(self, text: str, *, dims: int | None = None) -> list[float]:
        resolved_dims = dims or self._poincare_dims()
        features = self._embedding_features(text)
        if not features:
            return [0.0] * resolved_dims
        accum = [0.0] * resolved_dims
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            weight = 1.0
            if feature.startswith("pair:"):
                weight = 0.72
            elif feature.startswith("gram:"):
                weight = 0.44
            elif feature.startswith("prefix:") or feature.startswith("suffix:"):
                weight = 0.36
            else:
                weight = 1.0 + min(0.35, len(feature) / 48.0)
            for index in range(resolved_dims):
                byte = digest[index % len(digest)]
                signed = (byte / 255.0) * 2.0 - 1.0
                accum[index] += signed * weight
        mean = sum(accum) / max(1, len(accum))
        centered = [item - mean for item in accum]
        norm = math.sqrt(sum(item * item for item in centered))
        if norm <= 1e-8:
            return [0.0] * resolved_dims
        scaled = [(item / norm) * 0.72 for item in centered]
        return self._project_to_poincare_ball(scaled)

    def _blend_hyperbolic_vectors(self, weighted_vectors: Iterable[tuple[float, list[float]]], *, dims: int) -> list[float]:
        accum = [0.0] * dims
        total_weight = 0.0
        for weight, vector in weighted_vectors:
            if not vector:
                continue
            total_weight += abs(float(weight))
            for index in range(min(dims, len(vector))):
                accum[index] += float(weight) * float(vector[index])
        if total_weight <= 1e-8:
            return [0.0] * dims
        blended = [item / total_weight for item in accum]
        return self._project_to_poincare_ball(blended)

    def _compose_training_embedding(self, question: str, category: str, answer: str) -> list[float]:
        dims = self._poincare_dims()
        return self._blend_hyperbolic_vectors(
            [
                (0.52, self._embed_text_hyperbolic(question, dims=dims)),
                (0.16, self._embed_text_hyperbolic(category, dims=dims)),
                (0.32, self._embed_text_hyperbolic(answer, dims=dims)),
            ],
            dims=dims,
        )

    def _build_training_row(
        self,
        *,
        question: str,
        category: str,
        answer: str,
        embedding: Any = None,
        source: str = "",
    ) -> dict[str, Any] | None:
        q = str(question).strip()
        a = str(answer).strip()
        c = str(category or "general").strip() or "general"
        if not q or not a:
            return None
        dims = self._poincare_dims()
        vector = self._normalize_embedding(embedding, dims=dims)
        if vector is None:
            vector = self._compose_training_embedding(q, c, a)
        return {
            "question": q,
            "category": c,
            "answer": a,
            "embedding": [round(float(item), 8) for item in vector],
            "embedding_dims": dims,
            "embedding_space": "poincare",
            "embedding_model": self._embedding_model,
            "source": str(source or "").strip(),
        }

    def _poincare_distance(self, left: list[float], right: list[float]) -> float:
        u = self._project_to_poincare_ball(left)
        v = self._project_to_poincare_ball(right)
        du = sum(item * item for item in u)
        dv = sum(item * item for item in v)
        diff_sq = sum((a - b) * (a - b) for a, b in zip(u, v))
        denom = max(1e-8, (1.0 - du) * (1.0 - dv))
        arg = 1.0 + (2.0 * diff_sq / denom)
        if arg < 1.0:
            arg = 1.0
        return float(math.acosh(arg))

    def _load_training_rows(self) -> list[dict[str, Any]]:
        if not self.training_store_path.exists():
            return []
        try:
            payload = json.loads(self.training_store_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        rows: list[dict[str, Any]] = []
        changed = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            row = self._build_training_row(
                question=str(item.get("question") or ""),
                category=str(item.get("category") or "general"),
                answer=str(item.get("answer") or ""),
                embedding=item.get("embedding"),
                source=str(item.get("source") or ""),
            )
            if row is None:
                continue
            rows.append(row)
            if item.get("embedding_space") != "poincare" or item.get("embedding_model") != self._embedding_model or not isinstance(item.get("embedding"), list):
                changed = True
        if changed:
            self._loaded_training = rows
            self._save_training_rows()
        return rows

    def _save_training_rows(self) -> None:
        self.training_store_path.write_text(
            json.dumps(self._loaded_training, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_atheria_module(self) -> Any:
        if self._module is not None:
            return self._module
        source_dir = self._discover_source_dir()
        if source_dir is None:
            raise FileNotFoundError("Atheria source folder not found")
        source_text = str(source_dir)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        importlib.invalidate_caches()
        self._module = importlib.import_module("atheria_core")
        return self._module

    def _ensure_core(self) -> Any:
        if self._core is not None:
            return self._core
        module = self._load_atheria_module()
        tick_interval = float(self.runtime_config.get("atheria_tick_interval") or 0.04)
        core = module.AtheriaCore(tick_interval=tick_interval)
        core.bootstrap_default_mesh()
        model_json_path = str(self.runtime_config.get("atheria_model_json_path") or "")
        csv_path = str(self.runtime_config.get("atheria_csv_path") or "")
        with contextlib.suppress(Exception):
            if model_json_path or csv_path:
                core.migrate_from_codedump(
                    model_json_path=model_json_path or "model_with_qa.json",
                    csv_path=csv_path or "data.csv",
                )
        if self._loaded_training:
            core.aether.ingest_qa(
                (row["question"], row["category"], row["answer"])
                for row in self._loaded_training
            )
        self._core = core
        return self._core

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in re.findall(r"[A-Za-z0-9_\-\u00C0-\u024F]+", text.lower()) if token]

    def _lexical_support(self, query: str, row: dict[str, Any]) -> float:
        lowered_query = query.lower()
        haystack = f"{row.get('question', '')} {row.get('category', '')} {row.get('answer', '')}".strip()
        lowered_haystack = haystack.lower()
        query_tokens = set(self._tokenize(query))
        haystack_tokens = set(self._tokenize(haystack))
        overlap = len(query_tokens.intersection(haystack_tokens))
        score = float(overlap) / max(1.0, float(len(query_tokens) or 1))
        if row.get("question", "").lower() in lowered_query:
            score += 0.45
        if lowered_query and lowered_query in lowered_haystack:
            score += 0.7
        if row.get("category", "").lower() in lowered_query:
            score += 0.18
        score += min(0.16, max(0.0, len(row.get("answer", "")) / 2400.0))
        return min(1.0, max(0.0, score))

    def search_training(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        query_text = str(query).strip()
        if not query_text:
            return []
        query_vector = self._embed_text_hyperbolic(query_text)
        scored: list[dict[str, Any]] = []
        for row in self._loaded_training:
            dims = int(row.get("embedding_dims") or self._poincare_dims())
            vector = self._normalize_embedding(row.get("embedding"), dims=dims)
            if vector is None:
                vector = self._compose_training_embedding(
                    str(row.get("question") or ""),
                    str(row.get("category") or "general"),
                    str(row.get("answer") or ""),
                )
                row["embedding"] = [round(float(item), 8) for item in vector]
                row["embedding_dims"] = dims
                row["embedding_space"] = "poincare"
                row["embedding_model"] = self._embedding_model
                self._save_training_rows()
            hyper_distance = self._poincare_distance(query_vector, vector)
            hyper_similarity = 1.0 / (1.0 + hyper_distance)
            lexical_support = self._lexical_support(query_text, row)
            score = 0.82 * hyper_similarity + 0.18 * lexical_support
            if score < 0.34 and lexical_support <= 0.0:
                continue
            scored.append(
                {
                    "question": str(row["question"]),
                    "category": str(row["category"]),
                    "answer": str(row["answer"]),
                    "score": round(score, 6),
                    "distance": round(hyper_distance, 6),
                    "hyperbolic_similarity": round(hyper_similarity, 6),
                    "lexical_support": round(lexical_support, 6),
                    "retrieval_mode": "poincare_hyperbolic",
                    "embedding_space": "poincare",
                }
            )
        scored.sort(
            key=lambda item: (
                float(item["score"]),
                float(item["hyperbolic_similarity"]),
                float(item["lexical_support"]),
            ),
            reverse=True,
        )
        return scored[: max(1, limit)]

    def train_rows(self, rows: Iterable[tuple[str, str, str]]) -> int:
        normalized: list[dict[str, Any]] = []
        for question, category, answer in rows:
            row = self._build_training_row(
                question=str(question),
                category=str(category or "general"),
                answer=str(answer),
                source="nova-shell-train",
            )
            if row is not None:
                normalized.append(row)
        if not normalized:
            return 0
        self._loaded_training.extend(normalized)
        self._save_training_rows()
        if self._core is not None:
            self._core.aether.ingest_qa((row["question"], row["category"], row["answer"]) for row in normalized)
        return len(normalized)

    def train_qa(self, *, question: str, answer: str, category: str = "general") -> int:
        return self.train_rows([(question, category, answer)])

    def train_json_file(self, path: Path) -> int:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return 0
        rows = [
            (
                str(item.get("question") or ""),
                str(item.get("category") or "general"),
                str(item.get("answer") or ""),
            )
            for item in payload.get("questions", [])
            if isinstance(item, dict)
        ]
        return self.train_rows(rows)

    def train_csv_file(self, path: Path) -> int:
        rows: list[tuple[str, str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                question = str(row.get("Frage") or row.get("question") or "").strip()
                category = str(row.get("Kategorie") or row.get("category") or "general").strip() or "general"
                answer = str(row.get("Antwort") or row.get("answer") or "").strip()
                if question and answer:
                    rows.append((question, category, answer))
        return self.train_rows(rows)

    def train_text_file(self, path: Path, *, category: str = "") -> int:
        text = path.read_text(encoding="utf-8")
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
        effective_category = category.strip() or path.stem or "document"
        rows: list[tuple[str, str, str]] = []
        for index, chunk in enumerate(chunks, start=1):
            question = f"{effective_category} segment {index}"
            rows.append((question, effective_category, chunk))
        return self.train_rows(rows)

    def status_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available": self.is_available(),
            "source_dir": str(self._discover_source_dir() or ""),
            "core_loaded": self._core is not None,
            "trained_records": len(self._loaded_training),
            "categories": sorted({row["category"] for row in self._loaded_training}),
            "memory_embedding_space": "poincare",
            "memory_embedding_dims": self._poincare_dims(),
            "memory_retrieval_mode": "poincare_hyperbolic",
        }
        if self._core is not None:
            with contextlib.suppress(Exception):
                snapshot = self._core.dashboard_snapshot()
                payload["core_id"] = str(getattr(self._core, "core_id", ""))
                payload["dashboard"] = {
                    "phase": snapshot.get("phase"),
                    "system_temperature": snapshot.get("system_temperature"),
                    "rhythm_state": snapshot.get("rhythm_state"),
                    "market_role": snapshot.get("market_role"),
                    "qa_memory_rows": snapshot.get("qa_memory_rows"),
                }
        return payload

    def complete_prompt(self, prompt: str, *, model: str = "atheria-core", system_prompt: str = "") -> dict[str, Any]:
        core = self._ensure_core()
        module = self._load_atheria_module()
        query_tensor = module._fold_vector_from_text(prompt, dims=int(core.holographic_field.pattern.numel()))
        field_result = core.field_query(query_tensor, top_k=4)
        retrieved = self.search_training(prompt, limit=4)
        dashboard = core.dashboard_snapshot()
        top_matches = list(field_result.get("top_matches") or [])
        resonance_labels = [str(item.get("label")) for item in top_matches if isinstance(item, dict) and item.get("label")]
        if retrieved:
            primary = str(retrieved[0]["answer"]).strip()
            details = [f"- {row['category']}: {row['answer']}" for row in retrieved[1:3]]
            lines = [primary]
            if details:
                lines.append("")
                lines.append("Weitere Atheria-Erinnerungen:")
                lines.extend(details)
        else:
            lines = [
                "Ich habe dazu noch kein direkt trainiertes Wissen in meinem Atheria-Speicher.",
                "Trainiere mich mit `atheria train ...` oder stelle mir eine Frage zu bereits ingesstierten Inhalten.",
            ]
        resonance_text = ", ".join(resonance_labels[:4]) or "keine stabile Resonanz"
        lines.extend(
            [
                "",
                "Atheria-Zustand:",
                f"- Resonanz: {resonance_text}",
                f"- Retrieval: poincare_hyperbolic ({len(retrieved)} Treffer)",
                f"- Phase: {dashboard.get('phase', 'unknown')}",
                f"- Temperatur: {dashboard.get('system_temperature', 'unknown')}",
            ]
        )
        if system_prompt.strip():
            lines.extend(["", f"Systemfokus: {system_prompt.strip()[:400]}"])
        text = "\n".join(lines).strip()
        return {
            "provider": "atheria",
            "model": model,
            "text": text,
            "retrieved": retrieved,
            "field_result": field_result,
            "dashboard": {
                "phase": dashboard.get("phase"),
                "system_temperature": dashboard.get("system_temperature"),
                "rhythm_state": dashboard.get("rhythm_state"),
                "market_role": dashboard.get("market_role"),
            },
        }

    def close(self) -> None:
        self._core = None


class NovaAIProviderRuntime:
    """Provider-aware AI runtime with .env loading and local/remote model support."""

    def __init__(self, runtime_config: dict[str, Any], cwd: Path, atheria_runtime: NovaAtheriaRuntime | None = None) -> None:
        self.runtime_config = runtime_config
        self.cwd = cwd
        self.atheria_runtime = atheria_runtime
        self.provider_specs: dict[str, AIProviderSpec] = {
            "openai": AIProviderSpec(
                name="openai",
                kind="openai-chat",
                env_keys=("OPENAI_API_KEY",),
                base_url="https://api.openai.com/v1",
                base_url_env="OPENAI_BASE_URL",
                default_model="gpt-4o-mini",
                default_model_env="OPENAI_MODEL",
                fallback_models=("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"),
                openai_compat=True,
            ),
            "anthropic": AIProviderSpec(
                name="anthropic",
                kind="anthropic-messages",
                env_keys=("ANTHROPIC_API_KEY",),
                base_url="https://api.anthropic.com/v1",
                base_url_env="ANTHROPIC_BASE_URL",
                default_model="claude-3-5-haiku-latest",
                default_model_env="ANTHROPIC_MODEL",
                fallback_models=("claude-3-5-haiku-latest", "claude-3-7-sonnet-latest"),
            ),
            "gemini": AIProviderSpec(
                name="gemini",
                kind="gemini-generate-content",
                env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
                base_url="https://generativelanguage.googleapis.com/v1beta",
                base_url_env="GEMINI_BASE_URL",
                default_model="gemini-2.0-flash",
                default_model_env="GEMINI_MODEL",
                fallback_models=("gemini-2.0-flash", "gemini-1.5-flash"),
            ),
            "groq": AIProviderSpec(
                name="groq",
                kind="openai-chat",
                env_keys=("GROQ_API_KEY",),
                base_url="https://api.groq.com/openai/v1",
                base_url_env="GROQ_BASE_URL",
                default_model="llama-3.3-70b-versatile",
                default_model_env="GROQ_MODEL",
                fallback_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
                openai_compat=True,
            ),
            "openrouter": AIProviderSpec(
                name="openrouter",
                kind="openai-chat",
                env_keys=("OPENROUTER_API_KEY",),
                base_url="https://openrouter.ai/api/v1",
                base_url_env="OPENROUTER_BASE_URL",
                default_model="openai/gpt-4o-mini",
                default_model_env="OPENROUTER_MODEL",
                fallback_models=("openai/gpt-4o-mini", "anthropic/claude-3.5-haiku"),
                openai_compat=True,
            ),
            "ollama": AIProviderSpec(
                name="ollama",
                kind="ollama-chat",
                env_keys=(),
                base_url="http://127.0.0.1:11434",
                base_url_env="OLLAMA_BASE_URL",
                default_model="llama3.2",
                default_model_env="OLLAMA_MODEL",
                fallback_models=("llama3.2", "mistral", "qwen2.5"),
                requires_api_key=False,
            ),
            "lmstudio": AIProviderSpec(
                name="lmstudio",
                kind="openai-chat",
                env_keys=("LM_STUDIO_API_KEY",),
                base_url="http://127.0.0.1:1234/v1",
                base_url_env="LM_STUDIO_BASE_URL",
                default_model="",
                default_model_env="LM_STUDIO_MODEL",
                fallback_models=(),
                requires_api_key=False,
                openai_compat=True,
            ),
            "atheria": AIProviderSpec(
                name="atheria",
                kind="atheria-core",
                env_keys=(),
                base_url="local://atheria",
                base_url_env="ATHERIA_BASE_URL",
                default_model="atheria-core",
                default_model_env="ATHERIA_MODEL",
                fallback_models=("atheria-core",),
                requires_api_key=False,
            ),
        }
        self.loaded_env_files: list[str] = []
        self.active_provider = ""
        self.active_model = ""
        self.reload_env()
        self.active_provider = str(os.environ.get("NOVA_AI_PROVIDER") or runtime_config.get("ai_provider") or "")
        self.active_model = str(os.environ.get("NOVA_AI_MODEL") or runtime_config.get("ai_model") or "")

    def reload_env(self, path_text: str | None = None, *, override: bool = True) -> list[str]:
        candidates: list[Path] = []
        if path_text:
            custom = Path(os.path.expanduser(path_text))
            if not custom.is_absolute():
                custom = self.cwd / custom
            candidates.append(custom)
        else:
            candidates.extend(
                [
                    self.cwd / ".env",
                    Path(sys.executable).resolve().parent / ".env",
                    Path(__file__).resolve().parent / ".env",
                ]
            )
        self.loaded_env_files = load_dotenv_files(candidates, override=override)
        return list(self.loaded_env_files)

    def list_providers(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, spec in self.provider_specs.items():
            key_name = self._provider_key_name(spec)
            rows.append(
                {
                    "provider": name,
                    "configured": self.is_configured(name),
                    "active": name == self.get_active_provider(),
                    "model": self.get_active_model(name),
                    "base_url": self._provider_base_url(spec),
                    "api_key_env": key_name,
                    "auth_required": spec.requires_api_key,
                    "source": "local-runtime" if not spec.requires_api_key else "api",
                }
            )
        return rows

    def is_configured(self, provider: str) -> bool:
        spec = self._get_provider_spec(provider)
        if spec is None:
            return False
        if spec.name == "atheria":
            return bool(self.atheria_runtime is not None and self.atheria_runtime.is_available())
        if not spec.requires_api_key:
            return True
        return bool(self._provider_api_key(spec))

    def get_active_provider(self) -> str:
        if self.active_provider and self.active_provider in self.provider_specs:
            return self.active_provider
        for provider in ["openai", "anthropic", "gemini", "groq", "openrouter"]:
            if self.is_configured(provider):
                return provider
        for provider in ["lmstudio", "ollama", "atheria"]:
            spec = self.provider_specs[provider]
            if os.environ.get(spec.default_model_env) or self.runtime_config.get(f"{provider}_model"):
                return provider
        return ""

    def get_active_model(self, provider: str | None = None) -> str:
        selected_provider = provider or self.get_active_provider()
        if not selected_provider:
            return ""
        spec = self._get_provider_spec(selected_provider)
        if spec is None:
            return ""
        if self.active_provider == selected_provider and self.active_model:
            return self.active_model
        return str(os.environ.get(spec.default_model_env) or self.runtime_config.get(f"{selected_provider}_model") or spec.default_model)

    def use_provider(self, provider: str, model: str | None = None) -> CommandResult:
        spec = self._get_provider_spec(provider)
        if spec is None:
            return CommandResult(output="", error=f"unknown ai provider: {provider}")
        if not self.is_configured(provider):
            return CommandResult(output="", error=f"provider '{provider}' is not configured; set {self._provider_key_name(spec) or 'the required API key'} or start the local runtime")

        chosen_model = (model or self.get_active_model(provider)).strip()
        if not chosen_model:
            models_result = self.list_models(provider)
            if models_result.error is None:
                models = list(models_result.data.get("models", [])) if isinstance(models_result.data, dict) else []
                if models:
                    chosen_model = str(models[0])
        if not chosen_model:
            return CommandResult(output="", error=f"provider '{provider}' has no active model; specify one with ai use {provider} <model>")

        self.active_provider = provider
        self.active_model = chosen_model
        payload = {"provider": provider, "model": chosen_model, "base_url": self._provider_base_url(spec)}
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def list_models(self, provider: str | None = None) -> CommandResult:
        provider_name = provider or self.get_active_provider()
        spec = self._get_provider_spec(provider_name)
        if spec is None:
            return CommandResult(output="", error="no ai provider selected")

        try:
            models = self._fetch_models(spec)
            if not models:
                models = list(spec.fallback_models)
            payload = {"provider": provider_name, "models": models, "base_url": self._provider_base_url(spec)}
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        except Exception as exc:
            payload = {"provider": provider_name, "models": list(spec.fallback_models), "base_url": self._provider_base_url(spec), "error": str(exc)}
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def config_payload(self) -> dict[str, Any]:
        provider = self.get_active_provider()
        return {
            "active_provider": provider,
            "active_model": self.get_active_model(provider) if provider else "",
            "loaded_env_files": self.loaded_env_files,
            "providers": self.list_providers(),
        }

    def complete_prompt(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        system_prompt: str = "",
    ) -> CommandResult:
        provider_name = provider or self.get_active_provider()
        spec = self._get_provider_spec(provider_name)
        if spec is None:
            return CommandResult(output="", error="no ai provider configured; use ai use <provider> [model] or configure a .env file")
        if not self.is_configured(provider_name):
            return CommandResult(output="", error=f"provider '{provider_name}' is not configured")

        chosen_model = (model or self.get_active_model(provider_name)).strip()
        if not chosen_model:
            models_result = self.list_models(provider_name)
            if models_result.error is None and isinstance(models_result.data, dict):
                models = list(models_result.data.get("models", []))
                if models:
                    chosen_model = str(models[0])
        if not chosen_model:
            return CommandResult(output="", error=f"provider '{provider_name}' has no selected model")

        try:
            payload = self._complete_via_provider(spec, prompt, chosen_model, system_prompt)
            self.active_provider = provider_name
            self.active_model = chosen_model
            return CommandResult(output=payload["text"] + ("\n" if payload["text"] and not payload["text"].endswith("\n") else ""), data=payload, data_type=PipelineType.OBJECT)
        except Exception as exc:
            return CommandResult(output="", error=f"ai provider error ({provider_name}): {self._format_provider_error(spec, exc)}")

    def _format_provider_error(self, spec: AIProviderSpec, exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        timeout = isinstance(exc, TimeoutError)
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            timeout = True
        if not timeout and "timed out" in message.lower():
            timeout = True
        if reason is not None and "timed out" in str(reason).lower():
            timeout = True
        if timeout and spec.name in {"lmstudio", "ollama"}:
            timeout_env = "LM_STUDIO_TIMEOUT" if spec.name == "lmstudio" else "OLLAMA_TIMEOUT"
            return (
                f"{message}; local model may still be loading. "
                f"Warm the model in {spec.name} or increase `{timeout_env}` / `NOVA_AI_TIMEOUT`."
            )
        return message

    def _get_provider_spec(self, provider: str | None) -> AIProviderSpec | None:
        if not provider:
            return None
        return self.provider_specs.get(provider.lower())

    def _provider_key_name(self, spec: AIProviderSpec) -> str:
        for key_name in spec.env_keys:
            if os.environ.get(key_name):
                return key_name
        return spec.env_keys[0] if spec.env_keys else ""

    def _provider_api_key(self, spec: AIProviderSpec) -> str:
        for key_name in spec.env_keys:
            value = os.environ.get(key_name, "").strip()
            if value:
                return value
        return ""

    def _provider_base_url(self, spec: AIProviderSpec) -> str:
        return str(os.environ.get(spec.base_url_env) or self.runtime_config.get(f"{spec.name}_base_url") or spec.base_url).rstrip("/")

    def _provider_timeout_seconds(self, spec: AIProviderSpec, *, purpose: str) -> int:
        env_candidates = [
            f"{spec.name.upper().replace('-', '_')}_TIMEOUT",
            f"{spec.name.upper().replace('-', '_')}_REQUEST_TIMEOUT",
            "NOVA_AI_TIMEOUT",
        ]
        if spec.name == "lmstudio":
            env_candidates = ["LM_STUDIO_TIMEOUT", "LMSTUDIO_TIMEOUT", *env_candidates]
        default_timeout = 180 if spec.name in {"lmstudio", "ollama"} else 60
        if purpose == "models":
            default_timeout = 30 if spec.name in {"lmstudio", "ollama"} else 20
        for env_name in env_candidates:
            value = os.environ.get(env_name)
            if not value:
                continue
            with contextlib.suppress(Exception):
                return max(1, int(float(value)))
        config_value = self.runtime_config.get(f"{spec.name}_timeout") or self.runtime_config.get("ai_timeout")
        with contextlib.suppress(Exception):
            if config_value is not None:
                return max(1, int(float(config_value)))
        return default_timeout

    def _http_json(self, url: str, *, method: str = "GET", payload: Any = None, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
        body = None
        merged_headers = {"User-Agent": f"nova-shell/{__version__}"}
        if headers:
            merged_headers.update(headers)
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=body, headers=merged_headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            text = response.read().decode(charset)
        return json.loads(text) if text else {}

    def _fetch_models(self, spec: AIProviderSpec) -> list[str]:
        base_url = self._provider_base_url(spec)
        if spec.kind == "openai-chat":
            headers: dict[str, str] = {}
            api_key = self._provider_api_key(spec)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            data = self._http_json(f"{base_url}/models", headers=headers, timeout=self._provider_timeout_seconds(spec, purpose="models"))
            return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]
        if spec.kind == "ollama-chat":
            data = self._http_json(f"{base_url}/api/tags", timeout=self._provider_timeout_seconds(spec, purpose="models"))
            return [str(item.get("name")) for item in data.get("models", []) if item.get("name")]
        if spec.kind == "gemini-generate-content":
            api_key = self._provider_api_key(spec)
            data = self._http_json(f"{base_url}/models?key={urllib.parse.quote(api_key)}", timeout=self._provider_timeout_seconds(spec, purpose="models"))
            models = []
            for item in data.get("models", []):
                name = str(item.get("name", ""))
                if name.startswith("models/"):
                    name = name[len("models/") :]
                if name:
                    models.append(name)
            return models
        if spec.kind == "atheria-core":
            return ["atheria-core"]
        return list(spec.fallback_models)

    def _complete_via_provider(self, spec: AIProviderSpec, prompt: str, model: str, system_prompt: str) -> dict[str, Any]:
        base_url = self._provider_base_url(spec)
        if spec.kind == "openai-chat":
            headers: dict[str, str] = {}
            api_key = self._provider_api_key(spec)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            data = self._http_json(
                f"{base_url}/chat/completions",
                method="POST",
                payload={"model": model, "messages": messages, "temperature": 0.2},
                headers=headers,
                timeout=self._provider_timeout_seconds(spec, purpose="completion"),
            )
            choices = data.get("choices", [])
            message = choices[0].get("message", {}) if choices else {}
            content = message.get("content", "")
            if isinstance(content, list):
                content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            text = str(content).strip()
            return {"provider": spec.name, "model": model, "text": text, "raw": data}

        if spec.kind == "anthropic-messages":
            api_key = self._provider_api_key(spec)
            data = self._http_json(
                f"{base_url}/messages",
                method="POST",
                payload={
                    "model": model,
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=self._provider_timeout_seconds(spec, purpose="completion"),
            )
            parts = data.get("content", [])
            text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
            return {"provider": spec.name, "model": model, "text": text, "raw": data}

        if spec.kind == "gemini-generate-content":
            api_key = self._provider_api_key(spec)
            payload: dict[str, Any] = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            }
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
            data = self._http_json(
                f"{base_url}/models/{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(api_key)}",
                method="POST",
                payload=payload,
                timeout=self._provider_timeout_seconds(spec, purpose="completion"),
            )
            candidates = data.get("candidates", [])
            parts = []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
            return {"provider": spec.name, "model": model, "text": text, "raw": data}

        if spec.kind == "ollama-chat":
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            data = self._http_json(
                f"{base_url}/api/chat",
                method="POST",
                payload={"model": model, "messages": messages, "stream": False},
                timeout=self._provider_timeout_seconds(spec, purpose="completion"),
            )
            text = str(data.get("message", {}).get("content", "")).strip()
            return {"provider": spec.name, "model": model, "text": text, "raw": data}

        if spec.kind == "atheria-core":
            if self.atheria_runtime is None:
                raise RuntimeError("atheria runtime unavailable")
            return self.atheria_runtime.complete_prompt(prompt, model=model, system_prompt=system_prompt)

        raise RuntimeError(f"unsupported ai provider kind: {spec.kind}")


class VisionServer:
    """Small HTTP server to inspect runtime events and graph state."""

    def __init__(self, shell: "NovaShell") -> None:
        self.shell = shell
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, host: str = "127.0.0.1", port: int = 8765) -> CommandResult:
        if self._server is not None:
            return CommandResult(output=f"vision already running on http://{host}:{port}\n")

        shell = self.shell

        class Handler(http.server.BaseHTTPRequestHandler):
            def _write_json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/events":
                    self._write_json(shell.events.events)
                    return
                if parsed.path == "/graph":
                    self._write_json({
                        "nodes": [
                            {"name": node.name, "stages": node.stages, "parallel": node.parallel}
                            for node in shell.last_graph.nodes
                        ]
                    })
                    return
                if parsed.path == "/pulse/state":
                    tail = shell.events.events[-25:]
                    bottlenecks = sorted(
                        [e for e in tail if e.get("duration_ms")],
                        key=lambda e: float(e.get("duration_ms", 0.0)),
                        reverse=True,
                    )[:5]
                    self._write_json({"recent_events": tail, "bottlenecks": bottlenecks, "watch_hooks": list(shell._dflow_subscribers.keys())})
                    return
                if parsed.path == "/lsp/completions":
                    prefix = urllib.parse.parse_qs(parsed.query).get("prefix", [""])[0]
                    self._write_json({
                        "prefix": prefix,
                        "items": sorted([name for name in shell.commands.keys() if name.startswith(prefix)]),
                    })
                    return
                if parsed.path == "/commands":
                    self._write_json(sorted(shell.commands.keys()))
                    return
                if parsed.path == "/fabric/get":
                    handle = urllib.parse.parse_qs(parsed.query).get("handle", [""])[0]
                    result = shell.fabric.get(handle)
                    if result.error:
                        self._write_json({"error": result.error}, status=404)
                    else:
                        self._write_json({"handle": handle, "value": result.data})
                    return
                if parsed.path == "/fabric/get-bytes":
                    handle = urllib.parse.parse_qs(parsed.query).get("handle", [""])[0]
                    segment = shell.fabric._segments.get(handle)
                    if segment is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                    data = bytes(segment.buf)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b""

                if parsed.path == "/fabric/put":
                    try:
                        payload = json.loads(body.decode("utf-8")) if body else {}
                    except Exception:
                        payload = {}
                    value = str(payload.get("value", ""))
                    result = shell.fabric.put(value)
                    if result.error:
                        self._write_json({"error": result.error}, status=400)
                    else:
                        self._write_json(result.data)
                    return

                if parsed.path == "/flow/event":
                    try:
                        payload = json.loads(body.decode("utf-8")) if body else {}
                    except Exception:
                        payload = {}
                    event_name = str(payload.get("event", ""))
                    value = str(payload.get("payload", ""))
                    result = shell._publish_event(event_name, value, broadcast=False)
                    self._write_json(result.data)
                    return

                if parsed.path == "/fabric/put-bytes":
                    segment = shared_memory.SharedMemory(create=True, size=max(1, len(body)))
                    if body:
                        segment.buf[: len(body)] = body
                    handle = segment.name
                    shell.fabric._segments[handle] = segment
                    self._write_json({"handle": handle, "bytes": len(body)})
                    return

                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        try:
            self._server = http.server.ThreadingHTTPServer((host, port), Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            return CommandResult(output=f"vision started on http://{host}:{port}\n")
        except Exception as exc:
            self._server = None
            self._thread = None
            return CommandResult(output="", error=str(exc))

    def stop(self) -> CommandResult:
        if self._server is None:
            return CommandResult(output="vision not running\n")
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        return CommandResult(output="vision stopped\n")


class MeshWorkerServer:
    """Small HTTP worker runtime for local mesh execution."""

    def __init__(self, shell: "NovaShell", caps: set[str]) -> None:
        self.shell = shell
        self.caps = set(caps)

    def serve(self, host: str, port: int) -> int:
        shell = self.shell
        caps = sorted(self.caps)

        class Handler(http.server.BaseHTTPRequestHandler):
            def _write_json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path in {"/health", "/"}:
                    self._write_json({"status": "ok", "caps": caps, "node_id": shell.node_id})
                    return
                if parsed.path == "/caps":
                    self._write_json({"caps": caps})
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path not in {"/", "/execute"}:
                    self.send_response(404)
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {}
                command = str(payload.get("command", "")).strip()
                if not command:
                    self._write_json({"output": "", "data": None, "error": "missing command", "data_type": PipelineType.TEXT.value}, status=400)
                    return
                result = shell.route(command)
                response = {
                    "output": result.output,
                    "data": result.data,
                    "error": result.error,
                    "data_type": result.data_type.value,
                }
                self._write_json(response, status=200 if result.error is None else 500)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        server = http.server.ThreadingHTTPServer((host, port), Handler)
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0


class NovaShell:
    def __init__(self) -> None:
        self.runtime_config = load_runtime_config()
        self.cwd = Path.cwd()
        self.python = PythonEngine()
        self.cpp = CppEngine()
        self.gpu = GPUEngine()
        self.data = DataEngine()
        self.remote = RemoteEngine()
        self.wasm = WasmEngine()
        self.system = SystemEngine()
        self.events = EventBus()
        self.fabric = NovaFabric()
        self.zero = NovaZeroPool()
        self.policy = PolicyEngine()
        self.mesh = MeshScheduler()
        self.flow_state = FlowStateStore()
        self.jit = NovaComputeJIT()
        self.optimizer = NovaOptimizer(self)
        self.synth = NovaSynth(self)
        self.memory = NovaVectorMemory()
        self.atheria = NovaAtheriaRuntime(self.runtime_config, self.cwd)
        self.atheria_sensors = AtheriaSensorRegistry(self.atheria.storage_root)
        self.ai_runtime = NovaAIProviderRuntime(self.runtime_config, self.cwd, atheria_runtime=self.atheria)
        self.guard_store = GuardPolicyStore()
        self.fabric_remote = FabricRemoteBridge()
        self.reactive = ReactiveFlowEngine(self)
        self.novagraph = NovaGraphCompiler()
        self.node_id = uuid.uuid4().hex[:8]
        self.sync_counters: dict[str, GCounterCRDT] = {}
        self.sync_map = LWWMapCRDT(self.node_id)
        self.lens = NovaLensStore()
        self.last_graph = PipelineGraph()
        self.gpu_task_graphs: dict[str, GPUTaskGraphArtifact] = {}
        self.agents: dict[str, AIAgentDefinition] = {}
        self.agent_instances: dict[str, AgentRuntimeInstance] = {}
        self.agent_graphs: dict[str, AgentGraphDefinition] = {}
        self.tools: dict[str, ToolSchemaDefinition] = {}
        self._register_builtin_tools()
        self.vision = VisionServer(self)
        self.current_policy = "open"
        self.current_trace_id = ""
        self._ns_runtime: NovaInterpreter | None = None
        self._dflow_subscribers: dict[str, list[str]] = {}
        self.wasm_sandbox_default = bool(self.runtime_config.get("sandbox_default", False))
        self.current_memory_namespace = str(self.runtime_config.get("memory_namespace") or "default")
        self.current_memory_project = str(self.runtime_config.get("memory_project") or "default")
        self.local_mesh_workers: dict[str, LocalManagedWorker] = {}
        self.rag_watchers: dict[str, AutoRAGWatcherSpec] = {}
        self.mesh_log_dir = Path(tempfile.gettempdir()) / "nova-shell-mesh-workers"
        self.mesh_log_dir.mkdir(parents=True, exist_ok=True)

        self.commands: dict[str, Callable[[str, str, Any], CommandResult]] = {
            "py": self._run_python,
            "python": self._run_python,
            "cpp": self._run_cpp,
            "cpp.sandbox": self._run_cpp_sandbox,
            "cpp.expr": self._run_cpp_expr,
            "cpp.expr_chain": self._run_cpp_expr_chain,
            "gpu": self._run_gpu,
            "wasm": self._run_wasm,
            "data": self._run_data,
            "data.load": self._run_data_load,
            "remote": self._run_remote,
            "ai": self._run_ai,
            "atheria": self._run_atheria,
            "agent": self._run_agent,
            "memory": self._run_memory,
            "tool": self._run_tool,
            "tool.register": lambda args, pipeline_input, pipeline_data: self._run_tool(f"register {args}".strip(), pipeline_input, pipeline_data),
            "tool.call": lambda args, pipeline_input, pipeline_data: self._run_tool(f"call {args}".strip(), pipeline_input, pipeline_data),
            "tool.list": lambda args, pipeline_input, pipeline_data: self._run_tool(f"list {args}".strip(), pipeline_input, pipeline_data),
            "tool.show": lambda args, pipeline_input, pipeline_data: self._run_tool(f"show {args}".strip(), pipeline_input, pipeline_data),
            "rag": self._run_rag,
            "vision": self._run_vision,
            "pulse": self._run_pulse,
            "fabric": self._run_fabric,
            "zero": self._run_zero,
            "mesh": self._run_mesh,
            "event": self._run_event,
            "guard": self._run_guard,
            "secure": self._run_secure,
            "flow": self._run_flow,
            "reactive": self._run_reactive,
            "dflow": self._run_dflow,
            "opt": self._run_optimizer,
            "synth": self._run_synth,
            "graph": self._run_graph,
            "sync": self._run_sync,
            "lens": self._run_lens,
            "jit_wasm": self._run_jit_wasm,
            "on": self._run_on,
            "pack": self._run_pack,
            "observe": self._run_observe,
            "studio": self._run_studio,
            "watch": self._watch,
            "sys": self._run_system,
            "cd": self._cd,
            "pwd": self._pwd,
            "clear": self._clear_console,
            "cls": self._clear_console,
            "doctor": self._doctor,
            "help": self._help,
            "events": self._events,
            "ns.exec": self._ns_exec,
            "ns.run": self._ns_run,
            "ns.emit": self._ns_emit,
            "ns.check": self._ns_check,
        }

        self._history_file = Path.home() / ".nova_shell_history"
        self._init_history()

        self._loop_owner_thread = threading.get_ident()
        self.loop = asyncio.new_event_loop()
        self._closed = False
        atexit.register(self._close_loop)

    def _init_history(self) -> None:
        if readline is None:
            return
        if self._history_file.exists():
            readline.read_history_file(self._history_file)
        readline.set_history_length(1_000)
        atexit.register(self._save_history)

    def _save_history(self) -> None:
        if readline is None:
            return
        readline.write_history_file(self._history_file)

    def _close_loop(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self._stop_all_local_mesh_workers()
        with contextlib.suppress(Exception):
            self.vision.stop()
        with contextlib.suppress(Exception):
            self.reactive.clear()
        with contextlib.suppress(Exception):
            self.fabric.cleanup()
        with contextlib.suppress(Exception):
            self.zero.cleanup()
        with contextlib.suppress(Exception):
            self.flow_state.close()
        with contextlib.suppress(Exception):
            self.lens.close()
        with contextlib.suppress(Exception):
            self.memory.close()
        with contextlib.suppress(Exception):
            self.atheria.close()
        with contextlib.suppress(Exception):
            if not self.loop.is_closed():
                self.loop.close()

    def register_command(self, name: str, handler: Callable[..., CommandResult]) -> None:
        params = len(inspect.signature(handler).parameters)
        if params == 2:
            self.commands[name] = lambda args, pipeline_input, _pipeline_data: handler(args, pipeline_input)
            return
        self.commands[name] = handler

    def load_plugins(self, plugin_dir: str = "plugins") -> None:
        plugin_path = Path(plugin_dir)
        if not plugin_path.exists():
            return

        for file in plugin_path.glob("*.py"):
            namespace: dict[str, Any] = {}
            code = file.read_text(encoding="utf-8")
            exec(compile(code, str(file), "exec"), namespace)
            register = namespace.get("register")
            if callable(register):
                register(self)

    def _register_builtin_tools(self) -> None:
        builtin_tools = [
            ToolSchemaDefinition(
                name="csv_load",
                description="load rows from a csv file into pipeline data",
                schema={"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]},
                pipeline_template="data load {{file}}",
                builtin=True,
            ),
            ToolSchemaDefinition(
                name="table_mean",
                description="calculate the arithmetic mean for a numeric column from pipeline rows",
                schema={"type": "object", "properties": {"column": {"type": "string"}}, "required": ["column"]},
                pipeline_template='py sum(float(row[{{py:column}}]) for row in _) / len(_)',
                builtin=True,
            ),
            ToolSchemaDefinition(
                name="dataset_summarize",
                description="summarize a dataset file with the active ai provider",
                schema={"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]},
                pipeline_template='ai prompt --file {{file}} "Summarize this dataset"',
                builtin=True,
            ),
        ]
        for tool in builtin_tools:
            self.tools.setdefault(tool.name, tool)

    def _resolve_path(self, path_text: str) -> Path:
        target = Path(os.path.expanduser(path_text))
        if not target.is_absolute():
            target = self.cwd / target
        return target.resolve(strict=False)

    def _cd(self, path_arg: str, _: str, __: Any) -> CommandResult:
        parts = split_command(path_arg)
        target_text = parts[0] if parts else "~"
        try:
            target = self._resolve_path(target_text)
            if not target.exists() or not target.is_dir():
                return CommandResult(output="", error=f"directory not found: {target_text}")
            self.cwd = target
            self.atheria.cwd = target
            self.ai_runtime.cwd = target
            return CommandResult(output="")
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _pwd(self, _: str, __: str, ___: Any) -> CommandResult:
        return CommandResult(output=f"{self.cwd}\n", data=str(self.cwd), data_type=PipelineType.TEXT)

    def _clear_console(self, _: str, __: str, ___: Any) -> CommandResult:
        if not sys.stdout.isatty():
            return CommandResult(output="")
        clear_command = "cls" if _is_windows_runtime() else "clear"
        os.system(clear_command)
        return CommandResult(output="")

    def _doctor(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        modules = {
            "psutil": False,
            "yaml": False,
            "pyarrow": False,
            "wasmtime": False,
            "numpy": False,
            "pyopencl": False,
            "atheria": self.atheria.is_available(),
        }
        for module_name in ["psutil", "yaml", "pyarrow", "wasmtime", "numpy", "pyopencl"]:
            modules[module_name] = module_available(module_name)

        commands = {
            "g++": resolve_gxx_command(),
            "cl": resolve_cl_command(),
        }
        commands["emcc"] = resolve_emcc_command(self.runtime_config, modules)
        command_status = {name: bool(value) for name, value in commands.items()}

        payload = {
            "version": __version__,
            "platform": safe_platform_string(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "cwd": str(self.cwd),
            "profile": str(self.runtime_config.get("profile") or "dev"),
            "commands": commands,
            "command_status": command_status,
            "modules": modules,
            "sandbox_default": self.wasm_sandbox_default,
            "ai": {
                "active_provider": self.ai_runtime.get_active_provider(),
                "active_model": self.ai_runtime.get_active_model(),
                "loaded_env_files": self.ai_runtime.loaded_env_files,
            },
            "atheria": self.atheria.status_payload(),
            "runtime": {
                "memory_entries": len(self.memory.entries),
                "registered_tools": len(self.tools),
                "agent_instances": len(self.agent_instances),
            },
        }

        if parts and parts[0] == "json":
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        lines = [
            f"Nova-shell {payload['version']}",
            f"platform: {payload['platform']}",
            f"python: {payload['python']}",
            f"executable: {payload['executable']}",
            f"cwd: {payload['cwd']}",
            f"profile: {payload['profile']}",
            f"g++: {'ok' if payload['command_status']['g++'] else 'missing'}",
            f"emcc: {'ok' if payload['command_status']['emcc'] else 'missing'}",
            f"cl: {'ok' if payload['command_status']['cl'] else 'missing'}",
            f"sandbox_default: {'ok' if payload['sandbox_default'] else 'false'}",
            f"ai_provider: {payload['ai']['active_provider'] or 'none'}",
            f"ai_model: {payload['ai']['active_model'] or 'none'}",
            f"atheria_records: {payload['atheria'].get('trained_records', 0)}",
            f"memory_entries: {payload['runtime']['memory_entries']}",
            f"registered_tools: {payload['runtime']['registered_tools']}",
            f"agent_instances: {payload['runtime']['agent_instances']}",
        ]
        for name, available in payload["modules"].items():
            lines.append(f"{name}: {'ok' if available else 'missing'}")
        return CommandResult(output="\n".join(lines) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def _help(self, _: str, __: str, ___: Any) -> CommandResult:
        commands = "\n".join(sorted(self.commands.keys()))
        return CommandResult(output=f"Commands:\n{commands}\n")

    def _events(self, args: str, _: str, __: Any) -> CommandResult:
        action = args.strip()
        if action == "last":
            last_event = self.events.last()
            if last_event is None:
                return CommandResult(output="No events\n")
            return CommandResult(output=json.dumps(last_event, ensure_ascii=False) + "\n", data=last_event, data_type=PipelineType.OBJECT)
        if action == "clear":
            self.events.events.clear()
            return CommandResult(output="events cleared\n")
        if action == "stats":
            if not self.events.events:
                return CommandResult(output="No events\n")
            durations = [float(event.get("duration_ms", 0.0)) for event in self.events.events]
            rows = [int(event.get("rows_processed", 0)) for event in self.events.events]
            stats = {
                "count": len(self.events.events),
                "duration_ms_avg": sum(durations) / len(durations),
                "rows_processed_total": sum(rows),
            }
            return CommandResult(output=json.dumps(stats, ensure_ascii=False) + "\n", data=stats, data_type=PipelineType.OBJECT)
        return CommandResult(output="Usage: events last|clear|stats\n")

    def _tail_follow(self, file_path: Path, follow_seconds: float) -> Iterable[str]:
        initial_size = file_path.stat().st_size if file_path.exists() else 0
        with file_path.open("r", encoding="utf-8") as handle:
            if initial_size > 0:
                handle.seek(0, os.SEEK_END)
            else:
                handle.seek(0)
            deadline = time.time() + follow_seconds
            while time.time() <= deadline:
                line = handle.readline()
                if line:
                    yield line.rstrip("\n")
                    continue
                time.sleep(0.05)
            while True:
                line = handle.readline()
                if not line:
                    break
                yield line.rstrip("\n")

    def _watch(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: watch <file> [--lines N] [--follow-seconds S]")

        file_path = self._resolve_path(parts[0])
        lines_count = 10
        follow_seconds = 0.0

        i = 1
        while i < len(parts):
            token = parts[i]
            if token == "--lines" and i + 1 < len(parts):
                lines_count = int(parts[i + 1])
                i += 2
                continue
            if token == "--follow-seconds" and i + 1 < len(parts):
                follow_seconds = float(parts[i + 1])
                i += 2
                continue
            return CommandResult(output="", error=f"unknown watch option: {token}")

        if not file_path.exists():
            return CommandResult(output="", error=f"file not found: {file_path}")

        if follow_seconds > 0:
            return CommandResult(output="", data=self._tail_follow(file_path, follow_seconds), data_type=PipelineType.GENERATOR)

        lines = file_path.read_text(encoding="utf-8").splitlines()
        selected = lines[-lines_count:]
        output = "\n".join(selected)
        if output:
            output += "\n"
        return CommandResult(output=output, data=selected, data_type=PipelineType.TEXT_STREAM)

    def _normalize_inline_script(self, source: str) -> str:
        flattened = source.replace(";", "\n")
        normalized_lines: list[str] = []
        previous_was_block_header = False

        for raw in flattened.splitlines():
            statement = raw.strip()
            if not statement:
                continue
            if previous_was_block_header:
                normalized_lines.append(f"    {statement}")
            else:
                normalized_lines.append(statement)
            previous_was_block_header = statement.endswith(":")

        return "\n".join(normalized_lines)

    def _ns_exec(self, script: str, _: str, __: Any) -> CommandResult:
        source = script.strip()
        if not source:
            return CommandResult(output="", error="usage: ns.exec <inline_script>")
        try:
            parser = NovaParser()
            interpreter = NovaInterpreter(self)
            nodes = parser.parse(self._normalize_inline_script(source))
            self._ns_runtime = interpreter
            output = interpreter.execute(nodes)
            return CommandResult(output=output)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _ns_run(self, file_path: str, _: str, __: Any) -> CommandResult:
        parts = split_command(file_path)
        if not parts:
            return CommandResult(output="", error="usage: ns.run <script.ns>")

        try:
            parser = NovaParser()
            interpreter = NovaInterpreter(self)
            nodes = parser.parse_file(str(self._resolve_path(parts[0])))
            self._ns_runtime = interpreter
            output = interpreter.execute(nodes)
            return CommandResult(output=output)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _ns_emit(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if len(parts) < 2:
            return CommandResult(output="", error="usage: ns.emit <variable> <value>")
        if self._ns_runtime is None:
            return CommandResult(output="", error="no active NovaScript runtime; run ns.exec/ns.run first")
        variable = parts[0]
        value = " ".join(parts[1:])
        try:
            out = self._ns_runtime.emit(variable, value)
            return CommandResult(output=out)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _ns_check(self, source: str, _: str, __: Any) -> CommandResult:
        payload = source.strip()
        if not payload:
            return CommandResult(output="", error="usage: ns.check <script_file.ns>")
        try:
            parser = NovaParser()
            nodes = parser.parse_file(str(self._resolve_path(payload)))
            assignments = sum(1 for n in nodes if isinstance(n, NSAssignment))
            commands = sum(1 for n in nodes if isinstance(n, NSCommand))
            contracts = 0
            for n in nodes:
                if getattr(n, "declared_type", None):
                    contracts += 1
                if getattr(n, "output_contract", None):
                    contracts += 1
            watch_hooks = sum(1 for n in nodes if isinstance(n, NSWatchHook))
            result = {"nodes": len(nodes), "assignments": assignments, "commands": commands, "contracts": contracts, "watch_hooks": watch_hooks}
            return CommandResult(output=json.dumps(result, ensure_ascii=False) + "\n", data=result, data_type=PipelineType.OBJECT)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _is_ebpf_blocked(self, command: str) -> str | None:
        enforced = self.guard_store.enforced_policy
        if not enforced:
            return None
        policy = self.guard_store.loaded_policies.get(enforced)
        if not policy:
            return None
        blocked_terms = [str(v) for v in policy.get("blocked_terms", [])]
        for term in blocked_terms:
            if term and term in command:
                return f"ebpf policy '{enforced}' blocked term '{term}'"
        return None

    def _run_cpp_expr(self, expression: str, pipeline_input: str, _: Any) -> CommandResult:
        expr = expression.strip()
        if not expr:
            return CommandResult(output="", error="usage: cpp.expr <expression using x>")
        code = self.novagraph._build_cpp_chain(expr)
        return self.cpp.compile_and_run(code, pipeline_input)

    def _run_cpp_expr_chain(self, expression_chain: str, pipeline_input: str, _: Any) -> CommandResult:
        chain = expression_chain.strip()
        if not chain:
            return CommandResult(output="", error="usage: cpp.expr_chain <expr1 ; expr2 ; ...>")
        code = self.novagraph._build_cpp_chain(chain)
        return self.cpp.compile_and_run(code, pipeline_input)

    def _run_graph(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: graph aot <pipeline> | graph run <pipeline> | graph show <id>")

        action = parts[0]
        if action in {"aot", "run"}:
            if len(parts) < 2:
                return CommandResult(output="", error=f"usage: graph {action} <pipeline>")
            pipeline = parts[1] if len(parts) == 2 else args[len(action) :].strip()
            stages = self._split_pipeline(pipeline)
            artifact = self.novagraph.optimize(pipeline, stages)
            payload = {
                "graph_id": artifact.graph_id,
                "optimized_stages": artifact.optimized_stages,
                "fused_cpp_count": artifact.fused_cpp_count,
            }
            if action == "aot":
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

            result = self.route(" | ".join(artifact.optimized_stages))
            if result.error:
                return result
            payload["output"] = result.output
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "show":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: graph show <id>")
            artifact = self.novagraph.get(parts[1])
            if artifact is None:
                return CommandResult(output="", error="graph artifact not found")
            payload = {
                "graph_id": artifact.graph_id,
                "original_pipeline": artifact.original_pipeline,
                "optimized_stages": artifact.optimized_stages,
                "fused_cpp_count": artifact.fused_cpp_count,
                "generated_cpp": artifact.generated_cpp,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        return CommandResult(output="", error="usage: graph aot <pipeline> | graph run <pipeline> | graph show <id>")

    def _run_python(self, code: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        return self.python.execute(code, pipeline_input, pipeline_data, cwd=self.cwd)

    def _run_cpp(self, code: str, pipeline_input: str, _: Any) -> CommandResult:
        blocked = self._is_ebpf_blocked(code)
        if blocked:
            return CommandResult(output="", error=blocked)
        if self.wasm_sandbox_default:
            return self.cpp.compile_to_wasm_and_run(code, pipeline_input)
        return self.cpp.compile_and_run(code, pipeline_input)

    def _run_cpp_sandbox(self, code: str, pipeline_input: str, _: Any) -> CommandResult:
        blocked = self._is_ebpf_blocked(code)
        if blocked:
            return CommandResult(output="", error=blocked)
        return self.cpp.compile_to_wasm_and_run(code, pipeline_input)

    def _plan_gpu_task_graph(self, kernels: list[str], input_payload: str = "") -> GPUTaskGraphArtifact:
        artifact = GPUTaskGraphArtifact(
            graph_id=uuid.uuid4().hex[:12],
            kernels=[str(self._resolve_path(kernel)) for kernel in kernels],
            input_payload=input_payload,
        )
        self.gpu_task_graphs[artifact.graph_id] = artifact
        return artifact

    def _run_gpu_task_graph(self, kernels: list[str], input_payload: str = "") -> CommandResult:
        artifact = self._plan_gpu_task_graph(kernels, input_payload)
        current_output = input_payload
        final_result = CommandResult(output="")
        for kernel in artifact.kernels:
            final_result = self.gpu.run_kernel(kernel, current_output)
            if final_result.error:
                return final_result
            current_output = final_result.output.strip()
        artifact.final_output = final_result.output
        artifact.final_data = final_result.data
        payload = {
            "graph_id": artifact.graph_id,
            "kernels": artifact.kernels,
            "output": artifact.final_output,
        }
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def _run_gpu(self, args: str, pipeline_input: str, _: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: gpu <kernel_file> | gpu graph plan|run|show ...")
        if parts[0] == "graph":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: gpu graph plan <kernel1> [kernel2 ...] | gpu graph run <kernel1> [kernel2 ...] [--input values] | gpu graph show <id>")
            action = parts[1]
            if action == "show":
                artifact = self.gpu_task_graphs.get(parts[2])
                if artifact is None:
                    return CommandResult(output="", error="gpu task graph not found")
                payload = {
                    "graph_id": artifact.graph_id,
                    "kernels": artifact.kernels,
                    "input_payload": artifact.input_payload,
                    "output": artifact.final_output,
                }
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

            kernel_tokens = parts[2:]
            input_payload = pipeline_input
            if "--input" in kernel_tokens:
                idx = kernel_tokens.index("--input")
                if idx + 1 >= len(kernel_tokens):
                    return CommandResult(output="", error="usage: gpu graph run <kernel1> [kernel2 ...] [--input values]")
                input_payload = kernel_tokens[idx + 1]
                kernel_tokens = kernel_tokens[:idx] + kernel_tokens[idx + 2 :]
            if not kernel_tokens:
                return CommandResult(output="", error="gpu graph requires at least one kernel file")

            if action == "plan":
                artifact = self._plan_gpu_task_graph(kernel_tokens, input_payload)
                payload = {"graph_id": artifact.graph_id, "kernels": artifact.kernels, "input_payload": artifact.input_payload}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if action == "run":
                return self._run_gpu_task_graph(kernel_tokens, input_payload)
            return CommandResult(output="", error="usage: gpu graph plan|run|show ...")
        return self.gpu.run_kernel(str(self._resolve_path(parts[0])), pipeline_input)

    def _run_wasm(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: wasm <module.wasm>")
        return self.wasm.execute(str(self._resolve_path(parts[0])))

    def _run_remote(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if len(parts) < 2:
            return CommandResult(output="", error="usage: remote <worker_url> <command>")
        worker_url = parts[0]
        command = args[len(worker_url) :].strip()
        return self.remote.execute(worker_url, command)

    def _shell_literal(self, value: Any) -> str:
        if value is None:
            return "''"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (list, dict)):
            return shlex.quote(json.dumps(value, ensure_ascii=False))
        return shlex.quote(str(value))

    def _template_literal(self, value: Any, format_name: str) -> str:
        if format_name == "py":
            return repr(value)
        if format_name == "json":
            return json.dumps(value, ensure_ascii=False)
        if format_name == "raw":
            return str(value)
        return self._shell_literal(value)

    def _parse_json_object_arg(self, text: str, *, field_name: str) -> tuple[dict[str, Any] | None, CommandResult | None]:
        try:
            value = json.loads(text)
        except Exception as exc:
            return None, CommandResult(output="", error=f"invalid {field_name} json: {exc}")
        if not isinstance(value, dict):
            return None, CommandResult(output="", error=f"{field_name} must be a json object")
        return value, None

    def _coerce_tool_value(self, value: str) -> Any:
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        with contextlib.suppress(Exception):
            if "." in value:
                return float(value)
            return int(value)
        if (value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]")):
            with contextlib.suppress(Exception):
                return json.loads(value)
        return value

    def _parse_tool_call_payload(self, args_text: str) -> tuple[dict[str, Any] | None, CommandResult | None]:
        raw = args_text.strip()
        if not raw:
            return {}, None
        if raw.startswith("{"):
            return self._parse_json_object_arg(raw, field_name="tool args")
        payload: dict[str, Any] = {}
        for token in split_command(raw):
            if "=" not in token:
                return None, CommandResult(output="", error="tool call arguments must be json or key=value pairs")
            key, value = token.split("=", 1)
            payload[key] = self._coerce_tool_value(value)
        return payload, None

    def _schema_type_matches(self, expected: str, value: Any) -> bool:
        if expected == "string":
            return isinstance(value, str)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        return True

    def _validate_tool_payload(self, schema: dict[str, Any], payload: dict[str, Any]) -> str | None:
        if not schema:
            return None
        if schema.get("type") not in {None, "object"}:
            return "tool schema root type must be object"
        required = [str(name) for name in schema.get("required", [])]
        for name in required:
            if name not in payload:
                return f"missing required tool argument: {name}"
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for name, definition in properties.items():
                if name not in payload or not isinstance(definition, dict):
                    continue
                expected = str(definition.get("type", "")).strip()
                if expected and not self._schema_type_matches(expected, payload[name]):
                    return f"tool argument '{name}' must be {expected}"
        return None

    def _resolve_template_value(self, payload: dict[str, Any], dotted_name: str) -> Any:
        current: Any = payload
        for part in dotted_name.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
                continue
            raise KeyError(dotted_name)
        return current

    def _render_tool_pipeline(self, template: str, payload: dict[str, Any]) -> tuple[str | None, CommandResult | None]:
        def replace(match: re.Match[str]) -> str:
            format_name = (match.group(1) or "shell").strip().lower()
            key = match.group(2).strip()
            value = self._resolve_template_value(payload, key)
            return self._template_literal(value, format_name)

        try:
            rendered = re.sub(r"\{\{\s*(?:(shell|py|json|raw):)?([A-Za-z0-9_.-]+)\s*\}\}", replace, template)
        except KeyError as exc:
            missing = str(exc).strip("'")
            return None, CommandResult(output="", error=f"tool pipeline references unknown argument: {missing}")
        return rendered, None

    def _tool_catalog_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.schema,
                "pipeline_template": tool.pipeline_template,
                "builtin": tool.builtin,
                "created_at": tool.created_at,
            }
            for tool in self.tools.values()
        ]

    def _tool_invocation_command(self, tool_name: str, args_payload: dict[str, Any] | None = None) -> str:
        args_payload = args_payload or {}
        parts = [f"tool.call {tool_name}"]
        for key, value in args_payload.items():
            parts.append(f"{key}={self._shell_literal(value)}")
        return " ".join(parts)

    def _compose_plan_pipeline(self, steps: list[dict[str, Any]]) -> str:
        commands: list[str] = []
        for step in steps:
            tool_name = str(step.get("tool") or step.get("name") or "").strip()
            if not tool_name:
                continue
            args_payload = step.get("args", {})
            if not isinstance(args_payload, dict):
                args_payload = {}
            commands.append(self._tool_invocation_command(tool_name, args_payload))
        return " | ".join(commands)

    def _extract_csv_goal(self, prompt: str) -> tuple[str, str] | None:
        lowered = prompt.lower()
        file_matches = re.findall(r"([A-Za-z0-9_.-]+\.csv)", prompt, flags=re.IGNORECASE)
        if not file_matches:
            return None
        filename = file_matches[0]
        column = ""
        patterns = [
            r"(?:average|mean)\s+(?:of\s+)?([A-Za-z_][A-Za-z0-9_]*)",
            r"([A-Za-z_][A-Za-z0-9_]*)\s+(?:average|mean)",
        ]
        excluded = {"calculate", "csv", "items", "file", "in", "from"}
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if not match:
                continue
            candidate = match.group(1).strip().strip(".,:;")
            if candidate and candidate not in excluded:
                column = candidate
                break
        if not column and "price" in lowered:
            column = "price"
        if not column and "value" in lowered:
            column = "value"
        if not column:
            column = "A"
        return filename, column

    def _resolve_memory_scope(self, namespace: str | None = None, project: str | None = None, *, all_scopes: bool = False) -> tuple[str | None, str | None]:
        if all_scopes:
            return None, None
        return namespace or self.current_memory_namespace, project or self.current_memory_project

    def _parse_memory_scope_args(self, parts: list[str], *, start_index: int = 0) -> tuple[dict[str, Any], list[str]]:
        namespace = ""
        project = ""
        all_scopes = False
        limit: int | None = None
        remaining: list[str] = []
        i = start_index
        while i < len(parts):
            token = parts[i]
            if token == "--namespace" and i + 1 < len(parts):
                namespace = parts[i + 1]
                i += 2
                continue
            if token == "--project" and i + 1 < len(parts):
                project = parts[i + 1]
                i += 2
                continue
            if token == "--all":
                all_scopes = True
                i += 1
                continue
            if token == "--limit" and i + 1 < len(parts):
                with contextlib.suppress(Exception):
                    limit = max(1, int(parts[i + 1]))
                i += 2
                continue
            remaining.append(token)
            i += 1
        return {"namespace": namespace, "project": project, "all_scopes": all_scopes, "limit": limit}, remaining

    def _memory_scope_payload(self) -> dict[str, Any]:
        return {
            "namespace": self.current_memory_namespace,
            "project": self.current_memory_project,
            "count": self.memory.count(namespace=self.current_memory_namespace, project=self.current_memory_project),
            "total_count": self.memory.count(),
        }

    def _memory_context_hits(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        if not self.memory.entries:
            return []
        namespace, project = self._resolve_memory_scope()
        return self.memory.search(query, limit=limit, namespace=namespace, project=project)

    def _parse_agent_graph_edges(self, edges_text: str, nodes: list[str]) -> list[tuple[str, str]]:
        edges: list[tuple[str, str]] = []
        if not edges_text.strip():
            return [(nodes[index], nodes[index + 1]) for index in range(len(nodes) - 1)]
        for token in [item.strip() for item in edges_text.split(",") if item.strip()]:
            if ">" in token:
                left, right = token.split(">", 1)
            elif "->" in token:
                left, right = token.split("->", 1)
            else:
                continue
            edges.append((left.strip(), right.strip()))
        return edges

    def _topological_agent_graph(self, graph: AgentGraphDefinition) -> list[str]:
        indegree = {node: 0 for node in graph.nodes}
        outgoing: dict[str, list[str]] = {node: [] for node in graph.nodes}
        for left, right in graph.edges:
            if left not in indegree or right not in indegree:
                raise ValueError("agent graph edge references unknown node")
            indegree[right] += 1
            outgoing[left].append(right)
        queue = [node for node in graph.nodes if indegree[node] == 0]
        ordered: list[str] = []
        while queue:
            node = queue.pop(0)
            ordered.append(node)
            for target in outgoing.get(node, []):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(ordered) != len(graph.nodes):
            raise ValueError("agent graph contains a cycle")
        return ordered

    def _resolve_agent_handle(self, name: str) -> tuple[AgentRuntimeInstance | None, AIAgentDefinition | None]:
        if name in self.agent_instances:
            return self.agent_instances[name], None
        return None, self.agents.get(name)

    def _run_agent_handle(self, name: str, input_text: str) -> CommandResult:
        instance, definition = self._resolve_agent_handle(name)
        if instance is not None:
            return self._run_agent_instance_message(instance, input_text)
        if definition is not None:
            return self._run_agent_once(definition, input_text)
        return CommandResult(output="", error=f"agent not found: {name}")

    def _find_free_port(self) -> int:
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
        finally:
            sock.close()

    def _local_worker_command(self, host: str, port: int, caps: set[str]) -> list[str]:
        caps_text = ",".join(sorted(caps))
        if getattr(sys, "frozen", False):
            return [sys.executable, "--serve-worker", "--worker-host", host, "--worker-port", str(port), "--worker-caps", caps_text]
        return [sys.executable, str(Path(__file__).resolve()), "--serve-worker", "--worker-host", host, "--worker-port", str(port), "--worker-caps", caps_text]

    def _wait_for_worker_health(self, url: str, *, timeout_seconds: float = 10.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=1) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") == "ok":
                    return True
            except Exception:
                time.sleep(0.1)
        return False

    def _stop_local_mesh_worker(self, identifier: str) -> bool:
        match = self.local_mesh_workers.get(identifier)
        if match is None:
            match = next((worker for worker in self.local_mesh_workers.values() if worker.url == identifier or worker.url.endswith(f":{identifier}") or worker.worker_id == identifier), None)
        if match is None:
            return False
        process = match.process
        with contextlib.suppress(Exception):
            if process.poll() is None:
                process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=5)
        with contextlib.suppress(Exception):
            if process.poll() is None:
                process.kill()
        self.mesh.remove_worker(match.url)
        self.local_mesh_workers.pop(match.worker_id, None)
        return True

    def _stop_all_local_mesh_workers(self) -> None:
        for worker_id in list(self.local_mesh_workers.keys()):
            self._stop_local_mesh_worker(worker_id)

    def _shell_quote(self, value: str) -> str:
        return shlex.quote(str(value))

    def _infer_swarm_caps(self, name: str, prompt_template: str, provider: str, model: str, system_prompt: str) -> set[str]:
        lowered = " ".join([name, prompt_template, provider, model, system_prompt]).lower()
        caps = {"cpu", "py", "ai"}
        if any(token in lowered for token in ["gpu", "cuda", "torch", "vision", "embedding", "transformer"]):
            caps.add("gpu")
        if any(token in lowered for token in ["cpp", "native", "compile"]):
            caps.add("cpu")
        if provider == "atheria":
            caps.add("ai")
        return caps

    def _assign_swarm_worker(self, required_caps: set[str], *, data_handle: str | None = None) -> dict[str, Any] | None:
        if not self.mesh.workers:
            return None
        preferred = "gpu" if "gpu" in required_caps else "ai" if "ai" in required_caps else "py"
        worker = self.mesh.intelligent_select(preferred, data_handle)
        if worker is None and "cpu" in required_caps:
            worker = self.mesh.intelligent_select("cpu", data_handle)
        if worker is None:
            return None
        worker_caps = set(worker.get("caps", []))
        if required_caps.intersection({"gpu", "ai"}) and not required_caps.issubset(worker_caps.union({"cpu", "py"})):
            worker["load"] = max(worker.get("load", 1) - 1, 0)
            return None
        return worker

    def _remote_agent_create_command(
        self,
        remote_name: str,
        *,
        prompt_template: str,
        provider: str,
        model: str,
        system_prompt: str,
    ) -> str:
        parts = [
            "agent create",
            self._shell_quote(remote_name),
            self._shell_quote(prompt_template),
            "--provider",
            self._shell_quote(provider),
            "--model",
            self._shell_quote(model),
        ]
        if system_prompt:
            parts.extend(["--system", self._shell_quote(system_prompt)])
        return " ".join(parts)

    def _remote_agent_run_command(self, remote_name: str, input_text: str) -> str:
        return " ".join(["agent run", self._shell_quote(remote_name), self._shell_quote(input_text)])

    def _run_agent_handle_swarm(
        self,
        name: str,
        input_text: str,
        *,
        execution_id: str,
        step_kind: str,
        step_index: int,
    ) -> tuple[CommandResult, dict[str, Any]]:
        instance, definition = self._resolve_agent_handle(name)
        if instance is None and definition is None:
            result = CommandResult(output="", error=f"agent not found: {name}")
            return result, {"node": name, "mode": "missing", "error": result.error}
        prompt_template = instance.prompt_template if instance is not None else str(definition.prompt_template)
        provider = instance.provider if instance is not None else str(definition.provider)
        model = instance.model if instance is not None else str(definition.model)
        system_prompt = instance.system_prompt if instance is not None else str(definition.system_prompt)
        required_caps = self._infer_swarm_caps(name, prompt_template, provider, model, system_prompt)
        worker = self._assign_swarm_worker(required_caps)
        if worker is None:
            result = self._run_agent_handle(name, input_text)
            assignment = {
                "node": name,
                "mode": "local",
                "required_caps": sorted(required_caps),
                "worker": "local",
                "step_kind": step_kind,
                "step_index": step_index,
                "output": result.output.strip(),
                "error": result.error or "",
            }
            return result, assignment
        worker_url = str(worker["url"])
        remote_name = f"__swarm_{execution_id}_{step_index}_{re.sub(r'[^A-Za-z0-9_]+', '_', name)[:24]}".strip("_")
        create_command = self._remote_agent_create_command(
            remote_name,
            prompt_template=prompt_template,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
        )
        create_result = self.remote.execute(worker_url, create_command)
        if create_result.error:
            worker["load"] = max(worker.get("load", 1) - 1, 0)
            fallback = self._run_agent_handle(name, input_text)
            assignment = {
                "node": name,
                "mode": "local-fallback",
                "required_caps": sorted(required_caps),
                "worker": "local",
                "remote_worker": worker_url,
                "step_kind": step_kind,
                "step_index": step_index,
                "remote_error": create_result.error,
                "output": fallback.output.strip(),
                "error": fallback.error or "",
            }
            return fallback, assignment
        run_result = self.remote.execute(worker_url, self._remote_agent_run_command(remote_name, input_text))
        worker["load"] = max(worker.get("load", 1) - 1, 0)
        assignment = {
            "node": name,
            "mode": "mesh",
            "required_caps": sorted(required_caps),
            "worker": worker_url,
            "step_kind": step_kind,
            "step_index": step_index,
            "output": run_result.output.strip(),
            "error": run_result.error or "",
        }
        with contextlib.suppress(Exception):
            event_payload = json.dumps(
                {
                    "execution_id": execution_id,
                    "node": name,
                    "worker": worker_url,
                    "step_kind": step_kind,
                    "step_index": step_index,
                    "output": run_result.output.strip(),
                    "error": run_result.error or "",
                },
                ensure_ascii=False,
            )
            self._publish_event("swarm.agent.completed", event_payload, broadcast=True)
        return run_result, assignment

    def _load_structured_payload(self, raw: str) -> Any:
        text = str(raw).strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            try:
                import yaml  # type: ignore

                return yaml.safe_load(text)
            except Exception as exc:
                raise ValueError(f"invalid structured payload: {exc}") from exc

    def _deep_merge_payload(self, base: Any, patch: Any) -> Any:
        if isinstance(base, dict) and isinstance(patch, dict):
            merged = dict(base)
            for key, value in patch.items():
                merged[key] = self._deep_merge_payload(merged.get(key), value)
            return merged
        if isinstance(base, list) and isinstance(patch, list):
            result = list(base)
            for index, value in enumerate(patch):
                if index < len(result):
                    result[index] = self._deep_merge_payload(result[index], value)
                else:
                    result.append(value)
            return result
        return copy.deepcopy(patch)

    def _collect_diff_rows(self, before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
        if isinstance(before, dict) and isinstance(after, dict):
            keys = sorted(set(before.keys()).union(after.keys()))
            rows: list[dict[str, Any]] = []
            for key in keys:
                child_path = f"{path}.{key}"
                if key not in before:
                    rows.append({"path": child_path, "before": None, "after": after[key], "change": "added"})
                    continue
                if key not in after:
                    rows.append({"path": child_path, "before": before[key], "after": None, "change": "removed"})
                    continue
                rows.extend(self._collect_diff_rows(before[key], after[key], child_path))
            return rows
        if isinstance(before, list) and isinstance(after, list):
            rows = []
            length = max(len(before), len(after))
            for index in range(length):
                child_path = f"{path}[{index}]"
                if index >= len(before):
                    rows.append({"path": child_path, "before": None, "after": after[index], "change": "added"})
                    continue
                if index >= len(after):
                    rows.append({"path": child_path, "before": before[index], "after": None, "change": "removed"})
                    continue
                rows.extend(self._collect_diff_rows(before[index], after[index], child_path))
            return rows
        if before != after:
            return [{"path": path, "before": before, "after": after, "change": "modified"}]
        return []

    def _extract_numeric_features(self, payload: Any) -> list[float]:
        values: list[float] = []

        def visit(node: Any) -> None:
            if len(values) >= 14:
                return
            if isinstance(node, dict):
                for key in sorted(node.keys()):
                    visit(node[key])
                    if len(values) >= 14:
                        return
                return
            if isinstance(node, list):
                for item in node:
                    visit(item)
                    if len(values) >= 14:
                        return
                return
            with contextlib.suppress(Exception):
                values.append(float(node))

        visit(payload)
        if not values:
            text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            for index in range(14):
                values.append(((digest[index] / 255.0) * 2.0) - 1.0)
        while len(values) < 14:
            values.append(0.0)
        return values[:14]

    def _simulate_fork_payload(self, snapshot_id: str, forked_payload: Any) -> dict[str, Any]:
        simulation: dict[str, Any] = {
            "mode": "heuristic",
            "original_snapshot_id": snapshot_id,
            "numeric_features": [round(float(item), 6) for item in self._extract_numeric_features(forked_payload)],
        }
        if not self.atheria.is_available():
            return simulation
        source_dir = self.atheria._discover_source_dir()
        if source_dir is None:
            return simulation
        source_text = str(source_dir)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        try:
            info_module = importlib.import_module("atheria_information_einstein_like")
            market_module = importlib.import_module("atheria_market_future_projection")
        except Exception as exc:
            simulation["error"] = f"atheria simulation modules unavailable: {exc}"
            return simulation
        base_events = []
        snapshots = list(reversed(self.lens.list(limit=8)))
        for index, row in enumerate(snapshots):
            snapshot = self.lens.get(str(row["id"]))
            if snapshot is None:
                continue
            parsed = self._coerce_snapshot_payload(snapshot.get("data_preview", ""), snapshot.get("output", ""))
            vector = self._extract_numeric_features(parsed)
            base_events.append(
                info_module.InformationEvent(
                    event_id=str(snapshot["id"]),
                    timestamp=float(snapshot["ts"]),
                    vector=vector,
                    metadata={"stage": snapshot.get("stage", "")},
                )
            )
        if forked_payload is not None:
            base_events.append(
                info_module.InformationEvent(
                    event_id=f"{snapshot_id}_fork",
                    timestamp=time.time(),
                    vector=self._extract_numeric_features(forked_payload),
                    metadata={"stage": "lens.fork"},
                )
            )
        if len(base_events) >= 4:
            try:
                reconstruction = info_module.InformationEinsteinLikeSimulator().reconstruct(base_events)
                simulation["einstein_like"] = {
                    "field_summary": reconstruction.field_summary,
                    "quality": reconstruction.quality,
                    "attractors": reconstruction.attractors[:5],
                }
                simulation["mode"] = "atheria_einstein_like"
            except Exception as exc:
                simulation["einstein_like_error"] = str(exc)
        if len(base_events) >= 1:
            try:
                market_events = [
                    market_module.MarketEvent(
                        event_id=str(event.event_id),
                        timestamp=float(event.timestamp),
                        features=list(event.vector),
                        signal=float(sum(event.vector[:4]) / max(1, min(4, len(event.vector)))),
                        metadata=dict(event.metadata or {}),
                    )
                    for event in base_events
                ]
                projection = market_module.MarketLandscapeFutureProjector().run(market_events)
                simulation["projection"] = {
                    "forecast": list(projection.get("forecast", []))[:4],
                    "top_drivers": list(projection.get("top_drivers", []))[:5],
                    "statement": projection.get("statement", ""),
                    "proof_verdict": projection.get("proof_verdict", ""),
                }
                simulation["mode"] = "atheria_projected"
            except Exception as exc:
                simulation["projection_error"] = str(exc)
        return simulation

    def _coerce_snapshot_payload(self, data_preview: str, output_text: str) -> Any:
        for candidate in [data_preview, output_text]:
            text = str(candidate or "").strip()
            if not text:
                continue
            with contextlib.suppress(Exception):
                return json.loads(text)
        return {"data_preview": data_preview, "output": output_text}

    def _load_rag_file_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            return file_path.read_text(encoding="utf-8")
        if suffix == ".json":
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            return json.dumps(payload, ensure_ascii=False, indent=2)
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore
            except Exception as exc:
                raise RuntimeError(f"pdf ingestion requires pypdf: {exc}") from exc
            reader = PdfReader(str(file_path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(page.strip() for page in pages if page.strip())
        return file_path.read_text(encoding="utf-8", errors="replace")

    def _chunk_rag_text(self, text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
        if not paragraphs:
            cleaned = text.strip()
            return [cleaned] if cleaned else []
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else current + "\n\n" + paragraph
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(paragraph) <= chunk_size:
                current = paragraph
                continue
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + chunk_size)
                piece = paragraph[start:end].strip()
                if piece:
                    chunks.append(piece)
                if end >= len(paragraph):
                    break
                start = max(end - max(0, chunk_overlap), start + 1)
            current = ""
        if current:
            chunks.append(current)
        return chunks

    def _summarize_rag_document(self, text: str, source_file: Path) -> str:
        active_provider = self.ai_runtime.get_active_provider()
        if active_provider:
            prompt = "\n".join(
                [
                    "Summarize this document for Nova-shell auto-ingest in 4 bullet-free sentences.",
                    f"Source: {source_file.name}",
                    "",
                    text[:6000],
                ]
            )
            result = self.ai_runtime.complete_prompt(prompt)
            if result.error is None and result.output.strip():
                return result.output.strip()
        sentence_parts = re.split(r"(?<=[.!?])\s+", text.strip())
        summary = " ".join(part for part in sentence_parts[:3] if part).strip()
        if summary:
            return summary[:800]
        return text.strip()[:800]

    def _ingest_rag_file(
        self,
        file_path: Path,
        *,
        namespace: str,
        project: str,
        chunk_size: int,
        chunk_overlap: int,
        publish_topic: str,
        train_atheria: bool,
        summarize: bool,
    ) -> dict[str, Any]:
        text = self._load_rag_file_text(file_path)
        if not text.strip():
            raise ValueError("rag source file is empty")
        summary = self._summarize_rag_document(text, file_path) if summarize else ""
        chunks = self._chunk_rag_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            chunks = [text.strip()]
        zero_handle = ""
        if len(text.encode("utf-8")) >= 4096:
            zero_result = self.zero.put_text(text)
            if zero_result.error is None and isinstance(zero_result.data, dict):
                zero_handle = str(zero_result.data.get("handle") or "")
        chunk_ids: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            entry = self.memory.embed(
                chunk,
                entry_id=f"rag_{file_path.stem}_{index}_{uuid.uuid4().hex[:6]}",
                metadata={
                    "source_file": str(file_path),
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "summary": summary,
                    "zero_handle": zero_handle,
                    "ingest_mode": "auto-rag",
                },
                namespace=namespace,
                project=project,
            )
            chunk_ids.append(entry.entry_id)
        trained = 0
        if train_atheria:
            trained = self.atheria.train_text_file(file_path, category=project or file_path.stem or "auto_rag")
        event_payload = {
            "source_file": str(file_path),
            "namespace": namespace,
            "project": project,
            "chunk_ids": chunk_ids,
            "summary": summary,
            "trained_records": trained,
            "zero_handle": zero_handle,
        }
        self._publish_event(publish_topic, json.dumps(event_payload, ensure_ascii=False), broadcast=True)
        return {
            "file": str(file_path),
            "namespace": namespace,
            "project": project,
            "chunks": len(chunk_ids),
            "chunk_ids": chunk_ids,
            "summary": summary,
            "trained_records": trained,
            "publish_topic": publish_topic,
            "zero_handle": zero_handle,
        }

    def _planner_tool_candidates(self, prompt: str) -> list[ToolSchemaDefinition]:
        lowered = prompt.lower()
        candidates: list[tuple[int, ToolSchemaDefinition]] = []
        prompt_tokens = set(self.memory._tokenize(prompt))
        for tool in self.tools.values():
            haystack = f"{tool.name} {tool.description}".lower()
            score = 0
            if tool.name.lower() in lowered:
                score += 4
            description_tokens = set(self.memory._tokenize(haystack))
            score += len(prompt_tokens.intersection(description_tokens))
            if score > 0:
                candidates.append((score, tool))
        candidates.sort(key=lambda item: (-item[0], item[1].name))
        return [tool for _, tool in candidates[:3]]

    def _provider_ai_plan(self, prompt: str) -> CommandResult:
        provider = self.ai_runtime.get_active_provider()
        if not provider:
            return CommandResult(output="", error="no active ai provider")
        tool_rows = self._tool_catalog_rows()
        memory_hits = self._memory_context_hits(prompt, limit=3)
        planner_prompt = "\n".join(
            [
                "You are Nova Planner. Generate one runnable Nova-shell pipeline.",
                "Prefer tool orchestration over raw shell code when possible.",
                "Respond with JSON only using keys: pipeline, steps, summary, mode, tools, agents, memory_ids.",
                "Each step should be an object: {\"tool\": \"tool_name\", \"args\": {...}}.",
                "Do not wrap the JSON in markdown.",
                "",
                f"User goal: {prompt}",
                "",
                "Available tools:",
                json.dumps(tool_rows, ensure_ascii=False),
                "",
                "Relevant memory:",
                json.dumps(memory_hits, ensure_ascii=False),
            ]
        )
        result = self.ai_runtime.complete_prompt(
            planner_prompt,
            provider=provider,
            model=self.ai_runtime.get_active_model(provider),
            system_prompt="Produce strict JSON for Nova-shell planning.",
        )
        if result.error:
            return result
        text = result.output.strip()
        payload: dict[str, Any]
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"pipeline": text, "summary": "provider returned plain text", "mode": "provider-text"}
        steps = payload.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        pipeline = str(payload.get("pipeline", "")).strip()
        if not pipeline and steps:
            pipeline = self._compose_plan_pipeline([step for step in steps if isinstance(step, dict)])
        if not pipeline:
            return CommandResult(output="", error="planner returned no pipeline")
        payload.setdefault("mode", "provider")
        payload.setdefault("tools", [item["name"] for item in tool_rows[:3]])
        payload.setdefault("agents", [])
        payload.setdefault("memory_ids", [item["id"] for item in memory_hits])
        payload["pipeline"] = pipeline
        payload.setdefault("steps", steps)
        return CommandResult(output=f"{pipeline}\n", data=payload, data_type=PipelineType.OBJECT)

    def _parse_plan_steps_from_pipeline(self, pipeline: str) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for stage in self._split_pipeline(pipeline):
            stripped = stage.strip()
            if not stripped.startswith(("tool.call ", "tool call ")):
                continue
            normalized = stripped.replace("tool.call", "tool call", 1)
            parts = split_command(normalized)
            if len(parts) < 3:
                continue
            tool_name = parts[2]
            args_text = normalized.split(tool_name, 1)[1].strip()
            payload, _ = self._parse_tool_call_payload(args_text)
            steps.append({"tool": tool_name, "args": payload or {}})
        return steps

    def _normalize_plan_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        steps = normalized.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        valid_steps = [step for step in steps if isinstance(step, dict)]
        pipeline = str(normalized.get("pipeline", "")).strip()
        if not valid_steps and pipeline:
            valid_steps = self._parse_plan_steps_from_pipeline(pipeline)
        if not pipeline and valid_steps:
            pipeline = self._compose_plan_pipeline(valid_steps)
        normalized["steps"] = valid_steps
        normalized["pipeline"] = pipeline
        return normalized

    def _validate_plan_steps(self, steps: list[dict[str, Any]]) -> str | None:
        if not steps:
            return None
        for step in steps:
            tool_name = str(step.get("tool") or "").strip()
            if not tool_name:
                return "plan step missing tool name"
            tool = self.tools.get(tool_name)
            if tool is None:
                return f"tool not found: {tool_name}"
            args_payload = step.get("args", {})
            if not isinstance(args_payload, dict):
                return f"tool step args must be an object: {tool_name}"
            validation_error = self._validate_tool_payload(tool.schema, args_payload)
            if validation_error:
                return f"{tool_name}: {validation_error}"
        return None

    def _provider_repair_plan(self, prompt: str, plan_payload: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any] | None:
        provider = self.ai_runtime.get_active_provider()
        if not provider:
            return None
        repair_prompt = "\n".join(
            [
                "You are Nova Planner Repair. Return repaired JSON only.",
                "Use keys: pipeline, steps, summary, mode, tools, agents, memory_ids.",
                f"Original user goal: {prompt}",
                "",
                "Current plan:",
                json.dumps(plan_payload, ensure_ascii=False),
                "",
                "Failure:",
                json.dumps(failure, ensure_ascii=False),
                "",
                "Available tools:",
                json.dumps(self._tool_catalog_rows(), ensure_ascii=False),
            ]
        )
        repaired = self.ai_runtime.complete_prompt(
            repair_prompt,
            provider=provider,
            model=self.ai_runtime.get_active_model(provider),
            system_prompt="Repair the Nova-shell plan. Prefer valid tool graphs.",
        )
        if repaired.error:
            return None
        with contextlib.suppress(Exception):
            parsed = json.loads(repaired.output.strip())
            if isinstance(parsed, dict):
                return self._normalize_plan_payload(parsed)
        return None

    def _heuristic_repair_plan(self, prompt: str, failure: dict[str, Any]) -> dict[str, Any] | None:
        lowered = prompt.lower()
        csv_goal = self._extract_csv_goal(prompt)
        if csv_goal and any(keyword in lowered for keyword in ["average", "mean"]):
            filename, column = csv_goal
            steps = [
                {"tool": "csv_load", "args": {"file": filename}},
                {"tool": "table_mean", "args": {"column": column}},
            ]
            return self._normalize_plan_payload(
                {
                    "pipeline": self._compose_plan_pipeline(steps),
                    "steps": steps,
                    "mode": "repair-heuristic",
                    "summary": f"repair mean calculation for {filename}",
                    "tools": ["csv_load", "table_mean"],
                    "agents": [],
                    "memory_ids": [item["id"] for item in self._memory_context_hits(prompt, limit=3)],
                    "repair_reason": failure.get("error", ""),
                }
            )
        if csv_goal and any(keyword in lowered for keyword in ["summarize", "summary", "describe"]):
            filename, _ = csv_goal
            steps = [{"tool": "dataset_summarize", "args": {"file": filename}}]
            return self._normalize_plan_payload(
                {
                    "pipeline": self._compose_plan_pipeline(steps),
                    "steps": steps,
                    "mode": "repair-heuristic",
                    "summary": f"repair dataset summary for {filename}",
                    "tools": ["dataset_summarize"],
                    "agents": [],
                    "memory_ids": [item["id"] for item in self._memory_context_hits(prompt, limit=3)],
                    "repair_reason": failure.get("error", ""),
                }
            )
        return None

    def _repair_plan_after_failure(self, prompt: str, plan_payload: dict[str, Any], failure: dict[str, Any], attempt: int) -> dict[str, Any] | None:
        repaired = self._provider_repair_plan(prompt, plan_payload, failure)
        if repaired is None:
            repaired = self._heuristic_repair_plan(prompt, failure)
        if repaired is None:
            return None
        repaired.setdefault("replanned", [])
        repaired["replanned"] = list(plan_payload.get("replanned", [])) + [
            {"attempt": attempt, "failure": failure, "pipeline": repaired.get("pipeline", "")}
        ]
        return repaired

    def _execute_plan_payload(self, prompt: str, plan_payload: dict[str, Any], *, max_replans: int = 1) -> CommandResult:
        attempts: list[dict[str, Any]] = []
        current_payload = self._normalize_plan_payload(plan_payload)
        for attempt in range(max(1, max_replans + 1)):
            steps = list(current_payload.get("steps", []))
            pipeline = str(current_payload.get("pipeline", "")).strip()
            validation_error = self._validate_plan_steps(steps)
            if validation_error:
                failure = {"phase": "validation", "error": validation_error, "pipeline": pipeline}
                attempts.append({"attempt": attempt + 1, "status": "validation_failed", "failure": failure})
                if attempt >= max_replans:
                    return CommandResult(output="", error=validation_error)
                repaired = self._repair_plan_after_failure(prompt, current_payload, failure, attempt + 1)
                if repaired is None:
                    return CommandResult(output="", error=validation_error)
                current_payload = repaired
                continue
            if not steps and pipeline:
                result = self.route(pipeline)
                if result.error:
                    failure = {"phase": "execution", "error": result.error, "pipeline": pipeline}
                    attempts.append({"attempt": attempt + 1, "status": "execution_failed", "failure": failure})
                    if attempt >= max_replans:
                        return result
                    repaired = self._repair_plan_after_failure(prompt, current_payload, failure, attempt + 1)
                    if repaired is None:
                        return result
                    current_payload = repaired
                    continue
                final_payload = dict(current_payload)
                final_payload["attempts"] = attempts + [{"attempt": attempt + 1, "status": "ok"}]
                final_payload["execution"] = {
                    "output": result.output.strip(),
                    "data_type": result.data_type.value if isinstance(result.data_type, PipelineType) else str(result.data_type),
                }
                return CommandResult(output=result.output, data=final_payload, data_type=PipelineType.OBJECT)
            current_output = ""
            current_data: Any = None
            current_type = PipelineType.TEXT
            step_trace: list[dict[str, Any]] = []
            failed = False
            for index, step in enumerate(steps):
                tool_name = str(step.get("tool") or "").strip()
                args_payload = step.get("args", {})
                if not isinstance(args_payload, dict):
                    args_payload = {}
                command = self._tool_invocation_command(tool_name, args_payload)
                result = self._route_internal_with_input(
                    command,
                    initial_output=current_output,
                    initial_data=current_data,
                    initial_type=current_type,
                )
                step_trace.append(
                    {
                        "index": index,
                        "tool": tool_name,
                        "args": args_payload,
                        "output": result.output.strip(),
                        "error": result.error or "",
                    }
                )
                if result.error:
                    failure = {
                        "phase": "execution",
                        "step_index": index,
                        "step": step,
                        "error": result.error,
                        "pipeline": pipeline or self._compose_plan_pipeline(steps),
                    }
                    attempts.append({"attempt": attempt + 1, "status": "execution_failed", "failure": failure, "steps": step_trace})
                    if attempt >= max_replans:
                        return CommandResult(output="", error=result.error)
                    repaired = self._repair_plan_after_failure(prompt, current_payload, failure, attempt + 1)
                    if repaired is None:
                        return CommandResult(output="", error=result.error)
                    current_payload = repaired
                    failed = True
                    break
                current_output = result.output
                current_data = result.data
                current_type = result.data_type
            if failed:
                continue
            final_payload = dict(current_payload)
            final_payload["attempts"] = attempts + [{"attempt": attempt + 1, "status": "ok", "steps": step_trace}]
            final_payload["execution"] = {
                "output": current_output.strip(),
                "data_type": current_type.value if isinstance(current_type, PipelineType) else str(current_type),
            }
            return CommandResult(output=current_output, data=final_payload, data_type=PipelineType.OBJECT)
        return CommandResult(output="", error="plan execution failed")

    def _run_memory(self, args: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: memory embed|search|list|namespace|project|status ...")
        action = parts[0]

        if action == "namespace":
            if len(parts) == 1:
                payload = self._memory_scope_payload()
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            self.current_memory_namespace = parts[1].strip() or "default"
            payload = self._memory_scope_payload()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "project":
            if len(parts) == 1:
                payload = self._memory_scope_payload()
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            self.current_memory_project = parts[1].strip() or "default"
            payload = self._memory_scope_payload()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "status":
            payload = self._memory_scope_payload()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "embed":
            entry_id = ""
            file_path_text = ""
            metadata: dict[str, Any] = {}
            scope_options, text_tokens = self._parse_memory_scope_args(parts, start_index=1)
            namespace, project = self._resolve_memory_scope(scope_options["namespace"], scope_options["project"], all_scopes=bool(scope_options["all_scopes"]))
            i = 1
            text_tokens = []
            while i < len(parts):
                token = parts[i]
                if token in {"--id", "--key"} and i + 1 < len(parts):
                    entry_id = parts[i + 1]
                    i += 2
                    continue
                if token == "--file" and i + 1 < len(parts):
                    file_path_text = parts[i + 1]
                    i += 2
                    continue
                if token == "--meta" and i + 1 < len(parts):
                    parsed_meta, error = self._parse_json_object_arg(parts[i + 1], field_name="memory metadata")
                    if error is not None:
                        return error
                    metadata = parsed_meta or {}
                    i += 2
                    continue
                if token in {"--namespace", "--project", "--limit"} and i + 1 < len(parts):
                    i += 2
                    continue
                if token == "--all":
                    i += 1
                    continue
                text_tokens.append(token)
                i += 1
            text = " ".join(text_tokens).strip()
            if file_path_text:
                file_path = self._resolve_path(file_path_text)
                if not file_path.exists() or not file_path.is_file():
                    return CommandResult(output="", error=f"memory file not found: {file_path_text}")
                text = self._load_ai_file_context(file_path)
                metadata.setdefault("source_file", str(file_path))
            elif not text and pipeline_data is not None:
                text = self._serialize_ai_context_value(pipeline_data)
            elif not text:
                text = pipeline_input.strip()
            if not text:
                return CommandResult(output="", error="usage: memory embed [--id name] [--namespace n] [--project p] [--file path] [--meta json] <text>")
            entry = self.memory.embed(
                text,
                entry_id=entry_id or None,
                metadata=metadata,
                namespace=namespace or "default",
                project=project or "default",
            )
            payload = {
                "id": entry.entry_id,
                "namespace": entry.namespace,
                "project": entry.project,
                "dimensions": len(entry.vector),
                "metadata": entry.metadata,
                "text_preview": entry.text[:200],
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "search":
            scope_options, query_tokens = self._parse_memory_scope_args(parts, start_index=1)
            limit = int(scope_options["limit"] or 5)
            namespace, project = self._resolve_memory_scope(scope_options["namespace"], scope_options["project"], all_scopes=bool(scope_options["all_scopes"]))
            query = " ".join(query_tokens).strip() or pipeline_input.strip()
            if not query:
                return CommandResult(output="", error="usage: memory search [--namespace n] [--project p] [--all] [--limit n] <query>")
            payload = self.memory.search(query, limit=limit, namespace=namespace, project=project)
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "list":
            scope_options, _ = self._parse_memory_scope_args(parts, start_index=1)
            namespace, project = self._resolve_memory_scope(scope_options["namespace"], scope_options["project"], all_scopes=bool(scope_options["all_scopes"]))
            payload = self.memory.list_entries(namespace=namespace, project=project)
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        return CommandResult(output="", error="usage: memory embed|search|list|namespace|project|status ...")

    def _run_atheria(self, args: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: atheria status|init|sensor|train|search|chat ...")

        action = parts[0]

        if action == "status":
            payload = self.atheria.status_payload()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "init":
            if not self.atheria.is_available():
                return CommandResult(output="", error="atheria source folder not found")
            try:
                self.atheria._ensure_core()
            except Exception as exc:
                return CommandResult(output="", error=f"atheria init failed: {exc}")
            payload = self.atheria.status_payload()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "sensor":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: atheria sensor load|map|list|show|run ...")
            sensor_action = parts[1]
            if sensor_action == "list":
                payload = self.atheria_sensors.list_plugins()
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if sensor_action == "show":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: atheria sensor show <name>")
                spec = next((item for item in self.atheria_sensors.list_plugins() if item["name"] == parts[2]), None)
                if spec is None:
                    return CommandResult(output="", error="atheria sensor not found")
                return CommandResult(output=json.dumps(spec, ensure_ascii=False) + "\n", data=spec, data_type=PipelineType.OBJECT)
            if sensor_action == "load":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: atheria sensor load <file.py> [--name name] [--mapping json|file]")
                path = self._resolve_path(parts[2])
                name = ""
                mapping: dict[str, str] = {}
                i = 3
                while i < len(parts):
                    token = parts[i]
                    if token == "--name" and i + 1 < len(parts):
                        name = parts[i + 1]
                        i += 2
                        continue
                    if token == "--mapping" and i + 1 < len(parts):
                        mapping_source = parts[i + 1]
                        candidate = self._resolve_path(mapping_source)
                        try:
                            loaded = self._load_structured_payload(candidate.read_text(encoding="utf-8")) if candidate.exists() else self._load_structured_payload(mapping_source)
                        except Exception as exc:
                            return CommandResult(output="", error=f"invalid sensor mapping: {exc}")
                        if not isinstance(loaded, dict):
                            return CommandResult(output="", error="sensor mapping must be an object")
                        mapping = {str(key): str(value) for key, value in loaded.items()}
                        i += 2
                        continue
                    i += 1
                try:
                    spec = self.atheria_sensors.register(path, name=name or None, mapping=mapping or None)
                except Exception as exc:
                    return CommandResult(output="", error=str(exc))
                payload = {
                    "name": spec.name,
                    "path": spec.path,
                    "mapping": spec.mapping,
                    "description": spec.description,
                }
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if sensor_action == "map":
                if len(parts) < 4:
                    return CommandResult(output="", error="usage: atheria sensor map <name> <mapping.json|yaml|json>")
                name = parts[2]
                mapping_source = parts[3]
                candidate = self._resolve_path(mapping_source)
                try:
                    loaded = self._load_structured_payload(candidate.read_text(encoding="utf-8")) if candidate.exists() else self._load_structured_payload(mapping_source)
                except Exception as exc:
                    return CommandResult(output="", error=f"invalid sensor mapping: {exc}")
                if not isinstance(loaded, dict):
                    return CommandResult(output="", error="sensor mapping must be an object")
                try:
                    spec = self.atheria_sensors.set_mapping(name, {str(key): str(value) for key, value in loaded.items()})
                except KeyError:
                    return CommandResult(output="", error="atheria sensor not found")
                payload = {"name": spec.name, "mapping": spec.mapping}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if sensor_action == "run":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: atheria sensor run <name> [--input json] [--file payload.json] [--train] [--namespace n] [--project p] [--category name]")
                name = parts[2]
                input_json = ""
                file_path_text = ""
                namespace = self.current_memory_namespace
                project = self.current_memory_project
                category = ""
                train = False
                i = 3
                while i < len(parts):
                    token = parts[i]
                    if token == "--input" and i + 1 < len(parts):
                        input_json = parts[i + 1]
                        i += 2
                        continue
                    if token == "--file" and i + 1 < len(parts):
                        file_path_text = parts[i + 1]
                        i += 2
                        continue
                    if token == "--namespace" and i + 1 < len(parts):
                        namespace = parts[i + 1]
                        i += 2
                        continue
                    if token == "--project" and i + 1 < len(parts):
                        project = parts[i + 1]
                        i += 2
                        continue
                    if token == "--category" and i + 1 < len(parts):
                        category = parts[i + 1]
                        i += 2
                        continue
                    if token == "--train":
                        train = True
                        i += 1
                        continue
                    i += 1
                payload_source: Any = pipeline_data
                if file_path_text:
                    payload_file = self._resolve_path(file_path_text)
                    if not payload_file.exists() or not payload_file.is_file():
                        return CommandResult(output="", error=f"sensor payload file not found: {file_path_text}")
                    try:
                        payload_source = self._load_structured_payload(payload_file.read_text(encoding="utf-8"))
                    except Exception as exc:
                        return CommandResult(output="", error=f"failed to parse sensor payload file: {exc}")
                elif input_json:
                    try:
                        payload_source = self._load_structured_payload(input_json)
                    except Exception as exc:
                        return CommandResult(output="", error=str(exc))
                elif payload_source is None and pipeline_input.strip():
                    with contextlib.suppress(Exception):
                        payload_source = self._load_structured_payload(pipeline_input)
                if payload_source is None:
                    payload_source = {}
                try:
                    event_payload = self.atheria_sensors.run(name, payload_source)
                except KeyError:
                    return CommandResult(output="", error="atheria sensor not found")
                except Exception as exc:
                    return CommandResult(output="", error=f"sensor run failed: {exc}")
                resonance_query = event_payload["summary"] + "\n\n" + json.dumps(event_payload.get("features", {}), ensure_ascii=False)
                atheria_hits = self.atheria.search_training(resonance_query, limit=3)
                memory_hits = self._memory_context_hits(resonance_query, limit=3)
                top_atheria = float(atheria_hits[0]["score"]) if atheria_hits else 0.0
                top_memory = float(memory_hits[0]["score"]) if memory_hits else 0.0
                event_payload["score"] = round(max(top_atheria, top_memory), 6)
                event_payload["resonance"] = {
                    "atheria_hits": atheria_hits,
                    "memory_hits": memory_hits,
                    "top_source": "atheria" if top_atheria >= top_memory else "memory",
                    "top_category": str(atheria_hits[0]["category"]) if atheria_hits else "",
                }
                if train:
                    text = event_payload["summary"] + "\n\n" + json.dumps(event_payload, ensure_ascii=False, indent=2)
                    memory_entry = self.memory.embed(
                        text,
                        metadata={"sensor_name": name, "sensor_event_id": event_payload["event_id"]},
                        namespace=namespace,
                        project=project,
                    )
                    inserted = self.atheria.train_rows(
                        [
                            (
                                f"{name} sensor event {event_payload['event_id']}",
                                category or f"sensor:{name}",
                                text,
                            )
                        ]
                    )
                    event_payload["memory_id"] = memory_entry.entry_id
                    event_payload["trained_records"] = inserted
                return CommandResult(output=json.dumps(event_payload, ensure_ascii=False) + "\n", data=event_payload, data_type=PipelineType.OBJECT)
            return CommandResult(output="", error="usage: atheria sensor load|map|list|show|run ...")

        if action == "search":
            query = " ".join(parts[1:]).strip()
            if not query and pipeline_data is not None:
                query = self._serialize_ai_context_value(pipeline_data)
            if not query:
                query = pipeline_input.strip()
            if not query:
                return CommandResult(output="", error="usage: atheria search <query>")
            payload = self.atheria.search_training(query)
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "train":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: atheria train qa|json|csv|file|memory ...")
            train_action = parts[1]

            if train_action == "qa":
                question = ""
                answer = ""
                category = "general"
                i = 2
                while i < len(parts):
                    token = parts[i]
                    if token == "--question" and i + 1 < len(parts):
                        question = parts[i + 1]
                        i += 2
                        continue
                    if token == "--answer" and i + 1 < len(parts):
                        answer = parts[i + 1]
                        i += 2
                        continue
                    if token == "--category" and i + 1 < len(parts):
                        category = parts[i + 1]
                        i += 2
                        continue
                    i += 1
                if not question or not answer:
                    return CommandResult(output="", error="usage: atheria train qa --question text --answer text [--category name]")
                inserted = self.atheria.train_qa(question=question, answer=answer, category=category)
                payload = {"mode": "qa", "inserted": inserted, "category": category}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

            if train_action in {"json", "csv"}:
                if len(parts) < 3:
                    return CommandResult(output="", error=f"usage: atheria train {train_action} <file>")
                file_path = self._resolve_path(parts[2])
                if not file_path.exists() or not file_path.is_file():
                    return CommandResult(output="", error=f"atheria training file not found: {parts[2]}")
                try:
                    inserted = self.atheria.train_json_file(file_path) if train_action == "json" else self.atheria.train_csv_file(file_path)
                except Exception as exc:
                    return CommandResult(output="", error=f"atheria training failed: {exc}")
                payload = {"mode": train_action, "file": str(file_path), "inserted": inserted}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

            if train_action == "file":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: atheria train file <file> [--category name]")
                category = ""
                file_token = parts[2]
                i = 3
                while i < len(parts):
                    token = parts[i]
                    if token == "--category" and i + 1 < len(parts):
                        category = parts[i + 1]
                        i += 2
                        continue
                    i += 1
                file_path = self._resolve_path(file_token)
                if not file_path.exists() or not file_path.is_file():
                    return CommandResult(output="", error=f"atheria training file not found: {file_token}")
                suffix = file_path.suffix.lower()
                try:
                    if suffix == ".json":
                        inserted = self.atheria.train_json_file(file_path)
                    elif suffix == ".csv":
                        inserted = self.atheria.train_csv_file(file_path)
                    else:
                        inserted = self.atheria.train_text_file(file_path, category=category)
                except Exception as exc:
                    return CommandResult(output="", error=f"atheria training failed: {exc}")
                payload = {"mode": "file", "file": str(file_path), "category": category or file_path.stem or "document", "inserted": inserted}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

            if train_action == "memory":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: atheria train memory <memory_id> [--category name]")
                memory_id = parts[2]
                category = ""
                i = 3
                while i < len(parts):
                    token = parts[i]
                    if token == "--category" and i + 1 < len(parts):
                        category = parts[i + 1]
                        i += 2
                        continue
                    i += 1
                entry = self.memory.get_entry(memory_id)
                if entry is None:
                    return CommandResult(output="", error=f"memory entry not found: {memory_id}")
                source_file = str(entry.metadata.get("source_file") or "").strip()
                try:
                    if source_file:
                        source_path = Path(source_file)
                        if source_path.exists() and source_path.is_file():
                            suffix = source_path.suffix.lower()
                            if suffix == ".json":
                                inserted = self.atheria.train_json_file(source_path)
                            elif suffix == ".csv":
                                inserted = self.atheria.train_csv_file(source_path)
                            else:
                                inserted = self.atheria.train_text_file(source_path, category=category)
                            payload = {
                                "mode": "memory",
                                "memory_id": memory_id,
                                "source_file": str(source_path),
                                "category": category or source_path.stem or entry.project,
                                "inserted": inserted,
                            }
                            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
                    effective_category = category.strip() or str(entry.metadata.get("category") or "").strip() or entry.project or entry.namespace or "memory"
                    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", entry.text) if chunk.strip()]
                    if not chunks and entry.text.strip():
                        chunks = [entry.text.strip()]
                    rows = [
                        (f"{memory_id} segment {index}", effective_category, chunk)
                        for index, chunk in enumerate(chunks, start=1)
                    ]
                    inserted = self.atheria.train_rows(rows)
                except Exception as exc:
                    return CommandResult(output="", error=f"atheria training failed: {exc}")
                payload = {"mode": "memory", "memory_id": memory_id, "category": effective_category, "inserted": inserted}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

            return CommandResult(output="", error="usage: atheria train qa|json|csv|file|memory ...")

        if action == "chat":
            file_path_text = ""
            system_prompt = ""
            prompt_tokens: list[str] = []
            i = 1
            while i < len(parts):
                token = parts[i]
                if token == "--file" and i + 1 < len(parts):
                    file_path_text = parts[i + 1]
                    i += 2
                    continue
                if token == "--system" and i + 1 < len(parts):
                    system_prompt = parts[i + 1]
                    i += 2
                    continue
                prompt_tokens.append(token)
                i += 1
            prompt = " ".join(prompt_tokens).strip()
            if not prompt:
                return CommandResult(output="", error="usage: atheria chat [--file path] [--system text] <prompt>")
            enriched_prompt, context_error = self._build_ai_prompt_with_context(
                prompt,
                pipeline_input=pipeline_input,
                pipeline_data=pipeline_data,
                file_path_text=file_path_text or None,
            )
            if context_error is not None:
                return context_error
            return self.ai_runtime.complete_prompt(
                enriched_prompt,
                provider="atheria",
                model=self.ai_runtime.get_active_model("atheria") or "atheria-core",
                system_prompt=system_prompt,
            )

        return CommandResult(output="", error="usage: atheria status|init|sensor|train|search|chat ...")

    def _run_tool(self, args: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: tool register|call|list|show ...")
        action = parts[0]

        if action == "list":
            payload = self._tool_catalog_rows()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "show":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: tool show <name>")
            tool = self.tools.get(parts[1])
            if tool is None:
                return CommandResult(output="", error="tool not found")
            payload = {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.schema,
                "pipeline_template": tool.pipeline_template,
                "created_at": tool.created_at,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "register":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: tool register <name> --description text --schema json --pipeline template")
            name = parts[1]
            description = ""
            schema: dict[str, Any] = {}
            pipeline_template = ""
            i = 2
            while i < len(parts):
                token = parts[i]
                if token == "--description" and i + 1 < len(parts):
                    description = parts[i + 1]
                    i += 2
                    continue
                if token == "--schema" and i + 1 < len(parts):
                    parsed_schema, error = self._parse_json_object_arg(parts[i + 1], field_name="tool schema")
                    if error is not None:
                        return error
                    schema = parsed_schema or {}
                    i += 2
                    continue
                if token == "--schema-file" and i + 1 < len(parts):
                    schema_path = self._resolve_path(parts[i + 1])
                    if not schema_path.exists() or not schema_path.is_file():
                        return CommandResult(output="", error=f"tool schema file not found: {parts[i + 1]}")
                    parsed_schema, error = self._parse_json_object_arg(schema_path.read_text(encoding="utf-8"), field_name="tool schema")
                    if error is not None:
                        return error
                    schema = parsed_schema or {}
                    i += 2
                    continue
                if token == "--pipeline" and i + 1 < len(parts):
                    pipeline_template = parts[i + 1]
                    i += 2
                    continue
                i += 1
            if not pipeline_template:
                return CommandResult(output="", error="tool pipeline template must not be empty")
            validation_error = self._validate_tool_payload(schema, {})
            if validation_error and not validation_error.startswith("missing required tool argument"):
                return CommandResult(output="", error=validation_error)
            tool = ToolSchemaDefinition(name=name, description=description, schema=schema, pipeline_template=pipeline_template)
            self.tools[name] = tool
            payload = {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.schema,
                "pipeline_template": tool.pipeline_template,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "call":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: tool call <name> [json|key=value ...]")
            tool = self.tools.get(parts[1])
            if tool is None:
                return CommandResult(output="", error="tool not found")
            payload, error = self._parse_tool_call_payload(args.split(parts[1], 1)[1].strip())
            if error is not None:
                return error
            payload = payload or {}
            if pipeline_data is not None and "_" not in payload:
                payload["_"] = pipeline_data
            elif pipeline_input.strip() and "_" not in payload:
                payload["_"] = pipeline_input.strip()
            validation_error = self._validate_tool_payload(tool.schema, payload)
            if validation_error:
                return CommandResult(output="", error=validation_error)
            rendered_pipeline, render_error = self._render_tool_pipeline(tool.pipeline_template, payload)
            if render_error is not None:
                return render_error
            assert rendered_pipeline is not None
            result = self._route_internal_with_input(
                rendered_pipeline,
                initial_output=pipeline_input,
                initial_data=pipeline_data,
                initial_type=self._pipeline_type_from_value(pipeline_data if pipeline_data is not None else pipeline_input),
            )
            if result.error:
                return result
            return CommandResult(output=result.output, data=result.data, data_type=result.data_type)

        return CommandResult(output="", error="usage: tool register|call|list|show ...")

    def _heuristic_ai_plan(self, prompt: str) -> CommandResult:
        lowered = prompt.lower()
        tool_candidates = self._planner_tool_candidates(prompt)
        memory_hits = self._memory_context_hits(prompt, limit=3)
        csv_goal = self._extract_csv_goal(prompt)
        if csv_goal and any(keyword in lowered for keyword in ["average", "mean"]):
            filename, column = csv_goal
            steps = [
                {"tool": "csv_load", "args": {"file": filename}},
                {"tool": "table_mean", "args": {"column": column}},
            ]
            suggestion = self._compose_plan_pipeline(steps)
            payload = {
                "pipeline": suggestion,
                "steps": steps,
                "mode": "heuristic-tool-graph",
                "summary": f"load {filename} and compute mean for {column}",
                "tools": ["csv_load", "table_mean"],
                "agents": [],
                "memory_ids": [item["id"] for item in memory_hits],
            }
            return CommandResult(output=f"{suggestion}\n", data=payload, data_type=PipelineType.OBJECT)
        if csv_goal and any(keyword in lowered for keyword in ["summarize", "summary", "describe"]):
            filename, _ = csv_goal
            steps = [{"tool": "dataset_summarize", "args": {"file": filename}}]
            suggestion = self._compose_plan_pipeline(steps)
            payload = {
                "pipeline": suggestion,
                "steps": steps,
                "mode": "heuristic-tool-graph",
                "summary": f"summarize dataset {filename}",
                "tools": ["dataset_summarize"],
                "agents": [],
                "memory_ids": [item["id"] for item in memory_hits],
            }
            return CommandResult(output=f"{suggestion}\n", data=payload, data_type=PipelineType.OBJECT)
        if tool_candidates:
            steps = [{"tool": tool_candidates[0].name, "args": {}}]
            suggestion = self._compose_plan_pipeline(steps)
            payload = {
                "pipeline": suggestion,
                "steps": steps,
                "mode": "heuristic-tool",
                "summary": f"use registered tool {tool_candidates[0].name}",
                "tools": [tool.name for tool in tool_candidates],
                "agents": [],
                "memory_ids": [item["id"] for item in memory_hits],
            }
            return CommandResult(output=f"{suggestion}\n", data=payload, data_type=PipelineType.OBJECT)
        if "csv" in lowered and "average" in lowered:
            suggestion = "data load file.csv | py sum(float(r['A']) for r in _) / len(_)"
        elif "anomal" in lowered or "error" in lowered:
            suggestion = "watch logs.txt --follow-seconds 10 | py _.lower()"
        elif "event" in lowered or "trigger" in lowered:
            suggestion = "event on task_created 'py _.upper()'"
        elif "workflow" in lowered and self.agents:
            first_agents = ",".join(list(self.agents.keys())[:2])
            suggestion = f"agent workflow --agents {first_agents} --input {shlex.quote(prompt)}" if first_agents else "py # TODO: generated workflow"
        else:
            suggestion = "py # TODO: generated pipeline"
        payload = {
            "pipeline": suggestion,
            "steps": [],
            "mode": "heuristic",
            "summary": "fallback heuristic plan",
            "tools": [],
            "agents": [],
            "memory_ids": [item["id"] for item in memory_hits],
        }
        return CommandResult(output=f"{suggestion}\n", data=payload, data_type=PipelineType.OBJECT)

    def _ai_prompt_needs_data_context(self, prompt: str) -> bool:
        lowered = prompt.lower()
        keywords = [
            "dataset",
            "csv",
            "table",
            "dataframe",
            "rows",
            "columns",
            "summarize this data",
            "summarize this dataset",
            "analyze this data",
            "describe this dataset",
        ]
        return any(keyword in lowered for keyword in keywords)

    def _serialize_ai_context_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            preview = value[:5]
            payload = {"type": "list", "count": len(value), "preview": preview}
            return json.dumps(payload, ensure_ascii=False, indent=2)
        if isinstance(value, dict):
            payload = {"type": "object", "keys": list(value.keys())[:20], "preview": value}
            return json.dumps(payload, ensure_ascii=False, indent=2)
        if hasattr(value, "num_rows") and hasattr(value, "column_names"):
            preview_rows: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                preview_rows = value.slice(0, min(5, int(value.num_rows))).to_pylist()  # type: ignore[attr-defined]
            payload = {
                "type": "arrow_table",
                "rows": int(getattr(value, "num_rows", 0)),
                "columns": list(getattr(value, "column_names", [])),
                "preview": preview_rows,
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
        text = str(value)
        return text[:4000]

    def _load_ai_file_context(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            with file_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = []
                for index, row in enumerate(reader):
                    rows.append(row)
                    if index >= 4:
                        break
            payload = {"type": "csv", "path": str(file_path), "preview_rows": rows}
            return json.dumps(payload, ensure_ascii=False, indent=2)
        if suffix == ".json":
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            return self._serialize_ai_context_value(payload)
        text = file_path.read_text(encoding="utf-8")
        payload = {"type": "text", "path": str(file_path), "preview": text[:4000]}
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_ai_prompt_with_context(
        self,
        prompt: str,
        *,
        pipeline_input: str,
        pipeline_data: Any,
        file_path_text: str | None = None,
    ) -> tuple[str, CommandResult | None]:
        contexts: list[str] = []

        if file_path_text:
            try:
                file_path = self._resolve_path(file_path_text)
                if not file_path.exists() or not file_path.is_file():
                    return "", CommandResult(output="", error=f"ai context file not found: {file_path_text}")
                contexts.append("File context:\n" + self._load_ai_file_context(file_path))
            except Exception as exc:
                return "", CommandResult(output="", error=f"failed to read ai context file: {exc}")

        if pipeline_data is not None:
            serialized = self._serialize_ai_context_value(pipeline_data)
            if serialized:
                contexts.append("Pipeline data:\n" + serialized)
        elif pipeline_input.strip():
            contexts.append("Pipeline text:\n" + pipeline_input[:4000])

        if not contexts:
            return prompt, None

        enriched_prompt = prompt.strip() + "\n\nNova-shell context:\n" + "\n\n".join(contexts)
        return enriched_prompt, None

    def _load_agent_locked_file_context(self, file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="utf-8", errors="replace")

    def _resolve_agent_memory_context(self, memory_id: str) -> tuple[str, CommandResult | None]:
        entry = self.memory.get_entry(memory_id)
        if entry is None:
            return "", CommandResult(output="", error=f"memory entry not found: {memory_id}")
        source_file = str(entry.metadata.get("source_file") or "").strip()
        if source_file:
            try:
                source_path = Path(source_file)
                if source_path.exists() and source_path.is_file():
                    return self._load_agent_locked_file_context(source_path), None
            except Exception as exc:
                return "", CommandResult(output="", error=f"failed to read memory source file for {memory_id}: {exc}")
        return entry.text, None

    def _parse_agent_context_args(self, parts: list[str], *, start_index: int = 0) -> tuple[dict[str, Any], list[str]]:
        file_path_text = ""
        memory_ids: list[str] = []
        remaining: list[str] = []
        i = start_index
        while i < len(parts):
            token = parts[i]
            if token == "--file" and i + 1 < len(parts):
                file_path_text = parts[i + 1]
                i += 2
                continue
            if token == "--memory" and i + 1 < len(parts):
                memory_ids.append(parts[i + 1])
                i += 2
                continue
            remaining.append(token)
            i += 1
        return {"file_path_text": file_path_text, "memory_ids": memory_ids}, remaining

    def _build_agent_input_with_context(
        self,
        input_text: str,
        *,
        file_path_text: str = "",
        memory_ids: list[str] | None = None,
    ) -> tuple[str, CommandResult | None]:
        context_blocks: list[str] = []
        if file_path_text:
            try:
                file_path = self._resolve_path(file_path_text)
                if not file_path.exists() or not file_path.is_file():
                    return "", CommandResult(output="", error=f"agent context file not found: {file_path_text}")
                context_blocks.append(f"[File:{file_path.name}]\n" + self._load_agent_locked_file_context(file_path))
            except Exception as exc:
                return "", CommandResult(output="", error=f"failed to read agent context file: {exc}")
        for memory_id in memory_ids or []:
            memory_text, error = self._resolve_agent_memory_context(memory_id)
            if error is not None:
                return "", error
            context_blocks.append(f"[Memory:{memory_id}]\n" + memory_text)
        if not context_blocks:
            return input_text, None
        base_input = input_text.strip()
        enriched_parts = []
        if base_input:
            enriched_parts.append(base_input)
        enriched_parts.append(
            "Nova-shell locked context:\n"
            "Use the following source blocks as the authoritative context for this task.\n"
            "When asked for exact wording, quote only from these blocks."
        )
        enriched_parts.extend(context_blocks)
        return "\n\n".join(enriched_parts), None

    def _run_ai(self, args: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: ai providers|models [provider]|use <provider> [model]|config|env reload [file]|plan <prompt>|prompt <prompt>|<prompt>")

        action = parts[0]
        if action == "providers":
            payload = self.ai_runtime.list_providers()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "models":
            provider = parts[1] if len(parts) > 1 else None
            return self.ai_runtime.list_models(provider)
        if action == "use":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: ai use <provider> [model]")
            model = parts[2] if len(parts) > 2 else None
            return self.ai_runtime.use_provider(parts[1], model)
        if action == "config":
            payload = self.ai_runtime.config_payload()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "env":
            if len(parts) < 2 or parts[1] != "reload":
                return CommandResult(output="", error="usage: ai env reload [file]")
            path_text = parts[2] if len(parts) > 2 else None
            files = self.ai_runtime.reload_env(path_text)
            payload = {"loaded_env_files": files}
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "plan":
            run_plan = False
            max_replans = 1
            prompt_tokens: list[str] = []
            i = 1
            while i < len(parts):
                token = parts[i]
                if token == "--run":
                    run_plan = True
                    i += 1
                    continue
                if token == "--retries" and i + 1 < len(parts):
                    with contextlib.suppress(Exception):
                        max_replans = max(0, int(parts[i + 1]))
                    i += 2
                    continue
                prompt_tokens.append(token)
                i += 1
            prompt = " ".join(prompt_tokens).strip().strip('"')
            if not prompt:
                return CommandResult(output="", error="usage: ai plan [--run] [--retries n] <prompt>")
            if self.ai_runtime.get_active_provider():
                provider_plan = self._provider_ai_plan(prompt)
                if provider_plan.error is None:
                    plan_result = provider_plan
                else:
                    plan_result = self._heuristic_ai_plan(prompt)
            else:
                plan_result = self._heuristic_ai_plan(prompt)
            if not run_plan or plan_result.error:
                return plan_result
            plan_payload = dict(plan_result.data) if isinstance(plan_result.data, dict) else {"pipeline": plan_result.output.strip()}
            return self._execute_plan_payload(prompt, plan_payload, max_replans=max_replans)
        if action == "prompt":
            file_path_text: str | None = None
            prompt_tokens: list[str] = []
            i = 1
            while i < len(parts):
                token = parts[i]
                if token == "--file" and i + 1 < len(parts):
                    file_path_text = parts[i + 1]
                    i += 2
                    continue
                prompt_tokens.append(token)
                i += 1
            prompt = " ".join(prompt_tokens).strip().strip('"')
            if not prompt:
                return CommandResult(output="", error="usage: ai prompt [--file path] <prompt>")
            enriched_prompt, context_error = self._build_ai_prompt_with_context(
                prompt,
                pipeline_input=pipeline_input,
                pipeline_data=pipeline_data,
                file_path_text=file_path_text,
            )
            if context_error is not None:
                return context_error
            if enriched_prompt == prompt and self._ai_prompt_needs_data_context(prompt):
                return CommandResult(
                    output="",
                    error='dataset context missing. use `data load file.csv | ai prompt "Summarize this dataset"` or `ai prompt --file file.csv "Summarize this dataset"`',
                )
            return self.ai_runtime.complete_prompt(enriched_prompt)

        prompt = args.strip().strip('"')
        if not prompt:
            return CommandResult(output="", error="usage: ai <prompt>")
        active_provider = self.ai_runtime.get_active_provider()
        if active_provider:
            provider_result = self.ai_runtime.complete_prompt(prompt)
            if provider_result.error is None:
                return provider_result
        return self._heuristic_ai_plan(prompt)

    def _render_prompt_template(self, prompt_template: str, input_text: str) -> str:
        if "{{input}}" in prompt_template:
            return prompt_template.replace("{{input}}", input_text)
        if "{input}" in prompt_template:
            try:
                return prompt_template.format(input=input_text)
            except Exception:
                pass
        suffix = f"\n\nInput:\n{input_text}" if input_text else ""
        return prompt_template + suffix

    def _render_agent_prompt(self, agent: AIAgentDefinition, input_text: str) -> str:
        return self._render_prompt_template(agent.prompt_template, input_text)

    def _run_agent_once(self, agent: AIAgentDefinition, input_text: str) -> CommandResult:
        prompt = self._render_agent_prompt(agent, input_text)
        result = self.ai_runtime.complete_prompt(
            prompt,
            provider=agent.provider,
            model=agent.model,
            system_prompt=agent.system_prompt,
        )
        if result.error:
            return result
        payload = {
            "agent": agent.name,
            "provider": agent.provider,
            "model": agent.model,
            "prompt": prompt,
            "response": result.output.strip(),
        }
        return CommandResult(output=result.output, data=payload, data_type=PipelineType.OBJECT)

    def _run_agent_instance_message(self, instance: AgentRuntimeInstance, message: str) -> CommandResult:
        instance.history.append({"role": "user", "content": message})
        prompt = self._render_prompt_template(instance.prompt_template, message)
        if instance.history:
            transcript = "\n".join(f"{item['role']}: {item['content']}" for item in instance.history[-12:])
            prompt = prompt.strip() + "\n\nConversation history:\n" + transcript
        result = self.ai_runtime.complete_prompt(
            prompt,
            provider=instance.provider,
            model=instance.model,
            system_prompt=instance.system_prompt,
        )
        if result.error:
            return result
        reply = result.output.strip()
        instance.history.append({"role": "assistant", "content": reply})
        payload = {
            "agent": instance.name,
            "provider": instance.provider,
            "model": instance.model,
            "message": message,
            "response": reply,
            "history_length": len(instance.history),
            "source_agent": instance.source_agent,
        }
        return CommandResult(output=result.output, data=payload, data_type=PipelineType.OBJECT)

    def _run_agent(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: agent create|run|show|list|spawn|message|workflow|graph ...")

        action = parts[0]
        if action == "graph":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: agent graph create|show|list|run ...")
            graph_action = parts[1]
            if graph_action == "list":
                payload = [
                    {"name": graph.name, "nodes": graph.nodes, "edges": graph.edges, "created_at": graph.created_at}
                    for graph in self.agent_graphs.values()
                ]
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if graph_action == "show":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: agent graph show <name>")
                graph = self.agent_graphs.get(parts[2])
                if graph is None:
                    return CommandResult(output="", error="agent graph not found")
                payload = {"name": graph.name, "nodes": graph.nodes, "edges": graph.edges, "created_at": graph.created_at}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if graph_action == "create":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: agent graph create <name> --nodes a,b[,c] [--edges a>b,b>c]")
                name = parts[2]
                nodes: list[str] = []
                edges_text = ""
                i = 3
                while i < len(parts):
                    token = parts[i]
                    if token == "--nodes" and i + 1 < len(parts):
                        nodes = [node.strip() for node in parts[i + 1].split(",") if node.strip()]
                        i += 2
                        continue
                    if token == "--edges" and i + 1 < len(parts):
                        edges_text = parts[i + 1]
                        i += 2
                        continue
                    i += 1
                if not nodes:
                    return CommandResult(output="", error="agent graph requires --nodes a,b[,c]")
                edges = self._parse_agent_graph_edges(edges_text, nodes)
                graph = AgentGraphDefinition(name=name, nodes=nodes, edges=edges)
                try:
                    self._topological_agent_graph(graph)
                except Exception as exc:
                    return CommandResult(output="", error=str(exc))
                self.agent_graphs[name] = graph
                payload = {"name": graph.name, "nodes": graph.nodes, "edges": graph.edges}
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            if graph_action == "run":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: agent graph run <name> [--swarm] [--file path] [--memory id]... --input text")
                graph = self.agent_graphs.get(parts[2])
                if graph is None:
                    return CommandResult(output="", error="agent graph not found")
                input_text = ""
                swarm = False
                context_options, graph_tokens = self._parse_agent_context_args(parts, start_index=3)
                i = 0
                while i < len(graph_tokens):
                    token = graph_tokens[i]
                    if token == "--swarm":
                        swarm = True
                        i += 1
                        continue
                    if token == "--input" and i + 1 < len(graph_tokens):
                        input_text = graph_tokens[i + 1]
                        i += 2
                        continue
                    i += 1
                if not input_text:
                    return CommandResult(output="", error="agent graph run requires --input text")
                enriched_input, error = self._build_agent_input_with_context(
                    input_text,
                    file_path_text=str(context_options["file_path_text"] or ""),
                    memory_ids=list(context_options["memory_ids"] or []),
                )
                if error is not None:
                    return error
                ordered = self._topological_agent_graph(graph)
                inbound: dict[str, list[str]] = {node: [] for node in graph.nodes}
                for left, right in graph.edges:
                    inbound[right].append(left)
                node_outputs: dict[str, str] = {}
                steps: list[dict[str, Any]] = []
                assignments: list[dict[str, Any]] = []
                execution_id = uuid.uuid4().hex[:10]
                for index, node in enumerate(ordered):
                    incoming = inbound.get(node, [])
                    node_input = enriched_input if not incoming else "\n\n".join(node_outputs[source] for source in incoming if source in node_outputs)
                    if swarm:
                        result, assignment = self._run_agent_handle_swarm(
                            node,
                            node_input,
                            execution_id=execution_id,
                            step_kind="agent-graph",
                            step_index=index,
                        )
                        assignments.append(assignment)
                    else:
                        result = self._run_agent_handle(node, node_input)
                    if result.error:
                        return result
                    output_text = result.output.strip()
                    node_outputs[node] = output_text
                    steps.append({"node": node, "input": node_input, "output": output_text})
                sinks = [node for node in graph.nodes if all(left != node for left, _ in graph.edges)]
                final_output = "\n\n".join(node_outputs.get(node, "") for node in sinks if node_outputs.get(node, ""))
                payload = {
                    "name": graph.name,
                    "nodes": graph.nodes,
                    "edges": graph.edges,
                    "steps": steps,
                    "final_output": final_output,
                    "swarm": swarm,
                    "execution_id": execution_id,
                    "assignments": assignments,
                }
                return CommandResult(output=(final_output + "\n") if final_output else "", data=payload, data_type=PipelineType.OBJECT)
            return CommandResult(output="", error="usage: agent graph create|show|list|run ...")

        if action == "list":
            payload = [
                {
                    "name": agent.name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "system_prompt": agent.system_prompt,
                    "prompt_template": agent.prompt_template,
                }
                for agent in self.agents.values()
            ]
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "show":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: agent show <name>")
            agent = self.agents.get(parts[1])
            if agent is None:
                return CommandResult(output="", error="agent not found")
            payload = {
                "name": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "system_prompt": agent.system_prompt,
                "prompt_template": agent.prompt_template,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "spawn":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: agent spawn <instance_name> --from <agent>|--prompt <template> [--provider p] [--model m] [--system text]")
            instance_name = parts[1]
            source_agent = ""
            prompt_template = ""
            provider = ""
            model = ""
            system_prompt = ""
            i = 2
            while i < len(parts):
                token = parts[i]
                if token == "--from" and i + 1 < len(parts):
                    source_agent = parts[i + 1]
                    i += 2
                    continue
                if token == "--prompt" and i + 1 < len(parts):
                    prompt_template = parts[i + 1]
                    i += 2
                    continue
                if token == "--provider" and i + 1 < len(parts):
                    provider = parts[i + 1]
                    i += 2
                    continue
                if token == "--model" and i + 1 < len(parts):
                    model = parts[i + 1]
                    i += 2
                    continue
                if token == "--system" and i + 1 < len(parts):
                    system_prompt = parts[i + 1]
                    i += 2
                    continue
                i += 1
            if source_agent:
                definition = self.agents.get(source_agent)
                if definition is None:
                    return CommandResult(output="", error="agent not found")
                prompt_template = prompt_template or definition.prompt_template
                provider = provider or definition.provider
                model = model or definition.model
                system_prompt = system_prompt or definition.system_prompt
            else:
                provider = provider or self.ai_runtime.get_active_provider()
                model = model or self.ai_runtime.get_active_model(provider)
            if not prompt_template:
                return CommandResult(output="", error="agent runtime prompt_template must not be empty")
            if not provider or not model:
                return CommandResult(output="", error="agent runtime requires a provider and model")
            instance = AgentRuntimeInstance(
                name=instance_name,
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                prompt_template=prompt_template,
                source_agent=source_agent,
            )
            self.agent_instances[instance_name] = instance
            payload = {
                "name": instance.name,
                "provider": instance.provider,
                "model": instance.model,
                "system_prompt": instance.system_prompt,
                "prompt_template": instance.prompt_template,
                "source_agent": instance.source_agent,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "create":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: agent create <name> <prompt_template> [--provider p] [--model m] [--system text]")
            name = parts[1]
            prompt_tokens: list[str] = []
            provider = ""
            model = ""
            system_prompt = ""
            i = 2
            while i < len(parts):
                token = parts[i]
                if token == "--provider" and i + 1 < len(parts):
                    provider = parts[i + 1]
                    i += 2
                    continue
                if token == "--model" and i + 1 < len(parts):
                    model = parts[i + 1]
                    i += 2
                    continue
                if token == "--system" and i + 1 < len(parts):
                    system_prompt = parts[i + 1]
                    i += 2
                    continue
                prompt_tokens.append(token)
                i += 1
            prompt_template = " ".join(prompt_tokens).strip()
            if not prompt_template:
                return CommandResult(output="", error="agent prompt_template must not be empty")

            selected_provider = provider or self.ai_runtime.get_active_provider()
            if not selected_provider:
                return CommandResult(output="", error="configure an ai provider first with ai use <provider> [model]")
            selected_model = model or self.ai_runtime.get_active_model(selected_provider)
            if not selected_model:
                return CommandResult(output="", error=f"provider '{selected_provider}' has no selected model")

            agent = AIAgentDefinition(
                name=name,
                prompt_template=prompt_template,
                provider=selected_provider,
                model=selected_model,
                system_prompt=system_prompt,
            )
            self.agents[name] = agent
            payload = {
                "name": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "system_prompt": agent.system_prompt,
                "prompt_template": agent.prompt_template,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if action == "run":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: agent run <name> [--file path] [--memory id]... [input]")
            agent = self.agents.get(parts[1])
            if agent is None:
                return CommandResult(output="", error="agent not found")
            context_options, remaining = self._parse_agent_context_args(parts, start_index=2)
            input_text = " ".join(remaining).strip()
            enriched_input, error = self._build_agent_input_with_context(
                input_text,
                file_path_text=str(context_options["file_path_text"] or ""),
                memory_ids=list(context_options["memory_ids"] or []),
            )
            if error is not None:
                return error
            return self._run_agent_once(agent, enriched_input)

        if action == "message":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: agent message <instance_name> [--file path] [--memory id]... <message>")
            instance = self.agent_instances.get(parts[1])
            if instance is None:
                return CommandResult(output="", error="agent runtime not found")
            context_options, remaining = self._parse_agent_context_args(parts, start_index=2)
            message = " ".join(remaining).strip()
            if not message:
                return CommandResult(output="", error="agent message requires a message")
            enriched_message, error = self._build_agent_input_with_context(
                message,
                file_path_text=str(context_options["file_path_text"] or ""),
                memory_ids=list(context_options["memory_ids"] or []),
            )
            if error is not None:
                return error
            return self._run_agent_instance_message(instance, enriched_message)

        if action == "workflow":
            names: list[str] = []
            input_text = ""
            swarm = False
            context_options, workflow_tokens = self._parse_agent_context_args(parts, start_index=1)
            i = 0
            while i < len(workflow_tokens):
                token = workflow_tokens[i]
                if token == "--swarm":
                    swarm = True
                    i += 1
                    continue
                if token == "--agents" and i + 1 < len(workflow_tokens):
                    names.extend([name.strip() for name in workflow_tokens[i + 1].split(",") if name.strip()])
                    i += 2
                    continue
                if token == "--input" and i + 1 < len(workflow_tokens):
                    input_text = workflow_tokens[i + 1]
                    i += 2
                    continue
                names.append(token)
                i += 1
            if not names:
                return CommandResult(output="", error="usage: agent workflow [--file path] [--memory id]... --agents a,b[,c] --input text")
            current_text = input_text.strip()
            if not current_text:
                return CommandResult(output="", error="agent workflow requires --input text")
            enriched_input, error = self._build_agent_input_with_context(
                current_text,
                file_path_text=str(context_options["file_path_text"] or ""),
                memory_ids=list(context_options["memory_ids"] or []),
            )
            if error is not None:
                return error
            current_text = enriched_input
            steps: list[dict[str, Any]] = []
            assignments: list[dict[str, Any]] = []
            execution_id = uuid.uuid4().hex[:10]
            for index, name in enumerate(names):
                if swarm:
                    result, assignment = self._run_agent_handle_swarm(
                        name,
                        current_text,
                        execution_id=execution_id,
                        step_kind="agent-workflow",
                        step_index=index,
                    )
                    assignments.append(assignment)
                else:
                    if name in self.agent_instances:
                        result = self._run_agent_instance_message(self.agent_instances[name], current_text)
                    else:
                        definition = self.agents.get(name)
                        if definition is None:
                            return CommandResult(output="", error=f"agent not found in workflow: {name}")
                        result = self._run_agent_once(definition, current_text)
                if result.error:
                    return result
                output_text = result.output.strip()
                steps.append({"agent": name, "input": current_text, "output": output_text})
                current_text = output_text
            payload = {
                "agents": names,
                "input": input_text,
                "steps": steps,
                "final_output": current_text,
                "swarm": swarm,
                "execution_id": execution_id,
                "assignments": assignments,
            }
            return CommandResult(output=(current_text + "\n") if current_text else "", data=payload, data_type=PipelineType.OBJECT)

        return CommandResult(output="", error="usage: agent create|run|show|list|spawn|message|workflow|graph ...")

    def _subscribe_event_pipeline(self, event_name: str, pipeline: str) -> None:
        self._dflow_subscribers.setdefault(event_name, []).append(pipeline)

    def _publish_event(self, event_name: str, payload: str, *, broadcast: bool = False) -> CommandResult:
        self.events.emit(
            {
                "stage": f"event {event_name}",
                "node": "event.emit",
                "error": "",
                "output": payload[:200],
                "data_type": PipelineType.TEXT.value,
                "trace_id": self.current_trace_id,
                "duration_ms": "0.000",
                "rows_processed": "1" if payload else "0",
                "cpu_percent": "0.0",
                "rss_mb": "0.0",
                "cost_estimate": "0.0",
            }
        )
        executed: list[dict[str, str]] = []
        for pipeline in self._dflow_subscribers.get(event_name, []):
            result = self._route_with_input(pipeline, payload)
            executed.append({"pipeline": pipeline, "error": result.error or "", "output": result.output.strip()})
        if broadcast and self.mesh.workers:
            event_data = json.dumps({"event": event_name, "payload": payload}).encode("utf-8")
            for worker in self.mesh.list_workers():
                req = urllib.request.Request(worker["url"].rstrip("/") + "/flow/event", data=event_data, headers={"Content-Type": "application/json"}, method="POST")
                with contextlib.suppress(Exception):
                    urllib.request.urlopen(req, timeout=5).read()
        out = {"event": event_name, "payload": payload, "broadcast": broadcast, "executed": executed}
        return CommandResult(output=json.dumps(out, ensure_ascii=False) + "\n", data=out, data_type=PipelineType.OBJECT)

    def _run_event(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: event on|emit|list|history ...")
        action = parts[0]
        if action == "on":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: event on <name> <pipeline>")
            self._subscribe_event_pipeline(parts[1], parts[2])
            return CommandResult(output="subscribed\n")
        if action == "emit":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: event emit <name> <payload> [--broadcast]")
            event_name = parts[1]
            payload_parts = parts[2:]
            broadcast = False
            if payload_parts and payload_parts[-1] == "--broadcast":
                broadcast = True
                payload_parts = payload_parts[:-1]
            if not payload_parts:
                return CommandResult(output="", error="usage: event emit <name> <payload> [--broadcast]")
            return self._publish_event(event_name, " ".join(payload_parts), broadcast=broadcast)
        if action == "list":
            return CommandResult(output=json.dumps(self._dflow_subscribers, ensure_ascii=False) + "\n", data=self._dflow_subscribers, data_type=PipelineType.OBJECT)
        if action == "history":
            limit = int(parts[1]) if len(parts) > 1 else 25
            history = [event for event in self.events.events if str(event.get("node", "")) == "event.emit"]
            payload = history[-limit:]
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        return CommandResult(output="", error="usage: event on|emit|list|history ...")

    def _run_vision(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: vision start|stop|status [port]")
        action = parts[0]
        if action == "start":
            port = int(parts[1]) if len(parts) > 1 else 8765
            return self.vision.start(port=port)
        if action == "stop":
            return self.vision.stop()
        if action == "status":
            running = self.vision._server is not None
            return CommandResult(output=("running\n" if running else "stopped\n"))
        return CommandResult(output="", error="usage: vision start|stop|status [port]")

    def _run_fabric(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: fabric put <text> | fabric get <handle> | fabric put-arrow <csv> | fabric remote-put <url> <text> | fabric remote-get <url> <handle> | fabric rdma-put <url> <file> | fabric rdma-get <url> <handle> <out_file>")
        match parts[0]:
            case "put":
                value = args[len("put") :].strip()
                return self.fabric.put(value)
            case "put-arrow":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: fabric put-arrow <csv_file>")
                csv_path = self._resolve_path(parts[1])
                return self.fabric.put_arrow_from_csv(str(csv_path))
            case "get":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: fabric get <handle>")
                return self.fabric.get(parts[1])
            case "remote-put":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: fabric remote-put <url> <text>")
                payload = json.dumps({"value": " ".join(parts[2:])}).encode("utf-8")
                request = urllib.request.Request(
                    parts[1].rstrip("/") + "/fabric/put",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        body = json.loads(response.read().decode("utf-8"))
                    return CommandResult(output=f"{body.get('handle', '')}\n", data=body, data_type=PipelineType.OBJECT)
                except Exception as exc:
                    return CommandResult(output="", error=f"fabric remote-put error: {exc}")
            case "remote-get":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: fabric remote-get <url> <handle>")
                url = parts[1].rstrip("/") + "/fabric/get?handle=" + urllib.parse.quote(parts[2])
                try:
                    with urllib.request.urlopen(url, timeout=10) as response:
                        body = json.loads(response.read().decode("utf-8"))
                    return CommandResult(output=f"{body.get('value', '')}\n", data=body, data_type=PipelineType.OBJECT)
                except Exception as exc:
                    return CommandResult(output="", error=f"fabric remote-get error: {exc}")
            case "rdma-put":
                if len(parts) < 3:
                    return CommandResult(output="", error="usage: fabric rdma-put <url> <file>")
                return self.fabric_remote.put_file(parts[1], str(self._resolve_path(parts[2])))
            case "rdma-get":
                if len(parts) < 4:
                    return CommandResult(output="", error="usage: fabric rdma-get <url> <handle> <out_file>")
                return self.fabric_remote.get_file(parts[1], parts[2], str(self._resolve_path(parts[3])))
            case _:
                return CommandResult(output="", error="usage: fabric put <text> | fabric get <handle> | fabric put-arrow <csv> | fabric remote-put <url> <text> | fabric remote-get <url> <handle> | fabric rdma-put <url> <file> | fabric rdma-get <url> <handle> <out_file>")

    def _run_mesh(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: mesh add|list|run|intelligent-run|beat|start-worker|stop-worker ...")

        action = parts[0]
        if action == "start-worker":
            host = "127.0.0.1"
            port = 0
            caps: set[str] = {"cpu", "py", "ai"}
            i = 1
            while i < len(parts):
                token = parts[i]
                if token == "--host" and i + 1 < len(parts):
                    host = parts[i + 1]
                    i += 2
                    continue
                if token == "--port" and i + 1 < len(parts):
                    with contextlib.suppress(Exception):
                        port = int(parts[i + 1])
                    i += 2
                    continue
                if token == "--caps" and i + 1 < len(parts):
                    caps = {cap.strip() for cap in parts[i + 1].split(",") if cap.strip()}
                    i += 2
                    continue
                i += 1
            if port <= 0:
                port = self._find_free_port()
            url = f"http://{host}:{port}"
            worker_id = uuid.uuid4().hex[:8]
            log_path = self.mesh_log_dir / f"worker-{worker_id}.log"
            command = self._local_worker_command(host, port, caps)
            with log_path.open("w", encoding="utf-8") as handle:
                process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, cwd=str(self.cwd))
            if not self._wait_for_worker_health(url):
                with contextlib.suppress(Exception):
                    process.terminate()
                return CommandResult(output="", error=f"worker failed to start: {url}")
            managed = LocalManagedWorker(worker_id=worker_id, url=url, caps=caps, process=process, log_path=log_path)
            self.local_mesh_workers[worker_id] = managed
            self.mesh.add_worker(url, caps)
            worker = self.mesh.get_worker(url)
            if worker is not None:
                worker["managed_local"] = True
                worker["worker_id"] = worker_id
                worker["pid"] = process.pid
                worker["log_path"] = str(log_path)
            payload = {
                "worker_id": worker_id,
                "url": url,
                "caps": sorted(caps),
                "pid": process.pid,
                "log_path": str(log_path),
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "stop-worker":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: mesh stop-worker <worker_id|url|port>")
            ok = self._stop_local_mesh_worker(parts[1])
            if not ok:
                return CommandResult(output="", error="managed local worker not found")
            return CommandResult(output="stopped\n")
        if action == "add":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: mesh add <worker_url> <cap1,cap2,...>")
            caps = {cap.strip() for cap in parts[2].split(",") if cap.strip()}
            self.mesh.add_worker(parts[1], caps)
            return CommandResult(output=f"mesh worker added: {parts[1]}\n")
        if action == "beat":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: mesh beat <worker_url> [latency_ms] [handle1,handle2]")
            latency = float(parts[2]) if len(parts) > 2 else None
            handles = set(parts[3].split(",")) if len(parts) > 3 and parts[3] else None
            ok = self.mesh.heartbeat(parts[1], latency_ms=latency, data_handles=handles)
            if not ok:
                return CommandResult(output="", error="unknown mesh worker")
            return CommandResult(output="ok\n")
        if action == "list":
            payload = self.mesh.list_workers()
            return CommandResult(
                output=json.dumps(payload, ensure_ascii=False) + "\n",
                data=payload,
                data_type=PipelineType.OBJECT,
            )
        if action == "run":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: mesh run <capability> <command>")
            capability = parts[1]
            worker = self.mesh.select_worker(capability)
            if worker is None:
                return CommandResult(output="", error=f"no worker available for capability: {capability}")
            command = " ".join(parts[2:])
            try:
                return self.remote.execute(worker["url"], command)
            finally:
                worker["load"] = max(worker["load"] - 1, 0)
        if action == "intelligent-run":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: mesh intelligent-run <capability> <command> [--handle h]")
            capability = parts[1]
            data_handle = None
            if "--handle" in parts:
                idx = parts.index("--handle")
                if idx + 1 < len(parts):
                    data_handle = parts[idx + 1]
            worker = self.mesh.intelligent_select(capability, data_handle)
            if worker is None:
                return CommandResult(output="", error=f"no worker available for capability: {capability}")
            command_tokens = [t for t in parts[2:] if t not in {"--handle", data_handle}]
            command = " ".join(command_tokens)
            try:
                return self.remote.execute(worker["url"], command)
            finally:
                worker["load"] = max(worker["load"] - 1, 0)
        return CommandResult(output="", error="usage: mesh add|list|run|intelligent-run|beat|start-worker|stop-worker ...")

    def _run_guard(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output=f"current policy: {self.current_policy}\n")
        match parts[0]:
            case "set":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: guard set <policy>")
                name = parts[1]
                if name not in self.policy.policies and name not in self.guard_store.loaded_policies:
                    return CommandResult(output="", error=f"unknown policy: {name}")
                self.current_policy = name
                return CommandResult(output=f"policy set to {name}\n")
            case "list":
                payload = {
                    "built_in": sorted(self.policy.policies.keys()),
                    "loaded": sorted(self.guard_store.loaded_policies.keys()),
                    "ebpf_builtin": sorted(self.guard_store.builtin_policies.keys()),
                }
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            case "load":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: guard load <policy.yaml|policy.json>")
                try:
                    policy_path = self._resolve_path(parts[1])
                    data = self.guard_store.load(str(policy_path))
                    name = str(data.get("name") or policy_path.stem)
                    return CommandResult(output=f"loaded policy {name}\n", data=data, data_type=PipelineType.OBJECT)
                except Exception as exc:
                    return CommandResult(output="", error=f"failed to load policy: {exc}")
            case "sandbox":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: guard sandbox on|off|status")
                if parts[1] == "on":
                    self.wasm_sandbox_default = True
                    return CommandResult(output="sandbox on\n")
                if parts[1] == "off":
                    self.wasm_sandbox_default = False
                    return CommandResult(output="sandbox off\n")
                if parts[1] == "status":
                    payload = {"sandbox_default": self.wasm_sandbox_default}
                    return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
                return CommandResult(output="", error="usage: guard sandbox on|off|status")
            case "ebpf-status":
                payload = {
                    "available": self.guard_store.ebpf_available,
                    "mode": "kernel" if self.guard_store.ebpf_available else "userspace-fallback",
                    "enforced_policy": self.guard_store.enforced_policy or "",
                }
                return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
            case "ebpf-compile":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: guard ebpf-compile <policy|file>")
                policy_name, error = self._resolve_guard_policy_reference(parts[1])
                if error is not None:
                    return error
                return self.guard_store.compile_ebpf_profile(policy_name)
            case "ebpf-enforce":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: guard ebpf-enforce <policy|file>")
                policy_name, error = self._resolve_guard_policy_reference(parts[1])
                if error is not None:
                    return error
                return self.guard_store.enforce(policy_name)
            case "ebpf-release":
                self.guard_store.enforced_policy = None
                return CommandResult(output="released\n")
            case _:
                return CommandResult(output="", error="usage: guard [list]|set <policy>|load <file>|sandbox on|off|status|ebpf-status|ebpf-compile <policy|file>|ebpf-enforce <policy|file>|ebpf-release")

    def _resolve_guard_policy_reference(self, reference: str) -> tuple[str, CommandResult | None]:
        if reference in self.guard_store.loaded_policies or reference in self.guard_store.builtin_policies:
            return reference, None
        policy_path = self._resolve_path(reference)
        if policy_path.exists() and policy_path.is_file():
            try:
                data = self.guard_store.load(str(policy_path))
            except Exception as exc:
                return "", CommandResult(output="", error=f"failed to load policy: {exc}")
            return str(data.get("name") or policy_path.stem), None
        return "", CommandResult(output="", error=f"policy not loaded: {reference}. use 'guard load <file>' or a built-in eBPF profile")

    def _run_secure(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if len(parts) < 2:
            return CommandResult(output="", error="usage: secure <policy> <command>")
        policy_name = parts[0]
        command = args[len(policy_name) :].strip()
        if policy_name == "wasm" and command.startswith("py "):
            return CommandResult(output="", error="secure wasm mode requires wasm modules, not raw python")
        allowed, reason = self.policy.is_allowed(policy_name, command)
        if allowed:
            allowed, reason = self.guard_store.evaluate(policy_name, command)
        if not allowed:
            return CommandResult(output="", error=reason)
        return self.route(command)

    def _run_flow(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: flow state set|get ... | flow count-last <sec> [pattern]")

        if parts[0] == "state":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: flow state set|get <key> [value]")
            if parts[1] == "set":
                if len(parts) < 4:
                    return CommandResult(output="", error="usage: flow state set <key> <value>")
                self.flow_state.set(parts[2], " ".join(parts[3:]))
                return CommandResult(output="ok\n")
            if parts[1] == "get":
                value = self.flow_state.get(parts[2])
                return CommandResult(output=(f"{value}\n" if value is not None else "\n"))
            return CommandResult(output="", error="usage: flow state set|get <key> [value]")

        if parts[0] == "count-last":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: flow count-last <seconds> [pattern]")
            seconds = float(parts[1])
            pattern = parts[2] if len(parts) > 2 else "*"
            count = self.flow_state.count_last(seconds, pattern)
            return CommandResult(output=f"{count}\n", data=count, data_type=PipelineType.OBJECT)

        return CommandResult(output="", error="usage: flow state set|get ... | flow count-last <sec> [pattern]")

    def _run_optimizer(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: opt suggest <task> [payload] | opt run <task> [payload]")

        action = parts[0]
        if action not in {"suggest", "run"}:
            return CommandResult(output="", error="usage: opt suggest <task> [payload] | opt run <task> [payload]")

        if len(parts) < 2:
            return CommandResult(output="", error=f"usage: opt {action} <task> [payload]")

        task = parts[1]
        payload = " ".join(parts[2:]) if len(parts) > 2 else ""
        suggestion = self.optimizer.suggest_engine(task, payload)

        if action == "suggest":
            return CommandResult(output=json.dumps(suggestion, ensure_ascii=False) + "\n", data=suggestion, data_type=PipelineType.OBJECT)

        engine = suggestion["engine"]
        if engine == "mesh" and self.mesh.workers:
            workers = self.mesh.list_workers()
            capability = "gpu" if any("gpu" in w["caps"] for w in workers) else "cpu"
            command = f"mesh run {capability} py {payload or '0'}"
        elif engine == "gpu":
            command = f"py {payload}" if not payload else f"py {payload}"  # fallback-friendly path
        elif engine == "cpp":
            command = f"py {payload}" if payload else "py 0"
        else:
            command = f"py {payload}" if payload else "py 0"

        result = self.route(command)
        if result.error:
            return result
        response = {"suggestion": suggestion, "delegated_command": command, "output": result.output.strip()}
        return CommandResult(output=json.dumps(response, ensure_ascii=False) + "\n", data=response, data_type=PipelineType.OBJECT)

    def _run_reactive(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: reactive on-file|on-sync|list|stop|clear ...")

        action = parts[0]
        if action == "on-file":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: reactive on-file <glob> <pipeline> [--continuous]")
            once = "--continuous" not in parts[3:]
            trigger = self.reactive.register_file_trigger(parts[1], parts[2], once=once)
            return CommandResult(output=json.dumps({"id": trigger.trigger_id, "kind": trigger.kind}, ensure_ascii=False) + "\n", data={"id": trigger.trigger_id}, data_type=PipelineType.OBJECT)
        if action == "on-sync":
            if len(parts) < 4:
                return CommandResult(output="", error="usage: reactive on-sync <counter> <threshold> <pipeline> [--continuous]")
            once = "--continuous" not in parts[4:]
            trigger = self.reactive.register_sync_trigger(parts[1], int(parts[2]), parts[3], once=once)
            return CommandResult(output=json.dumps({"id": trigger.trigger_id, "kind": trigger.kind}, ensure_ascii=False) + "\n", data={"id": trigger.trigger_id}, data_type=PipelineType.OBJECT)
        if action == "list":
            payload = self.reactive.list()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "stop":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: reactive stop <id>")
            ok = self.reactive.stop(parts[1])
            return CommandResult(output=("stopped\n" if ok else "not found\n"))
        if action == "clear":
            self.reactive.clear()
            return CommandResult(output="cleared\n")

        return CommandResult(output="", error="usage: reactive on-file|on-sync|list|stop|clear ...")

    def _run_rag(self, args: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: rag ingest|watch|list|stop ...")
        action = parts[0]
        if action == "list":
            payload = []
            for watcher in self.rag_watchers.values():
                trigger = self.reactive.triggers.get(watcher.reactive_trigger_id)
                payload.append(
                    {
                        "id": watcher.watcher_id,
                        "pattern": watcher.pattern,
                        "namespace": watcher.namespace,
                        "project": watcher.project,
                        "chunk_size": watcher.chunk_size,
                        "chunk_overlap": watcher.chunk_overlap,
                        "publish_topic": watcher.publish_topic,
                        "summarize": watcher.summarize,
                        "train_atheria": watcher.train_atheria,
                        "reactive_trigger_id": watcher.reactive_trigger_id,
                        "active": bool(trigger.active) if trigger is not None else False,
                    }
                )
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "stop":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: rag stop <id>")
            watcher = self.rag_watchers.pop(parts[1], None)
            if watcher is None:
                return CommandResult(output="", error="rag watcher not found")
            self.reactive.stop(watcher.reactive_trigger_id)
            return CommandResult(output="stopped\n")
        if action not in {"ingest", "watch"}:
            return CommandResult(output="", error="usage: rag ingest|watch|list|stop ...")

        file_path_text = ""
        pattern = ""
        namespace = self.current_memory_namespace
        project = self.current_memory_project
        chunk_size = 1200
        chunk_overlap = 160
        publish_topic = "knowledge_updated"
        summarize = True
        train_atheria = True
        positional: list[str] = []
        i = 1
        while i < len(parts):
            token = parts[i]
            if token == "--file" and i + 1 < len(parts):
                file_path_text = parts[i + 1]
                i += 2
                continue
            if token == "--namespace" and i + 1 < len(parts):
                namespace = parts[i + 1]
                i += 2
                continue
            if token == "--project" and i + 1 < len(parts):
                project = parts[i + 1]
                i += 2
                continue
            if token == "--chunk-size" and i + 1 < len(parts):
                with contextlib.suppress(Exception):
                    chunk_size = max(200, int(parts[i + 1]))
                i += 2
                continue
            if token == "--chunk-overlap" and i + 1 < len(parts):
                with contextlib.suppress(Exception):
                    chunk_overlap = max(0, int(parts[i + 1]))
                i += 2
                continue
            if token == "--publish" and i + 1 < len(parts):
                publish_topic = parts[i + 1]
                i += 2
                continue
            if token == "--no-summary":
                summarize = False
                i += 1
                continue
            if token == "--no-atheria":
                train_atheria = False
                i += 1
                continue
            positional.append(token)
            i += 1

        if action == "ingest":
            if not file_path_text and positional:
                file_path_text = positional[0]
            if not file_path_text and pipeline_input.strip():
                file_path_text = pipeline_input.strip()
            if not file_path_text:
                return CommandResult(output="", error="usage: rag ingest --file <path> [--namespace n] [--project p] [--chunk-size n] [--chunk-overlap n] [--publish topic] [--no-summary] [--no-atheria]")
            file_path = self._resolve_path(file_path_text)
            if not file_path.exists() or not file_path.is_file():
                return CommandResult(output="", error=f"rag file not found: {file_path_text}")
            try:
                payload = self._ingest_rag_file(
                    file_path,
                    namespace=namespace,
                    project=project,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    publish_topic=publish_topic,
                    train_atheria=train_atheria,
                    summarize=summarize,
                )
            except Exception as exc:
                return CommandResult(output="", error=f"rag ingest failed: {exc}")
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

        if positional:
            pattern = positional[0]
        if not pattern:
            return CommandResult(output="", error="usage: rag watch <glob> [--namespace n] [--project p] [--chunk-size n] [--chunk-overlap n] [--publish topic] [--no-summary] [--no-atheria]")
        command = " ".join(
            [
                "rag ingest --file {{path}}",
                "--namespace",
                self._shell_quote(namespace),
                "--project",
                self._shell_quote(project),
                "--chunk-size",
                str(chunk_size),
                "--chunk-overlap",
                str(chunk_overlap),
                "--publish",
                self._shell_quote(publish_topic),
            ]
            + ([] if summarize else ["--no-summary"])
            + ([] if train_atheria else ["--no-atheria"])
        )
        trigger = self.reactive.register_file_trigger(pattern, command, once=False)
        watcher = AutoRAGWatcherSpec(
            watcher_id="rag_" + uuid.uuid4().hex[:8],
            pattern=pattern,
            namespace=namespace,
            project=project,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            publish_topic=publish_topic,
            summarize=summarize,
            train_atheria=train_atheria,
            reactive_trigger_id=trigger.trigger_id,
        )
        self.rag_watchers[watcher.watcher_id] = watcher
        payload = {
            "id": watcher.watcher_id,
            "pattern": watcher.pattern,
            "namespace": watcher.namespace,
            "project": watcher.project,
            "reactive_trigger_id": watcher.reactive_trigger_id,
            "publish_topic": watcher.publish_topic,
        }
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def _run_zero(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: zero put <text> | zero put-arrow <csv> | zero get <handle> | zero list | zero release <handle>")
        action = parts[0]
        if action == "put":
            value = args[len("put") :].strip()
            return self.zero.put_text(value)
        if action == "put-arrow":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: zero put-arrow <csv>")
            return self.zero.put_arrow_from_csv(str(self._resolve_path(parts[1])))
        if action == "get":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: zero get <handle>")
            return self.zero.get(parts[1])
        if action == "list":
            payload = self.zero.list()
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "release":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: zero release <handle>")
            return self.zero.release(parts[1])
        return CommandResult(output="", error="usage: zero put <text> | zero put-arrow <csv> | zero get <handle> | zero list | zero release <handle>")

    def _run_synth(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: synth suggest <code> | synth autotune <code>")
        action = parts[0]
        payload = args[len(action) :].strip()
        if action == "suggest":
            if not payload:
                return CommandResult(output="", error="usage: synth suggest <code>")
            data = self.synth.suggest(payload)
            return CommandResult(output=json.dumps(data, ensure_ascii=False) + "\n", data=data, data_type=PipelineType.OBJECT)
        if action == "autotune":
            if not payload:
                return CommandResult(output="", error="usage: synth autotune <code>")
            result = self.synth.autotune(payload)
            if result.error:
                return result
            payload_data = {"result": result.output}
            return CommandResult(output=json.dumps(payload_data, ensure_ascii=False) + "\n", data=payload_data, data_type=PipelineType.OBJECT)
        return CommandResult(output="", error="usage: synth suggest <code> | synth autotune <code>")

    def _run_dflow(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: dflow subscribe|publish|list ...")
        action = parts[0]
        if action == "subscribe":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: dflow subscribe <event> <pipeline>")
            self._subscribe_event_pipeline(parts[1], parts[2])
            return CommandResult(output="subscribed\n")
        if action == "publish":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: dflow publish <event> <payload> [--broadcast]")
            event_name = parts[1]
            payload_parts = parts[2:]
            broadcast = False
            if payload_parts and payload_parts[-1] == "--broadcast":
                broadcast = True
                payload_parts = payload_parts[:-1]
            if not payload_parts:
                return CommandResult(output="", error="usage: dflow publish <event> <payload> [--broadcast]")
            return self._publish_event(event_name, " ".join(payload_parts), broadcast=broadcast)
        if action == "list":
            return CommandResult(output=json.dumps(self._dflow_subscribers, ensure_ascii=False) + "\n", data=self._dflow_subscribers, data_type=PipelineType.OBJECT)
        return CommandResult(output="", error="usage: dflow subscribe|publish|list ...")

    def _run_pulse(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        action = parts[0] if parts else "status"
        if action == "status":
            payload = {
                "vision_running": self.vision._server is not None,
                "recent_event_count": len(self.events.events[-25:]),
                "active_reactive_triggers": len([t for t in self.reactive.triggers.values() if t.active]),
                "dflow_topics": sorted(self._dflow_subscribers.keys()),
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "snapshot":
            tail = self.events.events[-25:]
            bottlenecks = sorted(tail, key=lambda e: float(e.get("duration_ms", 0.0)), reverse=True)[:5]
            payload = {"events": tail, "bottlenecks": bottlenecks}
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        return CommandResult(output="", error="usage: pulse [status|snapshot]")

    def _run_jit_wasm(self, args: str, _: str, __: Any) -> CommandResult:
        return self.jit.execute_expression(args.strip())

    def _run_sync(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: sync inc|get|set|get-key|merge|export ...")

        action = parts[0]
        if action == "inc":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: sync inc <counter> [amount]")
            counter = self.sync_counters.setdefault(parts[1], GCounterCRDT(self.node_id))
            amount = int(parts[2]) if len(parts) > 2 else 1
            value = counter.increment(amount)
            return CommandResult(output=f"{value}\n", data=value, data_type=PipelineType.OBJECT)
        if action == "get":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: sync get <counter>")
            counter = self.sync_counters.setdefault(parts[1], GCounterCRDT(self.node_id))
            return CommandResult(output=f"{counter.value}\n", data=counter.value, data_type=PipelineType.OBJECT)
        if action == "set":
            if len(parts) < 3:
                return CommandResult(output="", error="usage: sync set <key> <value>")
            self.sync_map.set(parts[1], " ".join(parts[2:]))
            return CommandResult(output="ok\n")
        if action == "get-key":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: sync get-key <key>")
            value = self.sync_map.get(parts[1])
            return CommandResult(output=(f"{value}\n" if value is not None else "\n"))
        if action == "export":
            payload = {
                "node_id": self.node_id,
                "counters": {name: counter.counts for name, counter in self.sync_counters.items()},
                "map": self.sync_map.values,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "merge":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: sync merge <json_state>")
            try:
                payload = json.loads(" ".join(parts[1:]))
            except json.JSONDecodeError as exc:
                return CommandResult(output="", error=f"invalid json: {exc}")
            for name, counts in payload.get("counters", {}).items():
                counter = self.sync_counters.setdefault(name, GCounterCRDT(self.node_id))
                counter.merge({k: int(v) for k, v in counts.items()})
            self.sync_map.merge(payload.get("map", {}))
            return CommandResult(output="merged\n")

        return CommandResult(output="", error="usage: sync inc|get|set|get-key|merge|export ...")

    def _run_lens(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: lens list [n] | lens last | lens show <id> | lens replay <id> | lens fork <id> --inject json | lens forks [n] | lens diff <fork_id>")
        action = parts[0]
        if action == "list":
            limit = int(parts[1]) if len(parts) > 1 else 10
            payload = self.lens.list(limit)
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "last":
            payload = self.lens.list(1)
            if not payload:
                return CommandResult(output="\n")
            return CommandResult(output=json.dumps(payload[0], ensure_ascii=False) + "\n", data=payload[0], data_type=PipelineType.OBJECT)
        if action == "show":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: lens show <id>")
            payload = self.lens.get(parts[1])
            if payload is None:
                return CommandResult(output="", error="snapshot not found")
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "replay":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: lens replay <id>")
            return self.lens.replay(parts[1])
        if action == "fork":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: lens fork <snapshot_id> --inject json")
            snapshot = self.lens.get(parts[1])
            if snapshot is None:
                return CommandResult(output="", error="snapshot not found")
            inject_payload: dict[str, Any] = {}
            i = 2
            while i < len(parts):
                token = parts[i]
                if token == "--inject" and i + 1 < len(parts):
                    try:
                        loaded = self._load_structured_payload(parts[i + 1])
                    except Exception as exc:
                        return CommandResult(output="", error=str(exc))
                    if not isinstance(loaded, dict):
                        return CommandResult(output="", error="lens fork injection must be an object")
                    inject_payload = loaded
                    i += 2
                    continue
                i += 1
            base_payload = self._coerce_snapshot_payload(snapshot.get("data_preview", ""), snapshot.get("output", ""))
            forked_payload = self._deep_merge_payload(base_payload, inject_payload)
            diff = self._collect_diff_rows(base_payload, forked_payload)
            namespace = f"{self.current_memory_namespace}.fork.{parts[1][:6]}"
            project = f"{self.current_memory_project}.fork"
            simulation = self._simulate_fork_payload(parts[1], forked_payload)
            fork_output = json.dumps(forked_payload, ensure_ascii=False, indent=2)
            artifact = self.lens.record_fork(
                snapshot_id=parts[1],
                namespace=namespace,
                project=project,
                inject_payload=inject_payload,
                diff=diff,
                simulation=simulation,
                fork_output=fork_output,
                fork_data_preview=fork_output,
            )
            payload = {
                "id": artifact.fork_id,
                "snapshot_id": artifact.snapshot_id,
                "namespace": namespace,
                "project": project,
                "inject": inject_payload,
                "diff": diff,
                "simulation": simulation,
                "fork_output": forked_payload,
            }
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "forks":
            limit = int(parts[1]) if len(parts) > 1 else 10
            payload = self.lens.list_forks(limit)
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if action == "diff":
            if len(parts) < 2:
                return CommandResult(output="", error="usage: lens diff <fork_id>")
            payload = self.lens.get_fork(parts[1])
            if payload is None:
                return CommandResult(output="", error="fork not found")
            diff_payload = {
                "id": payload["id"],
                "snapshot_id": payload["snapshot_id"],
                "inject": payload["inject"],
                "diff": payload["diff"],
                "simulation": payload["simulation"],
            }
            return CommandResult(output=json.dumps(diff_payload, ensure_ascii=False) + "\n", data=diff_payload, data_type=PipelineType.OBJECT)
        return CommandResult(output="", error="usage: lens list [n] | lens last | lens show <id> | lens replay <id> | lens fork <id> --inject json | lens forks [n] | lens diff <fork_id>")

    def _run_on(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if len(parts) < 4 or parts[0] != "file":
            return CommandResult(output="", error='usage: on file "<glob>" --timeout <seconds> "<pipeline with _>"')

        pattern_path = Path(os.path.expanduser(parts[1]))
        if pattern_path.is_absolute():
            pattern = str(pattern_path)
        else:
            pattern = str((self.cwd / pattern_path).resolve(strict=False))
        timeout_s = 3.0
        if "--timeout" in parts:
            idx = parts.index("--timeout")
            if idx + 1 < len(parts):
                timeout_s = float(parts[idx + 1])

        pipeline = parts[-1]
        deadline = time.time() + timeout_s
        seen: set[str] = set()
        while time.time() < deadline:
            matches = sorted(glob.glob(pattern))
            new_matches = [m for m in matches if m not in seen]
            if new_matches:
                path = new_matches[0]
                seen.add(path)
                if "|" not in pipeline and (pipeline.startswith("py ") or pipeline.startswith("python ")):
                    return self._route_single(pipeline, path, path)
                command = pipeline.replace("_", shlex.quote(path))
                return self.route(command)
            time.sleep(0.05)

        return CommandResult(output="", error="on file timeout reached")

    def _run_pack(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if len(parts) < 1:
            return CommandResult(output="", error="usage: pack <script.ns> --output <bundle.npx> [--requirements req.txt]")

        script_path = self._resolve_path(parts[0])
        output_path = self._resolve_path("bundle.npx")
        requirements_path: Path | None = None

        i = 1
        while i < len(parts):
            if parts[i] == "--output" and i + 1 < len(parts):
                output_path = self._resolve_path(parts[i + 1])
                i += 2
                continue
            if parts[i] == "--requirements" and i + 1 < len(parts):
                requirements_path = self._resolve_path(parts[i + 1])
                i += 2
                continue
            return CommandResult(output="", error=f"unknown pack option: {parts[i]}")

        if not script_path.exists():
            return CommandResult(output="", error=f"script not found: {script_path}")

        manifest = {
            "script": script_path.name,
            "created_at": time.time(),
            "version": "0.7",
        }
        if requirements_path is not None:
            manifest["requirements"] = requirements_path.name

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(script_path, arcname=script_path.name)
            if requirements_path is not None and requirements_path.exists():
                zf.write(requirements_path, arcname=requirements_path.name)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        return CommandResult(output=f"packed {output_path}\n", data={"bundle": str(output_path)}, data_type=PipelineType.OBJECT)

    def _run_observe(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if len(parts) < 2 or parts[0] != "run":
            return CommandResult(output="", error="usage: observe run <pipeline>")

        pipeline = args[len("run") :].strip()
        trace_id = uuid.uuid4().hex[:12]
        self.current_trace_id = trace_id
        result = self.route(pipeline)
        self.current_trace_id = ""
        

        if result.error:
            return result

        stats = self._events("stats", "", None)
        payload = {
            "trace_id": trace_id,
            "result_preview": result.output[:200],
            "stats": stats.data if stats.data else {},
        }
        return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)

    def _run_studio(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: studio completions <prefix> | studio graph | studio events")

        if parts[0] == "completions":
            prefix = parts[1] if len(parts) > 1 else ""
            items = sorted([name for name in self.commands.keys() if name.startswith(prefix)])
            return CommandResult(output=json.dumps(items, ensure_ascii=False) + "\n", data=items, data_type=PipelineType.OBJECT)
        if parts[0] == "graph":
            payload = [{"name": node.name, "stages": node.stages, "parallel": node.parallel} for node in self.last_graph.nodes]
            return CommandResult(output=json.dumps(payload, ensure_ascii=False) + "\n", data=payload, data_type=PipelineType.OBJECT)
        if parts[0] == "events":
            return CommandResult(output=json.dumps(self.events.events, ensure_ascii=False) + "\n", data=self.events.events, data_type=PipelineType.OBJECT)

        return CommandResult(output="", error="usage: studio completions <prefix> | studio graph | studio events")

    def _run_data_load(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: data.load <csv_file> [--arrow]")
        file_path = str(self._resolve_path(parts[0]))
        if len(parts) > 1 and parts[1] == "--arrow":
            return self.data.load_csv_arrow(file_path)
        return self.data.load_csv(file_path)

    def _run_data(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: data load <csv_file> [--arrow]")
        if parts[0] == "load" and len(parts) >= 2:
            file_path = str(self._resolve_path(parts[1]))
            if len(parts) > 2 and parts[2] == "--arrow":
                return self.data.load_csv_arrow(file_path)
            return self.data.load_csv(file_path)
        return CommandResult(output="", error=f"unknown data command: {' '.join(parts)}")

    def _run_system(self, command: str, pipeline_input: str, _: Any) -> CommandResult:
        blocked = self._is_ebpf_blocked(command)
        if blocked:
            return CommandResult(output="", error=blocked)
        return self.system.execute(command, pipeline_input, cwd=self.cwd)

    def _split_pipeline(self, command: str) -> list[str]:
        stages: list[str] = []
        current: list[str] = []
        in_single = False
        in_double = False

        for char in command:
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double

            if char == "|" and not in_single and not in_double:
                stage = "".join(current).strip()
                if stage:
                    stages.append(stage)
                current = []
                continue

            current.append(char)

        tail = "".join(current).strip()
        if tail:
            stages.append(tail)

        return stages

    def _build_pipeline_graph(self, stages: list[str]) -> PipelineGraph:
        graph = PipelineGraph()

        for stage in stages:
            is_py_stage = stage.startswith("py ") or stage.startswith("python ")
            is_parallel = stage.startswith("parallel ")

            if is_py_stage and graph.nodes and graph.nodes[-1].name == "py_chain" and not graph.nodes[-1].parallel:
                graph.nodes[-1].stages.append(stage)
                continue

            node_name = "py_chain" if is_py_stage else stage
            graph.add(PipelineNode(name=node_name, stages=[stage], parallel=is_parallel))

        return graph

    def _route_single(self, command: str, pipeline_input: str = "", pipeline_data: Any = None) -> CommandResult:
        parts = split_command(command)
        if not parts:
            return CommandResult(output="")

        cmd = parts[0]
        rest = command[len(cmd) :].strip()

        match cmd:
            case "exit":
                raise SystemExit(0)
            case _ if cmd in self.commands:
                return self.commands[cmd](rest, pipeline_input, pipeline_data)
            case _:
                return self._run_system(command, pipeline_input, pipeline_data)

    def _parallel_stage(self, command: str, pipeline_output: str, pipeline_data: Any) -> CommandResult:
        target = command[len("parallel ") :].strip()
        if not target:
            return CommandResult(output="", error="usage: parallel <command>")

        if isinstance(pipeline_data, Iterable) and not isinstance(pipeline_data, (str, bytes, dict)):
            items = list(pipeline_data)
        else:
            items = pipeline_output.splitlines()

        if not items:
            return CommandResult(output="")

        def run_item(item: Any) -> CommandResult:
            item_text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            return self._route_single(target, item_text, item)

        with ThreadPoolExecutor() as executor:
            results = list(executor.map(run_item, items))

        for result in results:
            if result.error:
                return result

        merged_output = "".join(result.output for result in results)
        merged_data = [result.data for result in results]
        return CommandResult(output=merged_output, data=merged_data, data_type=PipelineType.OBJECT_STREAM)

    def _is_stream_type(self, data_type: PipelineType) -> bool:
        return data_type in {PipelineType.TEXT_STREAM, PipelineType.GENERATOR}

    def _stage_over_iterable(self, stage: str, values: Iterable[Any], *, lazy: bool = False) -> CommandResult:
        if lazy:
            def transformed() -> Iterable[Any]:
                for item in values:
                    item_text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                    result = self._route_single(stage, item_text, item)
                    if result.error:
                        raise RuntimeError(result.error)
                    yield result.data if result.data is not None else result.output.rstrip("\n")

            return CommandResult(output="", data=transformed(), data_type=PipelineType.GENERATOR)

        outputs: list[str] = []
        collected_data: list[Any] = []

        for item in values:
            item_text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            result = self._route_single(stage, item_text, item)
            if result.error:
                return result
            outputs.append(result.output)
            collected_data.append(result.data)

        return CommandResult(output="".join(outputs), data=collected_data, data_type=PipelineType.OBJECT_STREAM)

    def _execute_stage(
        self,
        stage: str,
        current_output: str,
        current_data: Any,
        current_type: PipelineType,
        *,
        emit_event: bool = True,
        node_name: str | None = None,
    ) -> tuple[CommandResult, int, float]:
        allowed, reason = self.policy.is_allowed(self.current_policy, stage)
        if allowed:
            allowed, reason = self.guard_store.evaluate(self.current_policy, stage)
        if not allowed:
            blocked = CommandResult(output="", error=reason)
            if emit_event:
                self.events.emit(
                    {
                        "stage": stage,
                        "node": node_name or stage,
                        "trace_id": self.current_trace_id,
                        "error": reason,
                        "output": "",
                        "data_type": blocked.data_type.value,
                        "duration_ms": "0.000",
                        "rows_processed": "0",
                        "cpu_percent": "0.0",
                        "rss_mb": "0.0",
                        "cost_estimate": "0.0",
                    }
                )
            return blocked, 0, 0.0

        stage_started = time.perf_counter()

        if stage.startswith("parallel "):
            result = self._parallel_stage(stage, current_output, current_data)
        elif current_type == PipelineType.GENERATOR and current_data is not None:
            result = self._stage_over_iterable(stage, current_data, lazy=True)
        elif self._is_stream_type(current_type) and isinstance(current_data, Iterable) and not isinstance(current_data, (str, bytes, dict)):
            result = self._stage_over_iterable(stage, current_data)
        else:
            result = self._route_single(stage, current_output, current_data)

        duration_ms = (time.perf_counter() - stage_started) * 1000
        cpu_percent, rss_mb = self._sample_resources()

        rows_processed = 0
        if isinstance(current_data, list):
            rows_processed = len(current_data)
        elif current_type == PipelineType.GENERATOR and current_data is not None:
            rows_processed = len(result.data) if isinstance(result.data, list) else 0
        elif isinstance(current_output, str) and current_output:
            rows_processed = len(current_output.splitlines())

        if emit_event:
            event_payload = {
                "stage": stage,
                "node": node_name or stage,
                "error": result.error or "",
                "output": result.output[:200],
                "data_type": result.data_type.value,
                "trace_id": self.current_trace_id,
                "duration_ms": f"{duration_ms:.3f}",
                "rows_processed": str(rows_processed),
                "cpu_percent": f"{cpu_percent:.2f}",
                "rss_mb": f"{rss_mb:.2f}",
                "cost_estimate": f"{duration_ms * 0.0001:.6f}",
            }
            self.events.emit(event_payload)
            self.flow_state.add_event(stage)

        data_preview = ""
        if isinstance(current_data, (list, dict, str, int, float)):
            data_preview = str(current_data)
        self.lens.record(stage, result, self.current_trace_id, data_preview)

        return result, rows_processed, duration_ms

    def _sample_resources(self) -> tuple[float, float]:
        try:
            import psutil

            proc = psutil.Process(os.getpid())
            return proc.cpu_percent(interval=0.0), proc.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0, 0.0

    def _materialize_if_generator(self, result: CommandResult) -> CommandResult:
        if result.data_type != PipelineType.GENERATOR or result.data is None:
            return result

        try:
            values = list(result.data)
            output = "\n".join(str(v) for v in values)
            if output:
                output += "\n"
            return CommandResult(output=output, data=values, data_type=PipelineType.OBJECT_STREAM)
        except RuntimeError as exc:
            return CommandResult(output="", error=str(exc), data_type=PipelineType.GENERATOR)

    def _pipeline_type_from_value(self, value: Any) -> PipelineType:
        if isinstance(value, list):
            return PipelineType.OBJECT_STREAM
        if isinstance(value, dict):
            return PipelineType.OBJECT
        return PipelineType.TEXT

    def _route_internal_with_input(
        self,
        command: str,
        *,
        initial_output: str,
        initial_data: Any,
        initial_type: PipelineType,
    ) -> CommandResult:
        owns_trace = False
        if not self.current_trace_id:
            self.current_trace_id = uuid.uuid4().hex[:12]
            owns_trace = True

        stages = self._split_pipeline(command)
        graph = self._build_pipeline_graph(stages)
        current_output = initial_output
        current_data = initial_data
        current_type = initial_type

        for node in graph.nodes:
            for index, stage in enumerate(node.stages):
                last_stage_in_node = index == len(node.stages) - 1
                result, _, _ = self._execute_stage(
                    stage,
                    current_output,
                    current_data,
                    current_type,
                    emit_event=last_stage_in_node,
                    node_name=node.name,
                )
                if result.error:
                    if owns_trace:
                        self.current_trace_id = ""
                    return result
                current_output = result.output
                current_data = result.data
                current_type = result.data_type

        final_result = self._materialize_if_generator(
            CommandResult(output=current_output, data=current_data, data_type=current_type)
        )
        if owns_trace:
            self.current_trace_id = ""
        return final_result

    def _route_with_input(self, command: str, value: Any) -> CommandResult:
        input_text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return self._route_internal_with_input(
            command,
            initial_output=input_text,
            initial_data=value,
            initial_type=self._pipeline_type_from_value(value),
        )

    def _route_internal(self, command: str) -> CommandResult:
        result = self._route_internal_with_input(
            command,
            initial_output="",
            initial_data=None,
            initial_type=PipelineType.TEXT,
        )
        if not command.strip().startswith("studio graph"):
            self.last_graph = self._build_pipeline_graph(self._split_pipeline(command))
        return result

    async def route_async(self, command: str) -> CommandResult:
        return self._route_internal(command)

    def route(self, command: str) -> CommandResult:
        if threading.get_ident() != self._loop_owner_thread:
            return asyncio.run(self.route_async(command))
        if self.loop.is_running():
            return self._route_internal(command)
        return self.loop.run_until_complete(self.route_async(command))

    def _parse_repl_python_command(self, command: str) -> tuple[str, str] | None:
        stripped = command.strip()
        if stripped == "py":
            return "py", ""
        if stripped.startswith("py "):
            return "py", stripped[3:]
        if stripped == "python":
            return "python", ""
        if stripped.startswith("python "):
            return "python", stripped[7:]
        return None

    def _python_block_incomplete(self, code: str) -> bool:
        if not code:
            return False
        try:
            return codeop.compile_command(code, symbol="exec") is None
        except (OverflowError, SyntaxError, ValueError, TypeError):
            return False

    def _read_repl_command(self) -> str:
        command = input(f"{self.cwd} > ").rstrip()
        parsed = self._parse_repl_python_command(command)
        if parsed is None:
            return command.strip()

        prefix, code = parsed
        if not self._python_block_incomplete(code):
            return command.strip()

        lines = [code]
        while True:
            next_line = input("... ").rstrip()
            lines.append(next_line)
            if not self._python_block_incomplete("\n".join(lines)):
                break
        return f"{prefix} " + "\n".join(lines)

    def repl(self) -> None:
        print(f"NovaShell {__version__} Compute Runtime")
        print(
            "Commands: py | cpp | gpu | wasm | jit_wasm | data | data.load | remote | mesh | ai | agent | memory | tool | event | vision | fabric | guard | secure | flow | sync | lens | studio | on | pack | observe | watch | parallel | events | ns.exec | ns.run | sys | cd | pwd | clear | cls | doctor | help | exit"
        )
        print("Pipelines: cmd | watch file | parallel py ...\n")

        while True:
            try:
                command = self._read_repl_command()
                if not command:
                    continue

                result = self.route(command)
                if result.output:
                    print(result.output, end="" if result.output.endswith("\n") else "\n")
                if result.error:
                    print(f"ERROR: {result.error}")
            except KeyboardInterrupt:
                print()
            except EOFError:
                print("\nbye")
                return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nova-shell", description="Nova-shell unified compute runtime")
    parser.add_argument("-c", "--command", help="run a single command and exit")
    parser.add_argument("--no-plugins", action="store_true", help="skip plugin discovery")
    parser.add_argument("--version", action="store_true", help="print the Nova-shell version")
    parser.add_argument("--serve-worker", action="store_true", help="run a local mesh worker HTTP server")
    parser.add_argument("--worker-host", default="127.0.0.1", help="host for --serve-worker")
    parser.add_argument("--worker-port", type=int, default=8769, help="port for --serve-worker")
    parser.add_argument("--worker-caps", default="cpu,py,ai", help="comma-separated capabilities for --serve-worker")
    args = parser.parse_args(argv)

    if args.version:
        print(f"nova-shell {__version__}")
        return 0

    shell = NovaShell()
    if not args.no_plugins:
        shell.load_plugins()

    if args.serve_worker:
        caps = {cap.strip() for cap in args.worker_caps.split(",") if cap.strip()}
        worker_server = MeshWorkerServer(shell, caps)
        return worker_server.serve(args.worker_host, args.worker_port)

    if args.command is not None:
        result = shell.route(args.command)
        if result.output:
            print(result.output, end="" if result.output.endswith("\n") else "\n")
        if result.error:
            print(f"ERROR: {result.error}", file=sys.stderr)
            return 1
        return 0

    shell.repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

