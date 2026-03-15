from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable


@dataclass(slots=True)
class Event:
    name: str
    payload: Any = None
    source: str = "nova"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "payload": self.payload,
            "source": self.source,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


EventHandler = Callable[[Event], Any]


@dataclass(slots=True)
class EventSubscription:
    event_name: str
    handler: EventHandler


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: dict[str, list[EventSubscription]] = {}
        self.history: list[Event] = []

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self._subscriptions.setdefault(event_name, []).append(EventSubscription(event_name=event_name, handler=handler))

    def publish(
        self,
        event_name: str,
        payload: Any = None,
        *,
        source: str = "nova",
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(name=event_name, payload=payload, source=source, metadata=metadata or {})
        self.history.append(event)
        for subscription in self._subscriptions.get(event_name, []):
            subscription.handler(event)
        for subscription in self._subscriptions.get("*", []):
            subscription.handler(event)
        return event
