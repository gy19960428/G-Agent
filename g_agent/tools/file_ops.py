"""file_ops: 文件读取 / 局部 patch / 文件引用展开。

从 g_agent.tool_handler 拆出，函数体保持一致。无工具间依赖。
"""

import os
import re
import itertools
import collections
import difflib
from collections import deque
from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = [
    "EXPAND_FILE_REFS_MAX_BYTES",
    "expand_file_refs",
    "file_patch",
    "file_read",
]

EXPAND_FILE_REFS_MAX_BYTES = 2 * 1024 * 1024  # 单次引用文件大小上限 2MB，防误展开巨型文件


def expand_file_refs(text: str, base_dir: str | None = None) -> str:
    """展开文本中的 {{file:路径:起始行:结束行}} 引用为实际文件内容。
    可与普通文本混排。展开失败抛 ValueError。
    base_dir: 相对路径的基准目录，默认为进程 cwd。
    沙箱：解析后的 realpath 必须位于 realpath(base_dir or cwd) 内，且文件 <= 2MB。"""
    pattern = r"\{\{file:(.+?):(\d+):(\d+)\}\}"
    base_real = os.path.realpath(base_dir or os.getcwd())

    def replacer(match: re.Match[str]) -> str:
        raw_path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        joined = os.path.join(base_dir or ".", raw_path)
        target_real = os.path.realpath(joined)
        if target_real != base_real and not target_real.startswith(base_real + os.sep):
            raise ValueError(f"引用文件超出沙箱: {target_real} (base={base_real})")
        if not os.path.isfile(target_real):
            raise ValueError(f"引用文件不存在: {target_real}")
        size = os.path.getsize(target_real)
        if size > EXPAND_FILE_REFS_MAX_BYTES:
            raise ValueError(f"引用文件超过 {EXPAND_FILE_REFS_MAX_BYTES} 字节上限: {target_real} ({size} bytes)")
        with open(target_real, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if start < 1 or end > len(lines) or start > end:
            raise ValueError(f"行号越界: {target_real} 共{len(lines)}行, 请求{start}-{end}")
        return "".join(lines[start - 1 : end])

    return re.sub(pattern, replacer, text)


def file_patch(path: str, old_content: str, new_content: str) -> dict[str, str]:
    """在文件中寻找唯一的 old_content 块并替换为 new_content"""
    path = str(Path(path).resolve())
    try:
        if not os.path.exists(path):
            return {"status": "error", "msg": "文件不存在"}
        with open(path, "r", encoding="utf-8") as f:
            full_text = f.read()
        if not old_content:
            return {"status": "error", "msg": "old_content 为空，请确认 arguments"}
        count = full_text.count(old_content)
        if count == 0:
            return {
                "status": "error",
                "msg": "未找到匹配的旧文本块，建议：先用 file_read 确认当前内容，再分小段进行 patch。若多次失败则询问用户，严禁自行使用 overwrite 或代码替换。",
            }
        if count > 1:
            return {
                "status": "error",
                "msg": f"找到 {count} 处匹配，无法确定唯一位置。请提供更长、更具体的旧文本块以确保唯一性。建议：包含上下文行来增强特征，或分小段逐个修改。",
            }
        updated_text = full_text.replace(old_content, new_content)
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated_text)
        return {"status": "success", "msg": "文件局部修改成功"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


_read_dirs: set[str] = set()


def _scan_files(base: str, depth: int = 2) -> Iterator[tuple[str, str]]:
    try:
        for e in os.scandir(base):
            if e.is_file():
                yield (e.name, e.path)
            elif depth > 0 and e.is_dir(follow_symlinks=False):
                yield from _scan_files(e.path, depth - 1)
    except (PermissionError, OSError):
        pass


def file_read(
    path: str,
    start: int = 1,
    keyword: str | None = None,
    count: int = 200,
    show_linenos: bool = True,
) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            stream: Iterable[tuple[int, str]] = ((i, l.rstrip("\r\n")) for i, l in enumerate(f, 1))
            stream = itertools.dropwhile(lambda x: x[0] < start, stream)
            if keyword:
                before: deque[tuple[int, str]] = collections.deque(maxlen=count // 3)
                for i, l in stream:
                    if keyword.lower() in l.lower():
                        res = list(before) + [(i, l)] + list(itertools.islice(stream, count - len(before) - 1))
                        break
                    before.append((i, l))
                else:
                    return (
                        f"Keyword '{keyword}' not found after line {start}. Falling back to content from line {start}:\n\n"
                        + file_read(path, start, None, count, show_linenos)
                    )
            else:
                res = list(itertools.islice(stream, count))
            realcnt = len(res)
            L_MAX = min(max(100, 256000 // max(realcnt, 1)), 8000)
            TAG = " ... [TRUNCATED]"
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (res[0][0] - 1 if res else start - 1) + realcnt + remaining
            tl_str = f"{total_lines}+" if remaining >= 5000 else str(total_lines)
            partial = total_lines > realcnt
            total_tag = (
                f"[FILE] {tl_str} lines"
                + (f" | PARTIAL showing {realcnt}; assess need for more" if partial else "")
                + "\n"
            )
            res = [(i, l if len(l) <= L_MAX else l[:L_MAX] + TAG) for i, l in res]
            result = "\n".join(f"{i}|{l}" if show_linenos else l for i, l in res)
            if show_linenos:
                result = total_tag + result
            elif partial:
                result += f"\n\n[FILE PARTIAL: showing {realcnt}/{tl_str} lines; assess need for more]"
            _read_dirs.add(os.path.dirname(os.path.abspath(path)))
            return result
    except FileNotFoundError:
        msg = f"Error: File not found: {path}"
        try:
            tgt = os.path.basename(path)
            scan = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            roots = [scan] + [d for d in _read_dirs if not d.startswith(scan)]
            cands = list(itertools.islice((c for base in roots for c in _scan_files(base)), 2000))
            top = sorted(
                [(difflib.SequenceMatcher(None, tgt.lower(), c[0].lower()).ratio(), c) for c in cands[:2000]],
                key=lambda x: -x[0],
            )[:5]
            top = [(s, c) for s, c in top if s > 0.3]
            if top:
                msg += "\n\nDid you mean:\n" + "\n".join(f"  {c[1]}  ({s:.0%})" for s, c in top)
        except Exception:
            pass
        return msg
    except Exception as e:
        return f"Error: {str(e)}"
