from __future__ import annotations

import atexit
import asyncio
import contextlib
import csv
import inspect
import io
import http.server
import threading
import time
import json
import os
import glob
import shlex
import subprocess
import tempfile
import zipfile
import uuid
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Callable, Iterable

from novascript import NovaInterpreter, NovaParser

try:
    import readline
except ImportError:  # pragma: no cover - platform dependent
    readline = None


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


class PythonEngine:
    """Execute Python snippets with optional pipeline input and persistent globals."""

    def __init__(self) -> None:
        self.globals: dict[str, Any] = {}

    def execute(self, code: str, pipeline_input: str = "", pipeline_data: Any = None) -> CommandResult:
        self.globals["_"] = pipeline_data if pipeline_data is not None else pipeline_input
        stdout_buffer = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buffer):
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
            binary = Path(tmp) / "program"

            source.write_text(code, encoding="utf-8")

            compile_proc = subprocess.run(
                ["g++", "-std=c++20", "-O2", str(source), "-o", str(binary)],
                capture_output=True,
                text=True,
            )
            if compile_proc.returncode != 0:
                return CommandResult(output="", error=compile_proc.stderr)

            run_proc = subprocess.run(
                [str(binary)],
                capture_output=True,
                text=True,
                input=pipeline_input,
            )
            return CommandResult(
                output=run_proc.stdout,
                error=run_proc.stderr if run_proc.stderr else None,
            )


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

    def execute(self, command: str, pipeline_input: str = "") -> CommandResult:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            input=pipeline_input,
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

    def put(self, value: str) -> CommandResult:
        payload = value.encode("utf-8")
        segment = shared_memory.SharedMemory(create=True, size=max(1, len(payload)))
        if payload:
            segment.buf[: len(payload)] = payload
        handle = segment.name
        self._segments[handle] = segment
        return CommandResult(
            output=f"{handle}\n",
            data={"handle": handle, "size": len(payload)},
            data_type=PipelineType.SHARED_MEMORY,
        )

    def get(self, handle: str) -> CommandResult:
        segment = self._segments.get(handle)
        if segment is None:
            try:
                segment = shared_memory.SharedMemory(name=handle)
            except FileNotFoundError:
                return CommandResult(output="", error=f"shared memory handle not found: {handle}")

        data = bytes(segment.buf).rstrip(b"\x00").decode("utf-8", errors="replace")
        return CommandResult(output=f"{data}\n", data=data, data_type=PipelineType.TEXT)

    def cleanup(self) -> None:
        for handle, segment in list(self._segments.items()):
            with contextlib.suppress(Exception):
                segment.close()
            with contextlib.suppress(Exception):
                segment.unlink()
            self._segments.pop(handle, None)


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

        parts = shlex.split(stage)
        if not parts:
            return True, None
        cmd = parts[0]
        if cmd in denied:
            return False, f"policy '{policy}' blocks command '{cmd}'"
        return True, None


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
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/events":
                    data = shell.events.events
                elif self.path == "/graph":
                    data = {
                        "nodes": [
                            {"name": node.name, "stages": node.stages, "parallel": node.parallel}
                            for node in shell.last_graph.nodes
                        ]
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return

                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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
        self.policy = PolicyEngine()
        self.last_graph = PipelineGraph()
        self.vision = VisionServer(self)
        self.current_policy = "open"
        self.current_trace_id = ""

        self.commands: dict[str, Callable[[str, str, Any], CommandResult]] = {
            "py": self._run_python,
            "python": self._run_python,
            "cpp": self._run_cpp,
            "gpu": self._run_gpu,
            "wasm": self._run_wasm,
            "data": self._run_data,
            "data.load": self._run_data_load,
            "remote": self._run_remote,
            "ai": self._run_ai,
            "vision": self._run_vision,
            "fabric": self._run_fabric,
            "guard": self._run_guard,
            "secure": self._run_secure,
            "on": self._run_on,
            "pack": self._run_pack,
            "observe": self._run_observe,
            "watch": self._watch,
            "sys": self._run_system,
            "cd": self._cd,
            "pwd": self._pwd,
            "help": self._help,
            "events": self._events,
            "ns.exec": self._ns_exec,
            "ns.run": self._ns_run,
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
        self.fabric.cleanup()
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

    def _cd(self, path_arg: str, _: str, __: Any) -> CommandResult:
        target_text = path_arg.strip() or "~"
        try:
            target = Path(os.path.expanduser(target_text))
            if not target.is_absolute():
                target = (self.cwd / target).resolve()
            if not target.exists() or not target.is_dir():
                return CommandResult(output="", error=f"directory not found: {target_text}")
            os.chdir(target)
            self.cwd = target
            return CommandResult(output="")
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _pwd(self, _: str, __: str, ___: Any) -> CommandResult:
        return CommandResult(output=f"{self.cwd}\n", data=str(self.cwd), data_type=PipelineType.TEXT)

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
        with file_path.open("r", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            deadline = time.time() + follow_seconds
            while time.time() < deadline:
                line = handle.readline()
                if line:
                    yield line.rstrip("\n")
                    continue
                time.sleep(0.05)

    def _watch(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output="", error="usage: watch <file> [--lines N] [--follow-seconds S]")

        file_path = Path(parts[0])
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
            output = interpreter.execute(nodes)
            return CommandResult(output=output)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _ns_run(self, file_path: str, _: str, __: Any) -> CommandResult:
        script_path = file_path.strip()
        if not script_path:
            return CommandResult(output="", error="usage: ns.run <script.ns>")

        try:
            parser = NovaParser()
            interpreter = NovaInterpreter(self)
            nodes = parser.parse_file(script_path)
            output = interpreter.execute(nodes)
            return CommandResult(output=output)
        except Exception as exc:
            return CommandResult(output="", error=str(exc))

    def _run_python(self, code: str, pipeline_input: str, pipeline_data: Any) -> CommandResult:
        return self.python.execute(code, pipeline_input, pipeline_data)

    def _run_cpp(self, code: str, pipeline_input: str, _: Any) -> CommandResult:
        return self.cpp.compile_and_run(code, pipeline_input)

    def _run_gpu(self, args: str, pipeline_input: str, _: Any) -> CommandResult:
        kernel_file = args.strip()
        if not kernel_file:
            return CommandResult(output="", error="usage: gpu <kernel_file>")
        return self.gpu.run_kernel(kernel_file, pipeline_input)

    def _run_wasm(self, args: str, _: str, __: Any) -> CommandResult:
        wasm_file = args.strip()
        if not wasm_file:
            return CommandResult(output="", error="usage: wasm <module.wasm>")
        return self.wasm.execute(wasm_file)

    def _run_remote(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if len(parts) < 2:
            return CommandResult(output="", error="usage: remote <worker_url> <command>")
        worker_url = parts[0]
        command = args[len(worker_url) :].strip()
        return self.remote.execute(worker_url, command)

    def _run_ai(self, args: str, _: str, __: Any) -> CommandResult:
        prompt = args.strip().strip('"')
        if not prompt:
            return CommandResult(output="", error="usage: ai \"<prompt>\"")

        lowered = prompt.lower()
        if "csv" in lowered and "average" in lowered:
            suggestion = "data load file.csv | py sum(float(r['A']) for r in _) / len(_)"
        elif "anomal" in lowered or "error" in lowered:
            suggestion = "watch logs.txt --follow-seconds 10 | py _.lower()"
        else:
            suggestion = "py # TODO: generated pipeline"

        return CommandResult(output=f"{suggestion}\n", data={"pipeline": suggestion}, data_type=PipelineType.OBJECT)

    def _run_vision(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
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
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output="", error="usage: fabric put <text> | fabric get <handle>")
        match parts[0]:
            case "put":
                value = args[len("put") :].strip()
                return self.fabric.put(value)
            case "get":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: fabric get <handle>")
                return self.fabric.get(parts[1])
            case _:
                return CommandResult(output="", error="usage: fabric put <text> | fabric get <handle>")

    def _run_guard(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output=f"current policy: {self.current_policy}\n")
        match parts[0]:
            case "set":
                if len(parts) < 2:
                    return CommandResult(output="", error="usage: guard set <policy>")
                name = parts[1]
                if name not in self.policy.policies:
                    return CommandResult(output="", error=f"unknown policy: {name}")
                self.current_policy = name
                return CommandResult(output=f"policy set to {name}\n")
            case "list":
                return CommandResult(output="\n".join(sorted(self.policy.policies.keys())) + "\n")
            case _:
                return CommandResult(output="", error="usage: guard [list]|set <policy>")

    def _run_secure(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if len(parts) < 2:
            return CommandResult(output="", error="usage: secure <policy> <command>")
        policy_name = parts[0]
        command = args[len(policy_name) :].strip()
        allowed, reason = self.policy.is_allowed(policy_name, command)
        if not allowed:
            return CommandResult(output="", error=reason)
        return self.route(command)

    def _run_on(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if len(parts) < 4 or parts[0] != "file":
            return CommandResult(output="", error='usage: on file "<glob>" --timeout <seconds> "<pipeline with _>"')

        pattern = parts[1]
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
        parts = shlex.split(args)
        if len(parts) < 1:
            return CommandResult(output="", error="usage: pack <script.ns> --output <bundle.npx> [--requirements req.txt]")

        script_path = Path(parts[0])
        output_path = Path("bundle.npx")
        requirements_path: Path | None = None

        i = 1
        while i < len(parts):
            if parts[i] == "--output" and i + 1 < len(parts):
                output_path = Path(parts[i + 1])
                i += 2
                continue
            if parts[i] == "--requirements" and i + 1 < len(parts):
                requirements_path = Path(parts[i + 1])
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
        parts = shlex.split(args)
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

    def _run_data_load(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output="", error="usage: data.load <csv_file> [--arrow]")
        file_path = parts[0]
        if len(parts) > 1 and parts[1] == "--arrow":
            return self.data.load_csv_arrow(file_path)
        return self.data.load_csv(file_path)

    def _run_data(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output="", error="usage: data load <csv_file> [--arrow]")
        if parts[0] == "load" and len(parts) >= 2:
            if len(parts) > 2 and parts[2] == "--arrow":
                return self.data.load_csv_arrow(parts[1])
            return self.data.load_csv(parts[1])
        return CommandResult(output="", error=f"unknown data command: {' '.join(parts)}")

    def _run_system(self, command: str, pipeline_input: str, _: Any) -> CommandResult:
        return self.system.execute(command, pipeline_input)

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
        parts = shlex.split(command)
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
            self.events.emit(
                {
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
            )

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

    def _route_internal(self, command: str) -> CommandResult:
        owns_trace = False
        if not self.current_trace_id:
            self.current_trace_id = uuid.uuid4().hex[:12]
            owns_trace = True

        stages = self._split_pipeline(command)
        graph = self._build_pipeline_graph(stages)
        self.last_graph = graph
        current_output = ""
        current_data: Any = None
        current_type = PipelineType.TEXT

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

    async def route_async(self, command: str) -> CommandResult:
        return self._route_internal(command)

    def route(self, command: str) -> CommandResult:
        if threading.get_ident() != self._loop_owner_thread:
            return asyncio.run(self.route_async(command))
        if self.loop.is_running():
            return self._route_internal(command)
        return self.loop.run_until_complete(self.route_async(command))

    def repl(self) -> None:
        print("NovaShell 0.7 Compute Runtime")
        print(
            "Commands: py | cpp | gpu | wasm | data | data.load | remote | ai | vision | fabric | guard | secure | on | pack | observe | watch | parallel | events | ns.exec | ns.run | sys | cd | pwd | help | exit"
        )
        print("Pipelines: cmd | watch file | parallel py ...\n")

        while True:
            try:
                command = input(f"{self.cwd} > ").strip()
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


if __name__ == "__main__":
    shell = NovaShell()
    shell.load_plugins()
    shell.repl()
