from __future__ import annotations

import pytest

from switch_tracker.core import db, market


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "market.db")
    db.ensure_schema(connection)
    connection.execute(
        "INSERT INTO store (id,name,base_url,kind,currency,tier,enabled) "
        "VALUES ('shop','Shop','https://shop.test','WOOCOMMERCE','INR',2,1)"
    )
    yield connection
    connection.close()


class TestMarketSchema:
    def test_market_tables_are_additive_and_idempotent(self, conn):
        expected = {
            "market_catalogue", "market_retailer_group", "market_retailer_group_member",
            "market_retailer_item", "market_scan", "market_item_observation", "market_evidence",
        }
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert expected <= tables
        db.ensure_schema(conn)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def test_existing_price_history_tables_remain(self, conn):
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"store", "game", "listing", "price_point", "run", "run_store"} <= names


class TestPhysicalReleaseIdentity:
    def test_exact_release_identity_is_idempotent(self, conn):
        first = market.create_product(conn, title="Zelda: Example", platform="SWITCH")
        second = market.create_product(conn, title=" zelda:  example ", platform="SWITCH")
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM market_catalogue").fetchone()[0] == 1

    @pytest.mark.parametrize(
        ("changes",),
        [
            ({"platform": "SWITCH2"},),
            ({"edition": "DELUXE"},),
            ({"region": "JP"},),
            ({"physical_format": market.MarketFormat.GAME_KEY_CARD},),
            ({"physical_format": market.MarketFormat.CODE_IN_BOX},),
        ],
    )
    def test_material_release_differences_create_distinct_products(self, conn, changes):
        base = market.create_product(conn, title="Example Game", platform="SWITCH")
        identity = {"title": "Example Game", "platform": "SWITCH"}
        identity.update(changes)
        different = market.create_product(conn, **identity)
        assert different != base

    def test_unknown_format_is_explicit_not_guessed(self, conn):
        product_id = market.create_product(conn, title="Mystery", platform="SWITCH")
        row = conn.execute(
            "SELECT physical_format FROM market_catalogue WHERE id=?", (product_id,)
        ).fetchone()
        assert row["physical_format"] == "UNKNOWN"

    def test_condition_is_not_part_of_product_identity(self, conn):
        product_id = market.create_product(conn, title="Example", platform="SWITCH")
        item = market.upsert_retailer_item(
            conn, store_id="shop", scope_key="switch-games", item_key="sku-a",
            url="https://shop.test/a", product_id=product_id,
        )
        assert item > 0
        assert conn.execute("SELECT COUNT(*) FROM market_catalogue").fetchone()[0] == 1

    def test_rejects_unknown_platform_and_empty_title(self, conn):
        with pytest.raises(ValueError):
            market.create_product(conn, title="Example", platform="UNKNOWN")
        with pytest.raises(ValueError):
            market.create_product(conn, title="  ", platform="SWITCH")


