from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventKind = Literal[
    "turn_started",
    "model_delta",
    "tool_requested",
    "tool_started",
    "tool_finished",
    "turn_finished",
    "turn_failed",
]


@dataclass(frozen=True)
class RuntimeEvent:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeBudget:
    max_model_rounds: int = 4
    max_tool_calls: int = 16
    wall_timeout_seconds: float = 120.0


@dataclass(frozen=True)
class TurnRequest:
    session_id: str
    user_text: str
    budget: RuntimeBudget = field(default_factory=RuntimeBudget)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnResult:
    session_id: str
    final_text: str
    events: tuple[RuntimeEvent, ...]
    ok: bool = True
    error: str | None = None
