"""S1.3 验证: _try_parse_tool_args 失败显式 _parse_error;BaseHandler.dispatch 短路。"""
import sys
import importlib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# test_tgapp_inline_selection.py 在 import 阶段把 g_agent.llm 替换为空 stub,
# 在该测试之后 collection 会拿到空 module。这里强制 pop 并重新 import 真模块。
sys.modules.pop("g_agent.llm", None)
_llm = importlib.import_module("g_agent.llm")
_try_parse_tool_args = _llm._try_parse_tool_args
from g_agent.loop import BaseHandler, StepOutcome, exhaust  # noqa: E402


def test_parse_empty_returns_empty_dict():
    assert _try_parse_tool_args("") == [{}]
    assert _try_parse_tool_args(None) == [{}]


def test_parse_valid_json():
    assert _try_parse_tool_args('{"a": 1}') == [{"a": 1}]


def test_parse_concatenated_json():
    out = _try_parse_tool_args('{"a":1}{"b":2}')
    assert out == [{"a": 1}, {"b": 2}]


def test_parse_invalid_returns_parse_error():
    raw = "not a json at all"
    out = _try_parse_tool_args(raw)
    assert len(out) == 1
    assert "_parse_error" in out[0]
    assert out[0]["_raw"] == raw


def test_parse_partially_invalid_concat_returns_parse_error():
    # 看似拼接 {..}{..} 但第二段不是合法 JSON
    raw = '{"a":1}{not_json}'
    out = _try_parse_tool_args(raw)
    assert len(out) == 1 and "_parse_error" in out[0]
    assert out[0]["_raw"] == raw


def test_dispatch_short_circuits_on_parse_error():
    called = {"hit": False}

    class H(BaseHandler):
        def do_dummy(self, args, response):
            called["hit"] = True
            return StepOutcome("should-not-run")

    h = H()
    out = exhaust(h.dispatch("dummy", {"_parse_error": "boom", "_raw": "xxx"}, response=None))
    assert called["hit"] is False
    assert isinstance(out, StepOutcome)
    assert "tool_args_parse_error" in out.data
    assert out.should_exit is False
    assert out.next_prompt and "参数解析失败" in out.next_prompt


def test_dispatch_passes_through_normal_args():
    class H(BaseHandler):
        def do_dummy(self, args, response):
            assert args.get("q") == "ok"
            return StepOutcome("OK")

    h = H()
    out = exhaust(h.dispatch("dummy", {"q": "ok"}, response=None))
    assert isinstance(out, StepOutcome) and out.data == "OK"


def test_unknown_tool_still_returns_outcome():
    h = BaseHandler()
    out = exhaust(h.dispatch("nonexistent_tool_x", {}, response=None))
    assert isinstance(out, StepOutcome) and out.should_exit is False
