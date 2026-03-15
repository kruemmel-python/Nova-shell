from __future__ import annotations

from dataclasses import dataclass
import ast
import json
from pathlib import Path
import shlex
from types import SimpleNamespace
from typing import Any
import textwrap


@dataclass
class Node:
    pass


@dataclass
class Assignment(Node):
    name: str
    command: str
    declared_type: str | None = None


@dataclass
class Command(Node):
    command: str
    output_contract: str | None = None


@dataclass
class ForLoop(Node):
    var: str
    iterable: str
    body: list[Node]


@dataclass
class IfBlock(Node):
    condition: str
    body: list[Node]


@dataclass
class WatchHook(Node):
    variable: str
    body: list[Node]


class NovaParser:
    """Parse a small NovaScript subset into an AST."""

    def parse(self, script: str) -> list[Node]:
        normalized = textwrap.dedent(script)
        lines = [line.rstrip("\n") for line in normalized.splitlines() if line.strip() and not line.lstrip().startswith("#")]
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

            if statement.startswith("watch ") and statement.endswith(":"):
                variable = statement[6:-1].strip()
                body, i = self._parse_block(lines, i + 1, indent + 4)
                nodes.append(WatchHook(variable=variable, body=body))
                continue

            statement, output_contract = self._split_output_contract(statement)

            if "=" in statement and not statement.startswith(("py ", "sys ", "cpp ", "gpu ", "data ", "data.load")):
                name, command = statement.split("=", 1)
                name_part = name.strip()
                declared_type = None
                if ":" in name_part:
                    var_name, type_name = name_part.split(":", 1)
                    name_part = var_name.strip()
                    declared_type = type_name.strip() or None
                nodes.append(Assignment(name=name_part, command=command.strip(), declared_type=declared_type))
            else:
                nodes.append(Command(statement, output_contract=output_contract))

            i += 1

        return nodes, i

    def _split_output_contract(self, statement: str) -> tuple[str, str | None]:
        in_single = False
        in_double = False
        escaped = False

        for index, char in enumerate(statement):
            if escaped:
                escaped = False
                continue
            if char == "\\" and (in_single or in_double):
                escaped = True
                continue
            if char == "'" and not in_double:
                in_single = not in_single
                continue
            if char == '"' and not in_single:
                in_double = not in_double
                continue
            if char == "-" and not in_single and not in_double and index + 1 < len(statement) and statement[index + 1] == ">":
                left = statement[:index]
                right = statement[index + 2 :]
                if left.rstrip() != left or right.lstrip() != right:
                    return left.strip(), right.strip() or None

        return statement, None


