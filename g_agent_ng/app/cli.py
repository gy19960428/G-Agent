from __future__ import annotations

import argparse
import asyncio

from g_agent_ng.llm.base import EchoClient
from g_agent_ng.runtime.engine import RuntimeEngine
from g_agent_ng.runtime.models import TurnRequest
from g_agent_ng.ui.terminal import TerminalRenderer


async def run_once(text: str, session_id: str) -> int:
    engine = RuntimeEngine(EchoClient())
    renderer = TerminalRenderer()
    result = await engine.run_turn(TurnRequest(session_id=session_id, user_text=text))
    for event in result.events:
        await renderer.render_event(event)
    if result.final_text and not result.final_text.endswith("\n"):
        print()
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="g-agent-ng", description="G-Agent Next smoke CLI")
    parser.add_argument("text", help="single user message to process")
    parser.add_argument("--session", default="local", help="session id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run_once(args.text, args.session)))


if __name__ == "__main__":
    main()
