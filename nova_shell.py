from __future__ import annotations

import atexit
import asyncio
import contextlib
import csv
import inspect
import io
import json
import os
import shlex
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
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


@dataclass
class CommandResult:
    output: str
    data: Any = None
    error: str | None = None
    data_type: PipelineType = PipelineType.TEXT


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


class NovaShell:
    def __init__(self) -> None:
        self.cwd = Path.cwd()
        self.python = PythonEngine()
        self.cpp = CppEngine()
        self.gpu = GPUEngine()
        self.data = DataEngine()
        self.system = SystemEngine()
        self.events = EventBus()

        self.commands: dict[str, Callable[[str, str, Any], CommandResult]] = {
            "py": self._run_python,
            "python": self._run_python,
            "cpp": self._run_cpp,
            "gpu": self._run_gpu,
            "data": self._run_data,
            "data.load": self._run_data_load,
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
        return CommandResult(output="Usage: events last|clear\n")

    def _watch(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output="", error="usage: watch <file> [--lines N]")

        file_path = Path(parts[0])
        lines_count = 10
        if len(parts) == 3 and parts[1] == "--lines":
            lines_count = int(parts[2])

        if not file_path.exists():
            return CommandResult(output="", error=f"file not found: {file_path}")

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

    def _run_data_load(self, args: str, _: str, __: Any) -> CommandResult:
        file_path = args.strip()
        if not file_path:
            return CommandResult(output="", error="usage: data.load <csv_file>")
        return self.data.load_csv(file_path)

    def _run_data(self, args: str, _: str, __: Any) -> CommandResult:
        parts = shlex.split(args)
        if not parts:
            return CommandResult(output="", error="usage: data load <csv_file>")
        if parts[0] == "load" and len(parts) >= 2:
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

        items = pipeline_data if isinstance(pipeline_data, list) else pipeline_output.splitlines()
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
        return data_type in {PipelineType.TEXT_STREAM}

    def _stage_over_stream(self, stage: str, stream_data: Iterable[Any]) -> CommandResult:
        outputs: list[str] = []
        collected_data: list[Any] = []
        for item in stream_data:
            item_text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            result = self._route_single(stage, item_text, item)
            if result.error:
                return result
            outputs.append(result.output)
            collected_data.append(result.data)

        return CommandResult(output="".join(outputs), data=collected_data, data_type=PipelineType.OBJECT_STREAM)

    async def route_async(self, command: str) -> CommandResult:
        stages = self._split_pipeline(command)
        current_output = ""
        current_data: Any = None
        current_type = PipelineType.TEXT

        for stage in stages:
            if stage.startswith("parallel "):
                result = await asyncio.to_thread(self._parallel_stage, stage, current_output, current_data)
            elif self._is_stream_type(current_type) and isinstance(current_data, Iterable) and not isinstance(current_data, (str, bytes, dict)):
                result = await asyncio.to_thread(self._stage_over_stream, stage, current_data)
            else:
                result = await asyncio.to_thread(self._route_single, stage, current_output, current_data)

            self.events.emit(
                {
                    "stage": stage,
                    "error": result.error or "",
                    "output": result.output[:200],
                    "data_type": result.data_type.value,
                }
            )
            if result.error:
                return result
            current_output = result.output
            current_data = result.data
            current_type = result.data_type

        return CommandResult(output=current_output, data=current_data, data_type=current_type)

    def route(self, command: str) -> CommandResult:
        return asyncio.run(self.route_async(command))

    def repl(self) -> None:
        print("NovaShell 0.6 Compute Runtime")
        print(
            "Commands: py | cpp | gpu | data | data.load | watch | parallel | events | ns.exec | ns.run | sys | cd | pwd | help | exit"
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
