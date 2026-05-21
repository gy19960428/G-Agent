import os
import sys
import threading
import queue
import time
import json
import re
import random
import locale

os.environ.setdefault(
    "G_AGENT_LANG", "zh" if any(k in (locale.getlocale()[0] or "").lower() for k in ("zh", "chinese")) else "en"
)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from g_agent.llm import (
    reload_mykeys,
    ToolClient,
    MixinSession,
    NativeToolClient,
    NativeClaudeSession,
    NativeOAISession,
    resolve_client,
)
from g_agent.loop import agent_runner_loop
from g_agent.tool_handler import ToolHandler, get_global_memory
from g_agent.tools.user_io import smart_format, format_error, consume_file
from g_agent.feishu_events import (
    _feishu_progress_display,
    _feishu_turn_summaries,
    _feishu_event,
    _feishu_progress_event,
    _feishu_done_event,
    _feishu_final_event,
    _feishu_error_event,
)

# script_dir 语义为项目根（assets/memory/temp 均在根下），g_agent 是子包
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool_schema(suffix=""):
    global TOOLS_SCHEMA
    TS = open(os.path.join(script_dir, f"assets/tools_schema{suffix}.json"), "r", encoding="utf-8").read()
    TOOLS_SCHEMA = json.loads(TS if os.name == "nt" else TS.replace("powershell", "bash"))


load_tool_schema()

lang_suffix = "_en" if os.environ.get("G_AGENT_LANG", "") == "en" else ""
mem_dir = os.path.join(script_dir, "memory")
if not os.path.exists(mem_dir):
    os.makedirs(mem_dir)
mem_txt = os.path.join(mem_dir, "global_mem.txt")
if not os.path.exists(mem_txt):
    open(mem_txt, "w", encoding="utf-8").write("# [Global Memory - L2]\n")
mem_insight = os.path.join(mem_dir, "global_mem_insight.txt")
if not os.path.exists(mem_insight):
    t = os.path.join(script_dir, f"assets/global_mem_insight_template{lang_suffix}.txt")
    open(mem_insight, "w", encoding="utf-8").write(open(t, encoding="utf-8").read() if os.path.exists(t) else "")
cdp_cfg = os.path.join(script_dir, "assets/tmwd_cdp_bridge/config.js")
if not os.path.exists(cdp_cfg):
    try:
        os.makedirs(os.path.dirname(cdp_cfg), exist_ok=True)
        open(cdp_cfg, "w", encoding="utf-8").write(f"const TID = '__ljq_{hex(random.randint(0, 99999999))[2:8]}';")
    except Exception as e:
        print(f"[WARN] CDP config init failed: {e} — advanced web features (tmwebdriver) will be unavailable.")


def get_system_prompt():
    with open(os.path.join(script_dir, f"assets/sys_prompt{lang_suffix}.txt"), "r", encoding="utf-8") as f:
        prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    return prompt


