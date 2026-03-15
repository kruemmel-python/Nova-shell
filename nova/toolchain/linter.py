from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nova.parser.ast import FlowDeclaration, NovaAST


@dataclass(slots=True)
class NovaLintDiagnostic:
    code: str
    message: str
    severity: str
    line: int
    column: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "line": self.line,
            "column": self.column,
        }


class NovaLinter:
    """Static checks for Nova declarations and flows."""

    BUILTIN_TOOLS = {
        "rss.fetch",
        "atheria.embed",
        "system.log",
        "event.emit",
        "flow.run",
        "state.set",
        "state.get",
        "service.deploy",
        "service.status",
        "package.install",
        "package.status",
        "py.exec",
        "sys.exec",
        "system.exec",
        "data.load",
        "ai.prompt",
        "atheria.chat",
        "atheria.search",
        "memory.embed",
        "memory.search",
        "cpp.exec",
        "cpp.sandbox",
        "gpu.run",
        "wasm.run",
    }

    def lint(self, ast: NovaAST) -> list[NovaLintDiagnostic]:
        diagnostics: list[NovaLintDiagnostic] = []
        seen: dict[tuple[str, str], int] = {}

        for declaration in ast.declarations:
            if not hasattr(declaration, "name"):
                continue
            kind = declaration.__class__.__name__.replace("Declaration", "").lower()
            name = str(getattr(declaration, "name"))
            key = (kind, name)
            if key in seen:
                diagnostics.append(
                    NovaLintDiagnostic(
                        code="duplicate-declaration",
                        message=f"duplicate {kind} declaration '{name}'",
                        severity="error",
                        line=declaration.span.line,
                        column=declaration.span.column,
                    )
                )
            seen[key] = declaration.span.line

        agents = set(ast.agents())
        tools = set(ast.tools())
        datasets = set(ast.datasets())
        states = set(ast.states())
        packages = set(ast.packages())
        services = ast.services()

        for service_name, declaration in services.items():
            package_name = declaration.properties.get("package")
            if package_name and str(package_name) not in packages:
                diagnostics.append(
                    NovaLintDiagnostic(
                        code="unknown-package",
                        message=f"service '{service_name}' references unknown package '{package_name}'",
                        severity="error",
                        line=declaration.span.line,
                        column=declaration.span.column,
                    )
                )

        for flow_name, flow in ast.flows().items():
            diagnostics.extend(self._lint_flow(flow_name, flow, agents, tools, datasets, states))
        return diagnostics

    def _lint_flow(
        self,
        flow_name: str,
        flow: FlowDeclaration,
        agents: set[str],
        tools: set[str],
        datasets: set[str],
        states: set[str],
    ) -> list[NovaLintDiagnostic]:
        diagnostics: list[NovaLintDiagnostic] = []
        aliases: set[str] = set()
        for step in flow.steps:
            if step.operation not in agents and step.operation not in tools and step.operation not in self.BUILTIN_TOOLS:
                diagnostics.append(
                    NovaLintDiagnostic(
                        code="unknown-operation",
                        message=f"flow '{flow_name}' uses unknown operation '{step.operation}'",
                        severity="error",
                        line=step.span.line,
                        column=step.span.column,
                    )
                )
            for argument in step.arguments:
                if argument in aliases or argument in datasets or argument in states:
                    continue
                if step.operation in agents:
                    continue
                if "." in argument or "/" in argument or argument.startswith("{") or argument.startswith("["):
                    continue
            if step.alias:
                aliases.add(step.alias)
        return diagnostics
