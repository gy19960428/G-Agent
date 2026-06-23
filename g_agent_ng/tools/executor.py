from __future__ import annotations

from g_agent_ng.llm.models import ToolCall
from g_agent_ng.runtime.context import RunContext
from g_agent_ng.tools.models import ToolResult
from g_agent_ng.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, call: ToolCall, context: RunContext) -> ToolResult:
        context.cancellation.raise_if_cancelled()
        tool = self._registry.get(call.name)
        return await tool.run(call.arguments, context)
