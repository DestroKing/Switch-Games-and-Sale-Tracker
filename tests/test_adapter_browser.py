"""The browser adapter end to end, against a real browser and a real server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio

from switch_tracker import paths
from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.browser import adapter as adapter_module
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


class TestSessionCookies:
    """Play-Asia prices per session, so currency='INR' is a claim the adapter
    has to make true. These cookies were previously set only in a standalone
    scraping script, never by the collector -- so the shipped config asserted
    INR while the collector recorded whatever the default session quoted."""

    async def test_pins_session_cookies_before_the_first_navigation(
        self, provider: BrowserProvider, server
    ) -> None:
        base, recorder = server
        # The card's title is written from document.cookie, so the extracted
        # title proves the cookie was present when the page's scripts ran --
        # not merely that add_cookies was called at some point.
        html = (
            "<html><body>"
            "<div class='card'><h3 class='name'></h3>"
            "<span class='cost'>Rs. 4499</span>"
            "<a class='more' href='/p/switch-game-1'>buy</a></div>"
            "<script>document.querySelector('h3.name').textContent = "
            "'Switch Game ' + document.cookie;</script>"
            "</body></html>"
        )
        recorder.plan("/shop", (200, html, {"content-type": "text/html; charset=utf-8"}))

        def profile_for(store_id: str):  # type: ignore[no-untyped-def]
            return replace(
                _test_profile(store_id),
                cookies=(("currency", "INR"),),
                cookie_domain="127.0.0.1",
            )

        adapter = BrowserAdapter(
            provider, profile_for=profile_for, settle_ms=(0, 0), render_ms=0
        )
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        assert "currency=INR" in outcome.listings[0].title

    async def test_a_profile_without_cookies_sets_none(
        self, provider: BrowserProvider, server
    ) -> None:
        """The seam must stay opt-in; every other store gets a clean session."""
        base, recorder = server
        html = (
            "<html><body>"
            "<div class='card'><h3 class='name'></h3>"
            "<span class='cost'>Rs. 4499</span>"
            "<a class='more' href='/p/switch-game-1'>buy</a></div>"
            "<script>document.querySelector('h3.name').textContent = "
            "'Switch Game [' + document.cookie + ']';</script>"
            "</body></html>"
        )
        recorder.plan("/shop", (200, html, {"content-type": "text/html; charset=utf-8"}))

        adapter = BrowserAdapter(
            provider, profile_for=_test_profile, settle_ms=(0, 0), render_ms=0
        )
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        assert "[]" in outcome.listings[0].title


PAGER_CARDS = "".join(
    f'<div class="card"><h3 class="name">Switch Game {i}</h3>'
    f'<span class="cost">Rs. {1999 + i}</span>'
    f'<a class="more" href="/p/game-{i}">buy</a></div>'
    for i in range(6)
)

#: A numeric pager with no `.next` class and a footer containing ">".
#: This is the shape that silently truncated Play-Asia: none of the profile's
#: real selectors match, and the `:has-text('>')` fallback matches the footer.
DEAD_PAGER = (
    f"<html><body><div class='results'>{PAGER_CARDS}</div>"
    "<div class='pager'><a href='#'>1</a><a href='#'>2</a><a href='#'>3</a></div>"
    "<footer><small>Terms &gt; Privacy</small></footer></body></html>"
)

#: The same pager, wired up: clicking "2" really does replace the results.
LIVE_PAGER = (
    f"<html><body><div class='results'>{PAGER_CARDS}</div>"
    "<div class='pager'><a href='#' id='p1'>1</a><a href='#' id='p2'>2</a></div>"
    "<script>document.getElementById('p2').addEventListener('click', (e) => {"
    "  e.preventDefault();"
    "  document.querySelector('.results').innerHTML = Array.from({length: 4}, (_, i) =>"
    "    `<div class=\"card\"><h3 class=\"name\">Switch Game p2-${i}</h3>`"
    "    + `<span class=\"cost\">Rs. ${2500 + i}</span>`"
    "    + `<a class=\"more\" href=\"/p/page2-${i}\">buy</a></div>`).join('');"
    "});</script></body></html>"
)


def _paging_profile(store_id: str):  # type: ignore[no-untyped-def]
    """The test card markup, driven through the real click-paging path."""
    return replace(_test_profile(store_id), next_page=("a.next", ":has-text('>')"))


class TestClickPagination:
    """The path Play-Asia actually uses, and the one nothing covered.

    Its search_urls carry no ``{p}``, so clicking is the ONLY way to advance.
    A click that succeeds without turning the page therefore does not fail --
    it silently re-extracts page 1 until the productivity tracker gives up,
    reporting a large raw-row count and one page of real products.
    """

    async def test_a_click_that_does_not_turn_the_page_ends_paging(
        self, provider: BrowserProvider, server
    ) -> None:
        base, recorder = server
        recorder.plan("/shop", (200, DEAD_PAGER, {"content-type": "text/html"}))

        seen: list[tuple[int, int]] = []

        class Sink:
            def page(self, store_id: str, page: int, count: int) -> None:
                seen.append((page, count))

        adapter = BrowserAdapter(
            provider, profile_for=_paging_profile, settle_ms=(0, 0), render_ms=0
        )
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop",)), Sink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        assert len(outcome.listings) == 6
        # One extraction. Before the fix this was five: the footer's "Terms >
        # Privacy" was clicked, reported success, and page 1 was re-scraped
        # until four unproductive pages had accumulated.
        assert len(seen) == 1, f"re-scraped page 1 {len(seen)} times: {seen}"

    async def test_a_click_that_does_turn_the_page_keeps_paging(
        self, provider: BrowserProvider, server
    ) -> None:
        """The guard must not break paging that genuinely works."""
        base, recorder = server
        recorder.plan("/shop", (200, LIVE_PAGER, {"content-type": "text/html"}))

        adapter = BrowserAdapter(
            provider, profile_for=_paging_profile, settle_ms=(0, 0), render_ms=0
        )
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        titles = {listing.title for listing in outcome.listings}
        assert any("p2-" in t for t in titles), f"page 2 never reached: {sorted(titles)}"
        assert len(outcome.listings) == 10


class TestBrowserFallback:
    async def test_falls_back_to_bundled_chromium_when_chrome_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The frozen build ships Chromium precisely so this can happen.

        channel="chrome" is preferred because e2zstore and Play-Asia scrape
        reliably only through real Chrome, but it requires Chrome to be
        installed. Without a fallback the exe's "no Python, no internet"
        promise silently also required "and Chrome".
        """
        from playwright.async_api import Error

        from switch_tracker.adapters.browser import provider as provider_module

        attempts: list[str | None] = []

        class FakeChromium:
            async def launch(self, **kw: object) -> str:
                channel = kw.get("channel")
                attempts.append(channel if isinstance(channel, str) else None)
                if channel is not None:
                    raise Error("Chromium distribution 'chrome' is not found")
                return "bundled-chromium"

        class FakePlaywright:
            chromium = FakeChromium()

            async def stop(self) -> None:
                return None

        class FakeStarter:
            async def start(self) -> FakePlaywright:
                return FakePlaywright()

        monkeypatch.setattr(provider_module, "async_playwright", lambda: FakeStarter())

        instance = provider_module.BrowserProvider()
        browser = await instance.browser()

        assert attempts == ["chrome", None], attempts
        assert browser == "bundled-chromium"
        assert instance.launched_channel == "chromium"

    async def test_prefers_real_chrome_when_it_is_available(
        self, provider: BrowserProvider
    ) -> None:
        await provider.browser()
        assert provider.launched_channel in {"chrome", "chromium"}


