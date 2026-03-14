from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova.ast import AgentDecl, DatasetDecl, EventDecl, FlowDecl, NovaProgram, SourceSpan, StateDecl, SystemDecl, ToolDecl


class NovaParseError(ValueError):
    """Parser error with source location."""

    def __init__(self, message: str, line: int, column: int = 1) -> None:
        super().__init__(f"{message} (line {line}, col {column})")
        self.line = line
        self.column = column


@dataclass(slots=True)
class _Cursor:
    lines: list[str]
    index: int = 0

    def eof(self) -> bool:
        return self.index >= len(self.lines)

    def peek(self) -> str:
        return self.lines[self.index]

    def next(self) -> str:
        line = self.lines[self.index]
        self.index += 1
        return line


class NovaParser:
    """Parser for Nova declarative language (.ns)."""

    _DECLARATION_KEYWORDS = {"agent", "dataset", "flow", "state", "event", "tool", "system"}

    def parse_file(self, file_path: str | Path) -> NovaProgram:
        source = Path(file_path).read_text(encoding="utf-8")
        return self.parse(source)

    def parse(self, source: str) -> NovaProgram:
        lines = source.splitlines()
        cursor = _Cursor(lines=lines)
        declarations: list[Any] = []

        while not cursor.eof():
            raw = cursor.peek().strip()
            if not raw or raw.startswith("#"):
                cursor.next()
                continue
            declarations.append(self._parse_declaration(cursor))

        return NovaProgram(declarations=declarations)

    def _parse_declaration(self, cursor: _Cursor) -> Any:
        header = cursor.next()
        line_no = cursor.index
        stripped = header.strip()

        if not stripped.endswith("{"):
            raise NovaParseError("declaration header must end with '{'", line_no)

        opening = stripped[:-1].strip()
        parts = opening.split(maxsplit=1)
        if len(parts) != 2:
            raise NovaParseError("declaration requires keyword and name", line_no)
        keyword, name = parts

        if keyword not in self._DECLARATION_KEYWORDS:
            raise NovaParseError(f"unknown declaration keyword '{keyword}'", line_no)

        match keyword:
            case "flow":
                steps = self._parse_flow_body(cursor)
                return FlowDecl(name=name, span=SourceSpan(line_no), steps=steps)
            case "event":
                trigger, actions = self._parse_event_body(cursor)
                return EventDecl(name=name, span=SourceSpan(line_no), trigger=trigger, actions=actions)
            case "agent" | "dataset" | "state" | "tool" | "system":
                properties = self._parse_property_block(cursor)
                return self._construct_property_node(keyword, name, line_no, properties)
            case _:
                raise NovaParseError(f"unsupported declaration '{keyword}'", line_no)

    def _construct_property_node(self, keyword: str, name: str, line_no: int, properties: dict[str, Any]) -> Any:
        span = SourceSpan(line=line_no)
        match keyword:
            case "agent":
                return AgentDecl(name=name, span=span, properties=properties)
            case "dataset":
                return DatasetDecl(name=name, span=span, properties=properties)
            case "state":
                return StateDecl(name=name, span=span, properties=properties)
            case "tool":
                return ToolDecl(name=name, span=span, properties=properties)
            case "system":
                return SystemDecl(name=name, span=span, properties=properties)
            case _:
                raise NovaParseError(f"unexpected property declaration '{keyword}'", line_no)

    def _parse_property_block(self, cursor: _Cursor) -> dict[str, Any]:
        props: dict[str, Any] = {}
        while not cursor.eof():
            line = cursor.next()
            line_no = cursor.index
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "}":
                return props
            if ":" not in stripped:
                raise NovaParseError("property line must contain ':'", line_no)
            key, value = stripped.split(":", 1)
            props[key.strip()] = self._coerce_value(value.strip())
        raise NovaParseError("missing closing '}'", cursor.index)

    def _parse_flow_body(self, cursor: _Cursor) -> list[str]:
        steps: list[str] = []
        in_fence = False

        while not cursor.eof():
            line = cursor.next()
            line_no = cursor.index
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "```":
                in_fence = not in_fence
                continue
            if stripped == "}" and not in_fence:
                return steps
            steps.append(stripped)

        raise NovaParseError("missing closing '}' for flow", line_no)

    def _parse_event_body(self, cursor: _Cursor) -> tuple[str, list[str]]:
        trigger = ""
        actions: list[str] = []
        while not cursor.eof():
            line = cursor.next()
            line_no = cursor.index
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "}":
                if not trigger:
                    raise NovaParseError("event requires trigger", line_no)
                return trigger, actions
            if stripped.startswith("on "):
                trigger = stripped[3:].strip()
            elif stripped.startswith("do "):
                actions.append(stripped[3:].strip())
            else:
                raise NovaParseError("event supports 'on' and 'do' entries", line_no)

        raise NovaParseError("missing closing '}' for event", cursor.index)

    def _coerce_value(self, value: str) -> Any:
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value
