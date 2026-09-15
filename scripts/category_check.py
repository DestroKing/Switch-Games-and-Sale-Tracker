"""Real per-category product counts for a WooCommerce/Shopify store's
``collections`` slugs.

Companion to scrape_check.py, for the other half of the launch-risk review:
none of the seven WooCommerce/Shopify stores added alongside GameLand/
GamePookie/CeX have ever been hit from this machine. A wrong slug on a
multi-category store is the quiet failure mode -- woocommerce.py folds each
configured category into one running total, so ONE bad slug in three just
contributes zero to both sides of the completeness check and vanishes with
no error (hitechgamez's three categories, one of them pre-owned-only, are
exactly this shape). This asks the store's own API directly, one slug at a
time, so a bad one is a visible number instead of a silent gap.

Drives the SHIPPED adapter's own resolution logic (WooAdapter._resolve_path /
._resolve_category), not a private reimplementation of it -- the point is to
ask the same question the real collector run will ask, not a similar one.

    uv run python scripts/category_check.py
    uv run python scripts/category_check.py hitechgamez gamebuy consolegarage

Paste the output back for anything flagged SUSPICIOUSLY LOW or UNREACHABLE --
that is exactly the input needed to correct a slug in one pass instead of
guessing at a replacement.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import quote

from switch_tracker.adapters.woocommerce import WooAdapter
from switch_tracker.config import overrides
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, StoreConfig

# The seven WooCommerce/Shopify stores added in the same batch as GameLand/
# GamePookie/CeX -- the ones no live network call has ever touched. Naming
# them here is only the DEFAULT; passing store ids on the command line always
# overrides it, so this list going stale later just narrows a default, it
# does not silently stop the script from working on anything else.
DEFAULT_TARGETS = ("sheenu", "gamebuy", "hitechgamez", "gamebot", "gamekart", "consolegarage", "hadiro")

#: A real category with this few products is worth a second look against the
#: store's own page -- not proof the slug is wrong, since a genuinely tiny
#: category exists too, but the exact signal a wrong slug produces.
_SUSPICIOUS_MAX = 1


async def _woo_count(client: PoliteClient, store: StoreConfig, slug: str) -> int | None:
    # Reusing the adapter's own (private) resolution methods rather than a
    # second copy of the same logic -- the point is to ask exactly the
    # question the real collector run will ask, not a similar one.
    adapter = WooAdapter(client)
    base_path = await adapter._resolve_path(store)
    if base_path is None:
        return None
    category = await adapter._resolve_category(store, slug)
    url = f"{store.base_url}{base_path}?per_page=1&category={quote(category)}"
    response = await client.get(url, {"accept": "application/json"})
    if not response.ok:
        return None
    header = response.headers.get("x-wp-total")
    return int(header) if header and header.isdigit() else 0


async def _shopify_count(client: PoliteClient, store: StoreConfig, handle: str) -> int | None:
    # products.json has no total-count header the way WooCommerce's Store API
    # does -- 250 is the page size, not a promise the collection is smaller.
    # Still enough to answer the actual question: is this slug real and
    # non-trivial, or does it come back empty.
    data = await client.get_json(f"{store.base_url}/collections/{handle}/products.json?limit=250")
    products = data.get("products") if isinstance(data, dict) else None
    return len(products) if isinstance(products, list) else None


async def check(store: StoreConfig) -> list[bool]:
    """Returns which of this store's slugs came back UNREACHABLE.

    An empty list means no network call was even attempted (no collections
    configured, or a kind this script does not check) -- that must not count
    toward "everything was unreachable" below, or a store with nothing to
    check would falsely look like proof of a proxy problem.
    """
    if not store.collections:
        print(f"\n{store.name} ({store.id}): no collections configured -- nothing to check")
        return []
    if store.kind not in (AdapterKind.WOOCOMMERCE, AdapterKind.SHOPIFY):
        print(f"\n{store.name} ({store.id}): kind {store.kind} has no category API to check here")
        return []

    print(f"\n{store.name} ({store.id}, {store.kind})")
    client = PoliteClient()
    unreachable: list[bool] = []
    for slug in store.collections:
        count = (
            await _woo_count(client, store, slug)
            if store.kind is AdapterKind.WOOCOMMERCE
            else await _shopify_count(client, store, slug)
        )
        unreachable.append(count is None)
        if count is None:
            print(f"    {slug:38}  UNREACHABLE -- store API did not answer")
        elif count <= _SUSPICIOUS_MAX:
            print(f"    {slug:38}  {count:>5} products  <-- SUSPICIOUSLY LOW, check this slug live")
        else:
            print(f"    {slug:38}  {count:>5} products")
    return unreachable


def _proxy_env() -> list[str]:
    # Both cases, the way curl/requests/httpx itself would look for them.
    names = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
    return [n for n in names if os.environ.get(n)]


async def run(store_ids: list[str]) -> int:
    by_id = {s.id: s for s in overrides.active_stores()}
    exit_code = 0
    all_unreachable: list[bool] = []
    for store_id in store_ids:
        store = by_id.get(store_id)
        if store is None:
            print(f"\n{store_id}: not in the shipped/overridden store list")
            exit_code = 1
            continue
        all_unreachable.extend(await check(store))

    # PoliteClient sets trust_env=False deliberately -- a public shop must
    # never be reached through a corporate proxy, and on a locked-down
    # machine going through one would be blocked anyway (see http.py). That
    # is correct for the real collector, but it means this script fails
    # exactly like a wall of wrong slugs on a machine where a proxy is the
    # ONLY way out. Every slug checked coming back UNREACHABLE, on a machine
    # that has a proxy configured, is that trap far more often than it is
    # seven simultaneously-wrong slugs -- say so instead of leaving it to be
    # misread as a slug problem.
    proxy_vars = _proxy_env()
    if proxy_vars and all_unreachable and all(all_unreachable):
        print(
            f"\nNOTE: every slug checked came back UNREACHABLE, and {', '.join(proxy_vars)} is set "
            "in this environment. PoliteClient ignores the proxy by design (core/http.py), so on a "
            "network that requires it for outbound access, this is not evidence any slug is wrong -- "
            "it is evidence this run never left the machine. Check network access before touching stores.py."
        )

    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "store_ids",
        nargs="*",
        default=list(DEFAULT_TARGETS),
        help="store ids to check (default: the seven new API stores)",
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.store_ids))


if __name__ == "__main__":
    sys.exit(main())
