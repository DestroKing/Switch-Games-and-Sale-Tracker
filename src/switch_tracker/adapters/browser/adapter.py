"""Scraping storefronts that expose no product API.

Amazon, Flipkart and several small Next.js-built Indian retailers have no
public feed, so the catalogue only exists after their JavaScript runs.
"""

from __future__ import annotations

import contextlib
import random
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Page

from switch_tracker.adapters.base import ProgressSink
from switch_tracker.adapters.browser.diagnostics import dump
from switch_tracker.adapters.browser.extract import Extracted, extract
from switch_tracker.adapters.browser.pagination import ProductivityTracker, read_claimed_total
from switch_tracker.adapters.browser.profiles import StoreProfile, effective_profile
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.core.models import (
    AdapterKind,
    Failed,
    FetchOutcome,
    Ok,
    Partial,
    Platform,
    ProductKind,
    RawListing,
    StoreConfig,
)
from switch_tracker.core.parse import classify, infer_condition, infer_region
from switch_tracker.core.skus import sku_from_url

# A backstop, NOT a target. Every store stops on its own real signal -- an
# empty page, or no next control left to click -- whatever page count that
# turns out to be. This exists only to bound a genuinely broken loop, so it is
# generous and shared by every store rather than tuned per store to whatever
# was true on the day someone looked.
MAX_PAGES_SAFETY = 300


