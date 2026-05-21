"""code_exec.code_run 冒烟测试。

覆盖 generator 包装的子进程执行器关键分支：
1. 不支持的 code_type → 直接 return error dict（不进 subprocess）
2. python 短脚本 → exit_code=0 + stdout 含预期字符串 + 临时 .ai.py 文件被 finally 清理
3. bash 单行 echo → exit_code=0 + stdout 含字符串
4. 极短 timeout 杀进程 → status=error + stdout 末尾含 "[Timeout Error]"

注意：code_run 是 generator，最终 dict 在 StopIteration.value 里。
"""

import os
import sys
import glob
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from g_agent.tools import code_exec  # noqa: E402


def _drain(gen):
    """耗尽 generator，返回 StopIteration.value（即 return dict）。"""
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as e:
        return e.value, chunks


def test_code_run_unsupported_type_returns_error_dict(tmp_path):
    gen = code_exec.code_run("noop", code_type="ruby", cwd=str(tmp_path))
    result, _ = _drain(gen)
    assert result == {"status": "error", "msg": "不支持的类型: ruby"}


def test_code_run_python_short_script_ok_and_tmpfile_cleaned(tmp_path):
    code = "print('hello-smoke')\n"
    gen = code_exec.code_run(code, code_type="python", timeout=15, cwd=str(tmp_path), code_cwd=str(tmp_path))
    result, _ = _drain(gen)
    assert result["status"] == "success", result
    assert result["exit_code"] == 0
    assert "hello-smoke" in result["stdout"]
    # finally 应清理 .ai.py 临时文件
    leftover = glob.glob(str(tmp_path / "*.ai.py"))
    assert leftover == [], f"tmp .ai.py 未清理: {leftover}"


def test_code_run_bash_echo_ok(tmp_path):
    if os.name == "nt":
        pytest.skip("bash 分支仅 POSIX 跑")
    gen = code_exec.code_run("echo bash-smoke", code_type="bash", timeout=10, cwd=str(tmp_path))
    result, _ = _drain(gen)
    assert result["status"] == "success", result
    assert result["exit_code"] == 0
    assert "bash-smoke" in result["stdout"]


def test_code_run_timeout_kills_process(tmp_path):
    # python 睡 10s，timeout=1 应被 kill；while 循环每秒检测一次，给 2.5s 余量
    code = "import time; time.sleep(10); print('should-not-print')\n"
    gen = code_exec.code_run(code, code_type="python", timeout=1, cwd=str(tmp_path), code_cwd=str(tmp_path))
    result, _ = _drain(gen)
    assert result["status"] == "error", result
    assert "[Timeout Error]" in result["stdout"]
    assert "should-not-print" not in result["stdout"]
