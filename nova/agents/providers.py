from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .runtime import AgentSpecification
    from nova.runtime.context import RuntimeContext


class ProviderAdapter(Protocol):
    name: str

    def invoke(self, specification: "AgentSpecification", prompt: str, inputs: list[Any], context: "RuntimeContext", model_name: str) -> str | None:
        ...


@dataclass(slots=True)
class LocalProviderAdapter:
    name: str = "local"

    def invoke(self, specification: "AgentSpecification", prompt: str, inputs: list[Any], context: "RuntimeContext", model_name: str) -> str | None:
        return None


@dataclass(slots=True)
class ShellProviderAdapter:
    name: str = "shell"

    def invoke(self, specification: "AgentSpecification", prompt: str, inputs: list[Any], context: "RuntimeContext", model_name: str) -> str | None:
        if context.command_executor is None:
            return None
        command = "ai prompt"
        if specification.system_prompt.strip():
            command += f" --system {json.dumps(specification.system_prompt, ensure_ascii=False)}"
        command += f" {json.dumps(prompt, ensure_ascii=False)}"
        result = context.command_executor.execute(command, pipeline_data=inputs)
        if result.error:
            return None
        return result.output.strip() or str(result.data or "")


@dataclass(slots=True)
class AtheriaProviderAdapter:
    name: str = "atheria"

    def invoke(self, specification: "AgentSpecification", prompt: str, inputs: list[Any], context: "RuntimeContext", model_name: str) -> str | None:
        if context.command_executor is None:
            return None
        result = context.command_executor.execute(f'atheria chat {prompt!r}', pipeline_data=inputs)
        if result.error:
            return None
        return result.output.strip() or str(result.data or "")


class ProviderRegistry:
    """Provider adapter registry for Nova agents."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderAdapter] = {
            "local": LocalProviderAdapter(),
            "shell": ShellProviderAdapter(),
            "atheria": AtheriaProviderAdapter(),
        }

    def resolve(self, name: str) -> ProviderAdapter | None:
        return self._providers.get(name.strip().lower())

    def execute(
        self,
        specification: "AgentSpecification",
        prompt: str,
        inputs: list[Any],
        context: "RuntimeContext",
    ) -> tuple[str, str, str] | None:
        provider_candidates = tuple(item for item in specification.providers if item) or ((specification.provider,) if specification.provider else ())
        model_candidates = tuple(item for item in specification.models if item) or (specification.model,)
        for provider_name in provider_candidates or ("local",):
            adapter = self.resolve(provider_name)
            if adapter is None:
                continue
            for model_name in model_candidates:
                output = adapter.invoke(specification, prompt, inputs, context, str(model_name))
                if output:
                    return output, adapter.name, str(model_name)
                if adapter.name == "local":
                    return None
        return None
