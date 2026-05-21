import ast
import asyncio
import glob
import json
import os
import queue as Q
import re
import socket
import sys
import time

# 确保能导入上级目录的模块（如 g_agent.agent）
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

HELP_COMMANDS = (
    ("/help", "显示帮助"),
    ("/status", "查看状态"),
    ("/stop", "停止当前任务"),
    ("/new", "开启新对话并清空当前上下文"),
    ("/restore", "恢复上次对话历史"),
    ("/continue", "列出可恢复会话"),
    ("/continue [n]", "恢复第 n 个会话"),
    ("/btw <q>", "side question — 临时插问主 agent 进展，不打断主线"),
    ("/review [scope]", "in-session code review; 默认审当前 git diff"),
    ("/llm", "查看当前模型列表"),
    ("/llm [n]", "切换到第 n 个模型"),
)
TELEGRAM_MENU_COMMANDS = (
    ("help", "显示帮助"),
    ("status", "查看状态"),
    ("stop", "停止当前任务"),
    ("new", "开启新对话并清空当前上下文"),
    ("restore", "恢复上次对话历史"),
    ("continue", "列出可恢复会话；/continue n 恢复第 n 个"),
    ("btw", "临时插问主 agent 进展，不打断主线"),
    ("review", "in-session code review；/review scope 指定范围"),
    ("llm", "查看模型列表；/llm n 切换到指定模型"),
)


def build_help_text(commands=HELP_COMMANDS):
    return "📖 命令列表:\n" + "\n".join(f"{cmd} - {desc}" for cmd, desc in commands)


HELP_TEXT = build_help_text()
FILE_HINT = "If you need to show files to user, use [FILE:filepath] in your response."
TAG_PATS = [r"<" + t + r">.*?</" + t + r">" for t in ("thinking", "summary", "tool_use", "file_content")]
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTORE_GLOBS = (
    os.path.join(PROJECT_ROOT, "temp", "model_responses", "model_responses_*.txt"),
    os.path.join(PROJECT_ROOT, "temp", "model_responses_*.txt"),
)
# channel sidecar: <log>.txt -> <log>.channel (单行内容 = fs/wechat/wecom/tg/dc/dingtalk/qq/qt/st/tui/unknown)
# 历史日志无 sidecar 时, restore 第一次扫描首 16KB 按指纹懒回填
CHANNEL_FINGERPRINTS = (
    ("fs", re.compile(r"feishu|飞书|FS-ASK|lark_oapi|open_id", re.I)),
    ("wecom", re.compile(r"wecom|企业微信|qyapi\.weixin", re.I)),
    ("wechat", re.compile(r"wxid_|微信|wechatapp|gewechat", re.I)),
    ("tg", re.compile(r"telegram|tg_chat|tgapp", re.I)),
    ("dc", re.compile(r"discord|dcapp", re.I)),
    ("dingtalk", re.compile(r"dingtalk|钉钉|dingtalkapp", re.I)),
    ("qq", re.compile(r"qqapp|mirai|napcat", re.I)),
    ("qt", re.compile(r"qtapp|PySide6", re.I)),
    ("st", re.compile(r"streamlit|stapp", re.I)),
    ("tui", re.compile(r"tuiapp|tui_v3|Textual", re.I)),
)


def _ensure_channel(log_path):
    """返回 log_path 所属 channel; 缺 sidecar 时按内容指纹懒回填。"""
    side = log_path[:-4] + ".channel" if log_path.endswith(".txt") else log_path + ".channel"
    try:
        if os.path.exists(side):
            v = open(side, "r", encoding="utf-8", errors="ignore").read().strip()
            return v or "unknown"
    except Exception:
        pass
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(16384)
    except Exception:
        head = ""
    hits = [ch for ch, pat in CHANNEL_FINGERPRINTS if pat.search(head)]
    ch = hits[0] if len(hits) == 1 else "unknown"
    try:
        with open(side, "w", encoding="utf-8") as f:
            f.write(ch)
    except Exception:
        pass
    return ch


