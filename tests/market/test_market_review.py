"""Manual review operations are validated, audited and followed by a rematch."""

from __future__ import annotations

import sqlite3

import pytest

from switch_tracker.market import db as market_db
from switch_tracker.market.identity import rematch
from switch_tracker.market.models import Format
from switch_tracker.market.review import ReviewError, confirm, merge, reject, reset, split


@pytest.fixture
def market(tmp_path):
    return market_db.open_db(tmp_path / "market.db")

def seed(conn: sqlite3.Connection, shop: str, sku: str, title: str, platform: str = "SWITCH") -> int:
    conn.execute("INSERT OR IGNORE INTO retailer (id, name, kind) VALUES (?, ?, 'INDEPENDENT')", (shop,))
    conn.execute(
        "INSERT OR IGNORE INTO storefront (id, retailer_id, name, base_url, stock_signal) "
        "VALUES (?, ?, ?, 'https://example.test', 'REPORTED')", (shop, shop, shop)
    )
    return conn.execute(
        "INSERT INTO listing (storefront_id, sku, url, title, platform, region, condition, first_seen, last_seen) "
        "VALUES (?, ?, 'https://example.test/p', ?, ?, 'IN', 'NEW', 't', 't') RETURNING id",
        (shop, sku, title, platform),
    ).fetchone()[0]


def release_for(conn, listing_id: int) -> int:
    return conn.execute("SELECT release_id FROM listing_match WHERE listing_id=?", (listing_id,)).fetchone()[0]


class TestReview:
    def test_confirm_writes_match_verification_and_audit(self, market):
        lid = seed(market, "s1", "a", "A Game Nintendo Switch")
        rematch(market)
        rid = release_for(market, lid)
        confirm(market, lid, rid, "checked box art")
        assert market.execute("SELECT tier FROM listing_match WHERE listing_id=?", (lid,)).fetchone()[0] == "CONFIRMED"
        assert market.execute("SELECT verified FROM release WHERE id=?", (rid,)).fetchone()[0] == 1
        audit = market.execute("SELECT action, note FROM audit_log").fetchone()
        assert tuple(audit) == ("confirm", "checked box art")

    def test_reject_records_pair_and_rematches(self, market):
        lid = seed(market, "s1", "a", "A Game Nintendo Switch")
        rematch(market)
        rid = release_for(market, lid)
        reject(market, lid, rid)
        assert market.execute("SELECT COUNT(*) FROM match_rejection WHERE listing_id=?", (lid,)).fetchone()[0] == 1
        assert market.execute("SELECT action FROM audit_log").fetchone()[0] == "reject"

    def test_reset_only_resets_confirmed_match(self, market):
        lid = seed(market, "s1", "a", "A Game Nintendo Switch")
        rematch(market)
        rid = release_for(market, lid)
        confirm(market, lid, rid)
        reset(market, lid)
        assert market.execute("SELECT tier FROM listing_match WHERE listing_id=?", (lid,)).fetchone()[0] == "EXACT_KEY"
        assert market.execute("SELECT action FROM audit_log ORDER BY id DESC").fetchone()[0] == "reset"

    def test_split_creates_verified_release_and_confirms_selected_listings(self, market):
        a = seed(market, "s1", "a", "A Game Nintendo Switch")
        b = seed(market, "s2", "b", "A Game Nintendo Switch")
        rematch(market)
        rid = split(market, [a, b], edition="DELUXE", region="IN", format=Format.FULL_GAME_CARD)
        assert market.execute("SELECT verified FROM release WHERE id=?", (rid,)).fetchone()[0] == 1
        assert all(row[0] == "CONFIRMED" for row in market.execute(
            "SELECT tier FROM listing_match WHERE listing_id IN (?, ?)", (a, b)
        ))
        assert market.execute("SELECT action FROM audit_log").fetchone()[0] == "split"

    def test_split_can_create_a_new_game_title(self, market):
        lid = seed(market, "s1", "a", "A Game Nintendo Switch")
        rematch(market)
        rid = split(market, [lid], edition="STANDARD", region="IN", format=Format.UNKNOWN, title="A Different Game")
        game_title = market.execute(
            "SELECT g.title FROM release r JOIN game g ON g.id=r.game_id WHERE r.id=?", (rid,)
        ).fetchone()[0]
        assert game_title == "A Different Game"

    def test_merge_aliases_repoints_confirmed_matches_and_moves_evidence(self, market):
        a = seed(market, "s1", "a", "A Game Nintendo Switch")
        b = seed(market, "s2", "b", "B Game Nintendo Switch")
        rematch(market)
        source, target = release_for(market, a), release_for(market, b)
        confirm(market, a, source)
        market.execute(
            "INSERT INTO evidence (release_id, claim, kind, reliability, source_url, observed_at, added_at) "
            "VALUES (?, 'OUT_OF_PRINT', 'OTHER', 'COMMUNITY', 'https://example.test', 't', 't')",
            (source,),
        )
        final = merge(market, source, target)
        assert final == target
        assert market.execute("SELECT target_id FROM release_alias WHERE release_id=?", (source,)).fetchone()[0] == target
        assert market.execute("SELECT release_id FROM listing_match WHERE listing_id=?", (a,)).fetchone()[0] == target
        assert market.execute("SELECT release_id FROM evidence").fetchone()[0] == target
        assert market.execute("SELECT action FROM audit_log ORDER BY id DESC").fetchone()[0] == "merge"

    @pytest.mark.parametrize("operation", ["confirm", "reject", "reset"])
    def test_unknown_listing_is_rejected(self, market, operation):
        with pytest.raises(ReviewError):
            if operation == "confirm":
                confirm(market, 999, 999)
            elif operation == "reject":
                reject(market, 999, 999)
            else:
                reset(market, 999)

    def test_split_rejects_cross_platform_selection(self, market):
        a = seed(market, "s1", "a", "A Game Nintendo Switch", "SWITCH")
        b = seed(market, "s2", "b", "A Game Nintendo Switch 2", "SWITCH2")
        with pytest.raises(ReviewError, match="same platform"):
            split(market, [a, b], edition="STANDARD", region="IN", format=Format.UNKNOWN)

    def test_merge_rejects_self_and_cycle(self, market):
        a = seed(market, "s1", "a", "A Game Nintendo Switch")
        b = seed(market, "s2", "b", "B Game Nintendo Switch")
        rematch(market)
        source, target = release_for(market, a), release_for(market, b)
        with pytest.raises(ReviewError, match="itself"):
            merge(market, source, source)
        merge(market, source, target)
        with pytest.raises(ReviewError, match="cycle"):
            merge(market, target, source)

    def test_failed_audit_write_rolls_back_review_operation(self, market):
        lid = seed(market, "s1", "a", "A Game Nintendo Switch")
        rematch(market)
        rid = release_for(market, lid)
        market.execute(
            "CREATE TRIGGER fail_audit BEFORE INSERT ON audit_log "
            "BEGIN SELECT RAISE(ABORT, 'audit failed'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            confirm(market, lid, rid)
        assert market.execute("SELECT tier FROM listing_match WHERE listing_id=?", (lid,)).fetchone()[0] == "EXACT_KEY"
        assert market.execute("SELECT verified FROM release WHERE id=?", (rid,)).fetchone()[0] == 0
