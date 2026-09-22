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
import json
import pathlib
import re
import sqlite3
import textwrap
import time

from switch_tracker import paths
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


def _echo_diagnostics(store_id: str, since: float) -> None:
    """Print what the adapter wrote to disk, instead of leaving it in a file.

    The redirect trace and the HTML dump are the only evidence that explains a
    navigation failure, and they were written where nobody reading a console
    would find them -- useless to anyone who cannot open the data directory or
    attach a file. Everything here goes to stdout so the whole diagnosis can be
    copied out of a terminal.

    Filtered by mtime rather than by deleting the directory first: a stale trace
    from an earlier run is worse than no trace, but destroying a store's history
    to guarantee freshness is not this script's business.
    """
    directory = paths.diagnostics_dir()
    written = [
        path
        for path in sorted(directory.glob(f"{store_id}*"))
        if path.is_file() and path.stat().st_mtime >= since
    ]
    if not written:
        return

    print(f"\n    -- diagnostics this run wrote ({directory}) --")
    for path in written:
        if path.suffix == ".json":
            print(f"      {path.name}")
            try:
                trace = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"        unreadable: {exc}")
                continue
            print(f"        requested: {trace.get('requested_url')}")
            print(f"        ended at : {trace.get('final_url')}")
            print(f"        error    : {trace.get('error')}")
            hops = trace.get("redirects") or []
            print(f"        {len(hops)} navigation response(s):")
            for hop in hops:
                location = hop.get("location") or ""
                arrow = f"  -> {location}" if location else ""
                print(f"          {hop.get('status')}  {hop.get('url')}{arrow}")
        elif path.suffix in (".html", ".htm"):
            _echo_html(path)


#: Markers that say WHY a page is not the catalogue, in the order worth reporting.
_PAGE_MARKERS = (
    ("Just a moment", "Cloudflare interstitial"),
    ("cf-browser-verification", "Cloudflare challenge"),
    ("captcha", "CAPTCHA"),
    ("Access Denied", "access denied"),
    ("Please enable JavaScript", "JS-gate"),
    ("window.location", "client-side redirect"),
    ("<meta http-equiv=\"refresh\"", "meta-refresh redirect"),
    ("Login", "login wall"),
)


def _echo_html(path: pathlib.Path) -> None:
    """A summary of a dumped page, never the page itself.

    A Flipkart results dump is a few hundred KB of generated markup. What
    identifies it is the title, the size, and which interstitial markers appear
    -- pasting the document would bury all three.
    """
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"      {path.name}: unreadable: {exc}")
        return
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    print(f"      {path.name}  {len(html)} chars")
    print(f"        title: {(title.group(1).strip()[:120] if title else '(none)')!r}")
    found = [name for marker, name in _PAGE_MARKERS if marker.lower() in html.lower()]
    print(f"        markers: {', '.join(found) if found else '(none of the known interstitials)'}")
    # Visible text is what distinguishes an error document from a real page.
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
    print(f"        text starts: {text[:300]!r}")


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

        restore: tuple[object, str] | None = None
        if store.id == "flipkart":
            # Which URL each page actually used, and whether it came from the
            # store's own pager or from the {p} template. The template carries
            # double-encoded filter params, so "fell back" vs "pager href" is
            # the difference between two different navigations -- and only one
            # of them is what a browser would really request.
            from switch_tracker.adapters.browser import adapter as browser_module

            original = browser_module._flipkart_page_url

            async def traced(page: object, template: str, number: int) -> str:
                chosen: str = await original(page, template, number)  # type: ignore[operator]
                fallback = template.replace("{p}", str(number))
                how = "template fallback" if chosen == fallback else "store's own pager href"
                print(f"      p{number} navigating via {how}")
                print(f"        {chosen}")
                return chosen

            browser_module._flipkart_page_url = traced  # type: ignore[assignment]
            restore = (browser_module, "_flipkart_page_url")

        sink = PrintSink()
        started = time.perf_counter()
        wall_start = time.time()
        try:
            outcome = await adapter.fetch(store, sink)
        finally:
            if restore is not None:
                setattr(restore[0], restore[1], original)
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
    _echo_diagnostics(store.id, wall_start)
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
    await _alternates(store, slug, cat)


