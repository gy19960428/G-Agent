"""_inline_eval 单元测试：覆盖 eval / exec / 异常吞掉 / cwd 还原 / chdir 异常路径还原。"""

import os
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import g_agent.tool_handler as th  # noqa: E402


def _mk_handler(tmp_path):
    """构造一个最小可用的 ToolHandler：跳过 __init__,只挂必要属性。"""
    h = th.ToolHandler.__new__(th.ToolHandler)
    h.cwd = str(tmp_path)
    h.parent = None
    return h


def test_inline_eval_expression(tmp_path):
    h = _mk_handler(tmp_path)
    assert h._inline_eval("1 + 2", str(tmp_path), {}) == "3"


def test_inline_eval_exec_with_result(tmp_path):
    h = _mk_handler(tmp_path)
    ns = {}
    out = h._inline_eval("_r = 'hello'", str(tmp_path), ns)
    assert out == "hello"
    assert ns["_r"] == "hello"


def test_inline_eval_exec_without_r_defaults_ok(tmp_path):
    h = _mk_handler(tmp_path)
    out = h._inline_eval("x = 1", str(tmp_path), {})
    assert out == "OK"


def test_inline_eval_swallows_exception(tmp_path):
    h = _mk_handler(tmp_path)
    out = h._inline_eval("1/0", str(tmp_path), {})
    assert isinstance(out, str) and out.startswith("Error:")


def test_inline_eval_restores_cwd_on_success(tmp_path):
    h = _mk_handler(tmp_path)
    original = os.getcwd()
    h._inline_eval("1", str(tmp_path), {})
    assert os.getcwd() == original


def test_inline_eval_restores_cwd_on_exception(tmp_path):
    h = _mk_handler(tmp_path)
    original = os.getcwd()
    h._inline_eval("raise RuntimeError('boom')", str(tmp_path), {})
    assert os.getcwd() == original


def test_inline_eval_sees_target_cwd(tmp_path):
    h = _mk_handler(tmp_path)
    out = h._inline_eval("__import__('os').getcwd()", str(tmp_path), {})
    # repr 包裹后会带引号,真实路径需 realpath 对齐 macOS /private 等差异
    assert os.path.realpath(out.strip("'\"")) == os.path.realpath(str(tmp_path))


def test_inline_eval_ns_isolation(tmp_path):
    h = _mk_handler(tmp_path)
    ns = {"injected": 42}
    out = h._inline_eval("injected * 2", str(tmp_path), ns)
    assert out == "84"
