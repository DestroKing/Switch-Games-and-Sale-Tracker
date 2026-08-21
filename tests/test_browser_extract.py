"""The four extraction layers, against a real browser and real markup.

Ordered hardest-to-break first, because CSS class names on these sites are the
least durable thing about them:

  1. JSON-LD   -- exists for search engines, so it survives redesigns
  2. Embedded  -- the site's own hydration state
  3. Selectors -- CSS, per-store profiles
  4. Text      -- a rupee figure inside a matched card, by pattern not class
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from playwright.async_api import Browser, Page, async_playwright

from switch_tracker.adapters.browser.extract import extract, from_json_ld, from_selectors
from switch_tracker.adapters.browser.profiles import StoreProfile
from switch_tracker.core.models import Region


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def browser() -> AsyncIterator[Browser]:
    async with async_playwright() as p:
        instance = await p.chromium.launch(headless=True)
        yield instance
        await instance.close()


@pytest_asyncio.fixture(loop_scope="module")
async def page(browser: Browser) -> AsyncIterator[Page]:
    context = await browser.new_context(locale="en-IN", timezone_id="Asia/Kolkata")
    yield await context.new_page()
    await context.close()


pytestmark = pytest.mark.asyncio(loop_scope="module")


CARD_PROFILE = StoreProfile(
    card=("div.card",),
    title=("h3.name",),
    price=("span.cost",),
    link=("a.more",),
    out_of_stock=(":has-text('Sold Out')",),
    default_region=Region.IN,
)


class TestJsonLd:
    async def test_reads_a_plain_product_node(self, page: Page, html_page) -> None:
        url = html_page(
            "/ld1",
            """<html><body><script type="application/ld+json">
            {"@type":"Product","name":"Mario Kart World","url":"https://s.in/p/1",
             "offers":{"price":"4499.00","availability":"https://schema.org/InStock"}}
            </script></body></html>""",
        )
        await page.goto(url)
        rows = await from_json_ld(page)
        assert [(r.title, r.price, r.in_stock) for r in rows] == [("Mario Kart World", 4499.0, True)]

    async def test_walks_into_an_itemlist(self, page: Page, html_page) -> None:
        """Category pages wrap their products in ItemList rather than listing them flat."""
        url = html_page(
            "/ld2",
            """<html><body><script type="application/ld+json">
            {"@type":"ItemList","itemListElement":[
              {"item":{"@type":"Product","name":"Zelda TotK","url":"https://s.in/p/2",
                       "offers":{"price":"4299"}}},
              {"item":{"@type":"Product","name":"Metroid Dread","url":"https://s.in/p/3",
                       "offers":{"price":"3499"}}}]}
            </script></body></html>""",
        )
        await page.goto(url)
        rows = await from_json_ld(page)
        assert {r.title for r in rows} == {"Zelda TotK", "Metroid Dread"}

    async def test_walks_into_a_graph(self, page: Page, html_page) -> None:
        url = html_page(
            "/ld3",
            """<html><body><script type="application/ld+json">
            {"@graph":[{"@type":"WebSite","name":"shop"},
                       {"@type":"Product","name":"Pikmin 4","url":"https://s.in/p/4",
                        "offers":{"price":"3999"}}]}
            </script></body></html>""",
        )
        await page.goto(url)
        assert [r.title for r in await from_json_ld(page)] == ["Pikmin 4"]

    async def test_marks_an_out_of_stock_offer(self, page: Page, html_page) -> None:
        url = html_page(
            "/ld4",
            """<html><body><script type="application/ld+json">
            {"@type":"Product","name":"Splatoon 3","url":"https://s.in/p/5",
             "offers":{"price":"3999","availability":"https://schema.org/OutOfStock"}}
            </script></body></html>""",
        )
        await page.goto(url)
        assert (await from_json_ld(page))[0].in_stock is False

    async def test_survives_malformed_json(self, page: Page, html_page) -> None:
        """One broken block must not discard the valid ones beside it."""
        url = html_page(
            "/ld5",
            """<html><body>
            <script type="application/ld+json">{not json at all</script>
            <script type="application/ld+json">
            {"@type":"Product","name":"Kirby","url":"https://s.in/p/6","offers":{"price":"3499"}}
            </script></body></html>""",
        )
        await page.goto(url)
        assert [r.title for r in await from_json_ld(page)] == ["Kirby"]

    async def test_skips_a_product_missing_a_price(self, page: Page, html_page) -> None:
        url = html_page(
            "/ld6",
            """<html><body><script type="application/ld+json">
            {"@type":"Product","name":"No Price","url":"https://s.in/p/7"}
            </script></body></html>""",
        )
        await page.goto(url)
        assert await from_json_ld(page) == []


class TestSelectors:
    async def test_reads_cards(self, page: Page, html_page) -> None:
        url = html_page(
            "/s1",
            """<html><body>
            <div class="card"><h3 class="name">Mario Kart World</h3>
              <span class="cost">₹4,499</span><a class="more" href="/p/1">buy</a></div>
            <div class="card"><h3 class="name">Zelda TotK</h3>
              <span class="cost">₹4,299</span><a class="more" href="/p/2">buy</a></div>
            </body></html>""",
        )
        await page.goto(url)
        rows = await from_selectors(page, CARD_PROFILE)
        assert [(r.title, r.price) for r in rows] == [("Mario Kart World", 4499.0), ("Zelda TotK", 4299.0)]

    async def test_falls_back_to_a_rupee_figure_in_the_card_text(self, page: Page, html_page) -> None:
        """Layer 4: no price selector matched, but the card plainly shows a price."""
        url = html_page(
            "/s2",
            """<html><body><div class="card"><h3 class="name">Metroid Dread</h3>
            <div class="whatever">Now only ₹3,499 today</div>
            <a class="more" href="/p/3">buy</a></div></body></html>""",
        )
        await page.goto(url)
        rows = await from_selectors(page, CARD_PROFILE)
        assert rows[0].price == 3499.0

    async def test_falls_back_to_a_title_attribute(self, page: Page, html_page) -> None:
        url = html_page(
            "/s3",
            """<html><body><div class="card">
            <a title="Pikmin 4" class="more" href="/p/4">link</a>
            <span class="cost">₹3,999</span></div></body></html>""",
        )
        await page.goto(url)
        assert (await from_selectors(page, CARD_PROFILE))[0].title == "Pikmin 4"

    async def test_falls_back_to_an_image_alt(self, page: Page, html_page) -> None:
        url = html_page(
            "/s4",
            """<html><body><div class="card">
            <img alt="Kirby and the Forgotten Land">
            <span class="cost">₹3,499</span><a class="more" href="/p/5">buy</a>
            </div></body></html>""",
        )
        await page.goto(url)
        assert (await from_selectors(page, CARD_PROFILE))[0].title == "Kirby and the Forgotten Land"

    async def test_emulates_has_text_for_out_of_stock(self, page: Page, html_page) -> None:
        """`:has-text(...)` is Playwright locator syntax, NOT real CSS.

        Running it through a native querySelector throws, and a caught
        exception there is easy to miss -- which is how out-of-stock detection
        was silently disabled for every store at once.
        """
        url = html_page(
            "/s5",
            """<html><body><div class="card"><h3 class="name">Splatoon 3</h3>
            <span class="cost">₹3,999</span><span class="badge">Sold Out</span>
            <a class="more" href="/p/6">buy</a></div></body></html>""",
        )
        await page.goto(url)
        assert (await from_selectors(page, CARD_PROFILE))[0].in_stock is False

    async def test_a_card_still_in_stock_is_not_flagged(self, page: Page, html_page) -> None:
        url = html_page(
            "/s6",
            """<html><body><div class="card"><h3 class="name">Splatoon 3</h3>
            <span class="cost">₹3,999</span><a class="more" href="/p/7">buy</a></div></body></html>""",
        )
        await page.goto(url)
        assert (await from_selectors(page, CARD_PROFILE))[0].in_stock is True

    async def test_tries_the_next_card_candidate_when_the_first_matches_nothing(
        self, page: Page, html_page
    ) -> None:
        profile = StoreProfile(
            card=("div.does-not-exist", "div.card"),
            title=("h3.name",),
            price=("span.cost",),
            link=("a.more",),
        )
        url = html_page(
            "/s7",
            """<html><body><div class="card"><h3 class="name">Zelda</h3>
            <span class="cost">₹4,299</span><a class="more" href="/p/8">buy</a></div></body></html>""",
        )
        await page.goto(url)
        assert len(await from_selectors(page, profile)) == 1

    async def test_skips_a_card_with_no_usable_price(self, page: Page, html_page) -> None:
        url = html_page(
            "/s8",
            """<html><body><div class="card"><h3 class="name">Mystery</h3>
            <a class="more" href="/p/9">buy</a></div></body></html>""",
        )
        await page.goto(url)
        assert await from_selectors(page, CARD_PROFILE) == []


class TestLayerPrecedence:
    async def test_json_ld_wins_over_selectors(self, page: Page, html_page) -> None:
        """The durable layer must be preferred whenever it is present."""
        url = html_page(
            "/pref",
            """<html><body>
            <script type="application/ld+json">
            {"@type":"Product","name":"From JSON-LD","url":"https://s.in/p/1",
             "offers":{"price":"4499"}}</script>
            <div class="card"><h3 class="name">From CSS</h3>
            <span class="cost">₹1</span><a class="more" href="/x">b</a></div>
            </body></html>""",
        )
        await page.goto(url)
        rows, method = await extract(page, "somestore", CARD_PROFILE)
        assert method == "json-ld"
        assert rows[0].title == "From JSON-LD"

    async def test_falls_through_to_selectors_when_no_json_ld(self, page: Page, html_page) -> None:
        url = html_page(
            "/pref2",
            """<html><body><div class="card"><h3 class="name">From CSS</h3>
            <span class="cost">₹4,499</span><a class="more" href="/x">b</a></div></body></html>""",
        )
        await page.goto(url)
        rows, method = await extract(page, "somestore", CARD_PROFILE)
        assert method == "selectors"
        assert rows[0].title == "From CSS"

    async def test_reports_none_when_every_layer_finds_nothing(self, page: Page, html_page) -> None:
        url = html_page("/pref3", "<html><body><p>Nothing here</p></body></html>")
        await page.goto(url)
        rows, method = await extract(page, "somestore", CARD_PROFILE)
        assert rows == []
        assert method == "none"


class TestFlipkartState:
    async def test_walks_the_hydration_state_structurally(self, page: Page, html_page) -> None:
        """Flipkart's own __INITIAL_STATE__ shape changes.

        Walking it looking for anything with a title and a price beats
        assuming a path that will move.
        """
        url = html_page(
            "/fk",
            """<html><body><script>
            window.__INITIAL_STATE__ = {"pageDataV4":{"page":{"data":{"x":[
              {"widget":{"data":{"products":[
                {"productInfo":{"value":{
                  "titles":{"title":"Mario Kart World"},
                  "title":"Mario Kart World",
                  "pricing":{"finalPrice":{"value":4499}},
                  "finalPrice":{"value":4499},
                  "baseUrl":"/mario-kart/p/itm1"}}}]}}}]}}}};
            </script></body></html>""",
        )
        await page.goto(url)
        rows, method = await extract(page, "flipkart", CARD_PROFILE)
        assert method == "embedded-state"
        assert rows[0].title == "Mario Kart World"
        assert rows[0].price == 4499.0

    async def test_is_only_attempted_for_flipkart(self, page: Page, html_page) -> None:
        """Other stores must not pay for a Flipkart-shaped guess."""
        url = html_page(
            "/fk2",
            """<html><body><script>
            window.__INITIAL_STATE__ = {"title":"x","price":{"value":1},"url":"/y"};
            </script></body></html>""",
        )
        await page.goto(url)
        _, method = await extract(page, "amazon_in", CARD_PROFILE)
        assert method == "none"
