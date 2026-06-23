from __future__ import annotations

from dataclasses import dataclass, field

from g_agent_ng.runtime.models import RuntimeEvent


@dataclass
class InMemorySessionStore:
    events: dict[str, list[RuntimeEvent]] = field(default_factory=dict)

    def append(self, session_id: str, event: RuntimeEvent) -> None:
        self.events.setdefault(session_id, []).append(event)

    def list_events(self, session_id: str) -> tuple[RuntimeEvent, ...]:
        return tuple(self.events.get(session_id, ()))
