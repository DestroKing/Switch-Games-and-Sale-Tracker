"""Why did a browser store extract N rows instead of the N on the page?

Console ONLY. Every other diagnostic here ends with "the HTML was written to
diagnostics/<store>.html", which is useless when the machine that can reach
the store cannot hand the file back. This prints everything needed to answer
the question instead, so it can be pasted into a conversation.

It answers four things a collection run never tells you:

  1. WHICH extraction layer won. extract() tries JSON-LD first and returns the
     moment it succeeds, so a page with five products in a schema.org block and
     twenty-four in the DOM yields five -- and nothing anywhere says the CSS
     selectors were never consulted.
  2. Where the rows are lost. A card is dropped for a missing title, a missing
     href, an unparseable price, or by the classifier -- four different bugs
     that look identical from the outside.
  3. Whether the page parameter does anything, by fingerprinting page 1
     against page 2 rather than trusting that a ?page= link exists.
  4. Whether the readiness condition is the cause, by running the WHOLE thing
     twice: once on the profile's setting and once on "networkidle". A store
     that server-renders a small slice and then replaces it over XHR shows a
     flat count on one and the real count on the other.

    uv run python scripts/diagnose_extraction.py gamepookie
    uv run python scripts/diagnose_extraction.py cex_in --url 2 --headful

Drives the SHIPPED profile and the SHIPPED extraction layers, for the reason
scrape_check.py gives at length: a diagnostic carrying its own private copy of
a store profile can pass while the collector fails on the same page.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from playwright.async_api import Page

from switch_tracker.adapters.browser.adapter import BrowserAdapter
from switch_tracker.adapters.browser.extract import extract, from_json_ld, from_selectors
from switch_tracker.adapters.browser.profiles import StoreProfile, WaitUntil, effective_profile
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.config import overrides
from switch_tracker.core.models import Platform, ProductKind, StoreConfig
from switch_tracker.core.parse import classify

_GOTO_TIMEOUT_MS = 45_000

#: Counts the schema.org blocks and their Product nodes without parsing them
#: in Python -- the question is how many the PAGE offers, which is exactly
#: what layer 1 will find, not whether our parser likes them.
_LD_COUNTS = """
() => {
  const blocks = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
  let products = 0;
  const walk = (n) => {
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (!n || typeof n !== 'object') return;
    if (String(n['@type'] ?? '').toLowerCase().includes('product')) products += 1;
    for (const k of ['@graph', 'itemListElement', 'item', 'mainEntity']) if (k in n) walk(n[k]);
  };
  for (const b of blocks) { try { walk(JSON.parse(b.textContent ?? '')); } catch { /* skip */ } }
  return { blocks: blocks.length, products };
}
"""


def _store(store_id: str) -> StoreConfig:
    for store in overrides.active_stores():
        if store.id == store_id:
            return store
    raise SystemExit(f"{store_id}: not in the shipped/overridden store list")


async def _counts_per_card_selector(page: Page, profile: StoreProfile) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for selector in profile.card:
        try:
            out.append((selector, await page.locator(selector).count()))
        except Exception as exc:  # noqa: BLE001 - an invalid selector is a finding, not a crash
            out.append((selector, -1))
            print(f"      (selector raised: {type(exc).__name__}: {exc})")
    return out


async def _report(
    adapter: BrowserAdapter,
    page: Page,
    store: StoreConfig,
    profile: StoreProfile,
    url: str,
    wait_until: WaitUntil,
) -> str:
    """Load one URL and print the whole funnel. Returns a page fingerprint."""
    print(f"\n  --- {url}")
    print(f"      wait_until={wait_until}")
    try:
        await page.goto(url, wait_until=wait_until, timeout=_GOTO_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 - a timeout here is the answer, not an error
        print(f"      goto FAILED: {type(exc).__name__}: {exc}")
        return ""

    if profile.ready:
        try:
            await page.wait_for_selector(profile.ready, timeout=15_000)
            print(f"      ready {profile.ready!r}: matched")
        except Exception:  # noqa: BLE001 - "never appeared" is exactly what we want to learn
            print(f"      ready {profile.ready!r}: NEVER APPEARED (cost the full 15s)")

    # The SHIPPED scroll/settle behaviour, so these counts are the ones a real
    # run would see rather than the ones an unscrolled page happens to show.
    await adapter._hydrate(page, profile)

    ld = await page.evaluate(_LD_COUNTS)
    ld_rows = await from_json_ld(page)
    print(f"      json-ld    : {ld['blocks']} block(s), {ld['products']} Product node(s)"
          f" -> layer 1 yields {len(ld_rows)} row(s)")

    print("      card selectors:")
    for selector, count in await _counts_per_card_selector(page, profile):
        print(f"        {count:>5}  {selector}")

    sel_rows = await from_selectors(page, profile)
    print(f"      selectors  : {len(sel_rows)} row(s)")

    rows, method = await extract(page, store.id, profile)
    print(f"      EXTRACT WINS WITH: {method}  ({len(rows)} rows)")
    if ld_rows and sel_rows and len(ld_rows) < len(sel_rows):
        print(f"      *** JSON-LD short-circuits extract() and is SMALLER than the DOM "
              f"({len(ld_rows)} vs {len(sel_rows)}) ***")

    kept = 0
    dropped_kind: list[str] = []
    for row in rows:
        result = classify(row.title, profile.platform_hint or store.platform_hint)
        if result.kind is ProductKind.GAME and result.platform is not Platform.UNKNOWN:
            kept += 1
        elif len(dropped_kind) < 5:
            dropped_kind.append(f"{row.title[:42]!r} -> {result.kind.value}/{result.platform.value}")
    print(f"      classifier : {kept} of {len(rows)} would become listings")
    for line in dropped_kind:
        print(f"        dropped  {line}")

    for row in rows[:3]:
        print(f"        sample   {row.price:>9.2f}  {row.title[:46]}  {row.href[:44]}")

    return "|".join(f"{r.title}~{r.href}" for r in rows[:5])


async def _jsonld_lockstep_probe(page: Page, profile: StoreProfile, template: str) -> None:
    """Does JSON-LD stay frozen, or does it regenerate to track the grid?

    Either answer still means ``skip_json_ld`` is the right fix -- extract()
    runs on the FIRST render, before any click happens, so a JSON-LD block
    that only mirrors whatever is currently on screen is no more useful than
    a static one. But which one it is says something different about the
    site: a frozen count is a "featured items" snippet unrelated to the
    catalogue; a count that climbs in lockstep with the cards means the block
    is real but always a step behind. Reported rather than assumed.

    Skipped entirely for a store with no click control -- this only tests
    what happens when MORE of the grid is loaded, which for a URL-paged store
    is a separate page.goto(), not a click.
    """
    if not profile.next_page:
        print("\n  (no next_page control on this profile -- click-lockstep probe not applicable)")
        return

    from switch_tracker.adapters.browser.adapter import _click_next

    print("\n================ does JSON-LD track the grid as the next control is clicked? ================")
    url = template.replace("{p}", "1")
    try:
        await page.goto(url, wait_until=profile.wait_until, timeout=_GOTO_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 - a timeout here is the answer, not an error
        print(f"      goto FAILED: {type(exc).__name__}: {exc}")
        return
    if profile.ready:
        try:
            await page.wait_for_selector(profile.ready, timeout=15_000)
        except Exception:  # noqa: BLE001 - "never appeared" is exactly what we want to learn
            print(f"      ready {profile.ready!r}: NEVER APPEARED")

    for click_number in range(4):
        if click_number > 0:
            advanced = await _click_next(page, profile, click_number + 1)
            if not advanced:
                print(f"      click {click_number}: control did not advance -- stopping here")
                break
        ld = await page.evaluate(_LD_COUNTS)
        cards = await page.locator(profile.card[0]).count() if profile.card else -1
        print(f"      after {click_number} click(s): json-ld {ld['products']:>3} product(s)   cards {cards:>3}")


async def run(store_id: str, url_index: int, headful: bool) -> int:
    store = _store(store_id)
    profile = effective_profile(store_id)
    if profile is None:
        raise SystemExit(f"{store_id}: no browser profile")
    if not store.search_urls:
        raise SystemExit(f"{store_id}: no search_urls")

    template = store.search_urls[url_index - 1]
    print(f"\n{store.name} ({store.id})")
    print(f"  template   : {template}")

    provider = BrowserProvider(headless=not headful)
    try:
        context = await provider.new_context()
        page = await context.new_page()
        adapter = BrowserAdapter(provider, render_ms=0)
        for wait_until in (profile.wait_until, "networkidle"):
            print(f"\n================ wait_until={wait_until} ================")
            prints: list[str] = []
            for page_number in (1, 2):
                url = template.replace("{p}", str(page_number))
                prints.append(
                    await _report(adapter, page, store, profile, url, wait_until)
                )
            if prints[0] and prints[0] == prints[1]:
                print("\n      *** PAGE 1 AND PAGE 2 ARE IDENTICAL -- the page parameter is inert ***")
            elif prints[0] and prints[1]:
                print("\n      page 1 and page 2 differ: URL paging works")
            if profile.wait_until == "networkidle":
                break
        await _jsonld_lockstep_probe(page, profile, template)
        await context.close()
    finally:
        await provider.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("store_id")
    parser.add_argument("--url", type=int, default=1, help="which search_url (1-based)")
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.store_id, args.url, args.headful))


if __name__ == "__main__":
    sys.exit(main())
