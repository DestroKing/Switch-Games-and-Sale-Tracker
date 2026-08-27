"""Run one store's real collection path against the live site and report it.

This hits a real shop over the network. It is a hand-run diagnostic, not a
test -- which is why it lives here and not under tests/, and why it no longer
carries a ``test_`` prefix that made pytest and PyCharm try to collect it.

It drives the SHIPPED adapter, the SHIPPED store config and the SHIPPED
profile. That is the entire point. The two scripts this replaced each carried
their own private copy of a store profile, so they could pass while the
collector failed on the same site -- and they did exactly that: Play-Asia's
private copy set ``next_page=()`` and paged by clicking page numbers itself,
so it never exercised the adapter's click-paging, where the real defect was.

    uv run python scripts/scrape_check.py playasia
    uv run python scripts/scrape_check.py e2zstore --pages 3 --headful
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from switch_tracker.adapters.browser import adapter as adapter_module
from switch_tracker.adapters.browser.adapter import BrowserAdapter
from switch_tracker.adapters.browser.profiles import StoreProfile, effective_profile
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.config import overrides
from switch_tracker.core.models import Failed, Partial, StoreConfig


class PrintSink:
    """The adapter's ProgressSink, wired to stdout, with per-page timing.

    Timing is the point: roughly 3.6s per page is fixed waiting the adapter
    does regardless of the site (two scroll settles, a render pause and the
    politeness gap). Knowing how much of a page's cost is that, versus the
    site's own render time, is the difference between tuning the right
    constant and guessing.
    """

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._last = self._start
        self._prev_count = 0

    def page(self, store_id: str, page: int, count: int) -> None:
        now = time.perf_counter()
        print(
            f"  page {page:>3}  ->  {count:>5} listings"
            f"   (+{count - self._prev_count:>3} this page)"
            f"   {now - self._last:>5.1f}s   total {now - self._start:>5.1f}s"
        )
        self._last = now
        self._prev_count = count


def _store(store_id: str) -> StoreConfig:
    store = next((s for s in overrides.active_stores() if s.id == store_id), None)
    if store is None:
        raise SystemExit(f"unknown store: {store_id}")
    return store


async def check(store_id: str, *, max_pages: int, headful: bool) -> int:
    store = _store(store_id)
    profile = effective_profile(store_id)
    if profile is None:
        raise SystemExit(f"{store_id} has no browser profile")

    # Bound the walk so a hand-run check cannot spend ten minutes on a large
    # catalogue. Restored in a finally, not after the happy path -- an early
    # return on a failed store would otherwise leave the cap applied for
    # anything else running in this interpreter.
    original = adapter_module.MAX_PAGES_SAFETY
    adapter_module.MAX_PAGES_SAFETY = max_pages
    try:
        return await _walk(store, profile, max_pages=max_pages, headful=headful)
    finally:
        adapter_module.MAX_PAGES_SAFETY = original


async def _walk(store: StoreConfig, profile: StoreProfile, *, max_pages: int, headful: bool) -> int:
    print(f"\n{store.name} ({store.id})")
    print(f"  currency   : {store.currency}")
    print(f"  cookies    : {dict(profile.cookies) or 'none'}")
    from switch_tracker.adapters.browser.adapter import uses_click_paging

    mechanism = (
        f"click: {profile.next_page}" if profile.next_page
        else "click: numeric page-number" if uses_click_paging(profile, store.search_urls[0])
        else "URL template {p}"
    )
    print(f"  paging     : {mechanism}")
    print(f"  urls       : {len(store.search_urls)}")
    print()

    provider = BrowserProvider(headless=not headful)
    started = time.perf_counter()
    try:
        outcome = await BrowserAdapter(provider).fetch(store, PrintSink())
    finally:
        await provider.close()

    print(f"\n  engine     : {provider.launched_channel}")
    print(f"  wall clock : {time.perf_counter() - started:.1f}s")
    print(f"  outcome    : {type(outcome).__name__}")
    if isinstance(outcome, Failed):
        print(f"  reason     : {outcome.reason}")
        return 1
    if isinstance(outcome, Partial):
        print(f"  reason     : {outcome.reason}")

    print(f"  listings   : {len(outcome.listings)}")
    print("\n  sample:")
    for item in outcome.listings[:15]:
        stock = "in stock" if item.in_stock else "OUT"
        print(f"    {item.native_currency} {item.native_price:>9.2f}  [{stock:>8}]  {item.title[:58]}")
        print(f"        sku={item.sku}  {item.url}")
    return 0


_PAGER_PROBE = """
() => {
  const out = { candidates: [], hrefsWithPage: [], cardCounts: {} };
  for (const el of document.querySelectorAll('a, button, li, span')) {
    const text = (el.innerText || '').trim();
    if (!text || text.length > 12) continue;
    if (!/^(\\d{1,3}|next|>|\\u203a|\\u00bb|last)$/i.test(text)) continue;
    out.candidates.push({
      text,
      tag: el.tagName.toLowerCase(),
      cls: (el.className || '').toString().slice(0, 60),
      href: el.getAttribute('href') || '',
      visible: el.offsetParent !== null,
      disabled: el.hasAttribute('disabled') || /disabled/i.test(el.className || ''),
    });
  }
  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href') || '';
    if (/page|offset|start|\\bp=/i.test(h)) out.hrefsWithPage.push(h.slice(0, 120));
  }
  return out;
}
"""


async def diagnose_pager(store_id: str, *, headful: bool) -> int:
    """Load page 1 and report what the page offers for turning it.

    Exists because 'the numeric clicker found nothing' is not actionable on its
    own -- you need to see what IS there before choosing a selector.
    """
    store = _store(store_id)
    profile = effective_profile(store_id)
    if profile is None:
        raise SystemExit(f"{store_id} has no browser profile")

    provider = BrowserProvider(headless=not headful)
    try:
        context = await provider.new_context()
        if profile.cookies and profile.cookie_domain:
            await context.add_cookies([
                {"name": n, "value": v, "domain": profile.cookie_domain, "path": "/"}
                for n, v in profile.cookies
            ])
        page = await context.new_page()
        url = store.search_urls[0].replace("{p}", "1")
        print(f"\n  loading {url}")
        await page.goto(url, wait_until=profile.wait_until, timeout=45_000)
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)

        print("\n  card selectors, in profile order:")
        for selector in profile.card:
            try:
                n = await page.locator(selector).count()
            except Exception as exc:  # noqa: BLE001
                n = f"error: {type(exc).__name__}"
            print(f"    {selector!r:34} -> {n}")

        print("\n  distinct product hrefs on this page:")
        hrefs = await page.evaluate(
            "() => [...new Set([...document.querySelectorAll(\"a[href*='/en/']\")]"
            ".map(a => a.getAttribute('href')).filter(h => /\\/\\d+\\/[a-z0-9]+$/i.test(h)))].length"
        )
        print(f"    {hrefs}")

        probe = await page.evaluate(_PAGER_PROBE)
        print("\n  pagination-shaped controls (text, tag, class, href, visible):")
        if not probe["candidates"]:
            print("    NONE FOUND -- the pager is not a numeric/next control in a/button/li/span")
        for c in probe["candidates"][:25]:
            flag = "" if c["visible"] else "  [hidden]"
            print(f"    {c['text']!r:8} {c['tag']:7} {c['cls']!r:40} {c['href'][:50]!r}{flag}")

        print("\n  links whose href mentions a page/offset parameter:")
        for h in dict.fromkeys(probe["hrefsWithPage"]):
            print(f"    {h}")
        if not probe["hrefsWithPage"]:
            print("    none -- so URL-based paging is probably not available")

        await dump_path(page, store_id)
    finally:
        await provider.close()
    return 0


async def dump_path(page: object, store_id: str) -> None:
    from switch_tracker import paths

    target = paths.diagnostics_dir() / f"{store_id}-pager.html"
    target.write_text(await page.content(), encoding="utf-8")  # type: ignore[attr-defined]
    print(f"\n  full HTML written to {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_id", help="e.g. playasia, e2zstore, amazon_in")
    parser.add_argument("--pages", type=int, default=5, help="page cap for this run")
    parser.add_argument("--headful", action="store_true", help="show the browser")
    parser.add_argument(
        "--diagnose-pager",
        action="store_true",
        help="load page 1 only and report what pagination controls the page actually has",
    )
    args = parser.parse_args(argv)
    if args.diagnose_pager:
        return asyncio.run(diagnose_pager(args.store_id, headful=args.headful))
    return asyncio.run(check(args.store_id, max_pages=args.pages, headful=args.headful))


if __name__ == "__main__":
    sys.exit(main())
