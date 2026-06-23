from __future__ import annotations

from typing import AsyncIterator, Protocol

from g_agent_ng.llm.models import ModelEvent, ModelRequest
from g_agent_ng.runtime.context import RunContext


class LLMClient(Protocol):
    async def stream(self, request: ModelRequest, context: RunContext) -> AsyncIterator[ModelEvent]:
        """Yield provider-normalized model events for one request."""
        ...


class EchoClient:
    """Deterministic local client used for smoke tests and offline development."""

    async def stream(self, request: ModelRequest, context: RunContext) -> AsyncIterator[ModelEvent]:
        context.cancellation.raise_if_cancelled()
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        yield ModelEvent(type="text", text=f"Echo: {last_user}")
        yield ModelEvent(type="finish")
