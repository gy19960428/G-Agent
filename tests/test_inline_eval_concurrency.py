"""_inline_eval 并发互斥测试。

contextlib.chdir 是进程级状态，多线程同时调用 _inline_eval 会互踩 cwd。
本测试用 N 线程并发跑，每个线程持自己的 tmpdir cwd，断言 eval 内 os.getcwd()
返回的是该线程传入的 cwd，而不是其它线程的 cwd（串扰）。

进程级 RLock 应保证同一时刻只有一个 inline_eval 在执行 chdir 段。
"""

import os
import sys
import threading
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import g_agent.tool_handler as th  # noqa: E402


def _run_one(handler, cwd, results, idx, barrier):
    barrier.wait()  # 同步起跑增加并发压力
    ns = {}
    # eval 内取 cwd，应等于传入的 cwd
    r = handler._inline_eval("__import__('os').getcwd()", cwd, ns)
    # repr(eval) -> "'<path>'"，剥引号
    results[idx] = (cwd, r.strip("'\""))


def test_inline_eval_concurrent_no_cwd_crosstalk(tmp_path):
    # 准备 N 个不同的 tmpdir，符号链接解引用后比较，规避 macOS /private 等
    N = 16
    handler = th.ToolHandler.__new__(th.ToolHandler)  # 跳过 __init__，_inline_eval 不依赖 self
    dirs = []
    for i in range(N):
        d = tmp_path / f"d{i}"
        d.mkdir()
        dirs.append(os.path.realpath(str(d)))

    results = [None] * N
    barrier = threading.Barrier(N)
    threads = [threading.Thread(target=_run_one, args=(handler, dirs[i], results, i, barrier)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    mismatches = []
    for i, item in enumerate(results):
        assert item is not None, f"thread {i} did not write result"
        expected, got = item
        got_real = os.path.realpath(got)
        if got_real != expected:
            mismatches.append((i, expected, got_real))
    assert not mismatches, f"cwd crosstalk detected: {mismatches}"


def test_inline_eval_lock_is_reentrant():
    # RLock 必须可重入，避免同线程嵌套调用死锁（_inline_eval 内的 eval 若再触发 _inline_eval）
    assert th._INLINE_EVAL_LOCK.acquire(blocking=False)
    try:
        # 第二次同线程 acquire 不应阻塞
        assert th._INLINE_EVAL_LOCK.acquire(blocking=False)
        th._INLINE_EVAL_LOCK.release()
    finally:
        th._INLINE_EVAL_LOCK.release()


def test_inline_eval_restores_cwd_on_exception(tmp_path):
    handler = th.ToolHandler.__new__(th.ToolHandler)
    before = os.getcwd()
    target = os.path.realpath(str(tmp_path))
    # 故意触发异常，验证 chdir 仍恢复 + 返回 Error 字符串
    r = handler._inline_eval("1/0", target, {})
    assert r.startswith("Error:"), r
    assert os.getcwd() == before, f"cwd not restored after exception: {os.getcwd()} != {before}"
