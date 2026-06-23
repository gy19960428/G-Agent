from __future__ import annotations

from dataclasses import asdict

from g_agent_ng.runtime.models import RuntimeEvent


class TerminalRenderer:
    async def render_event(self, event: RuntimeEvent) -> None:
        if event.kind == "model_delta":
            print(event.payload.get("text", ""), end="", flush=True)
        elif event.kind in {"turn_failed", "tool_finished"}:
            print(asdict(event), flush=True)