async def _alternates(store: StoreConfig, slug: str, cat: object) -> None:
    """Once ``category=`` is known to be refused, what is left?

    Two questions, and they have very different costs. Is the block specific to
    that ONE parameter -- in which case another route to the same filtered
    query is cheap -- or does the edge refuse category filtering by any name,
    leaving only "fetch the whole catalogue and filter it here"? Fetching
    HG World's 1595 products to keep two categories is sixteen pages per run,
    so it is worth one probe to find out it is unavoidable.

    Also dumps a product's own ``categories`` block, because local filtering
    can only be written against the fields the payload actually carries.
    """
    client = PoliteClient()
    base, v1 = store.base_url, "/wp-json/wc/store/v1/products"
    try:
        print("\n    -- alternate routes to the same filtered query --")
        for label, url in (
            # Is the WAF matching the literal word, or this parameter's use?
            ("harmless param merely CONTAINING 'category'", f"{base}{v1}?per_page=1&note=category"),
            ("category= alone, no per_page/page", f"{base}{v1}?category={cat}"),
            # Different parameter name, same intent.
            ("Store API category_id=", f"{base}{v1}?per_page=10&category_id={cat}"),
            # A different endpoint family entirely.
            ("WP REST product?product_cat=", f"{base}/wp-json/wp/v2/product?product_cat={cat}&per_page=10"),
            (
                "WC Store products/collection-data",
                f"{base}{v1}/collection-data?category={cat}",
            ),
        ):
            result = await client.get(url, {"accept": "application/json"})
            seen = {k: v for k, v in result.headers.items() if k in _TELLTALE}
            print(f"      {result.status or 'NO RESPONSE':>12}  {label}")
            if not result.ok:
                print(f"                    {seen}")

        # The OTHER adapter family. HG World ran as SHOPIFY for a month and was
        # switched to WOOCOMMERCE in one commit that also changed its
        # categories; the WooCommerce route then turned out to be blocked at
        # Cloudflare. So "which platform does this host actually serve" is a
        # live question for any store whose kind has been changed by hand, and
        # answering it costs three requests.
        print("\n    -- the other adapter family: Shopify product feed --")
        for label, url in (
            ("whole catalogue /products.json", f"{base}/products.json?limit=1"),
            (f"collection {slug!r}", f"{base}/collections/{slug}/products.json?limit=1"),
        ):
            result = await client.get(url, {"accept": "application/json"})
            shape = ""
            if result.ok:
                try:
                    body = json.loads(result.body)
                except ValueError:
                    shape = "  200 but NOT JSON (a WordPress 404 page answers 200 like this)"
                else:
                    if isinstance(body, dict):
                        products = body.get("products")
                        shape = (
                            f"  JSON dict, products={len(products)}"
                            if isinstance(products, list)
                            else f"  JSON dict, keys={sorted(body)[:8]}"
                        )
                    else:
                        shape = f"  JSON {type(body).__name__}, not the expected dict"
            print(f"      {result.status or 'NO RESPONSE':>12}  {label}{shape}")

        # The payload shape local filtering would have to match on.
        sample = await client.get_json(f"{base}{v1}?per_page=1")
        if isinstance(sample, list) and sample and isinstance(sample[0], dict):
            product = sample[0]
            print("\n    -- one product, as the unfiltered endpoint returns it --")
            print(f"      name={str(product.get('name'))[:70]!r}")
            print(f"      categories={json.dumps(product.get('categories'), indent=8)[:900]}")
            print(f"      top-level keys={sorted(product)}")
    finally:
        await client.aclose()