class Agent:
    def __init__(self):
        os.makedirs(os.path.join(script_dir, "temp"), exist_ok=True)
        self.lock = threading.Lock()
        self.task_dir = None
        self.history = []
        self.handler = None
        self.task_queue = queue.Queue()
        self.is_running = False
        self.stop_sig = False
        self.llm_no = 0
        self.inc_out = False
        self.verbose = True
        self.show_mode = "text"
        self.peer_hint = True
        self.log_path = os.path.join(
            script_dir, f"temp/model_responses/model_responses_{int(time.time()*1e6)%1000000:06d}.txt"
        )
        # channel sidecar: 进程启动按 G_AGENT_CHANNEL 写一次 (幂等), restore 用
        try:
            _ch = os.environ.get("G_AGENT_CHANNEL", "unknown") or "unknown"
            _side = self.log_path[:-4] + ".channel"
            os.makedirs(os.path.dirname(_side), exist_ok=True)
            if not os.path.exists(_side):
                with open(_side, "w", encoding="utf-8") as _f:
                    _f.write(_ch)
            # 暴露自身 log 路径，供 restore 排除自身（否则 mtime 最新永远命中自己）
            os.environ["G_AGENT_OWN_LOG"] = self.log_path
        except Exception:
            pass
        self.load_llm_sessions()

    def load_llm_sessions(self):
        mykeys, changed = reload_mykeys()
        if not changed and hasattr(self, "llmclients"):
            return
        try:
            oldhistory = self.llmclient.backend.history
        except:
            oldhistory = None
        llm_sessions = []
        for k, cfg in mykeys.items():
            if not any(x in k for x in ["api", "config", "cookie"]):
                continue
            try:
                if "mixin" in k:
                    llm_sessions += [{"mixin_cfg": cfg}]
                elif c := resolve_client(k):
                    llm_sessions += [c]
            except:
                pass
        for i, s in enumerate(llm_sessions):
            if isinstance(s, dict) and "mixin_cfg" in s:
                try:
                    mixin = MixinSession(llm_sessions, s["mixin_cfg"])
                    if isinstance(mixin._sessions[0], (NativeClaudeSession, NativeOAISession)):
                        llm_sessions[i] = NativeToolClient(mixin)
                    else:
                        llm_sessions[i] = ToolClient(mixin)
                except Exception as e:
                    print(f'\n\n\n[ERROR] Failed to init MixinSession with cfg {s["mixin_cfg"]}: {e}!!!\n\n')
        self.llmclients = llm_sessions
        self.llmclient = self.llmclients[self.llm_no % len(self.llmclients)]
        if oldhistory:
            self.llmclient.backend.history = oldhistory

    def next_llm(self, n=-1):
        self.load_llm_sessions()
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclients)
        lastc = self.llmclient
        self.llmclient = self.llmclients[self.llm_no]
        try:
            self.llmclient.backend.history = lastc.backend.history
        except:
            raise Exception("[ERROR] BAD Mixin config: Check your mykey.py")
        self.llmclient.last_tools = ""
        name = self.get_llm_name(model=True)
        if "glm" in name or "minimax" in name or "kimi" in name:
            load_tool_schema("_cn")
        else:
            load_tool_schema()

    def list_llms(self):
        self.load_llm_sessions()
        return [(i, self.get_llm_name(b), i == self.llm_no) for i, b in enumerate(self.llmclients)]

    def get_llm_name(self, b=None, model=False):
        b = self.llmclient if b is None else b
        if isinstance(b, dict):
            return "BADCONFIG_MIXIN"
        if model:
            return b.backend.model.lower()
        return f"{type(b.backend).__name__}/{b.backend.name}"

    def abort(self):
        if not self.is_running:
            return
        print("Abort current task...")
        self.stop_sig = True
        if self.handler is not None:
            self.handler.code_stop_signal.append(1)

    def put_task(self, query, source="user", images=None):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "images": images or [], "output": display_queue})
        return display_queue

    # i know it is dangerous, but raw_query is dangerous enough it doesn't enlarge
    def _handle_slash_cmd(self, raw_query, display_queue):
        if not raw_query.startswith("/"):
            return raw_query
        if _sm := re.match(r"/session\.(\w+)=(.*)", raw_query.strip()):
            k, v = _sm.group(1), _sm.group(2)
            vfile = os.path.join(script_dir, "temp", v)
            if os.path.isfile(vfile):
                v = open(vfile, encoding="utf-8").read().strip()
            try:
                v = json.loads(v)  # cover number parsing
            except (json.JSONDecodeError, ValueError):
                pass
            setattr(self.llmclient.backend, k, v)
            display_queue.put(
                {"done": smart_format(f"✅ session.{k} = {repr(v)}", max_str_len=500), "source": "system"}
            )
            return None
        if raw_query.strip() == "/resume":
            return r"帮我看看最近有哪些会话可以恢复。读model_responses/目录，按修改时间取最近10个文件，从每个文件里找最后一个<history>...</history>块，用一句话总结每个会话在聊什么，列表给我选。注意读文件后要把字面的\n替换成真换行才能正确匹配。"
        return raw_query

    def run(self):
        while True:
            task = self.task_queue.get()
            raw_query, source, display_queue = task["query"], task["source"], task["output"]
            _t_task = time.time()
            _q_preview = raw_query[:80].replace("\n", " ") if raw_query else ""
            print(
                f"[AGENT] task.begin source={source} qlen={len(raw_query or '')} qsize={self.task_queue.qsize()} preview={_q_preview!r}",
                flush=True,
            )
            raw_query = self._handle_slash_cmd(raw_query, display_queue)
            if raw_query is None:
                print(
                    f"[AGENT] task.end source={source} elapsed={time.time()-_t_task:.1f}s result=slash_cmd", flush=True
                )
                self.task_queue.task_done()
                continue
            self.is_running = True
            rquery = smart_format(raw_query.replace("\n", " "), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")

            sys_prompt = get_system_prompt() + getattr(self.llmclient.backend, "extra_sys_prompt", "")
            if self.peer_hint:
                sys_prompt += (
                    "\n[Peer] 用户提及其他会话/后台任务状态时: temp/model_responses/ (只找近期修改的文件尾部)\n"
                )
            handler = ToolHandler(self, self.history, os.path.join(script_dir, "temp"))
            if self.handler and "key_info" in self.handler.working:
                ki = re.sub(r"\n\[SYSTEM\] 此为.*?工作记忆[。\n]*", "", self.handler.working["key_info"])  # 去旧
                handler.working["key_info"] = ki
                handler.working["passed_sessions"] = ps = self.handler.working.get("passed_sessions", 0) + 1
                if ps > 0:
                    handler.working[
                        "key_info"
                    ] += f"\n[SYSTEM] 此为 {ps} 个对话前设置的key_info，若已在新任务，先更新或清除工作记忆。\n"
            self.handler = handler  # although new handler, the **full** history is in llmclient, so it is full history!
            self.llmclient.log_path = self.log_path
            user_input = raw_query
            if (
                source == "feishu" and not raw_query.startswith("/") and len(self.history) > 1
            ):  # 飞书普通消息才注入锚点，避免命令链路被包装
                user_input = handler._get_anchor_prompt() + f"\n\n### 用户当前消息\n{raw_query}"
            if "gpt" in self.get_llm_name(model=True):
                handler._done_hooks.append(
                    "请确定用户任务是否完成，如未完成需要继续工具调用直到完成任务，确实需要问用户应使用ask_user工具"
                )
            gen = agent_runner_loop(
                self.llmclient, sys_prompt, user_input, handler, TOOLS_SCHEMA, max_turns=80, verbose=self.verbose
            )
            try:
                full_resp = ""
                last_pos = 0
                last_progress_display = ""
                completed_turns = set()
                last_turn = None
                for chunk in gen:
                    if consume_file(self.task_dir, "_stop"):
                        self.abort()
                    if self.stop_sig:
                        break
                    full_resp += chunk
                    if source == "feishu":
                        progress = _feishu_progress_display(full_resp)
                        turn_updates = []
                        events = []
                        cur_turn = progress.get("turn") if progress else None
                        cur_display = progress.get("display") if progress else ""
                        seen_turns = {
                            item["turn"] for item in _feishu_turn_summaries(full_resp) if item.get("turn") is not None
                        }
                        # Any turn older than the current active turn is complete once a newer turn starts.
                        pending_done_turns = set(seen_turns - completed_turns)
                        if cur_turn is not None:
                            pending_done_turns = {t for t in pending_done_turns if t < cur_turn}
                        for done_turn in sorted(pending_done_turns):
                            done_event = _feishu_done_event(done_turn, full_resp)
                            if done_event:
                                events.append(done_event)
                                completed_turns.add(done_turn)
                        if cur_turn is not None and cur_turn != last_turn:
                            events.append(
                                _feishu_event(
                                    "turn_start",
                                    turn=cur_turn,
                                    text=full_resp,
                                    display=cur_display or f"Turn {cur_turn}：思考中",
                                    status="running",
                                )
                            )
                        elif cur_turn is not None and cur_display and cur_display != last_progress_display:
                            events.append(_feishu_progress_event(full_resp))
                        if cur_turn is not None:
                            last_turn = cur_turn
                        events = [ev for ev in events if ev]
                        if events:
                            display_queue.put(
                                {
                                    "next": full_resp,
                                    "progress": progress,
                                    "turn_updates": [],
                                    "events": events,
                                    "source": source,
                                }
                            )
                            if cur_display:
                                last_progress_display = cur_display
                    elif len(full_resp) - last_pos > 50 or "LLM Running" in chunk:
                        display_queue.put(
                            {"next": full_resp[last_pos:] if self.inc_out else full_resp, "source": source}
                        )
                        last_pos = len(full_resp)
                if self.inc_out and source != "feishu" and last_pos < len(full_resp):
                    display_queue.put({"next": full_resp[last_pos:], "source": source})
                if self.stop_sig:
                    self.history = handler.history_info
                    continue
                if "</summary>" in full_resp:
                    full_resp = full_resp.replace("</summary>", "</summary>\n\n")
                if "</file_content>" in full_resp:
                    full_resp = re.sub(
                        r"<file_content>\s*(.*?)\s*</file_content>",
                        r"\n````\n<file_content>\n\1\n</file_content>\n````",
                        full_resp,
                        flags=re.DOTALL,
                    )
                payload = {"done": full_resp, "source": source}
                if source == "feishu":
                    final_events = []
                    if last_turn is not None and last_turn not in completed_turns:
                        done_event = _feishu_done_event(last_turn, full_resp)
                        final_events.append(done_event)
                        completed_turns.add(last_turn)
                    final_event = _feishu_final_event(full_resp)
                    final_events.append(final_event)
                    payload["turn_updates"] = []
                    payload["final_display"] = final_event["display"]
                    payload["events"] = final_events
                display_queue.put(payload)
                self.history = handler.history_info
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                print(f"[AGENT] task.error source={source} exc={type(e).__name__}: {str(e)[:200]}", flush=True)
                payload = {"done": full_resp + f"\n```\n{format_error(e)}\n```", "source": source}
                if source == "feishu":
                    error_event = _feishu_error_event(full_resp, e)
                    payload["display"] = error_event["display"]
                    payload["events"] = [error_event]
                display_queue.put(payload)
            finally:
                if self.stop_sig:
                    print("User aborted the task.")
                _turns = getattr(self.handler, "current_turn", None)
                _result = "aborted" if self.stop_sig else "ok"
                _resp_bytes = len(full_resp) if "full_resp" in locals() else 0
                print(
                    f"[AGENT] task.end source={source} elapsed={time.time()-_t_task:.1f}s turns={_turns} result={_result} resp_bytes={_resp_bytes}",
                    flush=True,
                )
                self.is_running = self.stop_sig = False
                self.task_queue.task_done()
                if self.handler is not None:
                    self.handler.code_stop_signal.append(1)


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser()
    parser.add_argument("--task", metavar="IODIR", help="一次性任务模式(文件IO)")
    parser.add_argument("--reflect", metavar="SCRIPT", help="反射模式：加载监控脚本，check()触发时发任务")
    parser.add_argument("--input", help="prompt")
    parser.add_argument("--llm_no", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--nobg", action="store_true")
    args, _unknown = parser.parse_known_args()
    _reflect_args = dict(zip([k.lstrip("-") for k in _unknown[::2]], _unknown[1::2])) if _unknown else {}

    if args.task and not args.nobg:
        import subprocess
        import platform

        cmd = [sys.executable, os.path.abspath(__file__)] + [a for a in sys.argv[1:]] + ["--nobg"]
        d = os.path.join(script_dir, f"temp/{args.task}")
        os.makedirs(d, exist_ok=True)
        p = subprocess.Popen(
            cmd,
            cwd=script_dir,
            creationflags=0x08000000 if platform.system() == "Windows" else 0,
            stdout=open(os.path.join(d, "stdout.log"), "w", encoding="utf-8"),
            stderr=open(os.path.join(d, "stderr.log"), "w", encoding="utf-8"),
        )
        print(p.pid)
        sys.exit(0)

    agent = Agent()
    agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        agent.peer_hint = False
        agent.task_dir = d = os.path.join(script_dir, f"temp/{args.task}")
        nround = ""
        infile = os.path.join(d, "input.txt")
        if args.input:
            os.makedirs(d, exist_ok=True)
            import glob

            [os.remove(f) for f in glob.glob(os.path.join(d, "output*.txt"))]
            with open(infile, "w", encoding="utf-8") as f:
                f.write(args.input)
        if fh := consume_file(d, "_history.json"):
            agent.llmclient.backend.history = json.loads(fh)
        with open(infile, encoding="utf-8") as f:
            raw = f.read()
        while True:
            dq = agent.put_task(raw, source="task")
            while "done" not in (item := dq.get(timeout=300)):
                if "next" in item and random.random() < 0.95:  # 概率写一次中间结果
                    with open(f"{d}/output{nround}.txt", "w", encoding="utf-8") as f:
                        f.write(item.get("next", ""))
            with open(f"{d}/output{nround}.txt", "w", encoding="utf-8") as f:
                f.write(item["done"] + "\n\n[ROUND END]\n")
            consume_file(d, "_stop")  # 已经成功停下来了，避免打断下次reply
            for _ in range(300):  # 等reply.txt，10分钟超时
                time.sleep(2)
                if raw := consume_file(d, "reply.txt"):
                    break
            else:
                break
            nround = nround + 1 if isinstance(nround, int) else 1
    elif args.reflect:
        agent.peer_hint = False
        import importlib.util

        spec = importlib.util.spec_from_file_location("reflect_script", args.reflect)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "init"):
            mod.init(_reflect_args)
        _mt = os.path.getmtime(args.reflect)
        print(f"[Reflect] loaded {args.reflect}" + (f" args={_reflect_args}" if _reflect_args else ""))
        while True:
            if os.path.getmtime(args.reflect) != _mt:
                try:
                    spec.loader.exec_module(mod)
                    _mt = os.path.getmtime(args.reflect)
                    if hasattr(mod, "init"):
                        mod.init(_reflect_args)
                    print("[Reflect] reloaded")
                except Exception as e:
                    print(f"[Reflect] reload error: {e}")
            time.sleep(getattr(mod, "INTERVAL", 5))
            try:
                task = mod.check()
            except Exception as e:
                print(f"[Reflect] check() error: {e}")
                continue
            if task and task == "/exit":
                break
            if task is None:
                continue
            print(f"[Reflect] triggered: {task[:80]}")
            dq = agent.put_task(task, source="reflect")
            try:
                while "done" not in (item := dq.get(timeout=180)):
                    pass
                result = item["done"]
                print(result)
            except Exception as e:
                if getattr(mod, "ONCE", False):
                    raise
                print(f"[Reflect] drain error: {e}")
                result = f"[ERROR] {e}"
            log_dir = os.path.join(script_dir, "temp/reflect_logs")
            os.makedirs(log_dir, exist_ok=True)
            script_name = os.path.splitext(os.path.basename(args.reflect))[0]
            open(os.path.join(log_dir, f"{script_name}_{datetime.now():%Y-%m-%d}.log"), "a", encoding="utf-8").write(
                f"[{datetime.now():%m-%d %H:%M}]\n{result}\n\n"
            )
            if on_done := getattr(mod, "on_done", None):
                try:
                    on_done(result)
                except Exception as e:
                    print(f"[Reflect] on_done error: {e}")
            if getattr(mod, "ONCE", False):
                print("[Reflect] ONCE=True, exiting.")
                break
    else:
        try:
            pass
        except Exception:
            pass
        agent.inc_out = True
        if sys.stdout.isatty():
            try:
                model = agent.get_llm_name(model=True) or "?"
            except Exception:
                model = "?"
            try:
                sys.stdout.write(f"\x1b[92m✦\x1b[0m \x1b[1mG-Agent\x1b[0m " f"\x1b[90m· cli · model:\x1b[0m {model}\n")
                sys.stdout.flush()
            except Exception:
                pass
        while True:
            q = input("> ").strip()
            if not q:
                continue
            try:
                dq = agent.put_task(q, source="user")
                while True:
                    item = dq.get()
                    if "next" in item:
                        print(item["next"], end="", flush=True)
                    if "done" in item:
                        print()
                        break
            except KeyboardInterrupt:
                agent.abort()
                print("\n[Interrupted]")
