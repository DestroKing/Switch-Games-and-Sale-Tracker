"""Shopify exposes the whole catalogue as JSON at /products.json, no auth."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.shopify import ShopifyAdapter
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, Condition, Failed, Ok, Platform, StoreConfig


def product(
    pid: int, title: str, price: str = "4499.00", *, ptype: str = "", tags: list[str] | None = None
) -> dict[str, object]:
    return {
        "id": pid,
        "title": title,
        "handle": title.lower().replace(" ", "-"),
        "product_type": ptype,
        "tags": tags or [],
        "variants": [{"id": pid * 10, "title": "Default", "price": price, "available": True}],
        "images": [{"src": f"https://cdn/{pid}.jpg"}],
    }


def page(*products: dict[str, object]) -> tuple[int, str, dict[str, str]]:
    return (200, json.dumps({"products": list(products)}), {"content-type": "application/json"})


@pytest.fixture
def adapter() -> ShopifyAdapter:
    return ShopifyAdapter(PoliteClient(min_gap_s=0.0, timeout_s=5.0, backoff_base_s=0.01))


def store_at(base: str, **kw: object) -> StoreConfig:
    defaults: dict[str, object] = {
        "id": "shop",
        "name": "Shop",
        "base_url": base,
        "kind": AdapterKind.SHOPIFY,
        "currency": "INR",
        "tier": 2,
        "enabled": True,
        "platform_hint": Platform.SWITCH,
    }
    return replace(StoreConfig(**defaults), **kw)  # type: ignore[arg-type]


class TestFetching:
    async def test_reads_the_unscoped_catalogue(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/products.json", page(product(1, "Mario Kart World")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert [listing.title for listing in result.listings] == ["Mario Kart World"]

    async def test_scopes_to_configured_collections(self, adapter, server) -> None:
        """An unscoped general retailer leaks its whole catalogue through."""
        base, recorder = server
        recorder.plan("/collections/switch-games/products.json", page(product(1, "Zelda")))
        result = await adapter.fetch(store_at(base, collections=("switch-games",)), NullSink())
        assert isinstance(result, Ok)
        assert any("/collections/switch-games/products.json" in h for h in recorder.hits)

    async def test_builds_the_product_url_from_the_handle(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/products.json", page(product(1, "Mario Kart World")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].url == f"{base}/products/mario-kart-world"

    async def test_prefers_the_variant_sku_over_the_product_id(self, adapter, server) -> None:
        base, recorder = server
        item = product(1, "Zelda")
        item["variants"] = [{"id": 10, "title": "d", "price": "4499", "available": True, "sku": "NSW-001"}]
        recorder.plan("/products.json", page(item))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].sku == "NSW-001"

    async def test_falls_back_to_the_product_id_when_no_sku(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/products.json", page(product(77, "Zelda")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].sku == "77"


class TestClassificationContext:
    async def test_passes_product_type_and_tags_not_just_the_title(self, adapter, server) -> None:
        """Passing only the title is what made terse-titled stores look empty.

        A bare "Hogwarts Legacy" with product_type "Nintendo Switch Games" is
        a Switch game; the type has to reach the classifier.
        """
        base, recorder = server
        recorder.plan(
            "/products.json",
            page(product(1, "Hogwarts Legacy", ptype="Nintendo Switch Games")),
        )
        result = await adapter.fetch(store_at(base, platform_hint=None), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].platform is Platform.SWITCH

    async def test_a_pre_owned_category_reaches_the_condition_inference(
        self, adapter, server
    ) -> None:
        base, recorder = server
        recorder.plan("/products.json", page(product(1, "Zelda", ptype="Pre-Owned Games")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].condition is Condition.PRE_OWNED

    async def test_drops_non_games(self, adapter, server) -> None:
        """These shops also sell consoles, Joy-Cons, cases and eShop credit."""
        base, recorder = server
        recorder.plan(
            "/products.json",
            page(
                product(1, "Mario Kart World"),
                product(2, "Nintendo Switch Pro Controller"),
                product(3, "Nintendo eShop Gift Card"),
            ),
        )
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert [listing.title for listing in result.listings] == ["Mario Kart World"]

    async def test_skips_a_product_with_an_unparseable_price(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/products.json", page(product(1, "Zelda", price="")))
        assert isinstance(await adapter.fetch(store_at(base), NullSink()), Failed)


class TestPagination:
    async def test_stops_when_a_page_returns_fewer_than_the_page_size(
        self, adapter, server
    ) -> None:
        """Shopify's real stopping signal. No separate completeness check needed."""
        base, recorder = server
        recorder.plan("/products.json", page(product(1, "Zelda")))
        await adapter.fetch(store_at(base), NullSink())
        assert len([h for h in recorder.hits if h.startswith("/products.json")]) == 1

    async def test_keeps_paging_while_pages_come_back_full(self, adapter, server) -> None:
        base, recorder = server
        full = page(*(product(i, f"Game {i} Switch") for i in range(ShopifyAdapter.PAGE_SIZE)))
        recorder.plan("/products.json", full, page(product(9999, "Last Game Switch")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert len(result.listings) == ShopifyAdapter.PAGE_SIZE + 1

    async def test_reports_progress_per_page(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan("/products.json", page(product(1, "Zelda")))

        seen: list[tuple[int, int]] = []

        class Spy:
            def page(self, store_id: str, page: int, count: int) -> None:
                seen.append((page, count))

        await adapter.fetch(store_at(base), Spy())
        assert seen == [(1, 1)]


class TestFailures:
    async def test_an_empty_catalogue_is_a_failure_not_a_success(self, adapter, server) -> None:
        """A silent zero is the failure mode that quietly rots a tracker."""
        base, recorder = server
        recorder.plan("/products.json", page())
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Failed)
        assert result.reason

    async def test_an_unreachable_store_fails_with_a_readable_reason(self, adapter) -> None:
        result = await adapter.fetch(store_at("http://127.0.0.1:9"), NullSink())
        assert isinstance(result, Failed)
        assert result.reason
