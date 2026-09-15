"""Scraping storefronts that expose no product API.

Amazon, Flipkart and several small Next.js-built Indian retailers have no
public feed, so the catalogue only exists after their JavaScript runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Callable
from urllib.parse import SplitResult, parse_qs, urlencode, urljoin, urlsplit

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from switch_tracker.adapters.base import ProgressSink
from switch_tracker.adapters.browser.diagnostics import dump
from switch_tracker.adapters.browser.extract import Extracted, extract
from switch_tracker.adapters.browser.pagination import (
    ProductivityTracker,
    read_claimed_total,
    wait_for_cloudflare,
)
from switch_tracker.adapters.browser.profiles import StoreProfile, WaitUntil, effective_profile
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.core.models import (
    AdapterKind,
    Condition,
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

#: The adapter's OWN time budget, and the reason a long walk is not a data loss.
#:
#: CollectService wraps every store in asyncio.wait_for. When that fires the
#: coroutine is CANCELLED, its local listings list dies with the frame, and the
#: store records `failed` with zero rows -- every page already scraped, thrown
#: away. Nothing can recover them from outside; they only exist in here.
#:
#: So the adapter stops ITSELF first and returns Partial through the normal
#: path, which CollectService persists like any other result. The service's
#: deadline stays as a backstop for an adapter that is genuinely wedged rather
#: than merely slow.
#:
#: Must stay below CollectService.DEFAULT_BROWSER_DEADLINE_S or the self-limit
#: never gets the chance to fire. Asserted by a test rather than by this
#: comment, because a comment cannot fail a build.
DEFAULT_TIME_BUDGET_S = 540.0

#: Playwright's default readiness condition, and this project's. Named because
#: _goto compares against it to decide whether a fallback is even possible.
_DEFAULT_WAIT_UNTIL: WaitUntil = "domcontentloaded"
_GOTO_TIMEOUT_MS = 45_000


class BrowserAdapter:
    kind = AdapterKind.BROWSER

    def __init__(
        self,
        provider: BrowserProvider,
        *,
        profile_for: Callable[[str], StoreProfile | None] = effective_profile,
        settle_ms: tuple[int, int] = (800, 1600),
        render_ms: int = 1200,
        time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    ) -> None:
        self._provider = provider
        self._profile_for = profile_for
        self._time_budget_s = time_budget_s
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
        #: Tried, not found. Without this, a store that publishes no "showing
        #: X of Y" text leaves claimed_total None forever, so the read re-fires
        #: on EVERY page -- and document.body.innerText forces a full layout
        #: pass over the whole DOM each time. Measured on Play-Asia at ~10s a
        #: page, this was a meaningful slice of it, for an answer that was
        #: already known after page 1.
        claimed_total_attempted = False
        # Raw rows seen before the classifier drops consoles and accessories.
        # This is the number to compare against a store's own "X results"
        # text, which counts everything in the category rather than only games.
        raw_seen = 0
        out_of_time = False

        # Per-profile where set: one large catalogue should not force every
        # store's budget up, and a store with nothing deep to walk should not
        # inherit a twenty-minute allowance it can never use.
        budget = self._time_budget_s if profile.time_budget_s is None else profile.time_budget_s
        deadline = asyncio.get_running_loop().time() + budget
        # Per search URL, like the hand-verified sweep's own cap. Bounds a
        # normal deep walk; the time budget above catches the abnormal one
        # where individual pages are slow rather than numerous.
        page_cap = min(MAX_PAGES_SAFETY, profile.max_pages or MAX_PAGES_SAFETY)

        context = await self._provider.new_context()
        try:
            if profile.cookies and profile.cookie_domain:
                # Before the first navigation, or the store has already decided
                # what currency to quote by the time we set them.
                await context.add_cookies(
                    [
                        {
                            "name": name,
                            "value": value,
                            "domain": profile.cookie_domain,
                            "path": "/",
                        }
                        for name, value in profile.cookies
                    ]
                )

            page = await context.new_page()

            for template in store.search_urls:
                # Fresh per search URL, not shared across them: two URLs
                # legitimately overlapping in their early results must not
                # look like "this one ran dry" the moment the second starts.
                seen_skus: set[str] = set()
                tracker = ProductivityTracker()

                for page_number in range(1, page_cap + 1):
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
                    if not claimed_total_attempted:
                        claimed_total_attempted = True
                        claimed_total = read_claimed_total(await _body_text(page))

                    new_on_page = 0
                    kept_on_page = 0
                    for row in rows:
                        raw_seen += 1
                        listing = self._to_listing(store, profile, row)
                        if listing is None:
                            continue
                        kept_on_page += 1
                        listings.append(listing)
                        if listing.sku not in seen_skus:
                            seen_skus.add(listing.sku)
                            new_on_page += 1

                    sink.page(store.id, page_number, len(listings))

                    if not rows:
                        break  # a genuinely empty page is unambiguous

                    # Productivity is measured against rows that SURVIVED
                    # filtering, not every raw row scraped.
                    #
                    # A store with a product-URL filter can legitimately show
                    # 100 raw rows of which 10 are products. Against the raw
                    # count that scores 0.10, under the tracker's 0.15
                    # threshold, so four consecutive healthy pages would end a
                    # walk that was working perfectly.
                    #
                    # The `or len(rows)` matters: when a non-empty page yields
                    # NO keepers, 0/len(rows) scores unproductive, which is the
                    # right reading. Passing 0 would instead hit the tracker's
                    # divide-guard and return False, letting a dead walk run all
                    # the way to MAX_PAGES_SAFETY.
                    #
                    # ProductivityTracker itself is deliberately untouched: six
                    # other stores and nine direct tests depend on its current
                    # semantics. The adapter chooses WHAT to measure; the
                    # tracker keeps deciding what the measurement means.
                    considered = kept_on_page or len(rows)
                    if tracker.record(new_on_page, considered):
                        break

                    # Checked AFTER a page, never before one.
                    #
                    # Launching a browser context is itself slow, so a check at
                    # the top of the loop can find the budget already spent and
                    # return Failed having scraped nothing -- the precise
                    # outcome this budget exists to prevent. At least one page
                    # is always attempted; the budget bounds how many follow.
                    if asyncio.get_running_loop().time() >= deadline:
                        out_of_time = True
                        break

                    await page.wait_for_timeout(random.uniform(*self._settle_ms))

                if out_of_time:
                    break
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
            reason = (
                f"ran out of time after {int(budget)}s before collecting anything"
                if out_of_time
                else "; ".join(problems) or "page loaded but nothing extracted"
            )
            return Failed(
                f"{reason}{completeness} -- HTML dumped to diagnostics/{store.id}.html; "
                f"use 'Fix a broken store' on {store.id}"
            )

        via = f"via {'+'.join(sorted(methods))}"
        if out_of_time:
            # Partial, never Failed: these rows are real and must be persisted.
            return Partial(
                tuple(unique),
                f"stopped at the {int(budget)}s time budget with "
                f"{len(unique)} listings kept{completeness} ({via})",
            )
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
        if page_number > 1 and uses_click_paging(profile, template):
            # This store has no URL to go to: page 2+ exists only behind a
            # client-side button click with no navigation at all, confirmed by
            # pages 1/2/3 coming back byte-identical under a URL parameter.
            if not await _click_next(page, profile, page_number):
                raise _NoMorePages
            await wait_for_cloudflare(page)
            await self._hydrate(page, profile)
            return await extract(page, store.id, profile)

        await self._goto(page, template.replace("{p}", str(page_number)), profile)
        await wait_for_cloudflare(page)

        for selector in profile.dismiss:
            # A cookie banner that is not there is the normal case, not a fault.
            with contextlib.suppress(Exception):
                await page.locator(selector).first.click(timeout=1500)

        if profile.ready:
            # Absence is handled by extraction simply returning nothing, which
            # then dumps diagnostics -- far more useful than a timeout here.
            with contextlib.suppress(Exception):
                await page.wait_for_selector(profile.ready, timeout=15_000)

        await self._hydrate(page, profile)

        rows, method = await extract(page, store.id, profile)
        if not rows:
            suffix = f"-p{page_number}" if page_number > 1 else ""
            await dump(page, f"{store.id}{suffix}")
        return rows, method

    async def _goto(self, page: Page, url: str, profile: StoreProfile) -> None:
        """Navigate, degrading the readiness condition rather than losing the store.

        A store on the default makes exactly one goto call, as before -- the
        retry branch is unreachable for it.

        For a store that opted into "networkidle", the retry is not politeness,
        it is budget protection. CollectService allows a browser store 600s in
        total. A page that never reaches network idle burns the full 45s
        timeout, so roughly thirteen of them exhaust the store's entire budget
        and it records `failed` with ZERO listings -- strictly worse than the
        partial data a degraded load would have produced.

        Retried once and not repeatedly: a site that does not settle on page 1
        will not settle on page 7, so further attempts spend the same budget to
        learn nothing.
        """
        try:
            await page.goto(url, wait_until=profile.wait_until, timeout=_GOTO_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError:
            if profile.wait_until == _DEFAULT_WAIT_UNTIL:
                raise
        await page.goto(url, wait_until=_DEFAULT_WAIT_UNTIL, timeout=_GOTO_TIMEOUT_MS)

    def _render_ms_for(self, profile: StoreProfile) -> int:
        """How long to let the grid finish after scrolling.

        Per-profile because it is a property of the SITE, not of the adapter --
        the same reasoning that already puts scroll_passes and wait_until on the
        profile. Play-Asia can afford a shorter pause than the default: on its
        click-paged path _advanced() has already polled until the results
        actually changed, so a further full-length wait is mostly idling after
        content we have confirmed arrived.

        Not zero, and not shortened for everyone: _advanced only inspects the
        first few cards, so the rest of the grid may still be painting.
        """
        return self._render_ms if profile.render_ms is None else profile.render_ms

    async def _hydrate(self, page: Page, profile: StoreProfile) -> None:
        """Give a lazily-rendered grid the nudge it needs -- on EVERY page.

        This scroll used to live only on the goto path, so a click-paged store
        hydrated page 1 and then never scrolled again: pages 2 onward were
        extracted from whatever had rendered above the fold. Those are exactly
        the pages that then look unproductive, which feeds the tracker and ends
        paging early.

        Two shapes, chosen per store:

        * ``scroll_passes == 1`` -- one proportional jump. What every store did
          before this was configurable, and still the default.
        * ``scroll_passes > 1`` -- that many viewport-sized steps, pausing
          between. A lazily-loaded grid extends the document as it fills, so a
          single proportional jump lands mid-page and stops triggering loads.
          This is the pattern the hand-verified Play-Asia sweep used.
        """
        if profile.scroll_passes <= 1:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
        else:
            for _ in range(profile.scroll_passes):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(profile.scroll_settle_ms)
        await page.wait_for_timeout(self._render_ms_for(profile))

    def _to_listing(
        self, store: StoreConfig, profile: StoreProfile, row: Extracted
    ) -> RawListing | None:
        result = classify(row.title, profile.platform_hint or store.platform_hint)
        if result.kind is not ProductKind.GAME or result.platform is Platform.UNKNOWN:
            return None

        absolute = row.href if row.href.startswith("http") else urljoin(store.base_url, row.href)
        # Before the SKU is derived: a rejected row must never mint a listing.
        if rejects_url(profile, absolute):
            return None
        split = urlsplit(absolute)

        region = infer_region(row.title, profile.default_region)
        sku = sku_from_url(absolute, profile.sku_url_params)
        if profile.sku_includes_region:
            # Some stores (Play-Asia) list separate region editions of one
            # title as separate cards that all link to the SAME product URL --
            # region only appears in the card's title text, never the href.
            # sku_from_url alone therefore collapses every regional edition
            # onto one SKU, which UNIQUE(store_id, sku) then upserts into a
            # single row, silently discarding the rest. Suffixing the region
            # is what keeps them as distinct listings.
            sku = f"{sku}-{region.value.lower()}"

        return RawListing(
            store_id=store.id,
            sku=sku,
            # Query string dropped except for a store's declared id params:
            # session ids and tracking parameters churn between runs and would
            # make one product look like many. CeX routes its whole catalogue
            # through one path and identifies products ONLY by ?id=, so for it
            # the bare path is a page that does not exist.
            url=_canonical_url(split, profile.sku_url_params),
            title=row.title,
            native_currency=store.currency,
            native_price=row.price,
            in_stock=row.in_stock,
            platform=result.platform,
            region=region,
            condition=_condition_for(profile, row),
        )


def _condition_for(profile: StoreProfile, row: Extracted) -> Condition:
    """New or pre-owned, from the strongest signal the store actually gives.

    Three tiers, narrowest first:

    1. The profile ASSERTS it. A shop whose entire catalogue is one condition
       (CeX) cannot be read off its own listings, because those listings never
       say -- a pre-owned-only retailer has no reason to label anything.
    2. The profile opts into card text. "Pre-owned" lives in a badge or a
       category strip beside the title on some storefronts, so the title alone
       reads NEW for a used cartridge.
    3. The title, which is what every store did before and still the default.

    Tier 2 is opt-in rather than universal on purpose; see
    ``StoreProfile.condition_from_context`` for the Amazon case that makes
    turning it on globally a data-corruption bug rather than an improvement.
    """
    if profile.default_condition is not None:
        return profile.default_condition
    if profile.condition_from_context and row.context:
        return infer_condition(row.context)
    return infer_condition(row.title)


def _canonical_url(split: SplitResult, keep_params: tuple[str, ...]) -> str:
    """The stored URL: scheme, host, path, and ONLY the declared id params.

    Rebuilt from the parsed parts rather than string-trimmed so parameter
    order is ours and not the page's -- two cards linking to the same product
    with their query parameters in a different order must not produce two
    different stored URLs.
    """
    base = f"{split.scheme}://{split.netloc}{split.path}"
    if not keep_params:
        return base
    found = parse_qs(split.query)
    kept = [
        (name, found[name][0])
        for name in keep_params
        if found.get(name) and found[name][0]
    ]
    return f"{base}?{urlencode(kept)}" if kept else base


def uses_click_paging(profile: StoreProfile, template: str) -> bool:
    """Must this store's page 2+ be reached by clicking rather than by URL?

    Two independent reasons, and the second one matters:

    * The profile declares a next-page control -- the store renders page 2
      client-side, so a URL parameter silently returns page 1 forever.
    * The search URL has no ``{p}`` to substitute. There is simply no other
      URL to go to, so clicking is the only mechanism available.

    Inferring this from ``next_page`` alone was wrong: Play-Asia has no ``{p}``
    AND, deliberately, no CSS pager selectors, because the only mechanism its
    verified sweep used was the numeric page-number clicker. Under the old rule
    an empty ``next_page`` meant "re-fetch the same URL forever".
    """
    return bool(profile.next_page) or "{p}" not in template


def rejects_url(profile: StoreProfile, url: str) -> bool:
    """Is this href something other than a product?

    Public and module-level rather than a method: it holds no adapter state, and
    keeping it out of the class means it is testable without launching a browser
    -- the same reason ``sku_from_url`` lives where it does.

    Fails OPEN by construction. A row is dropped only on a POSITIVE match, so a
    badly chosen rule leaves junk listings in the database, which is
    recoverable. The alternative shape -- a regex the URL must match to survive
    -- fails closed, and a mis-anchored one silently deletes an entire store's
    history. That asymmetry is why this is substring matching and not a pattern.
    """
    if not profile.reject_url_parts and not profile.require_digit_in_url:
        # The default for every store that has not opted in: no string work.
        return False
    if any(part in url for part in profile.reject_url_parts):
        return True
    return profile.require_digit_in_url and not any(char.isdigit() for char in url)


class _NoMorePages(Exception):
    """The next-page control is gone or disabled -- the real end of a click-paged site."""


async def _body_text(page: Page) -> str:
    try:
        return str(await page.evaluate("document.body.innerText"))
    except Exception:  # noqa: BLE001
        return ""


#: Identity of the currently rendered result set: how many cards, and what the
#: first few of them point at. A real page turn always changes this; a click on
#: something that is not a pager never does.
_FINGERPRINT = """
nodes => nodes.length + '|' + nodes.slice(0, 5).map(
    n => ((n.querySelector('a') || {}).getAttribute
            ? n.querySelector('a').getAttribute('href')
            : null) || (n.textContent || '')
).map(t => String(t).trim()).join('~')
"""

#: Last resort: a numbered pager. Matched by the control's own TEXT rather than
#: by a class, because the storefronts that need this are exactly the ones whose
#: pagers carry no semantic class at all. Deliberately broad -- li and span are
#: included because real pagers use them -- which is only safe because every
#: click is verified against the fingerprint above before it counts.
_CLICK_PAGE_NUMBER = """
(targetNum) => {
  const buttons = Array.from(document.querySelectorAll('a, button, li, span'));
  const targetBtn = buttons.find(el => {
    const txt = el.innerText.trim();
    return txt === String(targetNum) || txt.toLowerCase() === 'next' || txt === '>';
  });
  if (targetBtn && targetBtn.offsetParent !== null) {
    targetBtn.click();
    return true;
  }
  return false;
}
"""

#: How long a click gets to actually change the results before it is judged a
#: no-op. Client-side pagers re-render fast; this only has to outlast a render.
_ADVANCE_TIMEOUT_MS = 4000
_ADVANCE_POLL_MS = 200


async def _results_fingerprint(page: Page, card_selectors: tuple[str, ...]) -> str:
    for selector in card_selectors:
        try:
            if await page.locator(selector).count() == 0:
                continue
            return str(await page.locator(selector).evaluate_all(_FINGERPRINT))
        except Exception:  # noqa: BLE001
            continue
    return ""


async def _advanced(page: Page, card_selectors: tuple[str, ...], before: str) -> bool:
    """Did the result set actually change?

    Deliberately NOT a URL comparison. A click that navigates somewhere without
    results -- a footer link, a terms page -- changes the URL while destroying
    the thing we came for, and would pass a URL check. An unchanged or empty
    fingerprint both correctly read as "did not advance".
    """
    waited = 0
    while waited < _ADVANCE_TIMEOUT_MS:
        current = await _results_fingerprint(page, card_selectors)
        if current and current != before:
            return True
        await page.wait_for_timeout(_ADVANCE_POLL_MS)
        waited += _ADVANCE_POLL_MS
    return False


async def _click_next(page: Page, profile: StoreProfile, target_page: int) -> bool:
    """Turn the page, and CONFIRM that it turned.

    The confirmation is the whole point. Play-Asia's search URLs carry no {p},
    so clicking is the only way to advance -- and its profile's last-resort
    selector, ``:has-text('>')``, matches every element on the page containing
    that character, ``<html>`` and ``<body>`` included. ``.last`` therefore
    picked a footer ``<small>``, clicked it, and reported success. The page
    never turned, page 1 was re-extracted until the productivity tracker gave
    up four pages later, and the run reported ten pages' worth of raw rows with
    one page of real products. Nothing anywhere raised.

    A click is now only a page turn if the rendered results changed, so a wrong
    selector ends paging honestly instead of inflating the row count.

    Biased toward the LAST match: pagination sits at the end of a results grid,
    and the same icon-only control could plausibly appear in a carousel above it.
    """
    before = await _results_fingerprint(page, profile.card)

    for selector in profile.next_page:
        locator = page.locator(selector).last
        try:
            if await locator.count() == 0:
                continue
            if await locator.is_disabled():
                return False  # the real "no more pages" signal for this control
            await locator.click(timeout=5000)
        except Exception:  # noqa: BLE001
            continue
        if await _advanced(page, profile.card, before):
            return True

    # No configured control worked. Try the numbered pager the storefront may
    # be using instead -- this is the mechanism that was proven against
    # Play-Asia by hand, now available to every click-paged store.
    try:
        clicked = bool(await page.evaluate(_CLICK_PAGE_NUMBER, target_page))
    except Exception:  # noqa: BLE001
        return False
    return bool(clicked) and await _advanced(page, profile.card, before)


def _dedupe(listings: list[RawListing]) -> list[RawListing]:
    by_sku = {listing.sku: listing for listing in listings}
    return list(by_sku.values())