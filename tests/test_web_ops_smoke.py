"""web_ops 冒烟测试：用 FakeDriver monkeypatch 模块级 driver，避开真 BrowserDriver。

覆盖：
1. web_scan(tabs_only=True) → metadata 形状 + url 截断
2. web_scan 在无 sessions 时返回 error dict
3. web_execute_js 异常被吞为 error dict（format_error 包装）

不测真 driver 路径（first_init_driver / html_simplify.execute_js_rich），那些靠运行时验证。
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from g_agent.tools import web_ops  # noqa: E402


class FakeDriver:
    def __init__(self, sessions=None):
        self._sessions = sessions or []
        self.default_session_id = sessions[0]["id"] if sessions else None

    def get_all_sessions(self):
        # 返回拷贝以模拟真 driver 的语义（web_scan 会 pop key）
        return [dict(s) for s in self._sessions]


@pytest.fixture
def patch_driver(monkeypatch):
    def _install(sessions):
        fake = FakeDriver(sessions)
        monkeypatch.setattr(web_ops, "driver", fake)
        return fake

    return _install


def test_web_scan_tabs_only_metadata_shape(patch_driver):
    long_url = "https://example.com/" + "a" * 200
    patch_driver(
        [
            {"id": "tab1", "url": long_url, "title": "T1", "connected_at": 123, "type": "page"},
            {"id": "tab2", "url": "https://short.example/", "title": "T2"},
        ]
    )
    r = web_ops.web_scan(tabs_only=True)
    assert r["status"] == "success", r
    md = r["metadata"]
    assert md["tabs_count"] == 2
    assert md["active_tab"] == "tab1"
    # url 应被截到 53 字（50 + '...'）
    assert md["tabs"][0]["url"].endswith("...")
    assert len(md["tabs"][0]["url"]) == 53
    # connected_at / type 应被 pop
    assert "connected_at" not in md["tabs"][0]
    assert "type" not in md["tabs"][0]
    # 短 url 不带 '...'
    assert not md["tabs"][1]["url"].endswith("...")
    # tabs_only=True 不应带 content
    assert "content" not in r


def test_web_scan_no_sessions_returns_error(patch_driver):
    patch_driver([])
    r = web_ops.web_scan(tabs_only=True)
    assert r["status"] == "error"
    assert "没有可用的浏览器标签页" in r["msg"]


def test_web_scan_switch_tab_updates_active(patch_driver):
    fake = patch_driver(
        [
            {"id": "tab1", "url": "u1", "title": "T1"},
            {"id": "tab2", "url": "u2", "title": "T2"},
        ]
    )
    r = web_ops.web_scan(tabs_only=True, switch_tab_id="tab2")
    assert r["status"] == "success"
    assert fake.default_session_id == "tab2"
    assert r["metadata"]["active_tab"] == "tab2"


def test_web_execute_js_no_sessions_returns_error(patch_driver):
    patch_driver([])
    r = web_ops.web_execute_js("return 1;")
    assert r["status"] == "error"
    assert "没有可用的浏览器标签页" in r["msg"]


def test_web_execute_js_driver_exception_wrapped(patch_driver, monkeypatch):
    fake = patch_driver([{"id": "tab1", "url": "u", "title": "T"}])
    # 让 execute_js_rich 抛异常，应被 format_error 包装为 error dict
    from g_agent import html_simplify

    def boom(*a, **kw):
        raise RuntimeError("simulated-driver-fail")

    monkeypatch.setattr(html_simplify, "execute_js_rich", boom)
    r = web_ops.web_execute_js("return 1;")
    assert r["status"] == "error"
    assert "simulated-driver-fail" in r["msg"]
