from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ModelRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ModelMessage:
    role: ModelRole
    content: str
    name: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolSpec, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelEvent:
    type: Literal["text", "tool_call", "usage", "finish", "error"]
    text: str = ""
    tool_call: ToolCall | None = None
    data: dict[str, Any] = field(default_factory=dict)
