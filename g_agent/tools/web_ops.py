"""web_ops: 浏览器自动化工具（driver 单例 + scan + execute_js）。

模块级可变状态 `driver` 由 first_init_driver() 通过 `global driver` 赋值；
web_scan / web_execute_js 始终读本模块的 driver，行为与原 tool_handler 一致。
"""

import importlib
import time
from typing import Any

from g_agent import html_simplify

from .user_io import smart_format, format_error

__all__ = ["driver", "first_init_driver", "web_scan", "web_execute_js"]

# Any 类型规避 first_init_driver 后 mypy 看不到 None→Driver 收窄；driver 单例由 global 赋值
driver: Any = None


def first_init_driver():
    global driver
    from g_agent.browser_driver import BrowserDriver

    driver = BrowserDriver()
    for i in range(20):
        time.sleep(1)
        sess = driver.get_all_sessions()
        if len(sess) > 0:
            break
    if len(sess) == 0:
        return
    if len(sess) == 1:
        # driver.newtab()
        time.sleep(3)


def web_scan(tabs_only=False, switch_tab_id=None, text_only=False, maxlen=35000):
    """获取当前页面的简化HTML内容和标签页列表。注意：简化过程会过滤边栏、浮动元素等非主体内容。
    tabs_only: 仅返回标签页列表，不获取HTML内容（节省token）。
    switch_tab_id: 可选参数，如果提供，则在扫描前切换到该标签页。
    应当多用execute_js，少全量观察html"""
    global driver
    try:
        if driver is None:
            first_init_driver()
        if len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        tabs = []
        for sess in driver.get_all_sessions():
            sess.pop("connected_at", None)
            sess.pop("type", None)
            sess["url"] = sess.get("url", "")[:50] + ("..." if len(sess.get("url", "")) > 50 else "")
            tabs.append(sess)
        if switch_tab_id:
            driver.default_session_id = switch_tab_id
        result = {
            "status": "success",
            "metadata": {"tabs_count": len(tabs), "tabs": tabs, "active_tab": driver.default_session_id},
        }
        if not tabs_only:
            importlib.reload(html_simplify)
            result["content"] = html_simplify.get_html(driver, cutlist=True, maxchars=maxlen, text_only=text_only)
            if text_only:
                result["content"] = smart_format(
                    result["content"], max_str_len=maxlen // 3, omit_str="\n\n[omitted long content]\n\n"
                )
        return result
    except Exception as e:
        return {"status": "error", "msg": format_error(e)}


def web_execute_js(script, switch_tab_id=None, no_monitor=False):
    """执行 JS 脚本来控制浏览器，并捕获结果和页面变化"""
    global driver
    try:
        if driver is None:
            first_init_driver()
        if len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        if switch_tab_id:
            driver.default_session_id = switch_tab_id
        result = html_simplify.execute_js_rich(script, driver, no_monitor=no_monitor)
        return result
    except Exception as e:
        return {"status": "error", "msg": format_error(e)}
