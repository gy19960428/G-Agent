from __future__ import annotations

from typing import Protocol

from g_agent_ng.runtime.models import RuntimeEvent, TurnRequest


class UIAdapter(Protocol):
    async def receive_user_turn(self) -> TurnRequest:
        ...

    async def render_event(self, event: RuntimeEvent) -> None:
        ...
