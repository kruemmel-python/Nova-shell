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

    MAX_PROVIDER_PROMPT_CHARS = 12000
    MAX_PROVIDER_PROMPT_CONTEXT_CHARS = 3000
    MAX_PROVIDER_MEMORY_SNIPPET_CHARS = 512
    MAX_STORED_OUTPUT_CHARS = 8192

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
        memory_query = self._bounded_text(json.dumps(task.inputs, ensure_ascii=False), self.MAX_PROVIDER_PROMPT_CONTEXT_CHARS)
        memory_context = self._compact_memory_context(
            context.memory_store.search(
                memory_scope.rsplit(":shard:", 1)[0],
                memory_query,
                top_k=int(specification.config.get("memory_top_k") or 5),
            )
        )
        output, provider_name, model_name = self._provider_output(specification, action, task.inputs, context, prompt_text, memory_context) or (
            self._render_output(specification, action, task.inputs, prompt_text),
            "local",
            specification.model,
        )
        stored_output = self._bounded_text(output, self.MAX_STORED_OUTPUT_CHARS)

        context.agent_memory.setdefault(memory_scope, []).append(
            {
                "agent": specification.name,
                "action": action,
                "model": model_name,
                "provider": provider_name,
                "prompt_version": prompt_version,
                "output": stored_output,
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
            stored_output,
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
            output_text=stored_output,
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
        structured = self._render_structured_output(specification, action, inputs)
        if structured is not None:
            return structured
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
            prompt = f"{self._bounded_text(prompt_text, self.MAX_PROVIDER_PROMPT_CONTEXT_CHARS)}\n\nTask:\n{prompt}"
        if memory_context:
            prompt += "\n\nMemory:\n" + "\n".join(self._bounded_text(str(item["text"]), self.MAX_PROVIDER_MEMORY_SNIPPET_CHARS) for item in memory_context[:3])
        prompt = self._bounded_text(prompt, self.MAX_PROVIDER_PROMPT_CHARS)
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

    def _render_structured_output(self, specification: AgentSpecification, action: str, inputs: list[Any]) -> str | None:
        if action not in {"summarize", "inspect", "evaluate", "review"} or not inputs:
            return None
        payload = self._coerce_structured_input(inputs[0])
        if isinstance(payload, dict) and {"file_count", "directory_count", "groups"}.issubset(payload.keys()):
            return self._render_folder_scan_output(specification, action, payload)
        return None

    def _coerce_structured_input(self, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    return value
        return value

    def _render_folder_scan_output(self, specification: AgentSpecification, action: str, payload: dict[str, Any]) -> str:
        file_count = int(payload.get("file_count") or 0)
        directory_count = int(payload.get("directory_count") or 0)
        groups = payload.get("groups") or {}
        if not isinstance(groups, dict):
            groups = {}
        normalized_groups: dict[str, dict[str, Any]] = {}
        for extension, details in groups.items():
            if isinstance(details, dict):
                normalized_groups[str(extension)] = details

        top_groups = sorted(
            normalized_groups.items(),
            key=lambda item: (-int((item[1] or {}).get("count") or 0), item[0]),
        )
        top_group_lines = [
            f"- {extension}: {int((details or {}).get('count') or 0)} Datei(en)"
            for extension, details in top_groups[:5]
        ]
        files_without_extension = int((normalized_groups.get("[Keine Endung]") or {}).get("count") or 0)
        extension_count = len(normalized_groups)
        dominant_extension = top_groups[0] if top_groups else None
        dominant_ratio = (
            (int((dominant_extension[1] or {}).get("count") or 0) / file_count)
            if dominant_extension and file_count
            else 0.0
        )

        largest_files = payload.get("largest_files") or []
        largest_lines: list[str] = []
        if isinstance(largest_files, list):
            for item in largest_files[:3]:
                if isinstance(item, dict):
                    largest_lines.append(f"- {item.get('name', 'unbekannt')} ({self._format_size(item.get('size'))})")

        findings: list[str] = []
        recommendations: list[str] = []

        if file_count == 0:
            findings.append("- Keine Dateien im Zielordner gefunden.")
            recommendations.append("- Keine Aktion erforderlich, bis Dateien vorhanden sind.")
        else:
            findings.append(f"- {file_count} Datei(en), {directory_count} Unterordner, {extension_count} Dateityp(en).")
            if files_without_extension:
                findings.append(f"- {files_without_extension} Datei(en) ohne Endung gefunden.")
                recommendations.append("- Dateien ohne Endung pruefen und sinnvoll benennen oder einsortieren.")
            if dominant_extension and dominant_ratio >= 0.5:
                findings.append(
                    f"- Deutlicher Schwerpunkt auf {dominant_extension[0]} ({int((dominant_extension[1] or {}).get('count') or 0)} Datei(en), {dominant_ratio:.0%})."
                )
                recommendations.append(f"- Fuer {dominant_extension[0]} einen eigenen Unterordner oder Batch-Workflow anlegen.")
            else:
                findings.append("- Kein einzelner Dateityp dominiert den Ordner.")
            if extension_count >= 6:
                findings.append("- Hohe Typenvielfalt deutet auf gemischten Ablageordner hin.")
                recommendations.append("- Unterordner nach Thema oder Dateityp anlegen, um die Root-Ebene zu entlasten.")
            if file_count >= 25:
                findings.append("- Viele Dateien liegen direkt im Zielordner.")
                recommendations.append("- Alte oder abgeschlossene Dateien archivieren und den Root-Ordner reduzieren.")
            if largest_lines:
                findings.append("- Groesste Dateien:")
                findings.extend(largest_lines)
                recommendations.append("- Grosse Dateien auf Relevanz, Dubletten oder Archivierung pruefen.")

        if not recommendations:
            recommendations.append("- Der Ordner wirkt aktuell stabil; nur bei Bedarf weiter strukturieren.")

        top_extensions = "\n".join(top_group_lines) if top_group_lines else "- Keine Dateitypen erkannt."
        return "\n".join(
            [
                f"{specification.name} [{specification.model}] {action}:",
                f"Uebersicht: {file_count} Datei(en), {directory_count} Unterordner.",
                "Top-Endungen:",
                top_extensions,
                "Befunde:",
                *findings,
                "Empfehlungen:",
                *recommendations,
            ]
        )

    def _format_size(self, value: Any) -> str:
        try:
            size = float(value)
        except (TypeError, ValueError):
            return "unbekannt"
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        return f"{size:.1f} {units[unit_index]}"

    def _bounded_text(self, value: Any, limit: int) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        overflow = len(text) - limit
        return f"{text[:limit].rstrip()}... [truncated {overflow} chars]"

    def _compact_memory_context(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for record in records:
            compacted.append(
                {
                    **record,
                    "text": self._bounded_text(record.get("text", ""), self.MAX_PROVIDER_MEMORY_SNIPPET_CHARS),
                }
            )
        return compacted
