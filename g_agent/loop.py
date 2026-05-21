import json
import re
import os
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class StepOutcome:
    data: Any
    next_prompt: Optional[str] = None
    should_exit: bool = False


def try_call_generator(func, *args, **kwargs):
    ret = func(*args, **kwargs)
    if hasattr(ret, "__iter__") and not isinstance(ret, (str, bytes, dict, list)):
        ret = yield from ret
    return ret


class BaseHandler:
    def tool_before_callback(self, tool_name, args, response):
        pass

    def tool_after_callback(self, tool_name, args, response, ret):
        pass

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        return next_prompt

    def dispatch(self, tool_name, args, response, index=0, tool_num=1):
        method_name = f"do_{tool_name}"
        # 短路: _try_parse_tool_args 失败时显式标记,避免把 do_xxx 当空 args 跑
        if isinstance(args, dict) and "_parse_error" in args:
            err = args.get("_parse_error", "unknown")
            raw = args.get("_raw", "")
            msg = f"[tool_args_parse_error] {tool_name}: {err}; raw[:200]={raw[:200]!r}"
            yield msg + "\n"
            return StepOutcome(msg, next_prompt="\n参数解析失败,请重新生成 JSON。\n", should_exit=False)
        if hasattr(self, method_name):
            args["_index"] = index
            args["_tool_num"] = tool_num
            prer = yield from try_call_generator(self.tool_before_callback, tool_name, args, response)
            ret = yield from try_call_generator(getattr(self, method_name), args, response)
            _ = yield from try_call_generator(self.tool_after_callback, tool_name, args, response, ret)
            return ret
        elif tool_name == "bad_json":
            return StepOutcome(None, next_prompt=args.get("msg", "bad_json"), should_exit=False)
        else:
            yield f"未知工具: {tool_name}\n"
            return StepOutcome(None, next_prompt=f"未知工具 {tool_name}", should_exit=False)


def json_default(o):
    return list(o) if isinstance(o, set) else str(o)


def exhaust(g):
    try:
        while True:
            next(g)
    except StopIteration as e:
        return e.value


def get_pretty_json(data):
    if isinstance(data, dict) and "script" in data:
        data = data.copy()
        data["script"] = data["script"].replace("; ", ";\n  ")
    return json.dumps(data, indent=2, ensure_ascii=False).replace("\\n", "\n")


