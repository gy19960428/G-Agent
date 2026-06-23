from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from g_agent_ng.browser.controller import BrowserTab, PageElement, PageSnapshot
from g_agent_ng.llm.base import EchoClient
from g_agent_ng.runtime.context import RunContext
from g_agent_ng.runtime.engine import RuntimeEngine
from g_agent_ng.runtime.models import TurnRequest
from g_agent_ng.tools.models import ToolResult
from g_agent_ng.tools.registry import ToolRegistry


class DemoTool:
    name = "demo.add"
    description = "demo tool"
    input_schema = {"type": "object"}

    async def run(self, args: dict, context: RunContext) -> ToolResult:
        return ToolResult(True, str(args["a"] + args["b"]))


async def check_runtime() -> None:
    result = await RuntimeEngine(EchoClient()).run_turn(TurnRequest(session_id="smoke", user_text="hello"))
    assert result.ok is True
    assert result.final_text == "Echo: hello"
    assert [event.kind for event in result.events] == ["turn_started", "model_delta", "turn_finished"]


def check_registry() -> None:
    registry = ToolRegistry()
    registry.add(DemoTool())
    assert registry.get("demo.add").name == "demo.add"
    assert len(registry.list()) == 1
    try:
        registry.add(DemoTool())
    except ValueError:
        return
    raise AssertionError("duplicate tool was accepted")


def check_browser_snapshot() -> None:
    tab = BrowserTab(tab_id="t1", title="Example", url="https://example.invalid")
    element = PageElement(ref="e1", role="button", name="Submit", bounds=(1, 2, 3, 4))
    snapshot = PageSnapshot(tab=tab, elements=(element,))
    assert snapshot.tab.tab_id == "t1"
    assert snapshot.elements[0].visible is True


async def main() -> None:
    await check_runtime()
    check_registry()
    check_browser_snapshot()
    print("g_agent_ng smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