class BrowserAdapter:
    kind = AdapterKind.BROWSER

    def __init__(
        self,
        provider: BrowserProvider,
        *,
        profile_for: Callable[[str], StoreProfile | None] = effective_profile,
        settle_ms: tuple[int, int] = (800, 1600),
        render_ms: int = 1200,
    ) -> None:
        self._provider = provider
        self._profile_for = profile_for
        # Courtesy gap between pages. Was 2.5-5s, tuned for tiny independent
        # shops where that cost is free. A real 40-page category listing pays
        # it on every page, and for a headless browser session on a major site
        # a shorter but still-real gap is enough politeness without being the
        # reason a large, correctly-scoped catalogue cannot finish in budget.
        self._settle_ms = settle_ms
        # How long to let a lazy-loaded grid populate after scrolling.
        self._render_ms = render_ms

    async def fetch(self, store: StoreConfig, sink: ProgressSink) -> FetchOutcome:
        profile = self._profile_for(store.id)
        if profile is None:
            return Failed(f"no browser profile for {store.id}")
        if not store.search_urls:
            return Failed("no search_urls configured")

        listings: list[RawListing] = []
        problems: list[str] = []
        methods: set[str] = set()
        claimed_total: int | None = None
        # Raw rows seen before the classifier drops consoles and accessories.
        # This is the number to compare against a store's own "X results"
        # text, which counts everything in the category rather than only games.
        raw_seen = 0

        context = await self._provider.new_context()
        try:
            page = await context.new_page()

            for template in store.search_urls:
                # Fresh per search URL, not shared across them: two URLs
                # legitimately overlapping in their early results must not
                # look like "this one ran dry" the moment the second starts.
                seen_skus: set[str] = set()
                tracker = ProductivityTracker()

                for page_number in range(1, MAX_PAGES_SAFETY + 1):
                    try:
                        rows, method = await self._load_page(
                            page, store, profile, template, page_number
                        )
                    except _NoMorePages:
                        break
                    except Exception as exc:  # noqa: BLE001 - one bad page is not a dead store
                        problems.append(f"p{page_number}: {type(exc).__name__}: {exc}")
                        continue

                    methods.add(method)
                    if claimed_total is None:
                        claimed_total = read_claimed_total(await _body_text(page))

                    new_on_page = 0
                    for row in rows:
                        raw_seen += 1
                        listing = self._to_listing(store, profile, row)
                        if listing is None:
                            continue
                        listings.append(listing)
                        if listing.sku not in seen_skus:
                            seen_skus.add(listing.sku)
                            new_on_page += 1

                    sink.page(store.id, page_number, len(listings))

                    if not rows:
                        break  # a genuinely empty page is unambiguous
                    if tracker.record(new_on_page, len(rows)):
                        break

                    await page.wait_for_timeout(random.uniform(*self._settle_ms))
        finally:
            await context.close()

        unique = _dedupe(listings)

        completeness = (
            f" (store's own count reports ~{claimed_total}, {raw_seen} raw rows seen before "
            "game-only filtering -- best-effort, not a structured total)"
            if claimed_total is not None
            else ""
        )

        if not unique:
            reason = "; ".join(problems) or "page loaded but nothing extracted"
            return Failed(
                f"{reason}{completeness} -- HTML dumped to diagnostics/{store.id}.html; "
                f"use 'Fix a broken store' on {store.id}"
            )

        via = f"via {'+'.join(sorted(methods))}"
        if problems:
            return Partial(tuple(unique), f"{'; '.join(problems)} ({via}){completeness}")
        if claimed_total is not None and raw_seen < claimed_total * 0.9:
            return Partial(tuple(unique), f"stopped early{completeness} ({via})")
        return Ok(tuple(unique))

    async def _load_page(
        self,
        page: Page,
        store: StoreConfig,
        profile: StoreProfile,
        template: str,
        page_number: int,
    ) -> tuple[list[Extracted], str]:
        if page_number > 1 and profile.next_page:
            # This store has no URL to go to: page 2+ exists only behind a
            # client-side button click with no navigation at all, confirmed by
            # pages 1/2/3 coming back byte-identical under a URL parameter.
            if not await _click_next(page, profile.next_page):
                raise _NoMorePages
            await page.wait_for_timeout(self._render_ms)
            return await extract(page, store.id, profile)

        await page.goto(
            template.replace("{p}", str(page_number)),
            wait_until="domcontentloaded",
            timeout=45_000,
        )

        for selector in profile.dismiss:
            # A cookie banner that is not there is the normal case, not a fault.
            with contextlib.suppress(Exception):
                await page.locator(selector).first.click(timeout=1500)

        if profile.ready:
            # Absence is handled by extraction simply returning nothing, which
            # then dumps diagnostics -- far more useful than a timeout here.
            with contextlib.suppress(Exception):
                await page.wait_for_selector(profile.ready, timeout=15_000)

        # Lazy-loaded grids need a nudge.
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
        await page.wait_for_timeout(self._render_ms)

        rows, method = await extract(page, store.id, profile)
        if not rows:
            suffix = f"-p{page_number}" if page_number > 1 else ""
            await dump(page, f"{store.id}{suffix}")
        return rows, method

    def _to_listing(
        self, store: StoreConfig, profile: StoreProfile, row: Extracted
    ) -> RawListing | None:
        result = classify(row.title, profile.platform_hint or store.platform_hint)
        if result.kind is not ProductKind.GAME or result.platform is Platform.UNKNOWN:
            return None

        absolute = row.href if row.href.startswith("http") else urljoin(store.base_url, row.href)
        split = urlsplit(absolute)

        return RawListing(
            store_id=store.id,
            sku=sku_from_url(absolute),
            # Query string dropped: session ids and tracking parameters churn
            # between runs and would make one product look like many.
            url=f"{split.scheme}://{split.netloc}{split.path}",
            title=row.title,
            native_currency=store.currency,
            native_price=row.price,
            in_stock=row.in_stock,
            platform=result.platform,
            region=infer_region(row.title, profile.default_region),
            condition=infer_condition(row.title),
        )


class _NoMorePages(Exception):
    """The next-page control is gone or disabled -- the real end of a click-paged site."""


async def _body_text(page: Page) -> str:
    try:
        return str(await page.evaluate("document.body.innerText"))
    except Exception:  # noqa: BLE001
        return ""


async def _click_next(page: Page, selectors: tuple[str, ...]) -> bool:
    """Biased toward the LAST match.

    Pagination sits at the end of a results grid, and the same icon-only
    button could plausibly appear elsewhere -- a carousel, a dropdown.
    """
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            if await locator.count() == 0:
                continue
            if await locator.is_disabled():
                return False  # the real "no more pages" signal for this control
            await locator.click(timeout=5000)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _dedupe(listings: list[RawListing]) -> list[RawListing]:
    by_sku = {listing.sku: listing for listing in listings}
    return list(by_sku.values())