class TestRetailerItemsAndCoverage:
    def _item(self, conn):
        product = market.create_product(conn, title="Example", platform="SWITCH")
        return market.upsert_retailer_item(
            conn, store_id="shop", scope_key="category-a", item_key="stable-url-1",
            url="https://shop.test/p/1", product_id=product,
        )

    def test_unpriced_item_is_discoverable_without_a_price_point(self, conn):
        item_id = self._item(conn)
        assert item_id > 0
        assert conn.execute("SELECT COUNT(*) FROM price_point").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM market_retailer_item").fetchone()[0] == 1

    @pytest.mark.parametrize(
        "status", [market.CoverageStatus.PARTIAL, market.CoverageStatus.FAILED, market.CoverageStatus.UNKNOWN]
    )
    def test_incomplete_scans_never_create_absence(self, conn, status):
        item_id = self._item(conn)
        scan_id = market.record_scan(
            conn, store_id="shop", scope_key="category-a",
            scope_type=market.ScopeType.PHYSICAL_GAME_CATEGORY, coverage_status=status,
        )
        assert market.reconcile_complete_scan(conn, scan_id) == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM market_item_observation WHERE retailer_item_id=?", (item_id,)
        ).fetchone()[0] == 0

    def test_complete_scan_records_absence_only_inside_its_scope(self, conn):
        item_id = self._item(conn)
        market.upsert_retailer_item(
            conn, store_id="shop", scope_key="category-b", item_key="other",
            url="https://shop.test/other",
        )
        scan_id = market.record_scan(
            conn, store_id="shop", scope_key="category-a",
            scope_type=market.ScopeType.PHYSICAL_GAME_CATEGORY,
            coverage_status=market.CoverageStatus.COMPLETE, pages_expected=2, pages_seen=2,
        )
        assert market.reconcile_complete_scan(conn, scan_id) == 1
        state = conn.execute(
            "SELECT state FROM market_item_observation WHERE scan_id=? AND retailer_item_id=?",
            (scan_id, item_id),
        ).fetchone()["state"]
        assert state == "NOT_LISTED"
        assert conn.execute(
            "SELECT COUNT(*) FROM market_item_observation WHERE scan_id=?", (scan_id,)
        ).fetchone()[0] == 1

    def test_complete_scan_cannot_claim_missing_pages(self, conn):
        with pytest.raises(ValueError):
            market.record_scan(
                conn, store_id="shop", scope_key="category-a",
                scope_type=market.ScopeType.PHYSICAL_GAME_CATEGORY,
                coverage_status=market.CoverageStatus.COMPLETE, pages_expected=3, pages_seen=2,
            )

    def test_search_result_scope_is_stored_as_search_scope_not_catalogue(self, conn):
        scan_id = market.record_scan(
            conn, store_id="shop", scope_key="query-zelda",
            scope_type=market.ScopeType.SEARCH_RESULTS,
            coverage_status=market.CoverageStatus.COMPLETE, pages_expected=1, pages_seen=1,
        )
        row = conn.execute("SELECT scope_type FROM market_scan WHERE id=?", (scan_id,)).fetchone()
        assert row["scope_type"] == "SEARCH_RESULTS"

    def test_not_listed_cannot_be_manually_recorded(self, conn):
        item_id = self._item(conn)
        scan_id = market.record_scan(
            conn, store_id="shop", scope_key="category-a",
            scope_type=market.ScopeType.PHYSICAL_GAME_CATEGORY,
            coverage_status=market.CoverageStatus.PARTIAL,
        )
        with pytest.raises(ValueError):
            market.record_observation(
                conn, scan_id=scan_id, retailer_item_id=item_id, state="NOT_LISTED"
            )

    def test_stock_observations_capture_price_and_condition_is_not_identity(self, conn):
        item_id = self._item(conn)
        scan_id = market.record_scan(
            conn, store_id="shop", scope_key="category-a",
            scope_type=market.ScopeType.PHYSICAL_GAME_CATEGORY,
            coverage_status=market.CoverageStatus.COMPLETE, pages_expected=1, pages_seen=1,
        )
        market.record_observation(
            conn, scan_id=scan_id, retailer_item_id=item_id,
            state="IN_STOCK", price=2499, currency="INR",
        )
        row = conn.execute(
            "SELECT state,price,currency FROM market_item_observation WHERE scan_id=?", (scan_id,)
        ).fetchone()
        assert tuple(row) == ("IN_STOCK", 2499, "INR")


class TestEvidenceAndRetailerGroups:
    def test_evidence_requires_http_source_and_is_dated(self, conn):
        product = market.create_product(conn, title="Example", platform="SWITCH")
        with pytest.raises(ValueError):
            market.add_evidence(
                conn, product_id=product, evidence_type="OUT_OF_PRINT", source_url="javascript:alert(1)"
            )
        evidence_id = market.add_evidence(
            conn, product_id=product, evidence_type="REPRINT",
            source_url="https://publisher.test/reprint", source_name="Publisher",
            verification="VERIFIED", confidence="HIGH",
        )
        row = conn.execute(
            "SELECT verification,confidence,checked_at FROM market_evidence WHERE id=?", (evidence_id,)
        ).fetchone()
        assert row["verification"] == "VERIFIED"
        assert row["confidence"] == "HIGH"
        assert row["checked_at"]

    def test_unknown_retailer_relationship_is_not_counted_as_independent(self, conn):
        group_id = market.set_retailer_group(
            conn, store_id="shop", group_key="shop-unknown", display_name="Shop"
        )
        row = conn.execute(
            """SELECT g.relationship FROM market_retailer_group g
               JOIN market_retailer_group_member m ON m.group_id=g.id WHERE m.store_id='shop'"""
        ).fetchone()
        assert group_id > 0
        assert row["relationship"] == "UNVERIFIED"

    def test_market_overview_and_catalogue_are_readable(self, conn):
        product = market.create_product(conn, title="Zelda Example", platform="SWITCH")
        result = market.catalogue(conn, q="Zelda")
        assert result["total"] == 1
        assert result["rows"][0]["id"] == product
        assert market.overview(conn)["products"] == 1
        assert market.product_detail(conn, product)["product"]["title"] == "Zelda Example"
        assert market.product_detail(conn, 999) is None
