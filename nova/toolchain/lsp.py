from __future__ import annotations

from typing import Any

from nova.parser.ast import FlowDeclaration, ImportDeclaration, NovaAST

from .linter import NovaLinter


class NovaLanguageServerFacade:
    """Small LSP-style facade for symbols, hover and diagnostics."""

    KEYWORDS = ["agent", "dataset", "event", "flow", "import", "package", "service", "state", "system", "tool"]

    def symbols(self, ast: NovaAST) -> list[dict[str, Any]]:
        symbols: list[dict[str, Any]] = []
        for declaration in ast.declarations:
            match declaration:
                case ImportDeclaration(target=target, alias=alias, span=span):
                    symbols.append({"name": alias or target, "kind": "import", "line": span.line, "column": span.column})
                case FlowDeclaration(name=name, span=span):
                    symbols.append({"name": name, "kind": "flow", "line": span.line, "column": span.column})
                case _ if hasattr(declaration, "name"):
                    symbols.append(
                        {
                            "name": getattr(declaration, "name"),
                            "kind": declaration.__class__.__name__.replace("Declaration", "").lower(),
                            "line": declaration.span.line,
                            "column": declaration.span.column,
                        }
                    )
        return symbols

    def hover(self, ast: NovaAST, line: int, column: int = 1) -> dict[str, Any] | None:
        for declaration in ast.declarations:
            if declaration.span.line == line:
                match declaration:
                    case ImportDeclaration(target=target, alias=alias):
                        return {"kind": "import", "contents": f"imports {target}" + (f" as {alias}" if alias else "")}
                    case FlowDeclaration(name=name, steps=steps):
                        return {"kind": "flow", "contents": f"flow {name} with {len(steps)} steps"}
                    case _ if hasattr(declaration, "name"):
                        return {
                            "kind": declaration.__class__.__name__.replace("Declaration", "").lower(),
                            "contents": f"{declaration.__class__.__name__.replace('Declaration', '').lower()} {getattr(declaration, 'name')}",
                        }
        for flow in ast.flows().values():
            for step in flow.steps:
                if step.span.line == line:
                    return {"kind": "step", "contents": f"{step.operation} {' '.join(step.arguments)}".strip()}
        return None

    def diagnostics(self, ast: NovaAST) -> list[dict[str, Any]]:
        return [item.to_dict() for item in NovaLinter().lint(ast)]

    def completions(self) -> list[str]:
        return list(self.KEYWORDS)
