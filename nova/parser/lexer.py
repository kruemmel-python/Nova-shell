from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Token:
    kind: str
    value: str
    line: int
    column: int = 1


class NovaLexer:
    """Line-oriented lexer for declarative Nova source files."""

    def tokenize(self, source: str) -> list[Token]:
        tokens: list[Token] = []
        for index, raw_line in enumerate(source.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "```":
                tokens.append(Token(kind="FENCE", value=stripped, line=index))
            elif stripped == "}":
                tokens.append(Token(kind="RBRACE", value=stripped, line=index))
            elif stripped.endswith("{"):
                tokens.append(Token(kind="HEADER", value=stripped[:-1].strip(), line=index))
            else:
                tokens.append(Token(kind="LINE", value=stripped, line=index))
        return tokens