def history(store_id: str, limit: int) -> None:
    """Where this store's settings REALLY come from, and every outcome on record.

    Written because a diagnosis went wrong on exactly this point. The repo also
    contains a ``stores.local.json`` at its root, left over from the TypeScript
    version's bare relative path -- and the application never reads it.
    :func:`paths.overrides_path` resolves under the DATA directory
    (``%LOCALAPPDATA%/switch-tracker`` on Windows), so reading the checked-in
    copy and reasoning about it gives a confidently wrong answer about which
    adapter a store has been using. Print the resolved path, not the tracked one.

    ``kind`` is overridable and ``collections`` is not (see overrides._FIELDS),
    which is why the effective pair is printed together: a store's configured
    categories can come from stores.py while its adapter comes from a probe
    correction written months ago.
    """
    print(f"    data_dir   {paths.data_dir()}")
    override_path = paths.overrides_path()
    print(f"    overrides  {override_path}  exists={override_path.exists()}")
    if override_path.exists():
        print(textwrap.indent(override_path.read_text(encoding="utf-8").strip(), "      "))
    else:
        print("      (absent -- every store's kind comes from stores.py as shipped)")

    store = next((s for s in overrides.active_stores() if s.id == store_id), None)
    if store is not None:
        print(f"    EFFECTIVE  kind={store.kind.value} collections={store.collections}")

    db = paths.db_path()
    print(f"    db         {db}  exists={db.exists()}")
    if not db.exists():
        return
    # Read-only URI: this is a live database and a hand-run diagnostic has no
    # business taking a write lock on it.
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT r.started_at, rs.status, rs.listings_found, rs.detail "
            "FROM run_store rs JOIN run r ON r.id = rs.run_id "
            "WHERE rs.store_id = ? ORDER BY r.started_at DESC LIMIT ?",
            (store_id, limit),
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        print(f"    no run_store rows for {store_id} -- it has never been collected here")
        return
    print(f"    last {len(rows)} run(s), newest first:")
    for started, status, found, detail in rows:
        print(f"      {started}  {status:<8} {found:>5} listings")
        if detail:
            print(f"                 {' '.join(str(detail).split())[:180]}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check live stores before a release.")
    parser.add_argument("store_ids", nargs="*", help="store ids; default is every enabled store")
    parser.add_argument("--kind", help="limit to one AdapterKind, e.g. BROWSER, WOOCOMMERCE")
    parser.add_argument("--pages", type=int, default=0, help="page cap for BROWSER stores")
    parser.add_argument("--headful", action="store_true", help="show the browser")
    parser.add_argument("--probe", action="store_true", help="isolate an HTTP refusal instead of running")
    parser.add_argument("--slug", help="category slug for --probe; defaults to the first collection")
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument(
        "--history",
        action="store_true",
        help="print where this store's settings resolve from, plus its recorded run outcomes",
    )
    parser.add_argument("--limit", type=int, default=15, help="how many runs --history shows")
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
        if args.history:
            history(store.id, args.limit)
            continue
        if args.probe:
            # Both feed kinds, not just the configured one: the point of a probe
            # is often to find out that the configured kind is wrong.
            if store.kind in (AdapterKind.WOOCOMMERCE, AdapterKind.SHOPIFY):
                await probe(store, args.slug)
            else:
                print(f"    --probe covers feed stores; {store.id} is {store.kind.value}")
            continue
        try:
            if not await run_store(store, pages=args.pages, headful=args.headful):
                failures.append(store.id)
        except Exception as exc:  # noqa: BLE001 - one bad store must not end the sweep
            print(f"    RAISED {type(exc).__name__}: {exc}")
            failures.append(store.id)

    if args.probe or args.history:
        return 0
    print(f"\n{len(stores) - len(failures)}/{len(stores)} stores usable")
    if failures:
        print(f"unusable: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
