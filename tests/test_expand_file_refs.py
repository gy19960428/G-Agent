"""expand_file_refs 单元测试：覆盖正常 / 越狱 / 不存在 / 行号越界 / 超大文件。

注意：本文件不能出现字面的 file-ref 双花括号 token，否则会被写入工具的预处理展开。
统一通过 _ref() 在运行时拼接构造。"""
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import g_agent.tools.file_ops as fo  # noqa: E402


def _ref(path: str, start: int, end: int) -> str:
    # 规避字面 token 被工具预处理展开
    return "{" + "{file:" + path + ":" + str(start) + ":" + str(end) + "}" + "}"


def _write(p: Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_expand_normal_inline_mix(tmp_path):
    _write(tmp_path / "a.txt", "L1\nL2\nL3\nL4\n")
    text = "before\n" + _ref("a.txt", 2, 3) + "\nafter"
    out = fo.expand_file_refs(text, base_dir=str(tmp_path))
    assert out == "before\nL2\nL3\n\nafter"


def test_expand_rejects_escape_via_relative_path(tmp_path):
    outer = tmp_path.parent / "outside_secret.txt"
    _write(outer, "TOP-SECRET\n")
    try:
        text = _ref("../" + outer.name, 1, 1)
        with pytest.raises(ValueError, match="超出沙箱"):
            fo.expand_file_refs(text, base_dir=str(tmp_path))
    finally:
        outer.unlink(missing_ok=True)


def test_expand_rejects_escape_via_symlink(tmp_path):
    outer = tmp_path.parent / "outside_link_target.txt"
    _write(outer, "LINKED-SECRET\n")
    link = tmp_path / "link.txt"
    try:
        os.symlink(outer, link)
        text = _ref("link.txt", 1, 1)
        with pytest.raises(ValueError, match="超出沙箱"):
            fo.expand_file_refs(text, base_dir=str(tmp_path))
    finally:
        outer.unlink(missing_ok=True)


def test_expand_rejects_absolute_path_outside(tmp_path):
    outer = tmp_path.parent / "abs_outside.txt"
    _write(outer, "ABS\n")
    try:
        text = _ref(str(outer), 1, 1)
        with pytest.raises(ValueError, match="超出沙箱"):
            fo.expand_file_refs(text, base_dir=str(tmp_path))
    finally:
        outer.unlink(missing_ok=True)


def test_expand_missing_file(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        fo.expand_file_refs(_ref("nope.txt", 1, 1), base_dir=str(tmp_path))


def test_expand_line_range_out_of_bounds(tmp_path):
    _write(tmp_path / "small.txt", "only one line\n")
    with pytest.raises(ValueError, match="行号越界"):
        fo.expand_file_refs(_ref("small.txt", 1, 5), base_dir=str(tmp_path))
    with pytest.raises(ValueError, match="行号越界"):
        fo.expand_file_refs(_ref("small.txt", 0, 1), base_dir=str(tmp_path))
    with pytest.raises(ValueError, match="行号越界"):
        fo.expand_file_refs(_ref("small.txt", 3, 2), base_dir=str(tmp_path))


def test_expand_rejects_oversize_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fo, "EXPAND_FILE_REFS_MAX_BYTES", 64)
    _write(tmp_path / "big.txt", "x" * 200 + "\n")
    with pytest.raises(ValueError, match="字节上限"):
        fo.expand_file_refs(_ref("big.txt", 1, 1), base_dir=str(tmp_path))


def test_expand_no_refs_returns_original(tmp_path):
    text = "plain text without any refs"
    assert fo.expand_file_refs(text, base_dir=str(tmp_path)) == text
