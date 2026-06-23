from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from g_agent_ng.runtime.context import RunContext


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def run(self, args: dict[str, Any], context: RunContext) -> ToolResult:
        ...
