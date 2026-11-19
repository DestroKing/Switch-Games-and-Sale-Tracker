"""Deterministic rematching over the market.db listing history."""

from __future__ import annotations

import json
import sqlite3

import pytest

from switch_tracker.market import db as market_db
from switch_tracker.market.identity import rematch
from switch_tracker.market.models import MatchTier


@pytest.fixture
def market(tmp_path):
    return market_db.open_db(tmp_path / "market.db")

def seed(conn: sqlite3.Connection, storefront: str, sku: str, title: str, *, region: str = "IN", platform: str = "SWITCH") -> int:
    conn.execute("INSERT OR IGNORE INTO retailer (id, name, kind) VALUES (?, ?, 'INDEPENDENT')", (storefront,))
    conn.execute(
        "INSERT OR IGNORE INTO storefront (id, retailer_id, name, base_url, stock_signal) "
        "VALUES (?, ?, ?, 'https://example.test', 'REPORTED')",
        (storefront, storefront, storefront),
    )
    return int(conn.execute(
        "INSERT INTO listing (storefront_id, sku, url, title, platform, region, condition, first_seen, last_seen) "
        "VALUES (?, ?, 'https://example.test/p', ?, ?, ?, 'NEW', 't', 't') RETURNING id",
        (storefront, sku, title, platform, region),
    ).fetchone()[0])


def match(conn, listing_id):
    return conn.execute("SELECT * FROM listing_match WHERE listing_id=?", (listing_id,)).fetchone()


