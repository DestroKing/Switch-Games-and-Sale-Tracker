"""Phase 1: price adapters feed observations, never unsupported rarity claims."""
from __future__ import annotations

from dataclasses import replace

import pytest

from switch_tracker.core import db, market
from switch_tracker.core.models import (
    AdapterKind, Condition, Platform, RawListing, Region, StoreConfig,
)
from switch_tracker.services.market_ingest import record_result, scope_for


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "phase1.db")
    db.ensure_schema(connection)
    connection.execute(
        "INSERT INTO store (id,name,base_url,kind,currency,tier,enabled) "
        "VALUES ('shop','Shop','https://shop.test','SHOPIFY','INR',2,1)"
    )
    connection.execute("INSERT INTO run (started_at) VALUES ('2026-01-01')")
    yield connection
    connection.close()


def store(**kwargs):
    base = dict(
        id="shop", name="Shop", base_url="https://shop.test",
        kind=AdapterKind.SHOPIFY, currency="INR", tier=2, enabled=True,
    )
    base.update(kwargs)
    return StoreConfig(**base)


def listing(sku="a", **kwargs):
    base = dict(
        store_id="shop", sku=sku, url=f"https://shop.test/{sku}",
        title="Example Deluxe Nintendo Switch", native_currency="INR",
        native_price=3999.0, in_stock=True, platform=Platform.SWITCH,
        region=Region.IN, condition=Condition.NEW,
    )
    base.update(kwargs)
    return RawListing(**base)


def test_success_imports_stock_without_inventing_release_identity(conn):
    scan_id = record_result(
        conn, store=store(), run_id=1, listings=[listing()], result="ok",
    )
    scan = conn.execute("SELECT * FROM market_scan WHERE id=?", (scan_id,)).fetchone()
    assert scan["coverage_status"] == "PARTIAL"
    assert scan["run_id"] == 1
    item = conn.execute("SELECT * FROM market_retailer_item").fetchone()
    assert item["product_id"] is None
    assert item["sku"] == "a"
    observed = conn.execute("SELECT * FROM market_item_observation").fetchone()
    assert (observed["state"], observed["price"], observed["currency"]) == (
        "IN_STOCK", 3999.0, "INR",
    )
    assert market.overview(conn)["products"] == 0


def test_partial_and_failed_scans_cannot_claim_absence(conn):
    record_result(conn, store=store(), run_id=1, listings=[listing()], result="ok")
    record_result(conn, store=store(), run_id=1, listings=[], result="partial")
    failed = record_result(conn, store=store(), run_id=1, listings=[], result="failed")
    assert market.reconcile_complete_scan(conn, failed) == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM market_item_observation WHERE state='NOT_LISTED'"
    ).fetchone()[0] == 0


def test_repeated_sku_updates_existing_item_and_appends_history(conn):
    record_result(conn, store=store(), run_id=1, listings=[listing()], result="ok")
    record_result(
        conn, store=store(), run_id=1,
        listings=[listing("a", native_price=2999, in_stock=False)], result="ok",
    )
    assert conn.execute("SELECT COUNT(*) FROM market_retailer_item").fetchone()[0] == 1
    assert [
        row[0] for row in conn.execute("SELECT state FROM market_item_observation ORDER BY id")
    ] == ["IN_STOCK", "OUT_OF_STOCK"]


def test_invalid_url_and_duplicate_sku_are_ignored(conn):
    record_result(
        conn, store=store(), run_id=1,
        listings=[
            listing(), listing(),
            listing("bad", url="javascript:alert(1)"),
            listing("other", store_id="different"),
        ],
        result="ok",
    )
    assert conn.execute("SELECT COUNT(*) FROM market_retailer_item").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM market_item_observation").fetchone()[0] == 1


def test_configured_scope_changes_with_collection_and_is_not_complete(conn):
    first = store(collections=("switch",))
    second = replace(first, collections=("switch2",))
    assert scope_for(first)[0] != scope_for(second)[0]
    assert scope_for(first)[1] is market.ScopeType.CONFIGURED_COLLECTION
    assert scope_for(store())[1] is market.ScopeType.RETAILER_CATALOGUE


def test_import_rollback_keeps_earlier_observations(conn):
    record_result(conn, store=store(), run_id=1, listings=[listing()], result="ok")
    with pytest.raises(ValueError):
        record_result(
            conn, store=store(), run_id=1,
            listings=[listing("new", native_price=-5)], result="ok",
        )
    assert conn.execute("SELECT COUNT(*) FROM market_scan").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM market_retailer_item").fetchone()[0] == 1
