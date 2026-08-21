"""The browser adapter end to end, against a real browser and a real server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio

from switch_tracker import paths
from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.browser.adapter import BrowserAdapter
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.core.models import AdapterKind, Failed, Ok, Partial, Platform, StoreConfig

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def provider() -> AsyncIterator[BrowserProvider]:
    instance = BrowserProvider()
    yield instance
    await instance.close()


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def card(name: str, price: str, href: str, extra: str = "") -> str:
    return (
        f'<div class="card"><h3 class="name">{name}</h3>'
        f'<span class="cost">{price}</span>{extra}'
        f'<a class="more" href="{href}">buy</a></div>'
    )


def shop_store(base: str, **kw) -> StoreConfig:
    cfg = StoreConfig(
        id="gamestheshop",
        name="Games The Shop",
        base_url=base,
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=(f"{base}/shop?page={{p}}",),
    )
    return replace(cfg, **kw)


@pytest.fixture
def adapter(provider: BrowserProvider) -> BrowserAdapter:
    # gamestheshop's real profile targets div.ak-card; point it at the simple
    # markup these tests serve instead of duplicating a whole store profile.
    # Production settle delays are courtesy to real shops; a local test server
    # needs none of it, and paying it here would make the suite 5x slower for
    # no extra coverage.
    return BrowserAdapter(provider, profile_for=_test_profile, settle_ms=(0, 0), render_ms=0)


def _test_profile(store_id: str):  # type: ignore[no-untyped-def]
    from switch_tracker.adapters.browser.profiles import StoreProfile
    from switch_tracker.core.models import Region

    return StoreProfile(
        card=("div.card",),
        title=("h3.name",),
        price=("span.cost",),
        link=("a.more",),
        out_of_stock=(":has-text('Sold Out')",),
        default_region=Region.IN,
        platform_hint=Platform.SWITCH,
    )


class TestCollecting:
    async def test_collects_listings_from_a_rendered_page(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{card('Mario Kart World', '₹4,499', '/p/1')}</body></html>", {}),
            (200, "<html><body></body></html>", {}),
        )
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Ok)
        assert [listing.title for listing in result.listings] == ["Mario Kart World"]
        assert result.listings[0].native_price == 4499.0

    async def test_derives_a_stable_sku_and_an_absolute_url(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{card('Zelda TotK', '₹4,299', '/product/zelda-totk?ref=x')}</body></html>", {}),  # noqa: E501
            (200, "<html><body></body></html>", {}),
        )
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].sku == "zelda-totk"
        assert result.listings[0].url.startswith("http")

    async def test_classifies_out_non_games(self, adapter, server) -> None:
        base, recorder = server
        body = card("Mario Kart World", "₹4,499", "/p/1") + card(
            "Nintendo Switch Pro Controller", "₹5,999", "/p/2"
        )
        recorder.plan_pages(
            "/shop", (200, f"<html><body>{body}</body></html>", {}), (200, "<html></html>", {})
        )
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Ok)
        assert [listing.title for listing in result.listings] == ["Mario Kart World"]

    async def test_marks_an_out_of_stock_card(self, adapter, server) -> None:
        base, recorder = server
        body = card("Splatoon 3", "₹3,999", "/p/1", '<span class="b">Sold Out</span>')
        recorder.plan_pages(
            "/shop", (200, f"<html><body>{body}</body></html>", {}), (200, "<html></html>", {})
        )
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].in_stock is False


class TestPagination:
    async def test_follows_the_url_template_across_pages(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{card('Game One Switch', '₹1,999', '/p/1')}</body></html>", {}),
            (200, f"<html><body>{card('Game Two Switch', '₹2,999', '/p/2')}</body></html>", {}),
            (200, "<html><body></body></html>", {}),
        )
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Ok)
        assert len(result.listings) == 2

    async def test_stops_on_a_genuinely_empty_page(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{card('Only Game Switch', '₹1,999', '/p/1')}</body></html>", {}),
            (200, "<html><body></body></html>", {}),
        )
        await adapter.fetch(shop_store(base), NullSink())
        pages = [h for h in recorder.hits if h.startswith("/shop")]
        assert len(pages) == 2

    async def test_dedupes_repeated_products_across_pages(self, adapter, server) -> None:
        """Sites recycle 'related items' filler into trailing pages."""
        base, recorder = server
        same = f"<html><body>{card('Repeated Game Switch', '₹1,999', '/p/same')}</body></html>"
        recorder.plan_pages("/shop", (200, same, {}), (200, same, {}), (200, "<html></html>", {}))
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Ok)
        assert len(result.listings) == 1

    async def test_reports_progress_per_page(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{card('Game One Switch', '₹1,999', '/p/1')}</body></html>", {}),
            (200, "<html><body></body></html>", {}),
        )
        seen: list[tuple[int, int]] = []

        class Spy:
            def page(self, store_id: str, page: int, count: int) -> None:
                seen.append((page, count))

        await adapter.fetch(shop_store(base), Spy())
        assert seen and seen[0] == (1, 1)


class TestFailures:
    async def test_a_page_with_nothing_extractable_fails_and_dumps_diagnostics(
        self, adapter, server, data_dir: Path
    ) -> None:
        """A silent zero is the worst failure mode a scraper has.

        The reason must be openable in a browser, not just a number.
        """
        base, recorder = server
        recorder.plan_pages("/shop", (200, "<html><body><p>nothing</p></body></html>", {}))
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Failed)
        assert "gamestheshop" in result.reason
        assert (data_dir / "diagnostics" / "gamestheshop.html").exists()

    async def test_a_store_with_no_search_urls_fails_readably(self, adapter, server) -> None:
        base, _ = server
        result = await adapter.fetch(shop_store(base, search_urls=()), NullSink())
        assert isinstance(result, Failed)
        assert "searchUrls" in result.reason or "search_urls" in result.reason


class TestCompleteness:
    async def test_flags_a_shortfall_against_the_stores_own_claim(self, adapter, server) -> None:
        """Best-effort only -- scraped prose, not a structured total."""
        base, recorder = server
        body = "<p>Showing 1-1 of 500 results</p>" + card("One Game Switch", "₹1,999", "/p/1")
        recorder.plan_pages(
            "/shop", (200, f"<html><body>{body}</body></html>", {}), (200, "<html></html>", {})
        )
        result = await adapter.fetch(shop_store(base), NullSink())
        assert isinstance(result, Partial)
        assert "500" in result.reason


class TestBrowserContext:
    async def test_emulates_an_indian_locale_and_timezone(self, provider) -> None:
        """Amazon and Play-Asia serve locale-dependent PRICES.

        Dropping this silently changes the data being recorded.
        """
        context = await provider.new_context()
        try:
            page = await context.new_page()
            await page.goto("about:blank")
            tz = await page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            locale = await page.evaluate("navigator.language")
            assert tz in {"Asia/Kolkata", "Asia/Calcutta"}
            assert locale == "en-IN"
        finally:
            await context.close()

    async def test_hides_the_automation_flag(self, provider) -> None:
        context = await provider.new_context()
        try:
            page = await context.new_page()
            await page.goto("about:blank")
            assert await page.evaluate("navigator.webdriver") in (None, False)
        finally:
            await context.close()
