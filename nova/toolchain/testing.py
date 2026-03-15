from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nova.runtime.runtime import NovaRuntime


@dataclass(slots=True)
class NovaTestCaseResult:
    name: str
    status: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class NovaTestSuiteResult:
    cases: list[NovaTestCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": len(self.cases),
            "passed": sum(1 for case in self.cases if case.status == "passed"),
            "failed": sum(1 for case in self.cases if case.status != "passed"),
            "cases": [case.to_dict() for case in self.cases],
        }


class NovaTestRunner:
    """Convention-based test runner for `.ns` programs."""

    def run(
        self,
        source_or_path: str | Path,
        *,
        base_path: str | Path | None = None,
        runtime: "NovaRuntime" | None = None,
    ) -> NovaTestSuiteResult:
        from nova.runtime.runtime import NovaRuntime

        owns_runtime = runtime is None
        active_runtime = runtime or NovaRuntime()
        try:
            if isinstance(source_or_path, Path) or (isinstance(source_or_path, str) and Path(source_or_path).exists()):
                target = Path(source_or_path)
                source = target.read_text(encoding="utf-8")
                root = base_path or target.parent
                source_name = str(target)
            else:
                source = str(source_or_path)
                root = base_path
                source_name = "<memory>"
            program = active_runtime.load(source, source_name=source_name, base_path=root)
            cases: list[NovaTestCaseResult] = []
            for flow_name, flow in program.ast.flows().items():
                if not (flow_name.startswith("test_") or flow_name.startswith("test.") or bool(flow.properties.get("test"))):
                    continue
                try:
                    active_runtime.execute_flow(flow_name)
                    self._assert_flow_expectations(active_runtime, flow.properties)
                    cases.append(NovaTestCaseResult(name=flow_name, status="passed"))
                except Exception as exc:
                    cases.append(NovaTestCaseResult(name=flow_name, status="failed", error=str(exc)))
            return NovaTestSuiteResult(cases=cases)
        finally:
            if owns_runtime:
                active_runtime.close()

    def _assert_flow_expectations(self, runtime: NovaRuntime, properties: dict[str, Any]) -> None:
        assert runtime.context is not None
        expect_state = properties.get("assert_state")
        if isinstance(expect_state, dict):
            for key, expected in expect_state.items():
                actual = runtime.context.states.get(str(key))
                if actual != expected:
                    raise AssertionError(f"state '{key}' expected {expected!r} but got {actual!r}")
        expect_outputs = properties.get("assert_outputs")
        if isinstance(expect_outputs, list):
            for key in expect_outputs:
                if str(key) not in runtime.context.outputs:
                    raise AssertionError(f"missing output '{key}'")
        expect_events = properties.get("assert_events")
        if isinstance(expect_events, list):
            seen = {event.name for event in runtime.context.event_bus.history}
            for name in expect_events:
                if str(name) not in seen:
                    raise AssertionError(f"missing event '{name}'")
