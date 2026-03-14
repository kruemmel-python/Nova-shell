from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolCallable = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class AgentConfig:
    name: str
    model: str = "llama3"
    memory_enabled: bool = True
    embeddings_backend: str = "atheria"
    tools: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentContext:
    state: dict[str, Any] = field(default_factory=dict)
    memory: list[dict[str, Any]] = field(default_factory=list)


class AgentRuntime:
    """Generic runtime for agent execution within Nova graph nodes."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentConfig] = {}
        self._tools: dict[str, ToolCallable] = {}

    def register_agent(self, config: AgentConfig) -> None:
        self._agents[config.name] = config

    def register_tool(self, name: str, tool: ToolCallable) -> None:
        self._tools[name] = tool

    def execute_task(self, agent_name: str, task: str, payload: dict[str, Any] | None = None, context: AgentContext | None = None) -> dict[str, Any]:
        payload = payload or {}
        context = context or AgentContext()
        config = self._agents[agent_name]

        trace: list[str] = [f"agent={config.name}", f"model={config.model}", f"task={task}"]
        for tool_name in config.tools:
            tool = self._tools.get(tool_name)
            if not tool:
                continue
            tool_result = tool(payload)
            trace.append(f"tool:{tool_name}")
            payload.update(tool_result)

        output = {
            "agent": config.name,
            "model": config.model,
            "task": task,
            "embedding_backend": config.embeddings_backend,
            "payload": payload,
            "trace": trace,
        }

        if config.memory_enabled:
            context.memory.append(output)
        context.state["last_task"] = output
        return output
