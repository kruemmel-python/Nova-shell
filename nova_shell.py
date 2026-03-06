from __future__ import annotations

import atexit
import contextlib
import io
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import readline
except ImportError:  # pragma: no cover - platform dependent
    readline = None


@dataclass
class CommandResult:
    output: str
    error: str | None = None


class PythonEngine:
    """Execute Python snippets with optional pipeline input."""

    def execute(self, code: str, pipeline_input: str = "") -> CommandResult:
        local_context: dict[str, Any] = {"_": pipeline_input}
        stdout_buffer = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buffer):
                try:
                    value = eval(code, {}, local_context)
                    if value is not None:
                        print(value)
                except SyntaxError:
                    exec(code, {}, local_context)

            return CommandResult(output=stdout_buffer.getvalue())
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
            error=proc.stderr if proc.stderr else None,
        )


class NovaShell:
    def __init__(self) -> None:
        self.cwd = Path.cwd()
        self.python = PythonEngine()
        self.cpp = CppEngine()
        self.system = SystemEngine()

        self.commands: dict[str, Callable[[str, str], CommandResult]] = {
            "py": self._run_python,
            "python": self._run_python,
            "cpp": self._run_cpp,
            "sys": self._run_system,
            "cd": self._cd,
            "pwd": self._pwd,
            "help": self._help,
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

    def register_command(self, name: str, handler: Callable[[str, str], CommandResult]) -> None:
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

    def _cd(self, path_arg: str, _: str) -> CommandResult:
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

    def _pwd(self, _: str, __: str) -> CommandResult:
        return CommandResult(output=f"{self.cwd}\n")

    def _help(self, _: str, __: str) -> CommandResult:
        commands = "\n".join(sorted(self.commands.keys()))
        return CommandResult(output=f"Commands:\n{commands}\n")

    def _run_python(self, code: str, pipeline_input: str) -> CommandResult:
        return self.python.execute(code, pipeline_input)

    def _run_cpp(self, code: str, pipeline_input: str) -> CommandResult:
        return self.cpp.compile_and_run(code, pipeline_input)

    def _run_system(self, command: str, pipeline_input: str) -> CommandResult:
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

    def _route_single(self, command: str, pipeline_input: str = "") -> CommandResult:
        parts = shlex.split(command)
        if not parts:
            return CommandResult(output="")

        cmd = parts[0]
        rest = command[len(cmd) :].strip()

        match cmd:
            case "exit":
                raise SystemExit(0)
            case _ if cmd in self.commands:
                return self.commands[cmd](rest, pipeline_input)
            case _:
                return self._run_system(command, pipeline_input)

    def route(self, command: str) -> CommandResult:
        stages = self._split_pipeline(command)
        current_output = ""

        for stage in stages:
            result = self._route_single(stage, current_output)
            if result.error:
                return result
            current_output = result.output

        return CommandResult(output=current_output)

    def repl(self) -> None:
        print("NovaShell 0.3")
        print("Commands: py | cpp | sys | cd | pwd | help | exit")
        print("Pipelines: cmd | py ... | cmd\n")

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
