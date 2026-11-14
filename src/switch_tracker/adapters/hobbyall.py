"""Hobbyall's public product API."""

from __future__ import annotations

import json
import re
from typing import Any

from switch_tracker.adapters.base import ProgressSink
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import (
    AdapterKind,
    Failed,
    FetchOutcome,
    Ok,
    Platform,
    ProductKind,
    RawListing,
    Region,
    StoreConfig,
)
from switch_tracker.core.parse import classify, infer_condition, infer_region, parse_price


class HobbyallAdapter:
    kind = AdapterKind.HOBBYALL
    URL = "/api/products"

    def __init__(self, client: PoliteClient) -> None:
        self._client = client

    async def fetch(self, store: StoreConfig, sink: ProgressSink) -> FetchOutcome:
        response = await self._client.get(f"{store.base_url}{self.URL}", {"accept": "application/json"})
        if not response.ok:
            return Failed(f"product API: HTTP {response.status or response.body}")
        try:
            payload = json.loads(response.body)
        except ValueError:
            return Failed("product API returned invalid JSON")
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return Failed("product API returned an unexpected response")
        products = payload.get("data")
        if not isinstance(products, list) or not products:
            return Failed("product API returned no products")

        listings: list[RawListing] = []
        seen: set[str] = set()
        for product in products:
            if not isinstance(product, dict):
                continue
            listing = self._to_listing(store, product)
            if listing is None or listing.sku in seen:
                continue
            seen.add(listing.sku)
            listings.append(listing)

        sink.page(store.id, 1, len(listings))
        if not listings:
            return Failed("product API reachable but returned no Switch games")
        # The endpoint currently exposes no pagination cursor or authoritative total.
        # A successful response is useful discovery, but cannot prove catalogue exhaustion.
        return Ok(tuple(listings), coverage_complete=False)

    def _to_listing(self, store: StoreConfig, product: dict[str, Any]) -> RawListing | None:
        product_id = str(product.get("id") or "").strip()
        title = str(product.get("name") or "").strip()
        platform_code = str(product.get("platform") or "").strip().upper()
        platform = {"NSW": Platform.SWITCH, "NSW2": Platform.SWITCH2}.get(platform_code)
        if not product_id or not title or platform is None:
            return None
        if str(product.get("category") or "").strip().casefold() != "games":
            return None

        result = classify(
            " ".join(
                str(product.get(key) or "")
                for key in ("name", "category", "navItem", "parentNavItem", "platform", "tag")
            ),
            title=title,
        )
        if result.kind is not ProductKind.GAME:
            return None

        price = parse_price(product.get("price"))
        if price is None or price <= 0 or product.get("isInquiryOnly") is True:
            return None
        availability = str(product.get("availability") or "").casefold()
        quantity = product.get("stockQuantity")
        in_stock = "out of stock" not in availability and "sold out" not in availability
        if isinstance(quantity, (int, float)) and quantity <= 0:
            in_stock = False

        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        slug = f"{slug[:100].rstrip('-')}-{product_id}"
        image = str(product.get("imgUrl") or product.get("img") or "").strip()
        if image and image.startswith("/"):
            image = f"{store.base_url.rstrip('/')}{image}"

        context = " ".join(str(product.get(key) or "") for key in ("name", "tag"))
        context = context.replace("open boxed", "open box").replace("Open Boxed", "Open Box")
        return RawListing(
            store_id=store.id,
            sku=product_id,
            url=f"{store.base_url.rstrip('/')}/product/{slug}",
            title=title,
            native_currency=store.currency,
            native_price=price,
            in_stock=in_stock,
            platform=platform,
            region=infer_region(title, Region.IN),
            condition=infer_condition(context),
            image_url=image or None,
        )
