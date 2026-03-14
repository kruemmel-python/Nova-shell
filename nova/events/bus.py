from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


EventHandler = Callable[[str, dict[str, Any]], None]


@dataclass(slots=True)
class EventBus:
    """Simple topic-based event bus for Nova runtime."""

    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        self._handlers.setdefault(topic, []).append(handler)

    def publish(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        message = payload or {}
        for handler in self._handlers.get(topic, []):
            handler(topic, message)
