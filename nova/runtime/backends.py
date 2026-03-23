from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .context import CommandExecution

if TYPE_CHECKING:
    from .context import RuntimeContext


@dataclass(slots=True)
class BackendExecutionRequest:
    operation: str
    arguments: tuple[str, ...]
    metadata: dict[str, Any]


class LocalPythonBackend:
    def __init__(self) -> None:
        self.globals: dict[str, Any] = {"os": os, "json": json, "sys": sys, "Path": Path}

    @contextlib.contextmanager
    def _push_context(self, context: "RuntimeContext") -> Any:
        base_path = context.base_path.resolve(strict=False)
        previous_cwd = Path.cwd()
        inserted = False
        base_text = str(base_path)
        if base_text not in sys.path:
            sys.path.insert(0, base_text)
            inserted = True
        os.chdir(base_path)
        try:
            yield
        finally:
            os.chdir(previous_cwd)
            if inserted:
                with contextlib.suppress(ValueError):
                    sys.path.remove(base_text)

    def execute(self, code: str, inputs: list[Any], context: "RuntimeContext") -> CommandExecution:
        stdout_buffer = io.StringIO()
        self.globals["context"] = context
        self.globals["_"] = inputs[0] if len(inputs) == 1 else (inputs if inputs else None)

        try:
            with self._push_context(context), contextlib.redirect_stdout(stdout_buffer):
                try:
                    value = eval(code, self.globals, self.globals)
                    if value is not None:
                        self.globals["_"] = value
                        print(value)
                except SyntaxError:
                    exec(code, self.globals, self.globals)
                    value = self.globals.get("_")
            return CommandExecution(output=stdout_buffer.getvalue(), data=value)
        except Exception as exc:
            return CommandExecution(error=str(exc))


class LocalSystemBackend:
    def execute(self, command: str, input_value: Any, cwd: Path) -> CommandExecution:
        input_text = input_value if isinstance(input_value, str) else json.dumps(input_value, ensure_ascii=False) if input_value is not None else ""
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, input=input_text, cwd=str(cwd))
        return CommandExecution(output=proc.stdout, data=proc.stdout, error=proc.stderr or None, metadata={"returncode": proc.returncode})


class ShellCommandBackend:
    def __init__(self, command_executor: Any | None) -> None:
        self.command_executor = command_executor

    def execute(self, command: str, input_value: Any, cwd: Path) -> CommandExecution:
        if self.command_executor is None:
            return CommandExecution(error="shell command executor not configured")
        return self.command_executor.execute(command, pipeline_data=input_value, cwd=cwd)


