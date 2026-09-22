"""Pagination recovery without requiring a live retailer or installed browser."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from switch_tracker import paths
from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.browser import adapter as module
from switch_tracker.adapters.browser.adapter import BrowserAdapter, _flipkart_page_url
from switch_tracker.adapters.browser.extract import Extracted
from switch_tracker.adapters.browser.profiles import PROFILES
from switch_tracker.config.stores import STORES
from switch_tracker.core.models import Ok, Partial


@pytest.mark.parametrize("retry_succeeds", [True, False])
async def test_retries_same_page_on_fresh_tab_and_preserves_rows(monkeypatch, retry_succeeds):
    store = next(s for s in STORES if s.id == "flipkart")
    old_page, fresh_page = AsyncMock(), AsyncMock()
    context = AsyncMock()
    context.new_page.side_effect = [old_page, fresh_page]
    provider = AsyncMock()
    provider.new_context.return_value = context
    adapter = BrowserAdapter(provider, settle_ms=(0, 0))
    monkeypatch.setattr(module, "_body_text", AsyncMock(return_value=""))
    monkeypatch.setattr(module, "_flipkart_page_url", AsyncMock(return_value=store.search_urls[0]))
    first = Extracted("Mario Switch", 3000, "https://www.flipkart.com/mario/p/one", True)
    second = Extracted("Zelda Switch", 4000, "https://www.flipkart.com/zelda/p/two", True)
    outcomes = [([first], "selectors"), RuntimeError("net::ERR_TOO_MANY_REDIRECTS")]
    outcomes += (
        [([second], "selectors"), ([], "selectors")]
        if retry_succeeds else [RuntimeError("net::ERR_TOO_MANY_REDIRECTS")]
    )
    loader = AsyncMock(side_effect=outcomes)
    monkeypatch.setattr(adapter, "_load_page", loader)
    result = await adapter.fetch(store, NullSink())
    assert isinstance(result, Ok if retry_succeeds else Partial)
    assert len(result.listings) == (2 if retry_succeeds else 1)
    calls = loader.call_args_list
    assert calls[1].args[0] is old_page
    assert calls[2].args[0] is fresh_page
    assert calls[1].args[-1] == calls[2].args[-1] == 2
    old_page.close.assert_awaited_once()
    context.close.assert_awaited_once()
    if not retry_succeeds:
        assert len(calls) == 3
        assert "fresh-tab retry" in result.reason


async def test_uses_live_pager_only_when_platform_filters_are_preserved():
    store = next(s for s in STORES if s.id == "flipkart")
    template = store.search_urls[0]
    page = MagicMock()
    page.url = template.replace("{p}", "2")
    target = template.replace("{p}", "3") + "&otracker=pagination"
    wrong = "https://www.flipkart.com/search?page=3"
    page.locator.return_value.evaluate_all = AsyncMock(return_value=[wrong, target])
    assert await _flipkart_page_url(page, template, 3) == target
    page.locator.return_value.evaluate_all.return_value = [wrong]
    assert await _flipkart_page_url(page, template, 3) == template.replace("{p}", "3")


async def test_failed_navigation_records_redirect_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    page = MagicMock()
    page.url = "chrome-error://chromewebdata/"
    adapter = BrowserAdapter(AsyncMock())

    async def fail(*args):
        response = MagicMock()
        response.request.is_navigation_request.return_value = True
        response.request.frame = page.main_frame
        response.url = "https://www.flipkart.com/search?page=3"
        response.status = 302
        response.headers = {"location": "/search?page=3&loop=1"}
        page.on.call_args.args[1](response)
        raise RuntimeError("net::ERR_TOO_MANY_REDIRECTS")

    monkeypatch.setattr(adapter, "_goto", fail)
    try:
        with pytest.raises(RuntimeError):
            await adapter._goto_flipkart(
                page, "https://www.flipkart.com/search?page=3", PROFILES["flipkart"], 3
            )
        trace = (paths.diagnostics_dir() / "flipkart-p3-navigation.json").read_text()
        assert '"status": 302' in trace
        assert "/search?page=3&loop=1" in trace
        page.remove_listener.assert_called_once()
    finally:
        paths.data_dir.cache_clear()


async def test_flipkart_page_two_navigates_by_url_rather_than_clicking(monkeypatch):
    """Page 2+ must still be reached by URL once a pager href has been chosen.

    ``_flipkart_page_url`` hands ``_load_page`` a fully substituted URL, and
    ``uses_click_paging`` answers "no ``{p}`` left, so this store can only be
    clicked" -- which is true of Play-Asia and false of Flipkart, whose pages
    are plain URLs. The store then advanced by clicking its numeric pager and
    ended the walk the first time that control could not be confirmed, with no
    problem recorded and no redirect trace written.
    """
    store = next(s for s in STORES if s.id == "flipkart")
    profile = PROFILES["flipkart"]
    target = store.search_urls[0].replace("{p}", "2")
    adapter = BrowserAdapter(AsyncMock(), settle_ms=(0, 0))

    click_next = AsyncMock(return_value=False)
    monkeypatch.setattr(module, "_click_next", click_next)
    monkeypatch.setattr(module, "wait_for_cloudflare", AsyncMock())
    monkeypatch.setattr(module, "extract", AsyncMock(return_value=([], "selectors")))
    monkeypatch.setattr(module, "dump", AsyncMock())
    monkeypatch.setattr(adapter, "_hydrate", AsyncMock())
    goto = AsyncMock()
    monkeypatch.setattr(adapter, "_goto_flipkart", goto)

    await adapter._load_page(
        AsyncMock(), store, profile, store.search_urls[0], 2, resolved_url=target
    )

    click_next.assert_not_awaited()
    assert goto.await_args.args[1] == target
