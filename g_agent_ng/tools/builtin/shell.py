from __future__ import annotations

import subprocess
from dataclasses import dataclass

from g_agent_ng.runtime.context import RunContext
from g_agent_ng.tools.models import ToolResult


@dataclass(frozen=True)
class ShellTool:
    name: str = "shell.run"
    description: str = "Run a command in a configured working directory."
    input_schema: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.input_schema is None:
            object.__setattr__(self, "input_schema", {"type": "object", "required": ["cmd"]})

    async def run(self, args: dict, context: RunContext) -> ToolResult:
        context.cancellation.raise_if_cancelled()
        cmd = args.get("cmd")
        if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
            return ToolResult(False, "", error="cmd must be a list of strings")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=float(args.get("timeout", 30)))
        content = (proc.stdout or "")[-4000:]
        if proc.returncode != 0:
            return ToolResult(False, content, {"returncode": proc.returncode, "stderr": (proc.stderr or "")[-2000:]}, "command failed")
        return ToolResult(True, content, {"returncode": proc.returncode})
