from __future__ import annotations

import ast as pyast
import re
import shlex
from pathlib import Path
from typing import Any, Callable

from .ast import (
    AgentDeclaration,
    DatasetDeclaration,
    EventDeclaration,
    FlowDeclaration,
    FlowStep,
    ImportDeclaration,
    NovaAST,
    PackageDeclaration,
    ServiceDeclaration,
    SourceSpan,
    StateDeclaration,
    SystemDeclaration,
    ToolDeclaration,
    TopLevelDeclaration,
)
from .errors import NovaSyntaxError

BlockParser = Callable[[str, list[tuple[str, int]], SourceSpan, "NovaParser"], TopLevelDeclaration]


class NovaParser:
    """Parse declarative Nova language source into a typed AST."""

    _HEADER_RE = re.compile(r"^(?P<kind>[A-Za-z_][A-Za-z0-9_-]*)\s+(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)\s*\{\s*(?P<rest>.*)$")
    _IMPORT_RE = re.compile(r"^import\s+(?P<target>.+?)(?:\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_.-]*))?$")
    _PROPERTY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(?P<value>.+)$")
    _INT_RE = re.compile(r"^[+-]?\d+$")
    _FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d+|\d+\.\d*|\.\d+)$")

    def __init__(self) -> None:
        self._extensions: dict[str, BlockParser] = {}

    def register_extension(self, keyword: str, parser: BlockParser) -> None:
        self._extensions[keyword] = parser

    def parse_file(self, path: str | Path) -> NovaAST:
        source_path = Path(path)
        return self.parse(source_path.read_text(encoding="utf-8"))

    def parse(self, source: str) -> NovaAST:
        lines = source.splitlines()
        declarations: list[TopLevelDeclaration] = []
        index = 0

        while index < len(lines):
            raw_line = lines[index]
            statement = self._strip_inline_comment(raw_line).strip()
            if not statement:
                index += 1
                continue

            if statement.startswith("import "):
                declarations.append(self._parse_import(statement, index + 1, raw_line))
                index += 1
                continue

            match = self._HEADER_RE.match(statement)
            if not match:
                raise NovaSyntaxError("expected a top-level block declaration", index + 1, 1, raw_line.rstrip("\n"))

            kind = match.group("kind")
            name = match.group("name")
            rest = match.group("rest").rstrip()
            header_column = raw_line.find(kind) + 1 if kind in raw_line else 1
            span = SourceSpan(index + 1, header_column)

            if rest.endswith("}"):
                inline_body = rest[:-1].strip()
                body_lines = [(inline_body, index + 1)] if inline_body else []
                index += 1
            else:
                body_lines, index = self._collect_block(lines, index + 1)

            declarations.append(self._parse_block(kind, name, body_lines, span))

        return NovaAST(declarations=declarations, source=source)

    def _parse_import(self, statement: str, line_number: int, raw_line: str) -> ImportDeclaration:
        match = self._IMPORT_RE.match(statement)
        if not match:
            raise NovaSyntaxError("invalid import statement", line_number, 1, raw_line.rstrip("\n"))
        target_value = self._parse_value(match.group("target"), line_number, raw_line.find("import") + 8, raw_line)
        target = str(target_value).strip()
        if not target:
            raise NovaSyntaxError("import target cannot be empty", line_number, 1, raw_line.rstrip("\n"))
        alias = match.group("alias")
        return ImportDeclaration(target=target, alias=alias, span=SourceSpan(line_number, 1))

    def _collect_block(self, lines: list[str], start_index: int) -> tuple[list[tuple[str, int]], int]:
        body_lines: list[tuple[str, int]] = []
        index = start_index

        while index < len(lines):
            raw_line = lines[index]
            stripped = self._strip_inline_comment(raw_line).strip()
            if not stripped:
                index += 1
                continue
            if stripped == "}":
                return body_lines, index + 1
            body_lines.append((stripped, index + 1))
            index += 1

        raise NovaSyntaxError("missing closing brace for block", start_index, 1)

    def _parse_block(
        self,
        kind: str,
        name: str,
        body_lines: list[tuple[str, int]],
        span: SourceSpan,
    ) -> TopLevelDeclaration:
        if kind in self._extensions:
            return self._extensions[kind](name, body_lines, span, self)

        match kind:
            case "agent":
                return AgentDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "dataset":
                return DatasetDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "tool":
                return ToolDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "service":
                return ServiceDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "package":
                return PackageDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "state":
                return StateDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "system":
                return SystemDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "event":
                return EventDeclaration(name=name, properties=self._parse_properties(body_lines), span=span)
            case "flow":
                properties, steps = self._parse_flow_body(body_lines)
                return FlowDeclaration(name=name, steps=steps, properties=properties, span=span)
            case _:
                raise NovaSyntaxError(f"unknown Nova block '{kind}'", span.line, span.column)

    def _parse_properties(self, body_lines: list[tuple[str, int]]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for line, line_number in body_lines:
            match = self._PROPERTY_RE.match(line)
            if not match:
                raise NovaSyntaxError("expected 'key: value' property", line_number, 1, line)
            key = match.group("key")
            value_text = match.group("value")
            properties[key] = self._parse_value(value_text, line_number, line.find(":") + 2, line)
        return properties

    def _parse_flow_body(self, body_lines: list[tuple[str, int]]) -> tuple[dict[str, Any], list[FlowStep]]:
        properties: dict[str, Any] = {}
        steps: list[FlowStep] = []

        for line, line_number in body_lines:
            match = self._PROPERTY_RE.match(line)
            if match:
                key = match.group("key")
                value_text = match.group("value")
                properties[key] = self._parse_value(value_text, line_number, line.find(":") + 2, line)
                continue
            steps.append(self._parse_flow_step(line, line_number))

        return properties, steps

    def _parse_flow_step(self, line: str, line_number: int) -> FlowStep:
        statement, alias = self._split_alias(line)
        try:
            tokens = shlex.split(statement, posix=True)
        except ValueError as exc:
            raise NovaSyntaxError(f"invalid flow statement: {exc}", line_number, 1, line) from exc

        if not tokens:
            raise NovaSyntaxError("empty flow statement", line_number, 1, line)

        return FlowStep(operation=tokens[0], arguments=tuple(tokens[1:]), alias=alias, span=SourceSpan(line_number, 1))

    def _split_alias(self, statement: str) -> tuple[str, str | None]:
        quote: str | None = None
        bracket_depth = 0
        index = 0

        while index < len(statement):
            char = statement[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {'"', "'"}:
                quote = char
            elif char in "[{(":
                bracket_depth += 1
            elif char in "]})":
                bracket_depth = max(bracket_depth - 1, 0)
            elif char == "-" and index + 1 < len(statement) and statement[index + 1] == ">" and bracket_depth == 0:
                left = statement[:index].strip()
                right = statement[index + 2 :].strip()
                return left, right or None
            index += 1

        return statement.strip(), None

    def _parse_value(self, raw_value: str, line_number: int, column: int, source_line: str) -> Any:
        value = raw_value.strip()
        if not value:
            raise NovaSyntaxError("expected a property value", line_number, column, source_line)

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [self._parse_value(item, line_number, column, source_line) for item in self._split_comma(inner)]

        if value.startswith("{") and value.endswith("}"):
            inner = value[1:-1].strip()
            if not inner:
                return {}
            result: dict[str, Any] = {}
            for item in self._split_comma(inner):
                if ":" not in item:
                    raise NovaSyntaxError("expected 'key: value' entry inside map", line_number, column, source_line)
                key, nested_value = item.split(":", 1)
                result[key.strip()] = self._parse_value(nested_value, line_number, column, source_line)
            return result

        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"null", "none"}:
            return None
        if self._INT_RE.match(value):
            return int(value)
        if self._FLOAT_RE.match(value):
            return float(value)
        if value[0] in {'"', "'"}:
            try:
                return pyast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise NovaSyntaxError(f"invalid string literal: {exc}", line_number, column, source_line) from exc
        return value

    def _split_comma(self, value: str) -> list[str]:
        items: list[str] = []
        quote: str | None = None
        bracket_depth = 0
        start = 0

        for index, char in enumerate(value):
            if quote:
                if char == "\\":
                    continue
                if char == quote:
                    quote = None
                continue
            if char in {'"', "'"}:
                quote = char
                continue
            if char in "[{(":
                bracket_depth += 1
                continue
            if char in "]})":
                bracket_depth = max(bracket_depth - 1, 0)
                continue
            if char == "," and bracket_depth == 0:
                items.append(value[start:index].strip())
                start = index + 1

        tail = value[start:].strip()
        if tail:
            items.append(tail)
        return items

    def _strip_inline_comment(self, raw_line: str) -> str:
        quote: str | None = None
        index = 0

        while index < len(raw_line):
            char = raw_line[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "#":
                return raw_line[:index]
            index += 1
        return raw_line
