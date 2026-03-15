from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


PROTOCOL_VERSION = "nova-exec/1"


@dataclass(slots=True)
class ExecutorTask:
    request_id: str
    capability: str
    kind: str
    operation: str | None = None
    arguments: list[str] = field(default_factory=list)
    command: str | None = None
    pipeline_data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    protocol: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "request_id": self.request_id,
            "capability": self.capability,
            "kind": self.kind,
            "operation": self.operation,
            "arguments": self.arguments,
            "command": self.command,
            "pipeline_data": self.pipeline_data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dispatch_task(cls, capability: str, task: dict[str, Any]) -> "ExecutorTask":
        return cls(
            request_id=str(task.get("request_id") or uuid.uuid4().hex[:16]),
            capability=capability,
            kind=str(task.get("kind") or "tool"),
            operation=str(task["tool"]) if task.get("tool") else (str(task["operation"]) if task.get("operation") else None),
            arguments=[str(item) for item in task.get("arguments", [])],
            command=str(task["command"]) if task.get("command") else None,
            pipeline_data=task.get("pipeline_data"),
            metadata={str(key): value for key, value in dict(task.get("metadata") or {}).items()},
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutorTask":
        return cls(
            protocol=str(payload.get("protocol") or PROTOCOL_VERSION),
            request_id=str(payload.get("request_id") or uuid.uuid4().hex[:16]),
            capability=str(payload.get("capability") or "tool"),
            kind=str(payload.get("kind") or "tool"),
            operation=str(payload["operation"]) if payload.get("operation") else None,
            arguments=[str(item) for item in payload.get("arguments", [])],
            command=str(payload["command"]) if payload.get("command") else None,
            pipeline_data=payload.get("pipeline_data"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class ExecutorResult:
    request_id: str
    status: str = "ok"
    output: str = ""
    data: Any = None
    error: str | None = None
    data_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    protocol: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "request_id": self.request_id,
            "status": self.status,
            "output": self.output,
            "data": self.data,
            "error": self.error,
            "data_type": self.data_type,
            "metadata": self.metadata,
        }
