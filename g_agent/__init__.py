"""G-Agent 核心包。

聚合 Agent 主类、ToolHandler、运行循环、LLM 客户端等对外符号。
子模块仍可按需直接 import。
"""
from g_agent.agent import Agent
from g_agent.tool_handler import ToolHandler
from g_agent.loop import BaseHandler, StepOutcome, agent_runner_loop
from g_agent.llm import (
    LLMSession, ToolClient, ClaudeSession, MixinSession,
    NativeToolClient, NativeClaudeSession, NativeOAISession,
    resolve_client, reload_mykeys, mykeys,
)

__all__ = [
    'Agent', 'ToolHandler',
    'BaseHandler', 'StepOutcome', 'agent_runner_loop',
    'LLMSession', 'ToolClient', 'ClaudeSession', 'MixinSession',
    'NativeToolClient', 'NativeClaudeSession', 'NativeOAISession',
    'resolve_client', 'reload_mykeys', 'mykeys',
]
