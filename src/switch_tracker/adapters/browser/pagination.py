"""When to stop paging a site that will never tell you it has finished."""

from __future__ import annotations

import re

from playwright.async_api import Page


class ProductivityTracker:
    """Decides when a scraped catalogue is genuinely exhausted.

    The obvious rule -- stop when a page yields zero new rows -- silently
    truncated two real stores' catalogues.  Sites fill trailing pages with
    "related items" filler that reshuffles slightly page to page, so the count
    of new rows almost never lands on precisely zero even after real content
    runs out.  The loop paged on, collecting mostly duplicates which then
    vanished at dedupe, and the run reported success with a much smaller
    number than the real catalogue.

    A PROPORTION of new rows, sustained over several pages, is what actually
    distinguishes "genuinely done" from "recycling filler".
    """

    #: Below this share of new rows, a page is filler rather than content.
    UNPRODUCTIVE_RATIO = 0.15
    #: Four, not one and not two -- tolerance for noise, since a single odd
    #: page is not evidence that a catalogue ended.
    GIVE_UP_AFTER = 4

    def __init__(self) -> None:
        self._streak = 0

    def record(self, new_rows: int, total_rows: int) -> bool:
        """Record a page's yield. Returns True when paging should stop."""
        if total_rows == 0:
            # An empty page is handled by the caller as an unambiguous end;
            # it must not divide by zero here.
            return False
        unproductive = new_rows == 0 or (new_rows / total_rows) < self.UNPRODUCTIVE_RATIO
        self._streak = self._streak + 1 if unproductive else 0
        return self._streak >= self.GIVE_UP_AFTER


# Sites phrase this differently and plenty show none at all, so this stays
# deliberately loose -- several patterns, first match wins -- rather than
# tuned to one store's exact wording.
_TOTAL_PATTERNS = (
    re.compile(r"of\s+([\d,]+)\s+(?:results?|items?|products?)", re.IGNORECASE),
    re.compile(r"([\d,]+)\s+(?:results?|items?|products?)\s+found", re.IGNORECASE),
    re.compile(r"showing[^.\n]*?of\s+([\d,]+)", re.IGNORECASE),
)


def read_claimed_total(page_text: str) -> int | None:
    """A store's own "showing X of Y" claim, if it makes one.

    Best-effort and NOT authoritative -- unlike WooCommerce's x-wp-total, this
    is scraped prose. Useful for spotting "paging stopped with most of the
    catalogue unseen"; never a reason to call a run failed.
    """
    for pattern in _TOTAL_PATTERNS:
        match = pattern.search(page_text)
        if match:
            value = int(match.group(1).replace(",", ""))
            if value > 0:
                return value
    return None


async def wait_for_cloudflare(page: Page, timeout_ms: int = 20000) -> None:
    """Waits for Cloudflare Turnstile challenge page to resolve if encountered."""
    try:
        title = await page.title()
        if "Just a moment..." in title:
            await page.wait_for_function(
                "() => !document.title.includes('Just a moment...')",
                timeout=timeout_ms,
            )
    except Exception:  # noqa: BLE001 - a challenge probe must never fail the page
        # Failing to read the title is not evidence of a challenge. The caller
        # carries on either way and extraction reports the real outcome.
        return
