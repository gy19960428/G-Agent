"""g_agent_cli - G-Agent 命令行入口包。

仅承担命令行子命令分发；核心类直接从 g_agent 包导入。
"""
from g_agent.tool_handler import ToolHandler, get_global_memory
from g_agent.tools.user_io import smart_format, format_error, consume_file
from g_agent.loop import BaseHandler, StepOutcome

__all__ = [
    'ToolHandler', 'smart_format', 'get_global_memory',
    'format_error', 'consume_file',
    'BaseHandler', 'StepOutcome',
]
