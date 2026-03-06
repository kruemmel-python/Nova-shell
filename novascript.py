from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import textwrap


@dataclass
class Node:
    pass


@dataclass
class Assignment(Node):
    name: str
    command: str


@dataclass
class Command(Node):
    command: str


@dataclass
class ForLoop(Node):
    var: str
    iterable: str
    body: list[Node]


@dataclass
class IfBlock(Node):
    condition: str
    body: list[Node]


class NovaParser:
    """Parse a small NovaScript subset into an AST."""

    def parse(self, script: str) -> list[Node]:
        normalized = textwrap.dedent(script)
        lines = [line.rstrip("\n") for line in normalized.splitlines() if line.strip()]
        nodes, _ = self._parse_block(lines, 0, 0)
        return nodes

    def parse_file(self, file_path: str | Path) -> list[Node]:
        source = Path(file_path).read_text(encoding="utf-8")
        return self.parse(source)

    def _parse_block(self, lines: list[str], start: int, indent: int) -> tuple[list[Node], int]:
        nodes: list[Node] = []
        i = start

        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip(" "))

            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"Unexpected indentation at line: {line}")

            statement = line.strip()

            if statement.startswith("for ") and statement.endswith(":"):
                header = statement[4:-1].strip()
                var, iterable = header.split(" in ", 1)
                body, i = self._parse_block(lines, i + 1, indent + 4)
                nodes.append(ForLoop(var=var.strip(), iterable=iterable.strip(), body=body))
                continue

            if statement.startswith("if ") and statement.endswith(":"):
                condition = statement[3:-1].strip()
                body, i = self._parse_block(lines, i + 1, indent + 4)
                nodes.append(IfBlock(condition=condition, body=body))
                continue

            if "=" in statement and not statement.startswith(("py ", "sys ", "cpp ", "gpu ", "data ", "data.load")):
                name, command = statement.split("=", 1)
                nodes.append(Assignment(name=name.strip(), command=command.strip()))
            else:
                nodes.append(Command(statement))

            i += 1

        return nodes, i


class NovaInterpreter:
    """Execute NovaScript AST nodes against a NovaShell instance."""

    def __init__(self, shell: Any):
        self.shell = shell
        self.variables: dict[str, str] = {}

    def execute(self, nodes: list[Node]) -> str:
        last_output = ""
        for node in nodes:
            last_output = self.run_node(node)
        return last_output

    def run_node(self, node: Node) -> str:
        match node:
            case Assignment(name=name, command=command):
                resolved = self._inject_variables(command)
                result = self.shell.route(resolved)
                if result.error:
                    raise RuntimeError(result.error)
                self.variables[name] = result.output
                return result.output

            case Command(command=command):
                resolved = self._inject_variables(command)
                result = self.shell.route(resolved)
                if result.error:
                    raise RuntimeError(result.error)
                return result.output

            case ForLoop(var=var, iterable=iterable, body=body):
                iterable_value = self.variables.get(iterable, "")
                aggregated: list[str] = []
                for item in iterable_value.splitlines():
                    self.variables[var] = item
                    for subnode in body:
                        output = self.run_node(subnode)
                        if output:
                            aggregated.append(output)
                return "".join(aggregated)

            case IfBlock(condition=condition, body=body):
                if not self._eval_condition(condition):
                    return ""
                aggregated: list[str] = []
                for subnode in body:
                    output = self.run_node(subnode)
                    if output:
                        aggregated.append(output)
                return "".join(aggregated)

            case _:
                raise TypeError(f"Unsupported node: {node}")

    def _inject_variables(self, command: str) -> str:
        is_python = command.startswith("py ") or command.startswith("python ")
        for name, value in self.variables.items():
            replacement = repr(value.strip()) if is_python else value.strip()
            command = command.replace(f"${name}", replacement)
        return command

    def _eval_condition(self, condition: str) -> bool:
        safe_locals: dict[str, Any] = {}
        for key, value in self.variables.items():
            safe_locals[key] = value
            safe_locals[f"{key}_lines"] = value.splitlines()

        safe_builtins = {"len": len, "int": int, "float": float, "str": str}
        return bool(eval(condition, {"__builtins__": safe_builtins}, safe_locals))