def write_channel_sidecar(log_path, channel=None):
    """供 g_agent.agent/g_agent.llm 等写入端调用; 进程启动写 sidecar, 幂等。"""
    if channel is None:
        channel = os.environ.get("G_AGENT_CHANNEL", "unknown") or "unknown"
    side = log_path[:-4] + ".channel" if log_path.endswith(".txt") else log_path + ".channel"
    try:
        if os.path.exists(side):
            return
        os.makedirs(os.path.dirname(side), exist_ok=True)
        with open(side, "w", encoding="utf-8") as f:
            f.write(channel)
    except Exception:
        pass


RESTORE_BLOCK_RE = re.compile(
    r"^=== (Prompt|Response) ===.*?\n(.*?)(?=^=== (?:Prompt|Response) ===|\Z)",
    re.DOTALL | re.MULTILINE,
)
HISTORY_RE = re.compile(r"<history>\s*(.*?)\s*</history>", re.DOTALL)
SUMMARY_RE = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.DOTALL)


def clean_reply(text):
    for pat in TAG_PATS:
        text = re.sub(pat, "", text or "", flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or "..."


def extract_files(text):
    return re.findall(r"\[FILE:([^\]]+)\]", text or "")


def strip_files(text):
    return re.sub(r"\[FILE:[^\]]+\]", "", text or "").strip()


def split_text(text, limit):
    text, parts = (text or "").strip() or "...", []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit * 0.6:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts + ([text] if text else []) or ["..."]


def _restore_log_files():
    raw = []
    for pattern in RESTORE_GLOBS:
        raw.extend(glob.glob(pattern))
    raw = sorted(set(raw))
    cur = os.environ.get("G_AGENT_CHANNEL", "unknown") or "unknown"
    own_log = os.environ.get("G_AGENT_OWN_LOG", "") or ""
    # 排除当前进程自身 log（mtime 永远最新会自我命中）
    raw = [f for f in raw if f != own_log]
    # 当前 channel 命中优先; 当前 channel 无命中再退化到 unknown 桶
    own = [f for f in raw if _ensure_channel(f) == cur]
    if own:
        return own
    return [f for f in raw if _ensure_channel(f) == "unknown"]


def _restore_text_pairs(content):
    users = re.findall(r"=== USER ===\n(.+?)(?==== |$)", content, re.DOTALL)
    resps = re.findall(r"=== Response ===.*?\n(.+?)(?==== Prompt|$)", content, re.DOTALL)
    restored = []
    for u, r in zip(users, resps):
        u, r = u.strip(), r.strip()[:500]
        if u and r:
            restored.extend([f"[USER]: {u}", f"[Agent] {r}"])
    return restored


def _native_prompt_obj(prompt_body):
    try:
        prompt = json.loads(prompt_body)
    except Exception:
        return None
    if not isinstance(prompt, dict) or prompt.get("role") != "user":
        return None
    if not isinstance(prompt.get("content"), list):
        return None
    return prompt


def _native_prompt_text(prompt):
    texts = []
    for block in prompt.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return "\n".join(texts).strip()


def _native_history_lines(prompt_text):
    match = HISTORY_RE.search(prompt_text or "")
    if not match:
        return []
    restored = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if line.startswith("[USER]: ") or line.startswith("[Agent] "):
            restored.append(line)
    return restored


def _native_first_user_line(prompt_text):
    text = (prompt_text or "").strip()
    if not text or "<history>" in text or text.startswith("### [WORKING MEMORY]"):
        return ""
    if text.startswith(FILE_HINT):
        text = text[len(FILE_HINT) :].lstrip()
    if "### 用户当前消息" in text:
        text = text.split("### 用户当前消息", 1)[-1].strip()
    return text


def _native_response_summary(response_body):
    try:
        blocks = ast.literal_eval((response_body or "").strip())
    except Exception:
        return ""
    if not isinstance(blocks, list):
        return ""
    text_parts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text:
                text_parts.append(text)
    match = SUMMARY_RE.search("\n".join(text_parts))
    return (match.group(1).strip() if match else "")[:500]


def _restore_native_history(content):
    blocks = RESTORE_BLOCK_RE.findall(content or "")
    if not blocks:
        return []
    pairs = []
    pending_prompt = None
    for label, body in blocks:
        if label == "Prompt":
            pending_prompt = body
        elif pending_prompt is not None:
            pairs.append((pending_prompt, body))
            pending_prompt = None
    for prompt_body, response_body in reversed(pairs):
        prompt = _native_prompt_obj(prompt_body)
        if prompt is None:
            continue
        prompt_text = _native_prompt_text(prompt)
        restored = list(_native_history_lines(prompt_text))
        if restored:
            summary = _native_response_summary(response_body)
            summary_line = f"[Agent] {summary}" if summary else ""
            if summary_line and (not restored or restored[-1] != summary_line):
                restored.append(summary_line)
            return restored
        user_text = _native_first_user_line(prompt_text)
        summary = _native_response_summary(response_body)
        if user_text and summary:
            return [f"[USER]: {user_text}", f"[Agent] {summary}"]
    return []


def format_restore():
    files = _restore_log_files()
    if not files:
        return None, "❌ 没有找到历史记录"
    latest = max(files, key=os.path.getmtime)
    with open(latest, "r", encoding="utf-8") as f:
        content = f.read()
    restored = _restore_text_pairs(content) or _restore_native_history(content)
    if not restored:
        return None, "❌ 历史记录里没有可恢复内容"
    count = sum(1 for line in restored if line.startswith("[USER]: "))
    return (restored, os.path.basename(latest), count), None


def build_done_text(raw_text):
    files = [p for p in extract_files(raw_text) if os.path.exists(p)]
    body = strip_files(clean_reply(raw_text))
    if files:
        body = (body + "\n\n" if body else "") + "\n".join(f"生成文件: {p}" for p in files)
    return body or "..."


def public_access(allowed):
    return not allowed or "*" in allowed


def to_allowed_set(value):
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    return {str(x).strip() for x in value if str(x).strip()}


def allowed_label(allowed):
    return "public" if public_access(allowed) else sorted(allowed)


def normalize_command(cmd):
    return (cmd or "").strip()


def is_supported_command(cmd):
    cmd = normalize_command(cmd)
    if not cmd.startswith("/"):
        return False
    return bool(
        re.fullmatch(r"/(?:help|stop|status|restore|new)", cmd)
        or re.fullmatch(r"/continue(?:\s+\d+)?", cmd)
        or re.fullmatch(r"/llm(?:\s+\d+)?", cmd)
    )


def ensure_single_instance(port, label):
    try:
        lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_sock.bind(("127.0.0.1", port))
        return lock_sock
    except OSError:
        print(f"[{label}] Another instance is already running, skipping...")
        sys.exit(1)


def require_runtime(agent, label, **required):
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[{label}] ERROR: please set {', '.join(missing)} in mykey.py or mykey.json")
        sys.exit(1)
    if agent.llmclient is None:
        print(f"[{label}] ERROR: no usable LLM backend found in mykey.py or mykey.json")
        sys.exit(1)


def redirect_log(script_file, log_name, label, allowed):
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(script_file))), "temp")
    os.makedirs(log_dir, exist_ok=True)
    logf = open(os.path.join(log_dir, log_name), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = logf
    print(f"[NEW] {label} process starting, the above are history infos ...")
    print(f"[{label}] allow list: {allowed_label(allowed)}")


class AgentChatMixin:
    label = "Chat"
    source = "chat"
    split_limit = 1500
    ping_interval = 20

    def __init__(self, agent, user_tasks):
        self.agent, self.user_tasks = agent, user_tasks

    async def send_text(self, chat_id, content, **ctx):
        raise NotImplementedError

    async def send_done(self, chat_id, raw_text, **ctx):
        await self.send_text(chat_id, build_done_text(raw_text), **ctx)

    async def handle_command(self, chat_id, cmd, **ctx):
        parts = normalize_command(cmd).split()
        op = (parts[0] if parts else "").lower()
        if op == "/help":
            return await self.send_text(chat_id, HELP_TEXT, **ctx)
        if op == "/stop":
            state = self.user_tasks.get(chat_id)
            if state:
                state["running"] = False
            self.agent.abort()
            return await self.send_text(chat_id, "⏹️ 正在停止...", **ctx)
        if op == "/status":
            llm = self.agent.get_llm_name() if self.agent.llmclient else "未配置"
            return await self.send_text(
                chat_id,
                f"状态: {'🔴 运行中' if self.agent.is_running else '🟢 空闲'}\nLLM: [{self.agent.llm_no}] {llm}",
                **ctx,
            )
        if op == "/llm":
            if not self.agent.llmclient:
                return await self.send_text(chat_id, "❌ 当前没有可用的 LLM 配置", **ctx)
            if len(parts) > 1:
                try:
                    self.agent.next_llm(int(parts[1]))
                    return await self.send_text(
                        chat_id, f"✅ 已切换到 [{self.agent.llm_no}] {self.agent.get_llm_name()}", **ctx
                    )
                except Exception:
                    return await self.send_text(chat_id, f"用法: /llm <0-{len(self.agent.list_llms()) - 1}>", **ctx)
            lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in self.agent.list_llms()]
            return await self.send_text(chat_id, "LLMs:\n" + "\n".join(lines), **ctx)
        if op == "/restore":
            try:
                restored_info, err = format_restore()
                if err:
                    return await self.send_text(chat_id, err, **ctx)
                restored, fname, count = restored_info
                self.agent.abort()
                self.agent.history.extend(restored)
                return await self.send_text(
                    chat_id, f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)", **ctx
                )
            except Exception as e:
                return await self.send_text(chat_id, f"❌ 恢复失败: {e}", **ctx)
        if op == "/continue":
            return await self.send_text(chat_id, _handle_continue_frontend(self.agent, cmd), **ctx)
        if op == "/new":
            return await self.send_text(chat_id, _reset_conversation(self.agent), **ctx)
        if op == "/btw":
            answer = await asyncio.to_thread(_handle_btw_frontend, self.agent, cmd)
            return await self.send_text(chat_id, answer, **ctx)
        if op == "/review":
            return await self.run_agent(chat_id, cmd, **ctx)
        return await self.send_text(chat_id, HELP_TEXT, **ctx)

    async def maybe_handle_command(self, chat_id, text, **ctx):
        if not is_supported_command(text):
            return False
        await self.handle_command(chat_id, text, **ctx)
        return True

    async def run_agent(self, chat_id, text, **ctx):
        state = {"running": True}
        self.user_tasks[chat_id] = state
        try:
            await self.send_text(chat_id, "思考中...", **ctx)
            dq = self.agent.put_task(f"{FILE_HINT}\n\n{text}", source=self.source)
            last_ping = time.time()
            while state["running"]:
                try:
                    item = await asyncio.to_thread(dq.get, True, 3)
                except Q.Empty:
                    if self.agent.is_running and time.time() - last_ping > self.ping_interval:
                        await self.send_text(chat_id, "⏳ 还在处理中，请稍等...", **ctx)
                        last_ping = time.time()
                    continue
                if "done" in item:
                    await self.send_done(chat_id, item.get("done", ""), **ctx)
                    break
            if not state["running"]:
                await self.send_text(chat_id, "⏹️ 已停止", **ctx)
        except Exception as e:
            import traceback

            print(f"[{self.label}] run_agent error: {e}")
            traceback.print_exc()
            await self.send_text(chat_id, f"❌ 错误: {e}", **ctx)
        finally:
            self.user_tasks.pop(chat_id, None)


from g_agent.agent import Agent as _GA
from continue_cmd import (
    handle_frontend_command as _handle_continue_frontend,
    install as _install_continue,
    reset_conversation as _reset_conversation,
)

_install_continue(_GA)
from btw_cmd import handle_frontend_command as _handle_btw_frontend, install as _install_btw

_install_btw(_GA)
from review_cmd import install as _install_review

_install_review(_GA)