class TestRematch:
    def test_same_title_at_three_stores_is_one_release(self, market):
        ids = [
            seed(market, f"shop{i}", f"sku{i}", "The Legend of Zelda Tears of the Kingdom Nintendo Switch")
            for i in range(3)
        ]
        counts = rematch(market)
        assert counts[MatchTier.EXACT_KEY] == 3
        assert market.execute("SELECT COUNT(*) FROM game").fetchone()[0] == 1
        assert market.execute("SELECT COUNT(*) FROM release").fetchone()[0] == 1
        assert {match(market, lid)["release_id"] for lid in ids}.__len__() == 1

    def test_edition_region_and_format_are_separate_releases(self, market):
        ids = [
            seed(market, "shop1", "a", "A Game Nintendo Switch"),
            seed(market, "shop2", "b", "A Game Deluxe Edition Nintendo Switch"),
            seed(market, "shop3", "c", "A Game Nintendo Switch", region="JP"),
            seed(market, "shop4", "d", "A Game Game-Key Card Nintendo Switch"),
        ]
        rematch(market)
        releases = {match(market, lid)["release_id"] for lid in ids}
        assert len(releases) == 4

    def test_unknown_format_is_not_a_wildcard(self, market):
        plain = seed(market, "shop1", "a", "A Game Nintendo Switch")
        keycard = seed(market, "shop2", "b", "A Game Game-Key Card Nintendo Switch")
        rematch(market)
        assert match(market, plain)["release_id"] != match(market, keycard)["release_id"]

    def test_near_family_is_probable_not_counted(self, market):
        larger = [seed(market, f"shop{i}", f"l{i}", "Legend Zelda Tears Kingdom Nintendo Switch") for i in range(5)]
        smaller = [seed(market, f"small{i}", f"s{i}", "Zelda Tears Kingdom Nintendo Switch") for i in range(2)]
        rematch(market)
        assert all(match(market, lid)["tier"] == MatchTier.EXACT_KEY.value for lid in larger)
        assert all(match(market, lid)["tier"] == MatchTier.PROBABLE.value for lid in smaller)
        assert {match(market, lid)["release_id"] for lid in smaller} == {match(market, larger[0])["release_id"]}

    def test_bundle_is_unmatched_and_edition_conflict_ambiguous(self, market):
        bundle = seed(market, "shop1", "a", "A Game Bundle Nintendo Switch")
        conflict = seed(market, "shop2", "b", "A Game Deluxe Edition Gold Edition Nintendo Switch")
        rematch(market)
        assert match(market, bundle)["tier"] == MatchTier.UNMATCHED.value
        assert match(market, conflict)["tier"] == MatchTier.AMBIGUOUS.value

    def test_learned_ean_produces_exact_code_match(self, market):
        first = seed(market, "shop1", "a", "A Game Nintendo Switch EAN: 0045496590420")
        second = seed(market, "shop2", "b", "Different Store Name Nintendo Switch EAN: 0045496590420")
        rematch(market)
        assert match(market, first)["tier"] == MatchTier.EXACT_KEY.value
        assert match(market, second)["tier"] == MatchTier.EXACT_CODE.value

    def test_code_collision_is_ambiguous(self, market):
        first = seed(market, "shop1", "a", "A Game Nintendo Switch EAN: 0045496590420")
        second = seed(market, "shop2", "b", "B Game Nintendo Switch EAN: 0045496590420")
        rematch(market)
        assert match(market, first)["tier"] == MatchTier.EXACT_KEY.value
        assert match(market, second)["tier"] == MatchTier.AMBIGUOUS.value

    def test_confirmed_match_survives_title_change(self, market):
        lid = seed(market, "shop1", "a", "A Game Nintendo Switch")
        rematch(market)
        release_id = match(market, lid)["release_id"]
        market.execute(
            "UPDATE listing_match SET tier='CONFIRMED', reasons='[\"confirmed by review\"]' WHERE listing_id=?",
            (lid,),
        )
        market.execute("UPDATE listing SET title='A Completely Different Name Nintendo Switch' WHERE id=?", (lid,))
        rematch(market)
        assert match(market, lid)["release_id"] == release_id
        assert match(market, lid)["tier"] == MatchTier.CONFIRMED.value

    def test_rejection_is_not_reproposed(self, market):
        lid = seed(market, "shop1", "a", "A Game Nintendo Switch")
        rematch(market)
        release_id = match(market, lid)["release_id"]
        market.execute(
            "INSERT INTO match_rejection (listing_id, release_id, at) VALUES (?, ?, 't')",
            (lid, release_id),
        )
        rematch(market)
        assert match(market, lid)["tier"] == MatchTier.UNMATCHED.value
        assert match(market, lid)["release_id"] is None

    def test_alias_redirects_new_matches(self, market):
        first = seed(market, "shop1", "a", "A Game Nintendo Switch")
        rematch(market)
        source = match(market, first)["release_id"]
        market.execute(
            "INSERT INTO game (title, key) VALUES ('A Game target', 'a game target')"
        )
        game_id = market.execute("SELECT id FROM game WHERE key='a game target'").fetchone()[0]
        target = market.execute(
            "INSERT INTO release (game_id, platform, edition, region, format, created_at) "
            "VALUES (?, 'SWITCH', 'STANDARD', 'IN', 'UNKNOWN', 't') RETURNING id",
            (game_id,),
        ).fetchone()[0]
        market.execute("INSERT INTO release_alias (release_id, target_id, at) VALUES (?, ?, 't')", (source, target))
        second = seed(market, "shop2", "b", "A Game Nintendo Switch")
        rematch(market)
        assert match(market, second)["release_id"] == target
        assert "merged by review" in " ".join(json.loads(match(market, second)["reasons"]))

    def test_idempotent_rematch_preserves_decided_at(self, market):
        lid = seed(market, "shop1", "a", "A Game Nintendo Switch")
        rematch(market)
        decided = match(market, lid)["decided_at"]
        rematch(market)
        assert match(market, lid)["decided_at"] == decided

    def test_every_match_has_nonempty_reasons(self, market):
        seed(market, "shop1", "a", "A Game Nintendo Switch")
        seed(market, "shop2", "b", "A Game Bundle Nintendo Switch")
        rematch(market)
        for row in market.execute("SELECT reasons FROM listing_match"):
            assert json.loads(row[0])
