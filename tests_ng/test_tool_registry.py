from __future__ import annotations

import pytest

from g_agent_ng.runtime.context import RunContext
from g_agent_ng.tools.models import ToolResult
from g_agent_ng.tools.registry import ToolRegistry


class DemoTool:
    name = "demo.add"
    description = "demo tool"
    input_schema = {"type": "object"}

    async def run(self, args: dict, context: RunContext) -> ToolResult:
        return ToolResult(True, str(args["a"] + args["b"]))


def test_tool_registry_lookup() -> None:
    registry = ToolRegistry()
    registry.add(DemoTool())

    assert registry.get("demo.add").name == "demo.add"
    assert len(registry.list()) == 1


def test_tool_registry_rejects_duplicate() -> None:
    registry = ToolRegistry()
    registry.add(DemoTool())

    with pytest.raises(ValueError):
        registry.add(DemoTool())
