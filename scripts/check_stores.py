"""Run ANY store -- any kind -- against the live site, and judge what came back.

One entry point for the pre-release sweep. ``scrape_check.py`` drives only
BROWSER stores and ``category_check.py`` only the feed stores' category slugs,
so answering "is everything working before I build the exe" meant two scripts,
two output shapes, and no verdict for a WooCommerce store's actual listings.
This drives whichever adapter the registry would really choose, for one store
or for all of them, and prints the same verdict either way.

It drives the SHIPPED registry, the SHIPPED store list WITH its local probe
corrections applied, and the SHIPPED profiles -- the same objects
services/collect.py uses. A private reimplementation could pass while the
collector failed on the same site, which has already happened here once.

    uv run python scripts/check_stores.py                    # every enabled store
    uv run python scripts/check_stores.py hgworld flipkart    # just these two
    uv run python scripts/check_stores.py --kind BROWSER      # one adapter kind
    uv run python scripts/check_stores.py flipkart --pages 3 --headful
    uv run python scripts/check_stores.py hgworld --probe     # isolate an HTTP refusal

``--probe`` answers a different question from a run: when a feed store returns
403/401, it re-asks the same host one variable at a time -- with and without
the category filter, at per_page 100 and 10, by term id and by slug, and then
REPEATS the first known-good request. That last one is the discriminator: if a
baseline that worked before the failures now fails too, the trigger is request
volume and no parameter change will help.

WARNING: real network, real shops. The politeness gap makes a full sweep slow
on purpose. Nothing here writes to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from switch_tracker.adapters.registry import build_registry
from switch_tracker.config import overrides
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, Failed, Ok, Partial, RawListing, StoreConfig

#: Headers a WAF or a wp-json hardening plugin announces itself under. Their
#: ABSENCE on a 403 is informative too -- that points at WordPress itself.
_TELLTALE = ("server", "cf-ray", "cf-mitigated", "x-sucuri-id", "x-sucuri-block", "retry-after")


class PrintSink:
    """Per-page progress, with the raw count kept for the page-repeat check."""

    def __init__(self) -> None:
        self.last_raw = 0

    def page(self, store_id: str, page: int, count: int) -> None:
        self.last_raw = count
        print(f"      p{page}: {count} listings so far")


def audit(store: StoreConfig, listings: tuple[RawListing, ...], raw: int) -> list[str]:
    """The failure modes a bare listing count cannot show.

    Every one of these has actually shipped broken here at least once, which
    is why each is a named check rather than a number left for a human to
    eyeball at the end of a twenty-store sweep.
    """
    warnings: list[str] = []
    if not listings:
        return warnings

    # A store repeating page 1 under every {p}: lots of raw pushes, few unique
    # rows surviving dedupe. This is the shape Flipkart's click-paging
    # regression produced -- four "productive" pages, 13 duplicates.
    if raw and len(listings) < raw * 0.75:
        warnings.append(f"{raw} raw pushes collapsed to {len(listings)} unique -- pages may repeat")

    skus = [x.sku for x in listings]
    if len(set(skus)) != len(skus):
        warnings.append("duplicate SKUs survived dedupe")
    if any(not x.sku for x in listings):
        warnings.append("blank SKU -- price history cannot accumulate across runs")

    zero = sum(1 for x in listings if x.native_price <= 0)
    if zero:
        warnings.append(f"{zero} listing(s) priced <= 0")
    # 100x errors are the WooCommerce minor-unit bug's signature.
    steep = sum(1 for x in listings if x.native_price > 500_000)
    if steep:
        warnings.append(f"{steep} listing(s) over 500k -- check the currency minor unit")

    wrong = {x.native_currency for x in listings} - {store.currency}
    if wrong:
        warnings.append(f"currency {sorted(wrong)} != configured {store.currency}")
    if all(not x.in_stock for x in listings):
        warnings.append("every listing out of stock -- the stock selector may be matching everything")
    if not any(x.url for x in listings):
        warnings.append("no listing has a URL")
    return warnings


async def run_store(store: StoreConfig, *, pages: int, headful: bool) -> bool:
    """Collect one store for real. True when it came back usable."""
    client = PoliteClient()
    provider = None
    try:
        if store.kind is AdapterKind.BROWSER:
            from switch_tracker.adapters.browser.provider import BrowserProvider

            provider = BrowserProvider(headless=not headful)
        registry = build_registry(client, provider)
        adapter = registry.get(store.kind)
        if adapter is None:
            print(f"    no adapter for kind {store.kind}")
            return False

        if pages and store.kind is AdapterKind.BROWSER:
            # Bound a hand-run sweep without editing the shipped profile.
            from switch_tracker.adapters.browser import profiles as profile_module

            profile = profile_module.PROFILES.get(store.id)
            if profile is not None:
                from dataclasses import replace

                profile_module.PROFILES[store.id] = replace(profile, max_pages=pages)

        sink = PrintSink()
        started = time.perf_counter()
        outcome = await adapter.fetch(store, sink)
        took = time.perf_counter() - started
    finally:
        await client.aclose()
        if provider is not None:
            await provider.close()

    listings = () if isinstance(outcome, Failed) else outcome.listings
    label = type(outcome).__name__.upper()
    print(f"    {label} in {took:.1f}s -- {len(listings)} listings")
    if isinstance(outcome, (Partial, Failed)):
        print(f"      reason: {outcome.reason}")
    for warning in audit(store, listings, sink.last_raw):
        print(f"      WARN: {warning}")
    if listings:
        sample = listings[0]
        print(
            f"      e.g. {sample.title[:60]!r} {sample.native_currency} {sample.native_price} "
            f"stock={sample.in_stock} cond={sample.condition} {sample.url[:60]}"
        )
    return isinstance(outcome, (Ok, Partial)) and bool(listings)


async def probe(store: StoreConfig, slug: str | None) -> None:
    """Isolate an HTTP refusal on a feed store, one variable at a time."""
    slug = slug or (store.collections[0] if store.collections else None)
    if slug is None:
        print(f"    {store.id} has no configured collections to probe")
        return

    client = PoliteClient()
    base, v1, legacy = store.base_url, "/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"
    try:
        terms = await client.get_json(f"{base}/wp-json/wp/v2/product_cat?slug={slug}")
        term = terms[0].get("id") if isinstance(terms, list) and terms else None
        print(f"    slug {slug!r} -> term id {term!r}")
        cat = term if term is not None else slug

        for label, url in (
            ("baseline per_page=1, no category", f"{base}{v1}?per_page=1"),
            ("per_page=100, no category", f"{base}{v1}?per_page=100&page=1"),
            ("per_page=100 + category (the real call)", f"{base}{v1}?per_page=100&page=1&category={cat}"),
            ("per_page=10 + category", f"{base}{v1}?per_page=10&page=1&category={cat}"),
            ("category by SLUG not id", f"{base}{v1}?per_page=10&page=1&category={slug}"),
            ("legacy path + category", f"{base}{legacy}?per_page=10&page=1&category={cat}"),
            ("baseline REPEATED after the above", f"{base}{v1}?per_page=1"),
        ):
            result = await client.get(url, {"accept": "application/json"})
            seen = {k: v for k, v in result.headers.items() if k in _TELLTALE}
            total = result.headers.get("x-wp-total")
            status = result.status or "NO RESPONSE"
            print(f"      {status:>12}  {label}")
            if total:
                print(f"                    x-wp-total={total}")
            if not result.ok:
                print(f"                    {seen} body={result.body[:120].strip()!r}")
    finally:
        await client.aclose()

    print(
        "    Reading it: last line failing too => rate limiting, not a parameter.\n"
        "    per_page=100 refused but 10 fine => lower WooAdapter.PER_PAGE.\n"
        "    category refused but bare fine => the filter is what is blocked."
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check live stores before a release.")
    parser.add_argument("store_ids", nargs="*", help="store ids; default is every enabled store")
    parser.add_argument("--kind", help="limit to one AdapterKind, e.g. BROWSER, WOOCOMMERCE")
    parser.add_argument("--pages", type=int, default=0, help="page cap for BROWSER stores")
    parser.add_argument("--headful", action="store_true", help="show the browser")
    parser.add_argument("--probe", action="store_true", help="isolate an HTTP refusal instead of running")
    parser.add_argument("--slug", help="category slug for --probe; defaults to the first collection")
    parser.add_argument("--include-disabled", action="store_true")
    args = parser.parse_args()

    stores = [
        s
        for s in overrides.active_stores()
        if (args.include_disabled or s.enabled or s.id in args.store_ids)
        and (not args.store_ids or s.id in args.store_ids)
        and (not args.kind or s.kind.value == args.kind.upper())
    ]
    unknown = set(args.store_ids) - {s.id for s in stores}
    if unknown:
        print(f"unknown store id(s): {sorted(unknown)}")
        return 2
    if not stores:
        print("no stores matched")
        return 2

    failures: list[str] = []
    for store in stores:
        print(f"\n== {store.id} ({store.kind.value}) {store.base_url}")
        if args.probe:
            if store.kind is AdapterKind.WOOCOMMERCE:
                await probe(store, args.slug)
            else:
                print(f"    --probe covers WOOCOMMERCE stores; {store.id} is {store.kind.value}")
            continue
        try:
            if not await run_store(store, pages=args.pages, headful=args.headful):
                failures.append(store.id)
        except Exception as exc:  # noqa: BLE001 - one bad store must not end the sweep
            print(f"    RAISED {type(exc).__name__}: {exc}")
            failures.append(store.id)

    if args.probe:
        return 0
    print(f"\n{len(stores) - len(failures)}/{len(stores)} stores usable")
    if failures:
        print(f"unusable: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
