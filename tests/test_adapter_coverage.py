"""Coverage: what a feed walk actually read, reported as facts beside its rows.

``Ok`` says "nothing went wrong that I noticed". It does not say "I read the
whole scope", and a walk that hit its page backstop used to report Ok anyway.
Anything deciding a product has LEFT a store needs the second statement, so
the walk reports it explicitly: pages, the store's own count, whether every
path reached its own end, and the SKU of every raw product -- games or not --
since a product the classifier dropped is still a product the store lists.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.hobbyall import HobbyallAdapter
from switch_tracker.adapters.shopify import ShopifyAdapter
from switch_tracker.adapters.woocommerce import WooAdapter
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, Ok, Partial, Platform, StoreConfig

V1 = "/wp-json/wc/store/v1/products"


def _client() -> PoliteClient:
    return PoliteClient(min_gap_s=0.0, timeout_s=5.0, backoff_base_s=0.01)


def _store(base: str, kind: AdapterKind, **kw: object) -> StoreConfig:
    cfg = StoreConfig(
        id="s",
        name="S",
        base_url=base,
        kind=kind,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
    )
    return replace(cfg, **kw)  # type: ignore[arg-type]


def shopify_product(pid: int, title: str, sku: str = "") -> dict[str, object]:
    return {
        "id": pid,
        "title": title,
        "handle": f"p{pid}",
        "variants": [{"id": pid * 10, "price": "999", "available": True, "sku": sku}],
    }


def shopify_page(*products: dict[str, object]) -> tuple[int, str, dict[str, str]]:
    return (200, json.dumps({"products": list(products)}), {"content-type": "application/json"})


def woo_product(pid: int, name: str, sku: str = "") -> dict[str, object]:
    return {
        "id": pid,
        "name": name,
        "sku": sku,
        "permalink": f"https://shop.in/p/{pid}",
        "is_in_stock": True,
        "prices": {"price": "99900", "currency_code": "INR", "currency_minor_unit": 2},
    }


def woo_page(*products: dict[str, object], total: int | None = None) -> tuple[int, str, dict[str, str]]:
    headers = {"content-type": "application/json"}
    if total is not None:
        headers["X-WP-Total"] = str(total)
    return (200, json.dumps(list(products)), headers)


class TestShopify:
    async def test_a_walk_to_a_short_page_reports_its_end(self, server) -> None:
        base, recorder = server
        adapter = ShopifyAdapter(_client())
        adapter.PAGE_SIZE = 2
        recorder.plan_pages(
            "/products.json",
            shopify_page(shopify_product(1, "Zelda"), shopify_product(2, "Kirby")),
            shopify_page(shopify_product(3, "Metroid")),
        )
        result = await adapter.fetch(_store(base, AdapterKind.SHOPIFY), NullSink())
        assert isinstance(result, Ok)
        assert result.coverage is not None
        assert result.coverage.end_reached is True
        assert (result.coverage.pages_attempted, result.coverage.pages_completed) == (2, 2)
        assert result.coverage.raw_seen == 3
        assert result.coverage.claimed_total is None

    async def test_hitting_the_page_backstop_is_partial_not_ok(self, server) -> None:
        """The defect: a feed still returning full pages at MAX_PAGES was reported Ok."""
        base, recorder = server
        adapter = ShopifyAdapter(_client())
        adapter.PAGE_SIZE, adapter.MAX_PAGES = 1, 2
        recorder.plan_pages(
            "/products.json",
            shopify_page(shopify_product(1, "Zelda")),
            shopify_page(shopify_product(2, "Kirby")),
            shopify_page(shopify_product(3, "Metroid")),
        )
        result = await adapter.fetch(_store(base, AdapterKind.SHOPIFY), NullSink())
        assert isinstance(result, Partial)
        assert "backstop" in result.reason
        assert result.coverage is not None
        assert result.coverage.end_reached is False

    async def test_every_collection_must_end_for_the_walk_to_end(self, server) -> None:
        base, recorder = server
        adapter = ShopifyAdapter(_client())
        recorder.plan_pages("/collections/a/products.json", shopify_page(shopify_product(1, "Zelda")))
        recorder.plan("/collections/b/products.json", (500, "boom", {}))
        result = await adapter.fetch(_store(base, AdapterKind.SHOPIFY, collections=("a", "b")), NullSink())
        assert isinstance(result, Partial)
        assert result.coverage is not None
        assert result.coverage.end_reached is False
        assert result.coverage.pages_completed < result.coverage.pages_attempted

    async def test_seen_skus_include_products_the_classifier_dropped(self, server) -> None:
        base, recorder = server
        adapter = ShopifyAdapter(_client())
        recorder.plan_pages(
            "/products.json",
            shopify_page(
                shopify_product(1, "Zelda", sku="NSW-1"),
                shopify_product(2, "Pro Controller for Nintendo Switch", sku="ACC-2"),
            ),
        )
        result = await adapter.fetch(_store(base, AdapterKind.SHOPIFY), NullSink())
        assert isinstance(result, Ok)
        assert [item.sku for item in result.listings] == ["NSW-1"]
        assert result.coverage is not None
        assert {"NSW-1", "ACC-2"} <= result.coverage.seen_skus

    async def test_seen_skus_cover_a_sku_rewritten_to_the_product_id(self, server) -> None:
        """one_product_per_sku swaps a shared SKU for the product id; both must count as seen."""
        base, recorder = server
        adapter = ShopifyAdapter(_client())
        recorder.plan_pages(
            "/products.json",
            shopify_page(shopify_product(1, "Zelda", sku="DUP"), shopify_product(2, "Kirby", sku="DUP")),
        )
        result = await adapter.fetch(_store(base, AdapterKind.SHOPIFY), NullSink())
        assert isinstance(result, Ok)
        assert result.coverage is not None
        assert {item.sku for item in result.listings} <= result.coverage.seen_skus


class TestWoo:
    async def test_reports_the_stores_own_count_and_the_end(self, server) -> None:
        base, recorder = server
        recorder.plan_pages(V1, woo_page(woo_product(1, "Zelda"), woo_product(2, "Kirby"), total=2))
        result = await WooAdapter(_client()).fetch(_store(base, AdapterKind.WOOCOMMERCE), NullSink())
        assert isinstance(result, Ok)
        assert result.coverage is not None
        assert result.coverage.claimed_total == 2
        assert result.coverage.raw_seen == 2
        assert result.coverage.end_reached is True

    async def test_hitting_the_page_backstop_is_partial_not_ok(self, server) -> None:
        base, recorder = server
        adapter = WooAdapter(_client())
        adapter.PER_PAGE, adapter.MAX_PAGES = 1, 2
        recorder.plan_pages(
            V1,
            woo_page(woo_product(1, "Zelda")),
            woo_page(woo_product(2, "Kirby")),
            woo_page(woo_product(3, "X")),
        )
        result = await adapter.fetch(_store(base, AdapterKind.WOOCOMMERCE), NullSink())
        assert isinstance(result, Partial)
        assert "backstop" in result.reason
        assert result.coverage is not None
        assert result.coverage.end_reached is False

    async def test_a_skipped_failed_page_is_not_an_end(self, server) -> None:
        base, recorder = server
        adapter = WooAdapter(_client())
        adapter.PER_PAGE = 1
        recorder.plan_pages(
            V1,
            woo_page(woo_product(1, "Zelda"), total=3),
            (404, "gone", {}),
            woo_page(woo_product(3, "Kirby"), total=3),
        )
        result = await adapter.fetch(_store(base, AdapterKind.WOOCOMMERCE), NullSink())
        assert isinstance(result, Partial)
        assert result.coverage is not None
        assert result.coverage.end_reached is False

    async def test_seen_skus_include_products_the_classifier_dropped(self, server) -> None:
        base, recorder = server
        recorder.plan_pages(
            V1,
            woo_page(
                woo_product(1, "Zelda", sku="G1"), woo_product(2, "Nintendo Switch OLED Console", sku="H2")
            ),
        )
        result = await WooAdapter(_client()).fetch(_store(base, AdapterKind.WOOCOMMERCE), NullSink())
        assert isinstance(result, Ok)
        assert result.coverage is not None
        assert {"G1", "H2", "1", "2"} <= result.coverage.seen_skus


async def test_hobbyall_reports_no_coverage_it_cannot_prove(server) -> None:
    """One unpaginated response with no total: nothing shows it is the whole catalogue."""
    base, recorder = server
    body = {
        "success": True,
        "data": [{"id": 7, "name": "Zelda", "platform": "NSW", "category": "Games", "price": 999}],
    }
    recorder.plan("/api/products", (200, json.dumps(body), {"content-type": "application/json"}))
    result = await HobbyallAdapter(_client()).fetch(_store(base, AdapterKind.HOBBYALL), NullSink())
    assert isinstance(result, Ok)
    assert result.coverage is None


@pytest.mark.parametrize("cls", [ShopifyAdapter, WooAdapter])
def test_backstops_stay_generous(cls: type) -> None:
    """Tests shrink these per instance; the class values must stay what production relies on."""
    assert cls.MAX_PAGES == 100
