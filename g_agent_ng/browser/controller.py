from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class BrowserTab:
    tab_id: str
    title: str
    url: str


@dataclass(frozen=True)
class PageElement:
    ref: str
    role: str
    name: str
    visible: bool = True
    bounds: tuple[int, int, int, int] | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageSnapshot:
    tab: BrowserTab
    elements: tuple[PageElement, ...] = ()


class BrowserController(Protocol):
    async def list_tabs(self) -> tuple[BrowserTab, ...]:
        ...

    async def snapshot(self, tab_id: str) -> PageSnapshot:
        ...

    async def click(self, element_ref: str) -> None:
        ...

    async def type_text(self, element_ref: str, text: str) -> None:
        ...
