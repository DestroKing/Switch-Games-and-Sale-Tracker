"""The WooCommerce Store API.

Public and unauthenticated -- it is what the shop's own front end calls.  Two
path shapes exist in the wild depending on the Woo version, so both are tried.

This is the only adapter with an AUTHORITATIVE completeness signal: the
``x-wp-total`` response header states how many products match the query just
run.  Everywhere else, "did we get everything" is inference.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from switch_tracker.adapters.base import ProgressSink
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import (
    AdapterKind,
    Failed,
    FetchOutcome,
    Ok,
    Partial,
    Platform,
    ProductKind,
    RawListing,
    Region,
    StoreConfig,
)
from switch_tracker.core.parse import classify, infer_condition, infer_region, parse_price

_PATHS = ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products")


class WooAdapter:
    kind = AdapterKind.WOOCOMMERCE

    PER_PAGE = 100
    # A backstop, not a target -- see ShopifyAdapter.MAX_PAGES.
    MAX_PAGES = 100

    def __init__(self, client: PoliteClient) -> None:
        self._client = client

    async def fetch(self, store: StoreConfig, sink: ProgressSink) -> FetchOutcome:
        base_path = await self._resolve_path(store)
        if base_path is None:
            return Failed("no Store API at either known path")

        category_values = (
            [await self._resolve_category(store, slug) for slug in store.collections]
            if store.collections
            else [None]
        )

        listings: list[RawListing] = []
        raw_fetched = 0
        expected_total = 0

        for category in category_values:
            suffix = f"&category={quote(category)}" if category else ""
            # Read ONCE per category query, not once per page.
            #
            # woocommerce.ts accumulates this inside the page loop, so a
            # 213-item category over three pages reports 639 expected and
            # labels a complete fetch "partial" on every run. The header
            # states the total for the QUERY, not for the page.
            category_total: int | None = None

            for page in range(1, self.MAX_PAGES + 1):
                url = f"{store.base_url}{base_path}?per_page={self.PER_PAGE}&page={page}{suffix}"
                response = await self._client.get(url, {"accept": "application/json"})
                if not response.ok:
                    break

                if category_total is None:
                    header = response.headers.get("x-wp-total")
                    if header and header.isdigit() and int(header) > 0:
                        category_total = int(header)

                try:
                    products = json.loads(response.body)
                except ValueError:
                    break
                if not isinstance(products, list) or not products:
                    break

                raw_fetched += len(products)
                for raw in products:
                    listing = self._to_listing(store, raw)
                    if listing is not None:
                        listings.append(listing)

                sink.page(store.id, page, len(listings))

                if len(products) < self.PER_PAGE:
                    break

            if category_total is not None:
                expected_total += category_total

        # expected_total counts EVERYTHING in the category, consoles and
        # accessories included if the store's own tagging mixes them in. So
        # raw_fetched vs expected_total answers "did we reach the end", not
        # "why is listings shorter" -- that gap is the classifier correctly
        # dropping non-game rows, which is a different and expected thing.
        completeness = (
            f" (fetched {raw_fetched} of {expected_total} in category, per the store's own count)"
            if expected_total > 0
            else ""
        )

        if not listings:
            return Failed(f"Store API reachable but returned no Switch products{completeness}")
        if expected_total > 0 and raw_fetched < expected_total:
            return Partial(tuple(listings), f"stopped early{completeness}")
        return Ok(tuple(listings))

    async def _resolve_path(self, store: StoreConfig) -> str | None:
        for path in _PATHS:
            probe = await self._client.get_json(f"{store.base_url}{path}?per_page=1")
            if isinstance(probe, list):
                return path
        return None

    async def _resolve_category(self, store: StoreConfig, slug: str) -> str:
        """Slug -> numeric WP term id.

        Filtering by the raw slug works on some installs and silently matches
        nothing on others -- one real store had the term in product_cat with
        213 products and ?category=<slug> still returned zero. Resolving to
        the numeric id first is what works everywhere; the slug remains the
        fallback for installs that do not expose product_cat.
        """
        terms = await self._client.get_json(
            f"{store.base_url}/wp-json/wp/v2/product_cat?slug={quote(slug)}"
        )
        if isinstance(terms, list) and terms and isinstance(terms[0], dict):
            term_id = terms[0].get("id")
            if term_id is not None:
                return str(term_id)
        return slug

    def _to_listing(self, store: StoreConfig, product: dict[str, Any]) -> RawListing | None:
        prices = product.get("prices") or {}
        raw_price = prices.get("price")
        if raw_price is None:
            return None

        parsed = parse_price(raw_price)
        if parsed is None:
            return None
        # Minor units, with the exponent given per response. Getting this
        # wrong yields prices 100x out.
        minor_unit = prices.get("currency_minor_unit")
        price = parsed / (10 ** (minor_unit if isinstance(minor_unit, int) else 2))

        name = str(product.get("name", ""))
        categories = " ".join(str(c.get("name", "")) for c in (product.get("categories") or []))
        context = f"{name} {categories}"

        result = classify(context, store.platform_hint)
        if result.kind is not ProductKind.GAME or result.platform is Platform.UNKNOWN:
            return None

        images = product.get("images") or []
        return RawListing(
            store_id=store.id,
            sku=str(product.get("sku") or "").strip() or str(product.get("id")),
            url=str(product.get("permalink", "")),
            title=name,
            native_currency=str(prices.get("currency_code") or store.currency),
            native_price=price,
            in_stock=product.get("is_in_stock") is not False,
            platform=result.platform,
            region=infer_region(name, Region.IN),
            condition=infer_condition(context),
            image_url=str(images[0].get("src")) if images else None,
        )
