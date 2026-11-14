"""Pure browser-adapter decisions that do not require a browser runtime."""

from __future__ import annotations

from playwright.async_api import Page

from switch_tracker.adapters.browser.extract import Extracted
from switch_tracker.adapters.browser.profiles import StoreProfile
from switch_tracker.core.models import Condition, RawListing
from switch_tracker.core.parse import infer_condition


def _condition_for(profile: StoreProfile, row: Extracted) -> Condition:
    """New or pre-owned, from the strongest signal the store actually gives.

    Narrowest first: a profile that ASSERTS it (CeX, whose listings never say),
    then the card text if the profile opted in (GameLand, where it is a badge),
    then the title -- the default, and what every store did before.

    Tier 2 is opt-in on purpose; ``StoreProfile.condition_from_context`` has
    the Amazon case that makes enabling it globally a corruption bug.
    """
    if profile.default_condition is not None:
        return profile.default_condition
    if profile.condition_from_context and row.context:
        return infer_condition(row.context)
    return infer_condition(row.title)


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


async def _advanced(
    page: Page, card_selectors: tuple[str, ...], before: str, timeout_ms: int = _ADVANCE_TIMEOUT_MS
) -> bool:
    """Did the result set actually change?

    Deliberately NOT a URL comparison. A click that navigates somewhere without
    results -- a footer link, a terms page -- changes the URL while destroying
    the thing we came for, and would pass a URL check. An unchanged or empty
    fingerprint both correctly read as "did not advance".
    """
    waited = 0
    while waited < timeout_ms:
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
    timeout_ms = profile.advance_timeout_ms or _ADVANCE_TIMEOUT_MS

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
        if await _advanced(page, profile.card, before, timeout_ms):
            return True

    # No configured control worked. Try the numbered pager the storefront may
    # be using instead -- this is the mechanism that was proven against
    # Play-Asia by hand, now available to every click-paged store.
    try:
        clicked = bool(await page.evaluate(_CLICK_PAGE_NUMBER, target_page))
    except Exception:  # noqa: BLE001
        return False
    return bool(clicked) and await _advanced(page, profile.card, before, timeout_ms)


def _dedupe(listings: list[RawListing]) -> list[RawListing]:
    by_sku = {listing.sku: listing for listing in listings}
    return list(by_sku.values())


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