class TestPerStorePageMechanics:
    """The three knobs, exercised through the real adapter."""

    async def test_scroll_pattern_follows_the_profile(
        self, provider: BrowserProvider, server
    ) -> None:
        """Observed in the browser, not mocked in our own code.

        The page counts real scroll events and writes the tally into the card
        title, so the EXTRACTED title reports how many times the adapter
        actually scrolled. A default profile must still make exactly one
        proportional jump, as it did before this was configurable.
        """
        base, recorder = server
        html = (
            "<html><body>"
            "<div style='height:8000px'></div>"
            "<div class='card'><h3 class='name'>Switch Game S0</h3>"
            "<span class='cost'>Rs. 4499</span>"
            "<a class='more' href='/p/game-a'>buy</a></div>"
            "<script>window.__n = 0;"
            "window.addEventListener('scroll', () => { window.__n++;"
            "  document.querySelector('h3.name').textContent = 'Switch Game S' + window.__n; });"
            "</script></body></html>"
        )
        recorder.plan("/shop", (200, html, {"content-type": "text/html"}))

        async def title_after(profile_for) -> str:  # type: ignore[no-untyped-def]
            adapter = BrowserAdapter(
                provider, profile_for=profile_for, settle_ms=(0, 0), render_ms=150
            )
            outcome = await adapter.fetch(
                shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
            )
            assert isinstance(outcome, (Ok, Partial)), outcome
            return outcome.listings[0].title

        def three_passes(store_id: str):  # type: ignore[no-untyped-def]
            return replace(_test_profile(store_id), scroll_passes=3, scroll_settle_ms=120)

        assert await title_after(_test_profile) == "Switch Game S1"
        assert await title_after(three_passes) == "Switch Game S3"

    async def test_a_networkidle_store_still_loads_a_normal_page(
        self, provider: BrowserProvider, server
    ) -> None:
        """networkidle is opt-in and must not change what gets extracted."""
        base, recorder = server
        html = (
            "<html><body>"
            "<div class='card'><h3 class='name'>Switch Game A</h3>"
            "<span class='cost'>Rs. 4499</span>"
            "<a class='more' href='/p/game-a'>buy</a></div></body></html>"
        )
        recorder.plan("/shop", (200, html, {"content-type": "text/html"}))

        def idle(store_id: str):  # type: ignore[no-untyped-def]
            return replace(_test_profile(store_id), wait_until="networkidle")

        adapter = BrowserAdapter(provider, profile_for=idle, settle_ms=(0, 0), render_ms=0)
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
        )
        assert isinstance(outcome, (Ok, Partial)), outcome
        assert len(outcome.listings) == 1

    async def test_a_networkidle_timeout_falls_back_instead_of_losing_the_page(
        self, provider: BrowserProvider, server
    ) -> None:
        """A page that never reaches network idle must still yield its rows.

        Without the fallback, goto raises after its full timeout. CollectService
        gives a browser store 600s, so a handful of such pages exhausts the
        budget and the store records `failed` with zero listings -- worse than
        the degraded load this produces instead.
        """
        base, recorder = server
        # A never-settling fetch loop keeps the network permanently busy, so
        # "networkidle" can never be reached while the DOM is perfectly usable.
        html = (
            "<html><body>"
            "<div class='card'><h3 class='name'>Switch Game A</h3>"
            "<span class='cost'>Rs. 4499</span>"
            "<a class='more' href='/p/game-a'>buy</a></div>"
            "<script>setInterval(() => { fetch('/ping?x=' + Date.now()); }, 100);</script>"
            "</body></html>"
        )
        recorder.plan("/shop", (200, html, {"content-type": "text/html"}))
        recorder.plan("/ping", (200, "{}", {"content-type": "application/json"}))

        def idle(store_id: str):  # type: ignore[no-untyped-def]
            return replace(_test_profile(store_id), wait_until="networkidle")

        adapter = BrowserAdapter(provider, profile_for=idle, settle_ms=(0, 0), render_ms=0)
        # Shorter than the production 45s so the test does not pay for it.
        monkey = adapter_module._GOTO_TIMEOUT_MS
        adapter_module._GOTO_TIMEOUT_MS = 2500
        try:
            outcome = await adapter.fetch(
                shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
            )
        finally:
            adapter_module._GOTO_TIMEOUT_MS = monkey

        assert isinstance(outcome, (Ok, Partial)), outcome
        assert len(outcome.listings) == 1, "fallback did not salvage the page"

    async def test_a_rejected_url_never_becomes_a_listing(
        self, provider: BrowserProvider, server
    ) -> None:
        base, recorder = server
        html = (
            "<html><body>"
            + card("Switch Game Real", "Rs. 4499", "/en/mario-kart/13/70abcd")
            + card("Nintendo Switch", "Rs. 4499", "/en/category/switch-games")
            + card("Switch Games Search", "Rs. 4499", "/en/search/switch")
            + "</body></html>"
        )
        recorder.plan("/shop", (200, html, {"content-type": "text/html"}))

        def filtered(store_id: str):  # type: ignore[no-untyped-def]
            return replace(
                _test_profile(store_id),
                reject_url_parts=("/search/", "/category/"),
                require_digit_in_url=True,
            )

        adapter = BrowserAdapter(provider, profile_for=filtered, settle_ms=(0, 0), render_ms=0)
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop",)), NullSink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        titles = [listing.title for listing in outcome.listings]
        assert titles == ["Switch Game Real"], titles

    async def test_filtering_does_not_trigger_a_premature_stop(
        self, provider: BrowserProvider, server
    ) -> None:
        """The denominator fix, observed end to end.

        18 of 20 rows are category links. Measured against raw rows that is a
        0.10 new-row ratio -- below the tracker's 0.15 threshold -- so the walk
        would end after four healthy pages. Measured against kept rows it is
        1.00 on page 1, and paging continues to the real end of the catalogue.
        """
        base, recorder = server
        real = "".join(card(f"Switch Game {i}", "Rs. 4499", f"/en/g-{i}/13/70{i:04d}") for i in range(2))
        junk = "".join(card("Nintendo Switch", "Rs. 4499", f"/en/category/c-{i}") for i in range(18))
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{real}{junk}</body></html>", {"content-type": "text/html"}),
            (200, f"<html><body>{real}{junk}</body></html>", {"content-type": "text/html"}),
            (200, "<html><body></body></html>", {"content-type": "text/html"}),
        )

        seen: list[int] = []

        class Sink:
            def page(self, store_id: str, page: int, count: int) -> None:
                seen.append(page)

        def filtered(store_id: str):  # type: ignore[no-untyped-def]
            return replace(
                _test_profile(store_id),
                reject_url_parts=("/category/",),
                require_digit_in_url=True,
            )

        adapter = BrowserAdapter(provider, profile_for=filtered, settle_ms=(0, 0), render_ms=0)
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop?page={{p}}",)), Sink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        assert len(outcome.listings) == 2
        # Reached the genuinely empty page 3 rather than stopping on the ratio.
        assert 3 in seen, seen


