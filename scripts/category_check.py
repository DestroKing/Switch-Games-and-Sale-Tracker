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


async def check(store: StoreConfig) -> None:
    if not store.collections:
        print(f"\n{store.name} ({store.id}): no collections configured -- nothing to check")
        return
    if store.kind not in (AdapterKind.WOOCOMMERCE, AdapterKind.SHOPIFY):
        print(f"\n{store.name} ({store.id}): kind {store.kind} has no category API to check here")
        return

    print(f"\n{store.name} ({store.id}, {store.kind})")
    client = PoliteClient()
    for slug in store.collections:
        count = (
            await _woo_count(client, store, slug)
            if store.kind is AdapterKind.WOOCOMMERCE
            else await _shopify_count(client, store, slug)
        )
        if count is None:
            print(f"    {slug:38}  UNREACHABLE -- store API did not answer")
        elif count <= _SUSPICIOUS_MAX:
            print(f"    {slug:38}  {count:>5} products  <-- SUSPICIOUSLY LOW, check this slug live")
        else:
            print(f"    {slug:38}  {count:>5} products")


async def run(store_ids: list[str]) -> int:
    by_id = {s.id: s for s in overrides.active_stores()}
    exit_code = 0
    for store_id in store_ids:
        store = by_id.get(store_id)
        if store is None:
            print(f"\n{store_id}: not in the shipped/overridden store list")
            exit_code = 1
            continue
        await check(store)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
