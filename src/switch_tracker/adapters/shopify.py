"""Shopify's public product feed.

Every Shopify storefront exposes its catalogue as JSON at /products.json with
no auth and no key.  Where collections are configured we page through those
instead -- faster, and politer than pulling a whole catalogue of unrelated
stock from a shop that also sells cameras.
"""

from __future__ import annotations

from typing import Any

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


class ShopifyAdapter:
    kind = AdapterKind.SHOPIFY

    PAGE_SIZE = 250
    # A backstop, NOT a target. The loop below already stops for real once a
    # page comes back short. This only bounds a genuinely broken feed that
    # never does, so it is generous rather than tuned to any one store's page
    # count -- a number like that goes stale the moment a catalogue grows.
    MAX_PAGES = 100

    def __init__(self, client: PoliteClient) -> None:
        self._client = client

    async def fetch(self, store: StoreConfig, sink: ProgressSink) -> FetchOutcome:
        paths = (
            [f"/collections/{c}/products.json" for c in store.collections]
            if store.collections
            else ["/products.json"]
        )

        listings: list[RawListing] = []
        problems: list[str] = []

        for path in paths:
            for page in range(1, self.MAX_PAGES + 1):
                url = f"{store.base_url}{path}?limit={self.PAGE_SIZE}&page={page}"
                data = await self._client.get_json(url)

                if not isinstance(data, dict):
                    problems.append(f"{path} page {page}: no parseable JSON")
                    break

                products = data.get("products") or []
                if not products:
                    break

                for raw in products:
                    listing = self._to_listing(store, raw)
                    if listing is not None:
                        listings.append(listing)

                sink.page(store.id, page, len(listings))

                # The real stopping signal: a short page means the last page.
                if len(products) < self.PAGE_SIZE:
                    break

        if not listings:
            return Failed("; ".join(problems) or "zero products returned")
        if problems:
            return Partial(tuple(listings), "; ".join(problems))
        return Ok(tuple(listings))

    def _to_listing(self, store: StoreConfig, product: dict[str, Any]) -> RawListing | None:
        variants = product.get("variants") or []
        if not variants:
            return None
        variant = variants[0]

        price = parse_price(variant.get("price"))
        if price is None:
            return None

        # Everything the store tells us, not just the title. A terse "Hogwarts
        # Legacy" with a product_type of "Nintendo Switch Games" is a Switch
        # game; passing the title alone is what made these stores look empty.
        context = " ".join(
            [
                str(product.get("title", "")),
                str(product.get("product_type") or ""),
                " ".join(str(t) for t in (product.get("tags") or [])),
            ]
        )
        result = classify(context, store.platform_hint)

        # Only cartridges belong in a cartridge price history.
        if result.kind is not ProductKind.GAME or result.platform is Platform.UNKNOWN:
            return None

        images = product.get("images") or []
        title = str(product.get("title", ""))
        sku = str(variant.get("sku") or "").strip() or str(product.get("id"))

        return RawListing(
            store_id=store.id,
            sku=sku,
            url=f"{store.base_url}/products/{product.get('handle')}",
            title=title,
            native_currency=store.currency,
            native_price=price,
            in_stock=variant.get("available") is not False,
            platform=result.platform,
            region=infer_region(title, Region.IN),
            condition=infer_condition(context),
            image_url=str(images[0].get("src")) if images else None,
        )
