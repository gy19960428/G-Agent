"""S1.4 验证: SSE 解析三家(Claude / OAI responses / OAI chat)行为锁定。
覆盖: 文本拼接 / tool_use 还原 / 未知事件 warn 一次(去重) / JSON 解析失败可 grep。
"""

import sys
import json
import importlib
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# tgapp stub 污染规避
sys.modules.pop("g_agent.llm", None)
llm = importlib.import_module("g_agent.llm")


def sse(events):
    """把 dict 列表(或裸字符串)编成 SSE 行 bytes 列表(模拟 iter_lines)。"""
    out = []
    for e in events:
        if isinstance(e, str):
            out.append(e.encode("utf-8"))
        else:
            out.append(("data: " + json.dumps(e)).encode("utf-8"))
    return out


def drain(gen):
    texts = []
    try:
        while True:
            texts.append(next(gen))
    except StopIteration as e:
        return "".join(texts), e.value


# ---------- Claude SSE ----------


def test_claude_sse_text_and_tool_use():
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi "}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}},
        {"type": "content_block_stop"},
        {"type": "content_block_start", "content_block": {"type": "tool_use", "id": "tu_1", "name": "code_run"}},
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"q":'}},
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '"ok"}'}},
        {"type": "content_block_stop"},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    text, blocks = drain(llm._parse_claude_sse(sse(events)))
    assert text == "hi world"
    assert any(b["type"] == "text" and b["text"] == "hi world" for b in blocks)
    tus = [b for b in blocks if b["type"] == "tool_use"]
    assert len(tus) == 1
    assert tus[0]["id"] == "tu_1" and tus[0]["name"] == "code_run"
    assert tus[0]["input"] == {"q": "ok"}


def test_claude_sse_unknown_event_warns_once(capsys):
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    events = [
        {"type": "weird_evt_xyz"},
        {"type": "weird_evt_xyz"},  # 去重: 第二次不应再打印
        {"type": "message_stop"},
    ]
    drain(llm._parse_claude_sse(sse(events)))
    out = capsys.readouterr().out
    assert out.count("[SSE-WARN] unknown") == 1
    assert "claude" in out and "weird_evt_xyz" in out


def test_claude_sse_json_parse_error_grepable(capsys):
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    lines = sse(["data: {not json", {"type": "message_stop"}])
    drain(llm._parse_claude_sse(lines))
    out = capsys.readouterr().out
    assert "[SSE-WARN] claude json parse error" in out


# ---------- OpenAI responses ----------


def test_oai_responses_text_and_tool_use():
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    events = [
        {"type": "response.output_text.delta", "delta": "hello"},
        {"type": "response.output_text.delta", "delta": " world"},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "function_call", "call_id": "fc_a", "name": "code_run"},
        },
        {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"x":1}'},
        {"type": "response.function_call_arguments.done", "output_index": 0, "arguments": '{"x":1}'},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1, "output_tokens": 2}}},
    ]
    text, blocks = drain(llm._parse_openai_sse(sse(events), api_mode="responses"))
    assert text == "hello world"
    tus = [b for b in blocks if b["type"] == "tool_use"]
    assert len(tus) == 1 and tus[0]["id"] == "fc_a"
    assert tus[0]["input"] == {"x": 1}


def test_oai_responses_unknown_event_warns_once(capsys):
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    events = [
        {"type": "response.brand_new_event_xyz"},
        {"type": "response.brand_new_event_xyz"},
        {"type": "response.completed", "response": {"usage": {}}},
    ]
    drain(llm._parse_openai_sse(sse(events), api_mode="responses"))
    out = capsys.readouterr().out
    assert out.count("[SSE-WARN] unknown") == 1
    assert "oai-responses" in out and "brand_new_event_xyz" in out


def test_oai_responses_known_silent_no_warn(capsys):
    """已知但忽略的 lifecycle 事件不应触发 unknown warn。"""
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    silent = next(iter(llm._OAI_RESP_SSE_KNOWN_EVENTS))
    events = [
        {"type": silent},
        {"type": "response.completed", "response": {"usage": {}}},
    ]
    drain(llm._parse_openai_sse(sse(events), api_mode="responses"))
    out = capsys.readouterr().out
    assert "[SSE-WARN] unknown" not in out


# ---------- OpenAI chat completions ----------


def test_oai_chat_text_and_tool_calls():
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    events = [
        {"choices": [{"delta": {"content": "foo"}}]},
        {"choices": [{"delta": {"content": "bar"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call_1", "function": {"name": "code_run", "arguments": '{"a":'}}
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}}]},
        "data: [DONE]",
    ]
    text, blocks = drain(llm._parse_openai_sse(sse(events), api_mode="chat_completions"))
    assert text == "foobar"
    tus = [b for b in blocks if b["type"] == "tool_use"]
    assert len(tus) == 1 and tus[0]["id"] == "call_1"
    assert tus[0]["input"] == {"a": 1}


def test_oai_chat_json_parse_error_grepable(capsys):
    llm._SEEN_UNKNOWN_SSE_EVENTS.clear()
    lines = sse(["data: {bad", "data: [DONE]"])
    drain(llm._parse_openai_sse(lines, api_mode="chat_completions"))
    out = capsys.readouterr().out
    assert "[SSE-WARN] oai-chat json parse error" in out