def agent_runner_loop(
    client,
    system_prompt,
    user_input,
    handler,
    tools_schema,
    max_turns=40,
    verbose=True,
    initial_user_content=None,
    yield_info=False,
):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_user_content if initial_user_content is not None else user_input},
    ]
    turn = 0
    handler.max_turns = max_turns
    _plan_reminded = False  # 一次性 plan 提醒，避免长任务超 max_turns 中断
    _task_dir = getattr(getattr(handler, "parent", None), "task_dir", "") or ""
    print(f"[LOOP] begin max_turns={max_turns} task_dir={_task_dir!r} verbose={verbose}", flush=True)
    while turn < handler.max_turns:
        turn += 1
        turnstr = f"LLM Running (Turn {turn}) ..."
        if handler.parent.task_dir:
            turnstr = f"Turn {turn} ..."
        if verbose:
            turnstr = f"**{turnstr}**"
        if yield_info:
            yield {"turn": turn}
        yield f"\n\n{turnstr}\n\n"
        if turn % 10 == 0:
            client.last_tools = ""  # 每10轮重置一次工具描述，避免上下文过大导致的模型性能下降
        # turn 过半仍未进入 plan 模式 → 注入系统提醒（一次性），防止 MAX_TURNS_EXCEEDED 中断
        if (
            (not _plan_reminded)
            and turn >= max(2, handler.max_turns // 2)
            and not getattr(handler, "working", {}).get("in_plan_mode")
        ):
            _plan_reminded = True
            _reminder = (
                f"\n\n[SYSTEM REMINDER] You have used {turn}/{handler.max_turns} turns "
                f"without entering plan mode. If this task is multi-step, on your NEXT tool call "
                f"create `./plan_XXX/plan.md` via file_write/file_patch (auto-enters plan mode, "
                f"raises turn budget to 100). Otherwise the loop will hard-stop at "
                f"{handler.max_turns} turns.\n"
            )
            if messages and isinstance(messages[-1].get("content"), str):
                messages[-1]["content"] = _reminder + messages[-1]["content"]
        _t_llm = time.time()
        print(f"[LOOP] turn={turn}/{handler.max_turns} llm.begin msgs={len(messages)}", flush=True)
        response_gen = client.chat(messages=messages, tools=tools_schema)
        if verbose:
            response = yield from response_gen
            yield "\n\n"
        else:
            response = exhaust(response_gen)
            cleaned = _clean_content(response.content)
            if cleaned:
                yield cleaned + "\n"
        _tc_cnt = len(response.tool_calls or []) if response else 0
        _cb = len(getattr(response, "content", "") or "") if response else 0
        print(
            f"[LOOP] turn={turn} llm.done elapsed={time.time()-_t_llm:.1f}s tool_calls={_tc_cnt} content_bytes={_cb}",
            flush=True,
        )

        if not response.tool_calls:
            tool_calls = [{"tool_name": "no_tool", "args": {}}]
        else:
            tool_calls = [
                {"tool_name": tc.function.name, "args": json.loads(tc.function.arguments), "id": tc.id}
                for tc in response.tool_calls
            ]

        tool_results = []
        next_prompts = set()
        exit_reason = {}
        for ii, tc in enumerate(tool_calls):
            tool_name, args, tid = tc["tool_name"], tc["args"], tc.get("id", "")
            if tool_name == "no_tool":
                pass
            else:
                if verbose:
                    yield f"🛠️ Tool: `{tool_name}`  📥 args:\n````text\n{get_pretty_json(args)}\n````\n"
                else:
                    yield f"🛠️ {tool_name}({_compact_tool_args(tool_name, args)})\n\n\n"
            handler.current_turn = turn
            _t_tool = time.time()
            print(f"[LOOP] turn={turn} tool.begin name={tool_name} idx={ii}", flush=True)
            gen = handler.dispatch(tool_name, args, response, index=ii, tool_num=len(tool_calls))
            try:
                v = next(gen)

                def proxy():
                    yield v
                    return (yield from gen)

                if verbose:
                    yield "`````\n"
                outcome = (yield from proxy()) if verbose else exhaust(proxy())
                if verbose:
                    yield "`````\n"
            except StopIteration as e:
                outcome = e.value
            print(
                f"[LOOP] turn={turn} tool.done name={tool_name} idx={ii} elapsed={time.time()-_t_tool:.1f}s exit={outcome.should_exit} has_next={bool(outcome.next_prompt)}",
                flush=True,
            )

            if outcome.should_exit:
                exit_reason = {"result": "EXITED", "data": outcome.data}
                break
            if not outcome.next_prompt:
                exit_reason = {"result": "CURRENT_TASK_DONE", "data": outcome.data}
                break
            if outcome.next_prompt.startswith("未知工具"):
                client.last_tools = ""
            if outcome.data is not None and tool_name != "no_tool":
                datastr = (
                    json.dumps(outcome.data, ensure_ascii=False, default=json_default)
                    if type(outcome.data) in [dict, list]
                    else str(outcome.data)
                )
                tool_results.append({"tool_use_id": tid, "content": datastr})
            next_prompts.add(outcome.next_prompt)
        if len(next_prompts) == 0 or exit_reason:
            if len(handler._done_hooks) == 0 or exit_reason.get("result", "") == "EXITED":
                break
            next_prompts.add(handler._done_hooks.pop(0))
        next_prompt = handler.turn_end_callback(
            response, tool_calls, tool_results, turn, "\n".join(next_prompts), exit_reason
        )
        messages = [
            {"role": "user", "content": next_prompt, "tool_results": tool_results}
        ]  # just new message, history is kept in *Session
    # 无条件 fire 一次终结 callback：MAX_TURNS_EXCEEDED 时 exit_reason 为 None,前端 hook 收不到 ctx['exit_reason'] 就只能等 idle 超时兜底,故用 MAX_TURNS_EXCEEDED 兜底,保证 done_event 一定被 set。
    if turn > 0:
        _final_reason = exit_reason or {"result": "MAX_TURNS_EXCEEDED"}
        handler.turn_end_callback(response, tool_calls, tool_results, turn, "", _final_reason)
    _ret = exit_reason or {"result": "MAX_TURNS_EXCEEDED"}
    print(f"[LOOP] end turns={turn} reason={_ret.get('result', '')}", flush=True)
    return _ret


def _clean_content(text):
    if not text:
        return ""

    def _shrink_code(m):
        lines = m.group(0).split("\n")
        lang = lines[0].replace("```", "").strip()
        body = [l for l in lines[1:-1] if l.strip()]
        if len(body) <= 6:
            return m.group(0)
        preview = "\n".join(body[:5])
        return f"```{lang}\n{preview}\n  ... ({len(body)} lines)\n```"

    text = re.sub(r"```[\s\S]*?```", _shrink_code, text)
    for p in [
        r"<file_content>[\s\S]*?</file_content>",
        r"<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>",
        r"(\r?\n){3,}",
    ]:
        text = re.sub(p, "\n\n" if "\\n" in p else "", text)
    return text.strip()


def _compact_tool_args(name, args):
    a = {k: v for k, v in args.items() if k != "_index"}
    for k in ("path",):
        if k in a:
            a[k] = os.path.basename(a[k])
    if name == "update_working_checkpoint":
        s = a.get("key_info", "")
        return (s[:60] + "...") if len(s) > 60 else s
    if name == "ask_user":
        q = str(a.get("question", ""))
        cs = a.get("candidates") or []
        if cs:
            q += "\ncandidates:\n" + "\n".join(f"- {c}" for c in cs)
        return q
    s = json.dumps(a, ensure_ascii=False)
    return (s[:120] + "...") if len(s) > 120 else s
