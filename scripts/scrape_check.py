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

from switch_tracker.adapters.browser import adapter as adapter_module
from switch_tracker.adapters.browser.adapter import BrowserAdapter
from switch_tracker.adapters.browser.profiles import StoreProfile, effective_profile
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.config import overrides
from switch_tracker.core.models import Failed, Partial, StoreConfig


class PrintSink:
    """The adapter's ProgressSink, wired to stdout."""

    def page(self, store_id: str, page: int, count: int) -> None:
        print(f"  page {page:>3}  ->  {count} listings so far")


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
    print(f"  next_page  : {profile.next_page or 'URL template only'}")
    print(f"  urls       : {len(store.search_urls)}")
    print()

    provider = BrowserProvider(headless=not headful)
    try:
        outcome = await BrowserAdapter(provider).fetch(store, PrintSink())
    finally:
        await provider.close()

    print(f"\n  engine     : {provider.launched_channel}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_id", help="e.g. playasia, e2zstore, amazon_in")
    parser.add_argument("--pages", type=int, default=5, help="page cap for this run")
    parser.add_argument("--headful", action="store_true", help="show the browser")
    args = parser.parse_args(argv)
    return asyncio.run(check(args.store_id, max_pages=args.pages, headful=args.headful))


if __name__ == "__main__":
    sys.exit(main())
