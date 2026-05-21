"""ask_user 公共解析层 (telegram / feishu 共享)

职责:
- 从 ga.do_ask_user 注入到 ctx["exit_reason"] 的 payload 中抽取规范化 AskUserEvent
- 提供线程安全的事件总线 (put / pop_by_menu_id / drain_latest / gc)
- 通过 register_hook 把上述逻辑挂到 agent._turn_end_hooks
零平台依赖, 任何 GUI/HTTP 行为由调用方在 on_event 回调里完成.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


DEFAULT_TTL_SEC = 600
_MENU_ID_LEN = 16


@dataclass
class AskUserEvent:
    """一次 ask_user 触发的规范化事件."""

    menu_id: str
    question: str
    candidates: List[str]
    owner_id: str
    source: str  # 'telegram' | 'feishu' | ...
    multi: bool = False
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
        return (time.time() - self.created_at) > ttl_sec


def _new_menu_id() -> str:
    return uuid.uuid4().hex[:_MENU_ID_LEN]


def extract_event(ctx: dict, owner_id: str, source: str, menu_id: Optional[str] = None) -> Optional[AskUserEvent]:
    """从 turn_end ctx 中抽取 ask_user 事件; 不匹配返回 None.

    严格匹配 ga.do_ask_user 协议:
      exit_reason.result == 'EXITED'
      exit_reason.data.status == 'INTERRUPT'
      exit_reason.data.intent == 'HUMAN_INTERVENTION'
      exit_reason.data.data = {question, candidates}
    candidates 规范化为非空 str 列表; 任一必填字段缺失/为空返回 None.
    """
    exit_reason = (ctx or {}).get("exit_reason") or {}
    if exit_reason.get("result") != "EXITED":
        return None
    payload = exit_reason.get("data")
    if not isinstance(payload, dict):
        return None
    if payload.get("status") != "INTERRUPT" or payload.get("intent") != "HUMAN_INTERVENTION":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    raw = data.get("candidates") or []
    if not isinstance(raw, (list, tuple)):
        return None
    candidates: List[str] = []
    for c in raw:
        if c is None:
            continue
        t = str(c).strip()
        if t:
            candidates.append(t)
    # 放宽: candidates 为空也允许返回 ev (纯问答卡片场景), 仅 question 必填
    question = str(data.get("question") or "").strip()
    if not question:
        return None
    return AskUserEvent(
        menu_id=menu_id or _new_menu_id(),
        question=question,
        candidates=candidates,
        owner_id=str(owner_id),
        source=source,
        multi=bool(data.get("multi", False)),
    )


class AskUserEventBus:
    """线程安全的内存事件存储.

    - put(ev): 写入 (key=menu_id)
    - pop_by_menu_id(menu_id): 一次性消费, 用于按钮回调; 防重点击
    - drain_latest(owner_id): 取该 owner 最新一条且清掉同 owner 队列, 用于 tg 流式段
    - gc(ttl_sec): 移除过期条目, 返回移除数
    """

    def __init__(self) -> None:
        self._items: Dict[str, AskUserEvent] = {}
        self._lock = threading.RLock()

    def put(self, ev: AskUserEvent) -> None:
        with self._lock:
            self._items[ev.menu_id] = ev

    def pop_by_menu_id(self, menu_id: str) -> Optional[AskUserEvent]:
        with self._lock:
            return self._items.pop(menu_id, None)

    def get_by_menu_id(self, menu_id: str) -> Optional[AskUserEvent]:
        with self._lock:
            return self._items.get(menu_id)

    def drain_latest(self, owner_id: str) -> Optional[AskUserEvent]:
        """取该 owner 最新一条并把同 owner 全部清掉 (避免历史堆积重发)."""
        owner = str(owner_id)
        with self._lock:
            matched = [ev for ev in self._items.values() if ev.owner_id == owner]
            if not matched:
                return None
            matched.sort(key=lambda e: e.created_at)
            latest = matched[-1]
            for ev in matched:
                self._items.pop(ev.menu_id, None)
            return latest

    def gc(self, ttl_sec: int = DEFAULT_TTL_SEC) -> int:
        with self._lock:
            expired = [mid for mid, ev in self._items.items() if ev.is_expired(ttl_sec)]
            for mid in expired:
                self._items.pop(mid, None)
            return len(expired)

    def size(self) -> int:
        with self._lock:
            return len(self._items)


def register_hook(
    agent, hook_key: str, owner_resolver: Callable[[dict], str], source: str, on_event: Callable[[AskUserEvent], None]
) -> None:
    """把 ask_user hook 注册到 agent._turn_end_hooks[hook_key].

    owner_resolver(ctx) -> owner_id 因 tg/fs 取 owner 渠道不同抽出来 (例如 tg 从模块级 chat_id, fs 从 ctx['_fs_open_id']).
    on_event(ev) 由调用方完成: bus.put + 渲染/通知; 异常会被吞掉并打印.
    """
    if not hasattr(agent, "_turn_end_hooks") or agent._turn_end_hooks is None:
        agent._turn_end_hooks = {}

    def _hook(ctx):
        try:
            owner_id = owner_resolver(ctx) if callable(owner_resolver) else owner_resolver
            if not owner_id:
                return
            ev = extract_event(ctx, owner_id=owner_id, source=source)
            if ev is None:
                return
            on_event(ev)
        except Exception as exc:  # noqa: BLE001
            print(f"[ask_user_common hook:{hook_key}] {type(exc).__name__}: {exc}", flush=True)

    agent._turn_end_hooks[hook_key] = _hook


def start_gc_timer(bus: AskUserEventBus, interval_sec: int = 300, ttl_sec: int = DEFAULT_TTL_SEC) -> threading.Timer:
    """启动周期 gc; 返回 Timer 引用便于 cancel. 自我重排."""

    def _tick():
        try:
            bus.gc(ttl_sec)
        finally:
            t = threading.Timer(interval_sec, _tick)
            t.daemon = True
            t.start()

    timer = threading.Timer(interval_sec, _tick)
    timer.daemon = True
    timer.start()
    return timer


__all__ = [
    "AskUserEvent",
    "AskUserEventBus",
    "extract_event",
    "register_hook",
    "start_gc_timer",
    "DEFAULT_TTL_SEC",
]
