import re

from g_agent import llm


def test_write_llm_log_appends_and_fsyncs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm.os, "fsync", lambda fd: calls.append(fd))

    log_path = tmp_path / "model_responses_test.txt"
    llm._write_llm_log("Prompt", "hello", str(log_path))
    llm._write_llm_log("Response", "world", str(log_path))

    text = log_path.read_text(encoding="utf-8")
    assert re.search(r"=== Prompt === \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\nhello\n\n", text)
    assert re.search(r"=== Response === \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\nworld\n\n", text)
    assert calls and len(calls) == 2


def test_llm_log_lock_is_reentrant():
    assert llm._LLM_LOG_LOCK.acquire(blocking=False)
    try:
        assert llm._LLM_LOG_LOCK.acquire(blocking=False)
        llm._LLM_LOG_LOCK.release()
    finally:
        llm._LLM_LOG_LOCK.release()
