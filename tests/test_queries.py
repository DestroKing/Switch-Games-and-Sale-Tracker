"""Dashboard reads.

Filtering, sorting and aggregation happen in SQL. The tempting shortcut is to
ship 200 rows and let the page sort them, but then "cheapest first" means
cheapest OF THOSE 200 -- a wrong answer that looks exactly like a right one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db
from switch_tracker.web import queries


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "q.db")
    db.ensure_schema(c)
    c.execute("INSERT INTO store VALUES ('nistore','NI Store','https://ni.in','WOOCOMMERCE','INR',2,1)")
    c.execute("INSERT INTO store VALUES ('amazon','Amazon','https://a.in','BROWSER','INR',1,1)")
    return c


def add_listing(
    conn: sqlite3.Connection,
    listing_id: int,
    store: str,
    title: str,
    *,
    platform: str = "SWITCH",
    region: str = "IN",
    condition: str = "NEW",
) -> None:
    conn.execute(
        "INSERT INTO listing (id, store_id, sku, url, raw_title, platform, region, condition, "
        "first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,'t','t')",
        (listing_id, store, f"sku{listing_id}", f"https://x/{listing_id}", title,
         platform, region, condition),
    )


def add_price(
    conn: sqlite3.Connection,
    listing_id: int,
    run_id: int,
    inr: float,
    *,
    at: str,
    in_stock: int = 1,
    currency: str = "INR",
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO run (id, started_at, finished_at) VALUES (?, ?, ?)",
        (run_id, at, at),
    )
    conn.execute(
        "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, native_price, "
        "inr_price, in_stock) VALUES (?,?,?,?,?,?,?)",
        (listing_id, run_id, at, currency, inr, inr, in_stock),
    )


class TestSummary:
    def test_counts_what_has_been_collected(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01")
        result = queries.summary(conn)
        assert result["listings"] == 1
        assert result["stores"] == 1
        assert result["points"] == 1

    def test_counts_listings_not_yet_matched_to_a_canonical_title(self, conn) -> None:
        """game_id is nullable and currently always NULL -- the matcher is unbuilt."""
        add_listing(conn, 1, "nistore", "Zelda")
        assert queries.summary(conn)["unmatched"] == 1


class TestHealth:
    def test_reports_every_store_from_the_latest_run(self, conn) -> None:
        conn.execute("INSERT INTO run (id, started_at) VALUES (1, '2026-08-01')")
        conn.execute("INSERT INTO run_store VALUES (1,'nistore','ok',101,900,NULL)")
        conn.execute("INSERT INTO run_store VALUES (1,'amazon','failed',0,120,'Cloudflare blocked us')")
        result = queries.health(conn)
        assert result["run"]["id"] == 1
        assert {s["store_id"] for s in result["stores"]} == {"nistore", "amazon"}

    def test_carries_the_failure_reason(self, conn) -> None:
        """A silent zero is the failure that quietly rots a tracker."""
        conn.execute("INSERT INTO run (id, started_at) VALUES (1, '2026-08-01')")
        conn.execute("INSERT INTO run_store VALUES (1,'amazon','failed',0,120,'Cloudflare blocked us')")
        amazon = queries.health(conn)["stores"][0]
        assert amazon["detail"] == "Cloudflare blocked us"

    def test_is_empty_before_the_first_run(self, conn) -> None:
        result = queries.health(conn)
        assert result["run"] is None
        assert result["stores"] == []


class TestListings:
    @pytest.fixture(autouse=True)
    def catalogue(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda Tears of the Kingdom")
        add_listing(conn, 2, "nistore", "Mario Kart World", platform="SWITCH2")
        add_listing(conn, 3, "amazon", "Metroid Dread", condition="PRE_OWNED", region="JP")
        add_price(conn, 1, 1, 4299, at="2026-08-01")
        add_price(conn, 2, 1, 4999, at="2026-08-01")
        add_price(conn, 3, 1, 1999, at="2026-08-01", in_stock=0)

    def test_sorts_over_the_whole_table_not_the_returned_page(self, conn) -> None:
        """The bug this design prevents.

        Asking for the single cheapest must return the cheapest of ALL rows,
        not the cheapest of whichever page was fetched first.
        """
        result = queries.listings(conn, queries.ListingQuery(sort="price", direction="asc", limit=1))
        assert result["rows"][0]["raw_title"] == "Metroid Dread"
        assert result["total"] == 3

    def test_sorts_descending(self, conn) -> None:
        result = queries.listings(conn, queries.ListingQuery(sort="price", direction="desc", limit=1))
        assert result["rows"][0]["raw_title"] == "Mario Kart World"

    def test_searches_titles(self, conn) -> None:
        result = queries.listings(conn, queries.ListingQuery(q="zelda"))
        assert [r["raw_title"] for r in result["rows"]] == ["Zelda Tears of the Kingdom"]

    def test_a_search_term_cannot_inject_sql_wildcards(self, conn) -> None:
        """'%' would otherwise match everything and look like a broken filter."""
        result = queries.listings(conn, queries.ListingQuery(q="%"))
        assert result["total"] == 0

    def test_filters_by_platform(self, conn) -> None:
        result = queries.listings(conn, queries.ListingQuery(platform="SWITCH2"))
        assert [r["raw_title"] for r in result["rows"]] == ["Mario Kart World"]

    def test_filters_by_store(self, conn) -> None:
        assert queries.listings(conn, queries.ListingQuery(store="amazon"))["total"] == 1

    def test_filters_by_condition(self, conn) -> None:
        result = queries.listings(conn, queries.ListingQuery(condition="PRE_OWNED"))
        assert [r["raw_title"] for r in result["rows"]] == ["Metroid Dread"]

    def test_filters_by_region(self, conn) -> None:
        assert queries.listings(conn, queries.ListingQuery(region="JP"))["total"] == 1

    def test_filters_out_of_stock(self, conn) -> None:
        result = queries.listings(conn, queries.ListingQuery(in_stock_only=True))
        assert result["total"] == 2

    def test_paginates(self, conn) -> None:
        first = queries.listings(conn, queries.ListingQuery(sort="price", limit=2, offset=0))
        second = queries.listings(conn, queries.ListingQuery(sort="price", limit=2, offset=2))
        assert len(first["rows"]) == 2
        assert len(second["rows"]) == 1
        assert first["total"] == second["total"] == 3

    def test_only_the_latest_price_per_listing_is_shown(self, conn) -> None:
        add_price(conn, 1, 2, 3299, at="2026-08-15")
        result = queries.listings(conn, queries.ListingQuery(q="zelda"))
        assert result["rows"][0]["inr_price"] == 3299

    def test_an_unknown_sort_key_cannot_reach_the_sql(self, conn) -> None:
        """Sort columns are whitelisted; they land in SQL text, not a parameter."""
        result = queries.listings(conn, queries.ListingQuery(sort="; DROP TABLE listing"))
        assert result["total"] == 3
        assert conn.execute("SELECT COUNT(*) c FROM listing").fetchone()["c"] == 3


class TestMovers:
    def test_compares_against_the_previous_observation(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01")
        add_price(conn, 1, 2, 3599, at="2026-08-15")
        movers = queries.movers(conn)
        assert len(movers) == 1
        assert movers[0]["prev_price"] == 4499
        assert movers[0]["now_price"] == 3599
        assert movers[0]["pct"] < 0

    def test_ignores_a_listing_whose_price_did_not_move(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01")
        add_price(conn, 1, 2, 4499, at="2026-08-15")
        assert queries.movers(conn) == []

    def test_says_nothing_before_a_second_run(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01")
        assert queries.movers(conn) == []

    def test_flags_a_synchronised_move_as_the_currency_not_a_sale(self, conn) -> None:
        """Many listings in one currency moving the same ratio on the same day
        is the rupee moving, not the shops changing their minds."""
        for i in range(1, 11):
            add_listing(conn, i, "nistore", f"Import Game {i}")
            add_price(conn, i, 1, 1000.0, at="2026-08-01", currency="USD")
            add_price(conn, i, 2, 1050.0, at="2026-08-15", currency="USD")
        movers = queries.movers(conn)
        assert all(m["fx_suspect"] for m in movers)

    def test_does_not_flag_a_rupee_price_move(self, conn) -> None:
        """A rupee price cannot move because of the rupee."""
        for i in range(1, 11):
            add_listing(conn, i, "nistore", f"Game {i}")
            add_price(conn, i, 1, 1000.0, at="2026-08-01", currency="INR")
            add_price(conn, i, 2, 1050.0, at="2026-08-15", currency="INR")
        assert not any(m["fx_suspect"] for m in queries.movers(conn))

    def test_does_not_flag_an_isolated_drop(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01", currency="USD")
        add_price(conn, 1, 2, 2999, at="2026-08-15", currency="USD")
        assert not queries.movers(conn)[0]["fx_suspect"]


class TestFacets:
    def test_populates_the_filters_from_what_is_actually_present(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_listing(conn, 2, "amazon", "Mario", platform="SWITCH2", region="JP")
        facets = queries.facets(conn)
        assert {s["id"] for s in facets["stores"]} == {"nistore", "amazon"}
        assert {p["platform"] for p in facets["platforms"]} == {"SWITCH", "SWITCH2"}
        assert {r["region"] for r in facets["regions"]} == {"IN", "JP"}


class TestHistory:
    def test_returns_a_listings_price_series_oldest_first(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01")
        add_price(conn, 1, 2, 3599, at="2026-08-15")
        series = queries.history(conn, 1)
        assert [p["inr_price"] for p in series] == [4499, 3599]
