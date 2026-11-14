"""Hobbyall's public product API adapter."""

from __future__ import annotations

import json

import pytest

from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.hobbyall import HobbyallAdapter
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import (
    AdapterKind,
    Condition,
    Failed,
    Ok,
    Platform,
    StoreConfig,
)


def product(pid: str, name: str, *, platform: str = "NSW", **kw: object) -> dict[str, object]:
    return {
        "id": pid, "name": name, "category": "Games",
        "navItem": "Nintendo Switch" if platform == "NSW" else "Nintendo Switch 2",
        "parentNavItem": "Nintendo", "platform": platform,
        "price": "4499.00", "oldPrice": "4999.00",
        "stockQuantity": 3, "availability": "In Stock",
        "tag": "New Sealed", "imgUrl": "/storage/products/game.webp",
        "isInquiryOnly": False, **kw,
    }


def payload(*products: dict[str, object]) -> tuple[int, str, dict[str, str]]:
    return 200, json.dumps({"success": True, "data": list(products)}), {"content-type": "application/json"}


@pytest.fixture
def adapter() -> HobbyallAdapter:
    return HobbyallAdapter(PoliteClient(min_gap_s=0.0, timeout_s=5.0, backoff_base_s=0.01))


def store_at(base: str) -> StoreConfig:
    return StoreConfig(
        id="hobbyall", name="Hobbyall", base_url=base,
        kind=AdapterKind.HOBBYALL, currency="INR", tier=2, enabled=True,
    )


class TestFetching:
    async def test_reads_the_public_products_api(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(product("PRD001", "Mario Kart World")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.coverage_complete is False
        assert recorder.hits == ["/api/products"]
        assert result.listings[0].sku == "PRD001"

    async def test_keeps_both_switch_platforms_and_maps_platform_codes(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(
            product("PRD001", "Mario Kart 8 Deluxe", platform="NSW"),
            product("PRD002", "Mario Kart World", platform="NSW2"),
        ))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert [x.platform for x in result.listings] == [Platform.SWITCH, Platform.SWITCH2]

    async def test_uses_api_id_as_stable_sku_and_deduplicates_repeated_ids(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(
            product("PRD001", "Mario Kart World"),
            product("PRD001", "Mario Kart World duplicate"),
        ))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert len(result.listings) == 1
        assert result.listings[0].sku == "PRD001"

    async def test_uses_api_product_slug_url_and_absolute_image_url(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(product("PRD001", "Mario Kart World")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        listing = result.listings[0]
        assert listing.url == f"{base}/product/mario-kart-world-PRD001"
        assert listing.image_url == f"{base}/storage/products/game.webp"

    async def test_reads_price_stock_and_preowned_condition(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(product(
            "PRD001", "Zelda: Tears of the Kingdom",
            price="3,499.00", tag="Open Boxed Mint", stockQuantity=0, availability="Out of Stock",
        )))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        listing = result.listings[0]
        assert listing.native_price == 3499.0
        assert listing.in_stock is False
        assert listing.condition is Condition.PRE_OWNED

    async def test_drops_non_games_inquiry_only_and_unpriced_products(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(
            product("PRD001", "Nintendo Switch 2 Console"),
            product("PRD002", "Lexar microSD Express Card", platform="NSW2", category="Accessories"),
            product("PRD003", "Metaphor ReFantazio", isInquiryOnly=True),
            product("PRD004", "Mario Kart World", price="INQUIRY ONLY"),
        ))
        assert isinstance(await adapter.fetch(store_at(base), NullSink()), Failed)

    async def test_rejects_unknown_platform_codes(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload(product("PRD001", "Mario Kart World", platform="PS5")))
        assert isinstance(await adapter.fetch(store_at(base), NullSink()), Failed)


class TestFailures:
    async def test_empty_catalogue_is_a_failure(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/api/products", payload())
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Failed)
        assert result.reason

    async def test_unexpected_json_shape_is_a_failure(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(
            "/api/products",
            (200, '{"success":true,"data":{}}', {"content-type": "application/json"}),
        )
        assert isinstance(await adapter.fetch(store_at(base), NullSink()), Failed)

    async def test_unreachable_store_fails_with_a_readable_reason(self, adapter) -> None:
        result = await adapter.fetch(store_at("http://127.0.0.1:9"), NullSink())
        assert isinstance(result, Failed)
        assert result.reason