class NovaInterpreter:
    """Execute NovaScript AST nodes against a NovaShell instance."""

    def __init__(self, shell: Any):
        self.shell = shell
        self.variables: dict[str, Any] = {}
        self.watchers: dict[str, list[list[Node]]] = {}

    def execute(self, nodes: list[Node]) -> str:
        last_output = ""
        for node in nodes:
            last_output = self.run_node(node)
        return last_output

    def _normalize_type_name(self, value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    def _result_type_name(self, result: Any) -> str:
        data_type = getattr(result, "data_type", None)
        if data_type is None:
            return "text"
        raw = getattr(data_type, "value", str(data_type))
        return self._normalize_type_name(str(raw))

    def _validate_contract(self, expected: str | None, result: Any, context: str) -> None:
        if not expected:
            return
        normalized_expected = self._normalize_type_name(expected)
        actual = self._result_type_name(result)
        if actual != normalized_expected:
            raise RuntimeError(f"contract violation in {context}: expected {normalized_expected}, got {actual}")

    def _trigger_watch(self, variable: str) -> str:
        blocks = self.watchers.get(variable, [])
        if not blocks:
            return ""
        outputs: list[str] = []
        for body in blocks:
            for subnode in body:
                out = self.run_node(subnode)
                if out:
                    outputs.append(out)
        return "".join(outputs)

    def emit(self, variable: str, value: str) -> str:
        self.variables[variable] = value
        return self._trigger_watch(variable)

    def _result_value(self, result: Any) -> Any:
        data = getattr(result, "data", None)
        if data is not None:
            return data
        output = getattr(result, "output", "")
        return output.strip() if isinstance(output, str) else output

    def _to_eval_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return SimpleNamespace(**{key: self._to_eval_value(item) for key, item in value.items()})
        if isinstance(value, list):
            return [self._to_eval_value(item) for item in value]
        return value

    def _eval_locals(self) -> dict[str, Any]:
        safe_locals: dict[str, Any] = {}
        for key, value in self.variables.items():
            safe_locals[key] = self._to_eval_value(value)
            if isinstance(value, str):
                safe_locals[f"{key}_lines"] = value.splitlines()
        return safe_locals

    def run_node(self, node: Node) -> str:
        match node:
            case Assignment(name=name, command=command, declared_type=declared_type):
                resolved = self._inject_variables(command)
                result = self.shell.route(resolved)
                if result.error:
                    raise RuntimeError(result.error)
                self._validate_contract(declared_type, result, f"assignment {name}")
                self.variables[name] = self._result_value(result)
                hook_output = self._trigger_watch(name)
                return result.output + hook_output

            case Command(command=command, output_contract=output_contract):
                resolved = self._inject_variables(command)
                result = self.shell.route(resolved)
                if result.error:
                    raise RuntimeError(result.error)
                self._validate_contract(output_contract, result, f"command '{command}'")
                return result.output

            case ForLoop(var=var, iterable=iterable, body=body):
                iterable_value = self.variables.get(iterable)
                if iterable_value is None:
                    safe_builtins = {"len": len, "int": int, "float": float, "str": str, "range": range}
                    iterable_value = eval(iterable, {"__builtins__": safe_builtins}, self._eval_locals())
                aggregated: list[str] = []
                if isinstance(iterable_value, str):
                    iterator = iterable_value.splitlines()
                else:
                    iterator = iterable_value
                for item in iterator:
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

            case WatchHook(variable=variable, body=body):
                self.watchers.setdefault(variable, []).append(body)
                return ""

            case _:
                raise TypeError(f"Unsupported node: {node}")

    def _inject_variables(self, command: str) -> str:
        is_python = command.startswith("py ") or command.startswith("python ")
        for name, value in self.variables.items():
            if is_python:
                replacement = repr(value)
            else:
                if isinstance(value, (dict, list)):
                    replacement = shlex.quote(json.dumps(value, ensure_ascii=False))
                else:
                    replacement = shlex.quote(str(value).strip())
            command = command.replace(f"${name}", replacement)
        return command

    def _eval_condition(self, condition: str) -> bool:
        safe_locals = self._eval_locals()
        safe_builtins = {"len": len, "int": int, "float": float, "str": str, "range": range}
        return bool(eval(condition, {"__builtins__": safe_builtins}, safe_locals))


class NovaJITCompiler:
    """Compile a tiny arithmetic subset into WebAssembly text (WAT)."""

    _OPS = {
        ast.Add: 'f64.add',
        ast.Sub: 'f64.sub',
        ast.Mult: 'f64.mul',
        ast.Div: 'f64.div',
    }

    def compile_expr_to_wat(self, expression: str) -> str:
        parsed = ast.parse(expression, mode='eval')
        body = self._compile_node(parsed.body)
        return (
            '(module\n'
            '  (func (export "run") (result f64)\n'
            f'    {body}\n'
            '  )\n'
            ')'
        )

    def _compile_node(self, node: ast.AST) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return f'f64.const {float(node.value)}'
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self._compile_node(node.operand)
            return f'f64.const -1\n    {inner}\n    f64.mul'
        if isinstance(node, ast.BinOp):
            op = self._OPS.get(type(node.op))
            if op is None:
                raise ValueError('unsupported operator for jit_wasm')
            left = self._compile_node(node.left)
            right = self._compile_node(node.right)
            return f'{left}\n    {right}\n    {op}'
        raise ValueError('unsupported expression for jit_wasm')
