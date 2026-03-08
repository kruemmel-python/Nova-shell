from __future__ import annotations

import argparse
import atexit
import asyncio
import codeop
import contextlib
import copy
import csv
import inspect
import io
import http.server
import threading
import time
import json
import os
import glob
import fnmatch
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


__version__ = "0.8.0"
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
        self.globals: dict[str, Any] = {}
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
        return [
            {
                "url": w["url"],
                "caps": sorted(w["caps"]),
                "load": w["load"],
                "latency_ms": w.get("latency_ms", 0.0),
                "data_handles": sorted(w.get("data_handles", set())),
                "last_seen": w.get("last_seen", 0.0),
            }
            for w in sorted(self.workers, key=lambda item: (item["load"], item["url"]))
        ]

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

    def close(self) -> None:
        self.conn.close()


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


class NovaAIProviderRuntime:
    """Provider-aware AI runtime with .env loading and local/remote model support."""

    def __init__(self, runtime_config: dict[str, Any], cwd: Path) -> None:
        self.runtime_config = runtime_config
        self.cwd = cwd
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
        if not spec.requires_api_key:
            return True
        return bool(self._provider_api_key(spec))

    def get_active_provider(self) -> str:
        if self.active_provider and self.active_provider in self.provider_specs:
            return self.active_provider
        for provider in ["openai", "anthropic", "gemini", "groq", "openrouter"]:
            if self.is_configured(provider):
                return provider
        for provider in ["lmstudio", "ollama"]:
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
            return CommandResult(output="", error=f"ai provider error ({provider_name}): {exc}")

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

    def _http_json(self, url: str, *, method: str = "GET", payload: Any = None, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
        body = None
        merged_headers = {"User-Agent": "nova-shell/0.8.0"}
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
            data = self._http_json(f"{base_url}/models", headers=headers)
            return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]
        if spec.kind == "ollama-chat":
            data = self._http_json(f"{base_url}/api/tags")
            return [str(item.get("name")) for item in data.get("models", []) if item.get("name")]
        if spec.kind == "gemini-generate-content":
            api_key = self._provider_api_key(spec)
            data = self._http_json(f"{base_url}/models?key={urllib.parse.quote(api_key)}")
            models = []
            for item in data.get("models", []):
                name = str(item.get("name", ""))
                if name.startswith("models/"):
                    name = name[len("models/") :]
                if name:
                    models.append(name)
            return models
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
            )
            text = str(data.get("message", {}).get("content", "")).strip()
            return {"provider": spec.name, "model": model, "text": text, "raw": data}

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
        self.ai_runtime = NovaAIProviderRuntime(self.runtime_config, self.cwd)
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
        self.vision = VisionServer(self)
        self.current_policy = "open"
        self.current_trace_id = ""
        self._ns_runtime: NovaInterpreter | None = None
        self._dflow_subscribers: dict[str, list[str]] = {}
        self.wasm_sandbox_default = bool(self.runtime_config.get("sandbox_default", False))

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
            "agent": self._run_agent,
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
        self.vision.stop()
        self.reactive.clear()
        self.fabric.cleanup()
        self.zero.cleanup()
        self.flow_state.close()
        self.lens.close()
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
        }
        for module_name in list(modules.keys()):
            with contextlib.suppress(Exception):
                __import__(module_name)
                modules[module_name] = True

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
            while time.time() < deadline:
                line = handle.readline()
                if line:
                    yield line.rstrip("\n")
                    continue
                time.sleep(0.05)

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

    def _heuristic_ai_plan(self, prompt: str) -> CommandResult:
        lowered = prompt.lower()
        if "csv" in lowered and "average" in lowered:
            suggestion = "data load file.csv | py sum(float(r['A']) for r in _) / len(_)"
        elif "anomal" in lowered or "error" in lowered:
            suggestion = "watch logs.txt --follow-seconds 10 | py _.lower()"
        elif "event" in lowered or "trigger" in lowered:
            suggestion = "event on task_created 'py _.upper()'"
        else:
            suggestion = "py # TODO: generated pipeline"
        payload = {"pipeline": suggestion, "mode": "heuristic"}
        return CommandResult(output=f"{suggestion}\n", data=payload, data_type=PipelineType.OBJECT)

    def _run_ai(self, args: str, _: str, __: Any) -> CommandResult:
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
            prompt = args[len("plan") :].strip().strip('"')
            if not prompt:
                return CommandResult(output="", error="usage: ai plan <prompt>")
            return self._heuristic_ai_plan(prompt)
        if action == "prompt":
            prompt = args[len("prompt") :].strip().strip('"')
            if not prompt:
                return CommandResult(output="", error="usage: ai prompt <prompt>")
            return self.ai_runtime.complete_prompt(prompt)

        prompt = args.strip().strip('"')
        if not prompt:
            return CommandResult(output="", error="usage: ai <prompt>")
        active_provider = self.ai_runtime.get_active_provider()
        if active_provider:
            provider_result = self.ai_runtime.complete_prompt(prompt)
            if provider_result.error is None:
                return provider_result
        return self._heuristic_ai_plan(prompt)

    def _render_agent_prompt(self, agent: AIAgentDefinition, input_text: str) -> str:
        if "{{input}}" in agent.prompt_template:
            return agent.prompt_template.replace("{{input}}", input_text)
        if "{input}" in agent.prompt_template:
            try:
                return agent.prompt_template.format(input=input_text)
            except Exception:
                pass
        suffix = f"\n\nInput:\n{input_text}" if input_text else ""
        return agent.prompt_template + suffix

    def _run_agent(self, args: str, _: str, __: Any) -> CommandResult:
        parts = split_command(args)
        if not parts:
            return CommandResult(output="", error="usage: agent create|run|show|list ...")

        action = parts[0]
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
                return CommandResult(output="", error="usage: agent run <name> [input]")
            agent = self.agents.get(parts[1])
            if agent is None:
                return CommandResult(output="", error="agent not found")
            input_text = args.split(parts[1], 1)[1].strip()
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

        return CommandResult(output="", error="usage: agent create|run|show|list ...")

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
            return CommandResult(output="", error="usage: mesh add|list|run|intelligent-run|beat ...")

        action = parts[0]
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
        return CommandResult(output="", error="usage: mesh add|list|run|intelligent-run|beat ...")

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
            return CommandResult(output="", error="usage: lens list [n] | lens last | lens show <id> | lens replay <id>")
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
        return CommandResult(output="", error="usage: lens list [n] | lens last | lens show <id> | lens replay <id>")

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
            "Commands: py | cpp | gpu | wasm | jit_wasm | data | data.load | remote | mesh | ai | agent | event | vision | fabric | guard | secure | flow | sync | lens | studio | on | pack | observe | watch | parallel | events | ns.exec | ns.run | sys | cd | pwd | clear | cls | doctor | help | exit"
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
    args = parser.parse_args(argv)

    if args.version:
        print(f"nova-shell {__version__}")
        return 0

    shell = NovaShell()
    if not args.no_plugins:
        shell.load_plugins()

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