class TestNumericPagerMechanism:
    """Play-Asia's exact mechanism: no CSS pager selectors, numeric text only.

    Its search URLs carry no "{p}", so URL paging is impossible and the click
    path must still be taken even though next_page is empty. With nothing to
    try, _click_next falls straight through to the page-number clicker -- the
    only mechanism the hand-verified sweep used.
    """

    async def test_a_url_without_a_page_placeholder_still_click_pages(
        self, provider: BrowserProvider, server
    ) -> None:
        base, recorder = server
        cards = "".join(
            card(f"Switch Game {i}", "Rs. 4499", f"/p/g-{i}") for i in range(3)
        )
        html = (
            f"<html><body><div class='results'>{cards}</div>"
            "<div class='pager'><a href='#'>1</a><a href='#' id='n'>2</a></div>"
            "<script>document.getElementById('n').addEventListener('click', (e) => {"
            "  e.preventDefault();"
            "  document.querySelector('.results').innerHTML = Array.from({length: 2}, (_, i) =>"
            "    `<div class=\"card\"><h3 class=\"name\">Switch Game p2-${i}</h3>`"
            "    + `<span class=\"cost\">Rs. 2500</span>`"
            "    + `<a class=\"more\" href=\"/p/page2-${i}\">buy</a></div>`).join('');"
            "  document.getElementById('n').remove();"
            "});</script></body></html>"
        )
        recorder.plan("/search", (200, html, {"content-type": "text/html"}))

        # next_page empty -- exactly Play-Asia's shipped profile.
        adapter = BrowserAdapter(
            provider, profile_for=_test_profile, settle_ms=(0, 0), render_ms=0
        )
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/search",)), NullSink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        titles = {listing.title for listing in outcome.listings}
        assert any("p2-" in t for t in titles), f"numeric pager never fired: {sorted(titles)}"
        assert len(outcome.listings) == 5


