import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_FRONTENDS = _ROOT / "frontends"
for _p in (str(_ROOT), str(_FRONTENDS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from g_agent.command_dispatch import (
    command_op,
    frontend_help_commands,
    is_supported_frontend_command,
    normalize_command,
    telegram_menu_commands,
)
from frontends.chatapp_common import HELP_COMMANDS, TELEGRAM_MENU_COMMANDS, is_supported_command


def test_normalize_and_command_op():
    assert normalize_command("  /llm 1  ") == "/llm 1"
    assert command_op("  /review current diff") == "/review"
    assert command_op(None) == ""


def test_frontend_command_compatibility_and_new_entries():
    supported = [
        "/help",
        "/status",
        "/stop",
        "/new",
        "/restore",
        "/continue",
        "/continue 2",
        "/llm",
        "/llm 1",
        "/btw what changed?",
        "/review",
        "/review frontends",
    ]
    for cmd in supported:
        assert is_supported_frontend_command(cmd)
        assert is_supported_command(cmd)

    rejected = ["help", "/unknown", "/continue abc", "/llm two"]
    for cmd in rejected:
        assert not is_supported_frontend_command(cmd)
        assert not is_supported_command(cmd)


def test_help_and_telegram_menu_are_derived_from_shared_specs():
    assert HELP_COMMANDS == frontend_help_commands()
    assert TELEGRAM_MENU_COMMANDS == telegram_menu_commands()
    assert ("/btw <q>", "side question - 临时插问主 agent 进展，不打断主线") in HELP_COMMANDS
    assert ("/review [scope]", "in-session code review; 默认审当前 git diff") in HELP_COMMANDS
    assert ("btw", "side question - 临时插问主 agent 进展，不打断主线") in TELEGRAM_MENU_COMMANDS
    assert ("review", "in-session code review; 默认审当前 git diff") in TELEGRAM_MENU_COMMANDS
