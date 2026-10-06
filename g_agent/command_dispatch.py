"""Shared slash-command parsing helpers.

This module keeps command capability checks in one place so chat frontends and
the core agent do not grow separate, drifting regex lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    usage: str | None = None
    frontend: bool = True
    core: bool = False
    accepts_arg: bool = False
    numeric_arg: bool = False

    @property
    def help_name(self) -> str:
        return self.usage or self.name

    @property
    def menu_name(self) -> str:
        return self.name.lstrip("/")


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("/help", "显示帮助", frontend=True),
    CommandSpec("/status", "查看状态", frontend=True),
    CommandSpec("/stop", "停止当前任务", frontend=True),
    CommandSpec("/new", "开启新对话并清空当前上下文", frontend=True),
    CommandSpec("/restore", "恢复上次对话历史", frontend=True),
    CommandSpec("/continue", "列出可恢复会话", frontend=True),
    CommandSpec("/continue", "恢复第 n 个会话", usage="/continue [n]", frontend=True, accepts_arg=True, numeric_arg=True),
    CommandSpec("/btw", "side question - 临时插问主 agent 进展，不打断主线", usage="/btw <q>", frontend=True, accepts_arg=True),
    CommandSpec("/review", "in-session code review; 默认审当前 git diff", usage="/review [scope]", frontend=True, accepts_arg=True),
    CommandSpec("/llm", "查看当前模型列表", frontend=True),
    CommandSpec("/llm", "切换到第 n 个模型", usage="/llm [n]", frontend=True, accepts_arg=True, numeric_arg=True),
    CommandSpec("/resume", "列出最近可恢复会话摘要", frontend=False, core=True),
)


def normalize_command(cmd: str | None) -> str:
    return (cmd or "").strip()


def command_op(cmd: str | None) -> str:
    parts = normalize_command(cmd).split(maxsplit=1)
    return (parts[0] if parts else "").lower()


def frontend_help_commands() -> tuple[tuple[str, str], ...]:
    return tuple((spec.help_name, spec.description) for spec in COMMAND_SPECS if spec.frontend)


def telegram_menu_commands() -> tuple[tuple[str, str], ...]:
    commands: list[tuple[str, str]] = []
    seen: set[str] = set()
    for spec in COMMAND_SPECS:
        if not spec.frontend or spec.menu_name in seen:
            continue
        seen.add(spec.menu_name)
        commands.append((spec.menu_name, spec.description))
    return tuple(commands)


def is_supported_frontend_command(cmd: str | None) -> bool:
    cmd = normalize_command(cmd)
    if not cmd.startswith("/"):
        return False
    return any(_matches_spec(cmd, spec) for spec in COMMAND_SPECS if spec.frontend)


def _matches_spec(cmd: str, spec: CommandSpec) -> bool:
    if not spec.accepts_arg:
        return cmd == spec.name
    if spec.numeric_arg:
        return re.fullmatch(rf"{re.escape(spec.name)}(?:\s+\d+)?", cmd) is not None
    return cmd == spec.name or cmd.startswith(spec.name + " ")
