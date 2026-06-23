from __future__ import annotations

import pytest

from g_agent_ng.llm.base import EchoClient
from g_agent_ng.runtime.engine import RuntimeEngine
from g_agent_ng.runtime.models import TurnRequest


@pytest.mark.asyncio
async def test_runtime_echo_turn() -> None:
    engine = RuntimeEngine(EchoClient())

    result = await engine.run_turn(TurnRequest(session_id="s1", user_text="hello"))

    assert result.ok is True
    assert result.final_text == "Echo: hello"
    assert [event.kind for event in result.events] == ["turn_started", "model_delta", "turn_finished"]
