from __future__ import annotations

from dataclasses import dataclass, field
import re

from nova.ast import AgentDecl, DatasetDecl, EventDecl, FlowDecl, NovaProgram


_REFERENCE_PATTERN = re.compile(r"\b([A-Za-z_][\w]*)\b")


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


class NovaValidator:
    """Static validation for Nova declarative programs."""

    def validate(self, program: NovaProgram) -> ValidationResult:
        errors: list[str] = []
        names = program.names()

        for decl in program.declarations:
            match decl:
                case AgentDecl(name=name, properties=properties):
                    if "model" not in properties:
                        errors.append(f"agent '{name}' missing required property 'model'")
                case DatasetDecl(name=name, properties=properties):
                    if "source" not in properties:
                        errors.append(f"dataset '{name}' missing required property 'source'")
                case EventDecl(name=name, trigger=trigger, actions=actions):
                    if not trigger:
                        errors.append(f"event '{name}' must define a trigger")
                    if not actions:
                        errors.append(f"event '{name}' must define at least one action")
                case FlowDecl(name=name, steps=steps):
                    if not steps:
                        errors.append(f"flow '{name}' must define at least one step")
                    errors.extend(self._validate_flow_references(name, steps, names))
                case _:
                    continue

        return ValidationResult(valid=not errors, errors=errors)

    def _validate_flow_references(self, flow_name: str, steps: list[str], known_names: set[str]) -> list[str]:
        errors: list[str] = []
        for step in steps:
            tokens = step.split()
            if not tokens:
                continue
            head = tokens[0]
            if "." in head:
                continue
            if head == "emit":
                continue
            if head not in known_names:
                errors.append(f"flow '{flow_name}' references unknown symbol '{head}'")
            for token in tokens[1:]:
                if _REFERENCE_PATTERN.fullmatch(token) and token not in known_names and token not in {"summarize", "fetch", "embed"}:
                    # only enforce explicit declaration names; allow task verbs
                    continue
        return errors
