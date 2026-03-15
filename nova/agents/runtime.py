from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from nova.parser.ast import AgentDeclaration

if TYPE_CHECKING:
    from nova.runtime.context import RuntimeContext


@dataclass(slots=True)
class AgentSpecification:
    name: str
    model: str = "local"
    provider: str = ""
    providers: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    memory: str | None = None
    embeddings: str | None = None
    system_prompt: str = ""
    prompt_version: str = "default"
    prompts: dict[str, str] = field(default_factory=dict)
    governance: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentTask:
    agent_name: str
    action: str
    inputs: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentExecutionResult:
    agent_name: str
    action: str
    output: str
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "action": self.action,
            "output": self.output,
            "data": self.data,
            "metadata": self.metadata,
        }


class AgentRuntime:
    """Generic agent runtime with explicit model/tool/memory configuration."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentSpecification] = {}

    def register(self, declaration: AgentDeclaration) -> AgentSpecification:
        tools_value = declaration.properties.get("tools", [])
        if isinstance(tools_value, list):
            tools = tuple(str(item) for item in tools_value)
        elif tools_value:
            tools = (str(tools_value),)
        else:
            tools = ()

        prompts_value = declaration.properties.get("prompts", {})
        prompts = {str(key): str(value) for key, value in prompts_value.items()} if isinstance(prompts_value, dict) else {}
        providers_value = declaration.properties.get("providers", [])
        if isinstance(providers_value, list):
            providers = tuple(str(item) for item in providers_value if str(item))
        elif declaration.properties.get("provider"):
            providers = (str(declaration.properties.get("provider")),)
        else:
            providers = ()
        models_value = declaration.properties.get("models", [])
        if isinstance(models_value, list):
            models = tuple(str(item) for item in models_value if str(item))
        elif declaration.properties.get("model"):
            models = (str(declaration.properties.get("model")),)
        else:
            models = ()

        specification = AgentSpecification(
            name=declaration.name,
            model=str(declaration.properties.get("model", "local")),
            provider=str(declaration.properties.get("provider", "")),
            providers=providers,
            models=models,
            tools=tools,
            memory=str(declaration.properties.get("memory")) if declaration.properties.get("memory") else None,
            embeddings=str(declaration.properties.get("embeddings")) if declaration.properties.get("embeddings") else None,
            system_prompt=str(declaration.properties.get("system_prompt", "")),
            prompt_version=str(declaration.properties.get("prompt_version", "default")),
            prompts=prompts,
            governance=dict(declaration.properties.get("governance") or {}),
            config=dict(declaration.properties),
        )
        self._agents[declaration.name] = specification
        return specification

    def specification(self, name: str) -> AgentSpecification:
        return self._agents[name]

    def execute(self, task: AgentTask, context: RuntimeContext) -> AgentExecutionResult:
        context.operations.check_failpoint("agent.execute")
        specification = self.specification(task.agent_name)
        self._enforce_governance(specification, task)
        memory_scope = self._memory_scope(specification, task)
        requested_tools = {str(item) for item in task.metadata.get("requested_tools", []) if str(item)}
        sandbox_session = context.tool_sandbox.authorize(
            specification.name,
            allowed_tools=specification.tools,
            requested_tools=requested_tools,
            metadata={"action": task.action or specification.config.get("default_action", "run")},
        )
        context.prompt_registry.register_agent(
            specification.name,
            specification.prompts or ({specification.prompt_version: specification.system_prompt} if specification.system_prompt else {}),
            active_version=specification.prompt_version or "default",
            metadata=specification.governance,
        )
        action = task.action or str(specification.config.get("default_action", "run"))
        prompt_version = str(task.metadata.get("prompt_version") or specification.prompt_version or "default")
        prompt_text = context.prompt_registry.resolve(specification.name, prompt_version) or specification.prompts.get(prompt_version, specification.system_prompt)
        memory_context = context.memory_store.search(memory_scope.rsplit(":shard:", 1)[0], json.dumps(task.inputs, ensure_ascii=False), top_k=int(specification.config.get("memory_top_k") or 5))
        output, provider_name, model_name = self._provider_output(specification, action, task.inputs, context, prompt_text, memory_context) or (
            self._render_output(specification, action, task.inputs, prompt_text),
            "local",
            specification.model,
        )

        context.agent_memory.setdefault(memory_scope, []).append(
            {
                "agent": specification.name,
                "action": action,
                "model": model_name,
                "provider": provider_name,
                "prompt_version": prompt_version,
                "output": output,
            }
        )
        context.agent_memory.setdefault("__agent_evaluations__", []).append(
            {
                "agent": specification.name,
                "provider": provider_name,
                "model": model_name,
                "prompt_version": prompt_version,
                "input_count": len(task.inputs),
                "tool_count": len(specification.tools),
                "memory_scope": memory_scope,
            }
        )
        memory_record = context.memory_store.append(
            memory_scope,
            output,
            shard=memory_scope.split(":shard:")[-1] if ":shard:" in memory_scope else "0",
            metadata={
                "agent": specification.name,
                "action": action,
                "provider": provider_name,
                "model": model_name,
                "prompt_version": prompt_version,
            },
        )
        evaluation = context.eval_store.record(
            specification.name,
            provider=provider_name,
            model=model_name,
            prompt_version=prompt_version,
            output_text=output,
            metadata={"memory_scope": memory_scope, "tool_session": sandbox_session, "memory_matches": memory_context},
        )

        if specification.embeddings:
            context.embeddings[f"{specification.name}:{len(context.embeddings) + 1}"] = {
                "provider": specification.embeddings,
                "memory_scope": memory_scope,
                "action": action,
                "input_count": len(task.inputs),
                "shard": memory_scope.split(":shard:")[-1] if ":shard:" in memory_scope else "0",
            }

        return AgentExecutionResult(
            agent_name=specification.name,
            action=action,
            output=output,
            data={
                "model": model_name,
                "provider": provider_name,
                "tools": list(specification.tools),
                "memory": memory_scope,
                "embeddings": specification.embeddings,
                "inputs": task.inputs,
                "prompt_version": prompt_version,
                "memory_matches": memory_context,
                "memory_record": memory_record,
                "evaluation": evaluation,
            },
            metadata={
                "model": model_name,
                "provider": provider_name,
                "tools": list(specification.tools),
                "prompt_version": prompt_version,
                "tool_session": sandbox_session,
            },
        )

    def _render_output(self, specification: AgentSpecification, action: str, inputs: list[Any], prompt_text: str) -> str:
        summarized_inputs = [self._summarize_input(value) for value in inputs]
        payload = "; ".join(item for item in summarized_inputs if item) or "no inputs"
        tools = ", ".join(specification.tools) if specification.tools else "no tools"
        prompt = prompt_text.strip()[:120] if prompt_text else specification.system_prompt.strip()[:120]
        return f"{specification.name} [{specification.model}] {action}: {payload} | tools={tools} | prompt={prompt}"

    def _provider_output(
        self,
        specification: AgentSpecification,
        action: str,
        inputs: list[Any],
        context: RuntimeContext,
        prompt_text: str,
        memory_context: list[dict[str, Any]],
    ) -> tuple[str, str, str] | None:
        prompt = self._render_output(specification, action, inputs, prompt_text)
        if prompt_text:
            prompt = f"{prompt_text}\n\nTask:\n{prompt}"
        if memory_context:
            prompt += "\n\nMemory:\n" + "\n".join(item["text"] for item in memory_context[:3])
        routed = context.provider_registry.execute(specification, prompt, inputs, context)
        if routed is None:
            return None
        return routed

    def _enforce_governance(self, specification: AgentSpecification, task: AgentTask) -> None:
        governance = dict(specification.governance or {})
        allowed_models = {str(item) for item in governance.get("allowed_models", []) if str(item)}
        if allowed_models and str(specification.model) not in allowed_models and not any(model in allowed_models for model in specification.models):
            raise PermissionError(f"agent '{specification.name}' model is not permitted by governance")
        blocked_tools = {str(item) for item in governance.get("blocked_tools", []) if str(item)}
        if blocked_tools.intersection(specification.tools):
            raise PermissionError(f"agent '{specification.name}' uses blocked tools")
        max_input_chars = governance.get("max_input_chars")
        if max_input_chars is not None:
            rendered = json.dumps(task.inputs, ensure_ascii=False)
            if len(rendered) > int(max_input_chars):
                raise PermissionError(f"agent '{specification.name}' input exceeds governance limit")

    def _memory_scope(self, specification: AgentSpecification, task: AgentTask) -> str:
        base_scope = specification.memory or f"agent::{specification.name}"
        shards = max(1, int(specification.config.get("memory_shards") or 1))
        if shards == 1:
            return base_scope
        payload = json.dumps(task.inputs, ensure_ascii=False, sort_keys=True)
        shard = int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16) % shards
        return f"{base_scope}:shard:{shard}"

    def _summarize_input(self, value: Any) -> str:
        match value:
            case list() if value and all(isinstance(item, dict) for item in value):
                titles = [
                    str(item.get("title") or item.get("name") or item.get("id") or "").strip()
                    for item in value
                    if isinstance(item, dict)
                ]
                titles = [item for item in titles if item][:3]
                label = ", ".join(titles) if titles else "structured records"
                return f"{len(value)} records ({label})"
            case dict():
                keys = ", ".join(sorted(str(key) for key in value.keys())[:5])
                return f"object {{{keys}}}"
            case str():
                compact = value.strip().replace("\n", " ")
                return compact[:120]
            case _:
                return str(value)