class TestTimeBudget:
    """A long walk must not become a lost walk.

    CollectService wraps each store in asyncio.wait_for. When that fires the
    coroutine is cancelled and every page already scraped dies with the frame --
    the store records `failed` with zero rows. The adapter therefore stops
    itself first and returns Partial, which the service persists normally.
    """

    async def test_a_spent_budget_keeps_the_pages_already_collected(
        self, provider: BrowserProvider, server
    ) -> None:
        """The whole point: stop early, but return the rows, not a failure."""
        base, recorder = server
        page1 = "".join(card(f"Switch Game {i}", "Rs. 4499", f"/p/g-{i}") for i in range(4))
        recorder.plan_pages(
            "/shop",
            (200, f"<html><body>{page1}</body></html>", {"content-type": "text/html"}),
            (200, "<html><body>" + card("Switch Game X", "Rs. 4499", "/p/gx") + "</body></html>",
             {"content-type": "text/html"}),
        )

        adapter = BrowserAdapter(
            provider, profile_for=_test_profile, settle_ms=(0, 0), render_ms=0,
            time_budget_s=0.0,
        )
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop?page={{p}}",)), NullSink()
        )

        # Partial, not Failed -- Failed makes CollectService record zero and
        # discard four perfectly good listings.
        assert isinstance(outcome, Partial), outcome
        assert len(outcome.listings) == 4
        assert "time budget" in outcome.reason
        assert not any(listing.title[-1] == "X" for listing in outcome.listings)

    async def test_max_pages_caps_the_walk_per_search_url(
        self, provider: BrowserProvider, server
    ) -> None:
        """The guard that keeps a deep catalogue inside the budget."""
        base, recorder = server
        pages = [
            (200,
             "<html><body>"
             + "".join(card(f"Switch Game p{n}-{i}", "Rs. 4499", f"/p/p{n}-{i}") for i in range(3))
             + "</body></html>",
             {"content-type": "text/html"})
            for n in range(1, 8)
        ]
        recorder.plan_pages("/shop", *pages)

        seen: list[int] = []

        class Sink:
            def page(self, store_id: str, page: int, count: int) -> None:
                seen.append(page)

        def capped(store_id: str):  # type: ignore[no-untyped-def]
            return replace(_test_profile(store_id), max_pages=3)

        adapter = BrowserAdapter(provider, profile_for=capped, settle_ms=(0, 0), render_ms=0)
        outcome = await adapter.fetch(
            shop_store(base, search_urls=(f"{base}/shop?page={{p}}",)), Sink()
        )

        assert isinstance(outcome, (Ok, Partial)), outcome
        assert seen == [1, 2, 3], seen
        assert len(outcome.listings) == 9

