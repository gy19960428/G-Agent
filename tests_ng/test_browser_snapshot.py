from __future__ import annotations

from g_agent_ng.browser.controller import BrowserTab, PageElement, PageSnapshot


def test_page_snapshot_is_structured() -> None:
    tab = BrowserTab(tab_id="t1", title="Example", url="https://example.invalid")
    element = PageElement(ref="e1", role="button", name="Submit", bounds=(1, 2, 3, 4))

    snapshot = PageSnapshot(tab=tab, elements=(element,))

    assert snapshot.tab.tab_id == "t1"
    assert snapshot.elements[0].role == "button"
    assert snapshot.elements[0].visible is True
