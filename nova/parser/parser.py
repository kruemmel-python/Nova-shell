from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova.ast import (
    AgentDecl,
    DatasetDecl,
    EventDecl,
    FlowDecl,
    MemoryDecl,
    MeshDecl,
    NovaProgram,
    SensorDecl,
    SourceSpan,
    StateDecl,
    SystemDecl,
    ToolDecl,
)
from nova.parser.lexer import NovaLexer, Token


class NovaParseError(ValueError):
    """Parser error with source location."""

    def __init__(self, message: str, line: int, column: int = 1) -> None:
        super().__init__(f"{message} (line {line}, col {column})")
        self.line = line
        self.column = column


@dataclass(slots=True)
class _Cursor:
    tokens: list[Token]
    index: int = 0

    def eof(self) -> bool:
        return self.index >= len(self.tokens)

    def peek(self) -> Token:
        return self.tokens[self.index]

    def next(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token


class NovaParser:
    """Parser for Nova declarative language (.ns)."""

    _DECLARATION_KEYWORDS = {"agent", "dataset", "flow", "state", "event", "tool", "system", "sensor", "memory", "mesh"}

    def __init__(self, lexer: NovaLexer | None = None) -> None:
        self.lexer = lexer or NovaLexer()

    def parse_file(self, file_path: str | Path) -> NovaProgram:
        source = Path(file_path).read_text(encoding="utf-8")
        return self.parse(source)

    def parse(self, source: str) -> NovaProgram:
        cursor = _Cursor(tokens=self.lexer.tokenize(source))
        declarations: list[Any] = []
        while not cursor.eof():
            declarations.append(self._parse_declaration(cursor))
        return NovaProgram(declarations=declarations)

    def _parse_declaration(self, cursor: _Cursor) -> Any:
        header = cursor.next()
        if header.kind != "HEADER":
            raise NovaParseError("expected declaration header", header.line)

        parts = header.value.split(maxsplit=1)
        if len(parts) != 2:
            raise NovaParseError("declaration requires keyword and name", header.line)
        keyword, name = parts
        if keyword not in self._DECLARATION_KEYWORDS:
            raise NovaParseError(f"unknown declaration keyword '{keyword}'", header.line)

        match keyword:
            case "flow":
                steps = self._parse_flow_body(cursor)
                return FlowDecl(name=name, span=SourceSpan(header.line), steps=steps)
            case "event":
                trigger, actions = self._parse_event_body(cursor)
                return EventDecl(name=name, span=SourceSpan(header.line), trigger=trigger, actions=actions)
            case _:
                properties = self._parse_property_block(cursor)
                return self._construct_property_node(keyword, name, header.line, properties)

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
            case "sensor":
                return SensorDecl(name=name, span=span, properties=properties)
            case "memory":
                return MemoryDecl(name=name, span=span, properties=properties)
            case "mesh":
                return MeshDecl(name=name, span=span, properties=properties)
            case _:
                raise NovaParseError(f"unexpected property declaration '{keyword}'", line_no)

    def _parse_property_block(self, cursor: _Cursor) -> dict[str, Any]:
        props: dict[str, Any] = {}
        while not cursor.eof():
            token = cursor.next()
            if token.kind == "RBRACE":
                return props
            if token.kind != "LINE":
                raise NovaParseError("invalid token in property block", token.line)
            if ":" not in token.value:
                raise NovaParseError("property line must contain ':'", token.line)
            key, value = token.value.split(":", 1)
            props[key.strip()] = self._coerce_value(value.strip())
        raise NovaParseError("missing closing '}'", cursor.index)

    def _parse_flow_body(self, cursor: _Cursor) -> list[str]:
        steps: list[str] = []
        in_fence = False
        last_line = 1

        while not cursor.eof():
            token = cursor.next()
            last_line = token.line
            if token.kind == "FENCE":
                in_fence = not in_fence
                continue
            if token.kind == "RBRACE" and not in_fence:
                return steps
            if token.kind in {"LINE", "HEADER"}:
                steps.append(token.value)
                continue
            raise NovaParseError("invalid flow content", token.line)

        raise NovaParseError("missing closing '}' for flow", last_line)

    def _parse_event_body(self, cursor: _Cursor) -> tuple[str, list[str]]:
        trigger = ""
        actions: list[str] = []
        while not cursor.eof():
            token = cursor.next()
            if token.kind == "RBRACE":
                if not trigger:
                    raise NovaParseError("event requires trigger", token.line)
                return trigger, actions
            if token.kind != "LINE":
                raise NovaParseError("event supports only line statements", token.line)
            if token.value.startswith("on "):
                trigger = token.value[3:].strip()
            elif token.value.startswith("do "):
                actions.append(token.value[3:].strip())
            else:
                raise NovaParseError("event supports 'on' and 'do' entries", token.line)

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
