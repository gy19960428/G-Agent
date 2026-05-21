"""user_io: 用户交互 / 通用文本格式化 / 错误格式化 / 记忆访问日志。

从 g_agent.tool_handler 拆出，行为保持一致。被其他 tools 子模块依赖（如 code_exec、web_ops）。
"""
import sys
import os
import re
import json
import traceback
from datetime import datetime

# script_dir 语义同 tool_handler.py：项目根（assets/memory/temp 均在根下）
script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

__all__ = [
    "extract_turn_brief",
    "ask_user",
    "format_error",
    "log_memory_access",
    "smart_format",
    "consume_file",
]


def extract_turn_brief(text):
    text = text or ''
    for tag in ('summary', 'thinking'):
        m = re.search(rf'<{tag}>\s*(.*?)\s*</{tag}>', text, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
        return lines[0] if lines else m.group(1).strip()
    return ''


def ask_user(question, candidates=None, multi=False):
    """question: 向用户提出的问题。candidates: 可选的候选项列表。multi: 多选模式（前端据此渲染多选卡片）。"""
    return {"status": "INTERRUPT", "intent": "HUMAN_INTERVENTION",
        "data": {"question": question, "candidates": candidates or [], "multi": bool(multi)}}


def format_error(e):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb = traceback.extract_tb(exc_traceback)
    if tb:
        f = tb[-1]
        fname = os.path.basename(f.filename)
        return f"{exc_type.__name__}: {str(e)} @ {fname}:{f.lineno}, {f.name} -> `{f.line}`"
    return f"{exc_type.__name__}: {str(e)}"


def log_memory_access(path):
    if 'memory' not in path: return
    stats_file = os.path.join(script_dir, 'memory/file_access_stats.json')
    try:
        with open(stats_file, 'r', encoding='utf-8') as f: stats = json.load(f)
    except: stats = {}
    fname = os.path.basename(path)
    stats[fname] = {'count': stats.get(fname, {}).get('count', 0) + 1, 'last': datetime.now().strftime('%Y-%m-%d')}
    with open(stats_file, 'w', encoding='utf-8') as f: json.dump(stats, f, indent=2, ensure_ascii=False)


def smart_format(data, max_str_len=100, omit_str=' ... '):
    if not isinstance(data, str): data = str(data)
    if len(data) < max_str_len + len(omit_str)*2: return data
    return f"{data[:max_str_len//2]}{omit_str}{data[-max_str_len//2:]}"


def consume_file(dr, file):
    if dr and os.path.exists(os.path.join(dr, file)):
        with open(os.path.join(dr, file), encoding='utf-8', errors='replace') as f: content = f.read()
        os.remove(os.path.join(dr, file))
        return content
