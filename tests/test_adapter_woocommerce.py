"""The WooCommerce Store API: public, unauthenticated, and the only adapter
with an authoritative "did we get everything" signal."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from switch_tracker.adapters.base import NullSink
from switch_tracker.adapters.woocommerce import WooAdapter
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, Condition, Failed, Ok, Partial, Platform, StoreConfig

V1 = "/wp-json/wc/store/v1/products"
LEGACY = "/wp-json/wc/store/products"
TERMS = "/wp-json/wp/v2/product_cat"


def product(pid: int, name: str, minor: int = 449900, unit: int = 2, cats: list[str] | None = None):
    return {
        "id": pid,
        "name": name,
        "permalink": f"https://shop.in/product/{pid}",
        "is_in_stock": True,
        "categories": [{"name": c} for c in (cats or [])],
        "images": [{"src": f"https://cdn/{pid}.jpg"}],
        "prices": {"price": str(minor), "currency_code": "INR", "currency_minor_unit": unit},
    }


def page(*products, total: int | None = None):
    headers = {"content-type": "application/json"}
    if total is not None:
        headers["X-WP-Total"] = str(total)
    return (200, json.dumps(list(products)), headers)


@pytest.fixture
def adapter() -> WooAdapter:
    return WooAdapter(PoliteClient(min_gap_s=0.0, timeout_s=5.0, backoff_base_s=0.01))


def store_at(base: str, **kw) -> StoreConfig:
    base_cfg = StoreConfig(
        id="woo",
        name="Woo",
        base_url=base,
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
    )
    return replace(base_cfg, **kw)


class TestPathDiscovery:
    async def test_uses_the_v1_path_when_available(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(V1, page(product(1, "Mario Kart World")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)

    async def test_falls_back_to_the_legacy_path_for_older_installs(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(V1, (404, "not here", {}))
        recorder.plan(LEGACY, page(product(1, "Mario Kart World")))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert any(h.startswith(LEGACY) for h in recorder.hits)

    async def test_fails_readably_when_neither_path_answers(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(V1, (404, "no", {}))
        recorder.plan(LEGACY, (404, "no", {}))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Failed)
        assert "Store API" in result.reason


class TestCategoryResolution:
    async def test_full_path_disambiguates_duplicate_category_slugs(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(TERMS, (200, json.dumps([
            {"id": 11, "slug": "nintendo-games", "parent": 90},
            {"id": 42, "slug": "nintendo-games", "parent": 80},
        ]), {"content-type": "application/json"}))
        recorder.plan(f"{TERMS}/90", (200, json.dumps({"slug": "nintendo-accessories", "parent": 0}), {}))
        recorder.plan(f"{TERMS}/80", (200, json.dumps({"slug": "gaming-tittle", "parent": 0}), {}))
        recorder.plan(V1, page(product(1, "Zelda Nintendo Switch Game")))
        result = await adapter.fetch(
            store_at(base, collections=("gaming-tittle/nintendo-games",)), NullSink()
        )
        assert isinstance(result, Ok)
        assert any("category=42" in hit for hit in recorder.hits)
        assert not any("category=11" in hit for hit in recorder.hits)

    async def test_unresolved_full_path_does_not_collect_unrelated_products(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(TERMS, (200, "[]", {"content-type": "application/json"}))
        recorder.plan(V1, page(product(1, "Zelda Nintendo Switch Game")))
        result = await adapter.fetch(
            store_at(base, collections=("gaming-tittle/nintendo-games",)), NullSink()
        )
        assert isinstance(result, Failed)
        assert not any("&page=1" in hit for hit in recorder.hits)

    async def test_resolves_a_slug_to_its_numeric_term_id(self, adapter, server) -> None:
        """Filtering by raw slug silently returns zero on some installs.

        One real store had the term in product_cat with 213 products and
        ?category=<slug> still matched nothing. Resolving to the numeric id
        first is the version that works everywhere.
        """
        base, recorder = server
        recorder.plan(TERMS, (200, json.dumps([{"id": 42}]), {"content-type": "application/json"}))
        recorder.plan(V1, page(product(1, "Zelda")))
        await adapter.fetch(store_at(base, collections=("nintendo-games",)), NullSink())
        assert any("category=42" in h for h in recorder.hits)

    async def test_falls_back_to_the_raw_slug_when_the_lookup_is_empty(self, adapter, server) -> None:
        """product_cat is not exposed on every install."""
        base, recorder = server
        recorder.plan(TERMS, (200, "[]", {"content-type": "application/json"}))
        recorder.plan(V1, page(product(1, "Zelda")))
        await adapter.fetch(store_at(base, collections=("nintendo-games",)), NullSink())
        assert any("category=nintendo-games" in h for h in recorder.hits)


class TestPrices:
    async def test_divides_by_the_currency_minor_unit(self, adapter, server) -> None:
        """The Store API quotes minor units with the exponent per response.

        Getting this wrong yields prices 100x out.
        """
        base, recorder = server
        recorder.plan(V1, page(product(1, "Zelda", minor=449900, unit=2)))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].native_price == 4499.0

    async def test_honours_a_non_default_minor_unit(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(V1, page(product(1, "Zelda", minor=4499, unit=0)))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].native_price == 4499.0

    async def test_takes_the_currency_from_the_response(self, adapter, server) -> None:
        base, recorder = server
        item = product(1, "Zelda")
        item["prices"]["currency_code"] = "USD"
        recorder.plan(V1, page(item))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].native_currency == "USD"


class TestClassificationContext:
    async def test_category_names_reach_the_condition_inference(self, adapter, server) -> None:
        """A store's own "Pre-Owned Games" category is the source of truth.

        This is why condition needs no per-store config.
        """
        base, recorder = server
        recorder.plan(V1, page(product(1, "Zelda", cats=["Pre-Owned Games"])))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Ok)
        assert result.listings[0].condition is Condition.PRE_OWNED


class TestCompleteness:
    async def test_x_wp_total_is_counted_once_per_query_not_once_per_page(
        self, adapter, server
    ) -> None:
        """The bug this port fixes.

        woocommerce.ts does `expectedTotal += total` INSIDE the page loop, so a
        213-item category spread over three pages accumulates 639 and reports
        "fetched 213 of 639 -- stopped early". A complete fetch was being
        labelled partial on every single run.
        """
        base, recorder = server
        first = [product(i, f"Game {i} Switch") for i in range(100)]
        second = [product(100 + i, f"Game {100 + i} Switch") for i in range(100)]
        third = [product(200 + i, f"Game {200 + i} Switch") for i in range(13)]
        recorder.plan_pages(
            V1, page(*first, total=213), page(*second, total=213), page(*third, total=213)
        )

        result = await adapter.fetch(store_at(base), NullSink())

        assert isinstance(result, Ok), f"expected Ok, got {result}"
        assert len(result.listings) == 213

    async def test_reports_partial_on_a_genuine_shortfall(self, adapter, server) -> None:
        base, recorder = server
        recorder.plan(V1, page(*(product(i, f"Game {i} Switch") for i in range(50)), total=500))
        result = await adapter.fetch(store_at(base), NullSink())
        assert isinstance(result, Partial)
        assert "500" in result.reason

    async def test_succeeds_when_the_store_sends_no_total(self, adapter, server) -> None:
        """Not every Woo version sends the header; its absence is not a fault."""
        base, recorder = server
        recorder.plan(V1, page(product(1, "Zelda")))
        assert isinstance(await adapter.fetch(store_at(base), NullSink()), Ok)


class TestFailures:
    async def test_a_reachable_api_with_no_switch_products_is_a_failure(
        self, adapter, server
    ) -> None:
        base, recorder = server
        recorder.plan(V1, page(product(1, "Canon EOS R5 Camera")))
        result = await adapter.fetch(store_at(base, platform_hint=None), NullSink())
        assert isinstance(result, Failed)