class BackendRouter:
    """Routes declarative Nova operations to local or shell-backed runtime executors."""

    def __init__(self, command_executor: Any | None = None, *, executor_manager: Any | None = None) -> None:
        self.python = LocalPythonBackend()
        self.system = LocalSystemBackend()
        self.shell = ShellCommandBackend(command_executor)
        self.executor_manager = executor_manager

    def execute(self, request: BackendExecutionRequest, context: "RuntimeContext") -> CommandExecution:
        operation = request.operation
        resolved_inputs = [context.resolve_reference(argument) for argument in request.arguments[1:]]
        primary_input = resolved_inputs[0] if len(resolved_inputs) == 1 else resolved_inputs if resolved_inputs else None

        native_backend = self._native_backend_for_operation(operation)
        if native_backend is not None and self.executor_manager is not None:
            try:
                from nova.mesh.protocol import ExecutorTask

                task = ExecutorTask(
                    request_id=f"{native_backend}-{abs(hash((operation, tuple(request.arguments)))):x}"[:16],
                    capability=native_backend,
                    kind="backend",
                    operation=operation,
                    arguments=list(request.arguments),
                    command=request.arguments[0] if request.arguments else None,
                    pipeline_data=primary_input,
                    metadata={
                        **dict(request.metadata),
                        "base_path": str(context.base_path),
                    },
                )
                return self.executor_manager.execute(native_backend, task)
            except Exception as exc:
                if operation not in {"py.exec", "cpp.exec", "cpp.sandbox", "gpu.run", "wasm.run"}:
                    return CommandExecution(error=str(exc))

        match operation:
            case "py.exec":
                if not request.arguments:
                    return CommandExecution(error="py.exec requires python code")
                return self.python.execute(request.arguments[0], resolved_inputs, context)
            case "sys.exec" | "system.exec":
                if not request.arguments:
                    return CommandExecution(error=f"{operation} requires a command")
                return self.system.execute(request.arguments[0], primary_input, context.base_path)
            case "data.load":
                if not request.arguments:
                    return CommandExecution(error="data.load requires a file path")
                return self._load_data(request.arguments[0], context.base_path)
            case "mesh.dispatch":
                if len(request.arguments) < 2:
                    return CommandExecution(error="mesh.dispatch requires <capability> <command>")
                capability = request.arguments[0]
                command = request.arguments[1]
                task = {"kind": "backend", "operation": operation, "command": command, "arguments": list(request.arguments[2:])}
                return context.mesh.dispatch(capability, task, lambda: self.shell.execute(command, primary_input, context.base_path))
            case _:
                command = self._build_shell_command(request, context)
                return self.shell.execute(command, primary_input, context.base_path)

    def _native_backend_for_operation(self, operation: str) -> str | None:
        if operation == "py.exec":
            return "py"
        if operation in {"cpp.exec", "cpp.sandbox"}:
            return "cpp"
        if operation == "gpu.run":
            return "gpu"
        if operation == "wasm.run":
            return "wasm"
        if operation in {"ai.prompt", "atheria.chat", "atheria.search", "memory.embed", "memory.search"}:
            return "ai"
        return None

    def _build_shell_command(self, request: BackendExecutionRequest, context: "RuntimeContext") -> str:
        operation = request.operation
        arguments = list(request.arguments)

        if operation == "py.exec" and arguments:
            return f"py {arguments[0]}"
        if operation in {"sys.exec", "system.exec"} and arguments:
            return f"sys {arguments[0]}"
        if operation == "data.load" and arguments:
            return f"data.load {json.dumps(arguments[0], ensure_ascii=False)}"
        if operation == "ai.prompt" and arguments:
            return f'ai prompt {json.dumps(arguments[0], ensure_ascii=False)}'
        if operation == "atheria.chat" and arguments:
            return f'atheria chat {json.dumps(arguments[0], ensure_ascii=False)}'
        if operation == "atheria.search" and arguments:
            return f'atheria search {json.dumps(arguments[0], ensure_ascii=False)}'
        if operation == "memory.embed" and arguments:
            return f'memory embed {json.dumps(arguments[0], ensure_ascii=False)}'
        if operation == "memory.search" and arguments:
            return f'memory search {json.dumps(arguments[0], ensure_ascii=False)}'
        if operation in {"cpp.exec", "cpp.sandbox", "gpu.run", "wasm.run"} and arguments:
            prefix = {
                "cpp.exec": "cpp",
                "cpp.sandbox": "cpp.sandbox",
                "gpu.run": "gpu",
                "wasm.run": "wasm",
            }[operation]
            return f"{prefix} {json.dumps(arguments[0], ensure_ascii=False)}"

        rendered_arguments = " ".join(json.dumps(str(context.resolve_reference(argument)), ensure_ascii=False) for argument in arguments)
        return f"{operation} {rendered_arguments}".strip()

    def _load_data(self, path_text: str, base_path: Path) -> CommandExecution:
        target = Path(path_text)
        if not target.is_absolute():
            target = (base_path / target).resolve(strict=False)
        if not target.exists():
            return CommandExecution(error=f"data file not found: {target}")
        if target.is_dir():
            entries: list[dict[str, Any]] = []
            try:
                children = sorted(target.iterdir(), key=lambda item: item.name.lower())
            except OSError as exc:
                return CommandExecution(error=str(exc))
            for child in children:
                try:
                    stat = child.stat()
                except OSError as exc:
                    entries.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "kind": "unknown",
                            "extension": child.suffix.lower(),
                            "error": str(exc),
                        }
                    )
                    continue
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "kind": "directory" if child.is_dir() else "file" if child.is_file() else "other",
                        "extension": child.suffix.lower() if child.is_file() else "",
                        "size": stat.st_size if child.is_file() else None,
                        "modified_at": stat.st_mtime,
                    }
                )
            return CommandExecution(output=json.dumps(entries, ensure_ascii=False), data=entries)
        if target.suffix.lower() == ".json":
            data = json.loads(target.read_text(encoding="utf-8"))
            return CommandExecution(output=json.dumps(data, ensure_ascii=False), data=data)
        rows = [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
        return CommandExecution(output="\n".join(rows), data=rows)
