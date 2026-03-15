from __future__ import annotations

import json
from typing import Any

from nova.parser.ast import FlowDeclaration, FlowStep, ImportDeclaration, NovaAST


class NovaFormatter:
    """Canonical formatter for Nova source files."""

    def format_ast(self, ast: NovaAST) -> str:
        blocks: list[str] = []
        for declaration in ast.declarations:
            match declaration:
                case ImportDeclaration(target=target, alias=alias):
                    line = f"import {json.dumps(target, ensure_ascii=False)}"
                    if alias:
                        line += f" as {alias}"
                    blocks.append(line)
                case FlowDeclaration(name=name, properties=properties, steps=steps):
                    lines = [f"flow {name} {{"]
                    for key, value in sorted(properties.items()):
                        lines.append(f"  {key}: {self._render_value(value)}")
                    for step in steps:
                        lines.append(f"  {self._render_step(step)}")
                    lines.append("}")
                    blocks.append("\n".join(lines))
                case _:
                    properties = getattr(declaration, "properties", None)
                    name = getattr(declaration, "name", "")
                    kind = declaration.__class__.__name__.replace("Declaration", "").lower()
                    if not isinstance(properties, dict):
                        continue
                    lines = [f"{kind} {name} {{"]
                    for key, value in sorted(properties.items()):
                        lines.append(f"  {key}: {self._render_value(value)}")
                    lines.append("}")
                    blocks.append("\n".join(lines))
        return "\n\n".join(blocks).strip() + ("\n" if blocks else "")

    def format_source(self, source: str, *, parser: Any) -> str:
        return self.format_ast(parser.parse(source))

    def _render_step(self, step: FlowStep) -> str:
        statement = " ".join([step.operation, *step.arguments]).strip()
        if step.alias:
            return f"{statement} -> {step.alias}"
        return statement

    def _render_value(self, value: Any) -> str:
        match value:
            case None:
                return "null"
            case bool():
                return "true" if value else "false"
            case int() | float():
                return str(value)
            case str():
                if value and all(char.isalnum() or char in "._-/" for char in value):
                    return value
                return json.dumps(value, ensure_ascii=False)
            case list():
                return "[" + ", ".join(self._render_value(item) for item in value) + "]"
            case dict():
                items = ", ".join(f"{key}: {self._render_value(item)}" for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
                return "{" + items + "}"
            case _:
                return json.dumps(str(value), ensure_ascii=False)
