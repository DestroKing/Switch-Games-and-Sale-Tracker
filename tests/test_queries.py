"""Dashboard reads.

Filtering, sorting and aggregation happen in SQL. The tempting shortcut is to
ship 200 rows and let the page sort them, but then "cheapest first" means
cheapest OF THOSE 200 -- a wrong answer that looks exactly like a right one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db, matcher
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
        (
            listing_id,
            store,
            f"sku{listing_id}",
            f"https://x/{listing_id}",
            title,
            platform,
            region,
            condition,
        ),
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


@pytest.fixture
def shelf(conn: sqlite3.Connection) -> sqlite3.Connection:
    """One game at three offers -- the cheapest OUT of stock -- plus a second game."""
    add_listing(conn, 1, "nistore", "Metroid Prime 4 Beyond")
    add_listing(conn, 2, "amazon", "Metroid Prime 4: Beyond - Nintendo Switch")
    add_listing(conn, 3, "amazon", "Metroid Prime 4 Beyond (Asia)", region="ASIA_EN")
    add_listing(conn, 4, "nistore", "Kirby Air Riders", platform="SWITCH2")
    add_price(conn, 1, 1, 4999, at="2026-01-01T00:00:00Z")
    add_price(conn, 2, 1, 4499, at="2026-01-01T00:00:00Z")
    add_price(conn, 3, 1, 3999, at="2026-01-01T00:00:00Z", in_stock=0)
    add_price(conn, 4, 1, 5999, at="2026-01-01T00:00:00Z")
    matcher.rematch(conn)
    return conn


class TestNoLongerListed:
    """A product the shop removed keeps its last price point forever; it must stop being buyable."""

    def later_amazon_run(self, conn, status: str) -> None:
        conn.execute("INSERT OR IGNORE INTO run (id, started_at) VALUES (2, '2026-01-02T00:00:00Z')")
        conn.execute("INSERT INTO run_store VALUES (2, 'amazon', ?, 0, 0, NULL)", (status,))

    def metroid(self, conn) -> dict:
        rows = queries.games(conn, queries.ListingQuery())["rows"]
        return next(r for r in rows if r["game"] == "metroid prime 4 beyond")

    def test_a_listing_missing_from_a_later_full_run_is_not_the_best_offer(self, shelf) -> None:
        """Amazon's ₹4,499 copy was absent from Amazon's next successful run: gone from the shop."""
        self.later_amazon_run(shelf, "ok")
        assert (self.metroid(shelf)["best_price"], self.metroid(shelf)["best_store"]) == (4999, "NI Store")
        listed = queries.listings(shelf, queries.ListingQuery(in_stock_only=True))["rows"]
        assert 2 not in [r["id"] for r in listed]

    @pytest.mark.parametrize("status", ["partial", "failed"])
    def test_a_partial_or_failed_run_proves_nothing(self, shelf, status: str) -> None:
        """A run that did not finish the catalogue may simply not have reached it."""
        self.later_amazon_run(shelf, status)
        assert self.metroid(shelf)["best_price"] == 4499


class TestGames:
    def test_one_row_per_game_across_stores_and_regions(self, shelf) -> None:
        result = queries.games(shelf, queries.ListingQuery())
        assert result["total"] == 2
        metroid = next(r for r in result["rows"] if r["game"] == "metroid prime 4 beyond")
        assert (metroid["offers"], metroid["stores"]) == (3, 2)

    def test_the_best_offer_is_the_cheapest_one_you_can_buy(self, shelf) -> None:
        """The ₹3,999 copy is out of stock, so ₹4,499 is the real best -- and its
        store and URL are reported with it, not the out-of-stock row's."""
        metroid = queries.games(shelf, queries.ListingQuery(q="metroid"))["rows"][0]
        assert (metroid["best_price"], metroid["best_store"], metroid["best_url"]) == (
            4499,
            "Amazon",
            "https://x/2",
        )

    def test_an_out_of_stock_only_game_still_shows_its_price(self, shelf) -> None:
        shelf.execute("UPDATE price_point SET in_stock = 0 WHERE listing_id = 4")
        kirby = queries.games(shelf, queries.ListingQuery(q="kirby"))["rows"][0]
        assert (kirby["best_price"], kirby["best_in_stock"]) == (5999, False)

    def test_takes_the_same_filters_as_listings(self, shelf) -> None:
        only_ni = queries.games(shelf, queries.ListingQuery(stores=("nistore",), q="metroid"))["rows"][0]
        assert (only_ni["best_price"], only_ni["offers"]) == (4999, 1)

    def test_out_of_stock_only_games_sort_last_in_both_price_directions(self, shelf) -> None:
        shelf.execute("UPDATE price_point SET in_stock = 0 WHERE listing_id = 4")  # Kirby: nothing in stock
        for direction in ("asc", "desc"):
            rows = queries.games(shelf, queries.ListingQuery(sort="price", direction=direction))["rows"]
            assert rows[-1]["game"] == "kirby air riders", direction

    def test_a_game_is_named_after_a_new_copy_not_the_cheapest(self, shelf) -> None:
        """The cheapest offer is often used; the row must not read "- Pre-Owned"."""
        add_listing(
            shelf, 7, "amazon", "Kirby Air Riders - Pre-Owned", platform="SWITCH2", condition="PRE_OWNED"
        )
        add_price(shelf, 7, 1, 2999, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        kirby = queries.games(shelf, queries.ListingQuery(q="kirby"))["rows"][0]
        assert (kirby["best_price"], kirby["title"]) == (2999, "Kirby Air Riders")

    def test_a_game_sold_only_used_is_still_named(self, shelf) -> None:
        add_listing(shelf, 8, "amazon", "Pikmin 1+2 (Pre-Owned)", condition="PRE_OWNED")
        add_price(shelf, 8, 1, 2499, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        assert (
            queries.games(shelf, queries.ListingQuery(q="pikmin"))["rows"][0]["title"]
            == "Pikmin 1+2 (Pre-Owned)"
        )

    def test_sorts_titles_as_displayed_not_by_match_key(self, shelf) -> None:
        """By key, "The Legend of Zelda" files under L. Readers look under T."""
        add_listing(shelf, 5, "nistore", "The Legend of Zelda: Echoes of Wisdom")
        add_price(shelf, 5, 1, 3999, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        titles = [r["title"] for r in queries.games(shelf, queries.ListingQuery(sort="title"))["rows"]]
        assert titles == sorted(titles, key=str.lower)

    def test_sorts_by_offers(self, shelf) -> None:
        rows = queries.games(shelf, queries.ListingQuery(sort="offers", direction="desc"))["rows"]
        assert [r["offers"] for r in rows] == [3, 1]

    def test_a_game_key_narrows_listings_to_that_games_offers(self, shelf) -> None:
        result = queries.listings(shelf, queries.ListingQuery(game="metroid prime 4 beyond"))
        assert {r["id"] for r in result["rows"]} == {1, 2, 3}


class TestLowestEver:
    def test_reports_the_lowest_price_ever_recorded_across_stores_and_runs(self, shelf) -> None:
        add_price(shelf, 1, 2, 3499, at="2026-02-01T00:00:00Z")  # NI dipped to 3,499 once...
        add_price(shelf, 1, 3, 4999, at="2026-03-01T00:00:00Z")  # ...then went back up
        metroid = queries.games(shelf, queries.ListingQuery(q="metroid"))["rows"][0]
        assert (metroid["best_price"], metroid["lowest_ever"]) == (4499, 3499)
        assert metroid["at_lowest"] is False

    def test_at_lowest_needs_history_not_one_observation(self, shelf) -> None:
        """Seen once, every price is trivially the lowest ever -- not worth a badge."""
        kirby = queries.games(shelf, queries.ListingQuery(q="kirby"))["rows"][0]
        assert (kirby["lowest_ever"], kirby["at_lowest"]) == (5999, False)
        add_price(shelf, 4, 2, 5499, at="2026-02-01T00:00:00Z")  # second run, a new low
        kirby = queries.games(shelf, queries.ListingQuery(q="kirby"))["rows"][0]
        assert (kirby["best_price"], kirby["at_lowest"]) == (5499, True)

    def test_respects_the_condition_being_viewed(self, shelf) -> None:
        add_listing(shelf, 7, "amazon", "Kirby Air Riders - Used", platform="SWITCH2", condition="PRE_OWNED")
        add_price(shelf, 7, 1, 2999, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        new_only = queries.games(shelf, queries.ListingQuery(q="kirby", condition="NEW"))["rows"][0]
        assert new_only["lowest_ever"] == 5999  # the used copy's 2,999 does not count


class TestOffersWithNoRupeePrice:
    """An offer with no exchange rate yet still counts -- as listings() counts it."""

    @pytest.fixture
    def unpriced(self, shelf):
        add_listing(shelf, 9, "nistore", "Metroid Prime 4 Beyond (US)", region="US")
        shelf.execute(
            "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, native_price, "
            "inr_price, in_stock) VALUES (9, 1, '2026-01-01T00:00:00Z', 'USD', 59.99, NULL, 1)"
        )
        matcher.rematch(shelf)
        return shelf

    def test_offers_count_matches_the_expanded_list(self, unpriced) -> None:
        game = "metroid prime 4 beyond"
        row = queries.games(unpriced, queries.ListingQuery(q="metroid"))["rows"][0]
        offers = queries.listings(unpriced, queries.ListingQuery(game=game, platform="SWITCH"))
        assert row["offers"] == offers["total"] == 4
        assert row["best_price"] == 4499  # an unpriced offer is never "best"

    def test_a_game_with_only_unpriced_offers_sorts_last_and_never_hits(self, unpriced) -> None:
        add_listing(unpriced, 10, "amazon", "Hades II")
        unpriced.execute(
            "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, native_price, "
            "inr_price, in_stock) VALUES (10, 1, '2026-01-01T00:00:00Z', 'USD', 29.99, NULL, 1)"
        )
        matcher.rematch(unpriced)
        for direction in ("asc", "desc"):
            rows = queries.games(unpriced, queries.ListingQuery(sort="price", direction=direction))["rows"]
            assert rows[-1]["game"] == "hades ii", direction
        [status] = queries.watch_status(unpriced, [{"game": "hades ii", "platform": "SWITCH", "target": 9e9}])
        assert status["hit"] is False


class TestWatchStatus:
    def test_a_new_only_watch_ignores_a_used_copy_under_target(self, shelf) -> None:
        add_listing(shelf, 7, "amazon", "Kirby Air Riders - Used", platform="SWITCH2", condition="PRE_OWNED")
        add_price(shelf, 7, 1, 2999, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        item = {"game": "kirby air riders", "platform": "SWITCH2", "target": 4000}
        [any_copy] = queries.watch_status(shelf, [{**item, "condition": "ANY"}])
        [new_only] = queries.watch_status(shelf, [{**item, "condition": "NEW"}])
        assert (any_copy["hit"], any_copy["best"]["best_price"]) == (True, 2999)
        assert (new_only["hit"], new_only["best"]["best_price"]) == (False, 5999)

    def test_a_watch_follows_its_game_through_an_alias(self, shelf) -> None:
        """Adding the alias that fixes a split must not orphan a watch on the old key."""
        aliases = {"metroid prime 4": "metroid prime 4 beyond"}
        [status] = queries.watch_status(
            shelf, [{"game": "metroid prime 4", "platform": "SWITCH", "target": 4500}], aliases
        )
        assert (status["game"], status["hit"]) == ("metroid prime 4", True)  # stored key kept for DELETE

    def test_a_watch_survives_a_matcher_rekey(self, shelf) -> None:
        """Watched before publisher prefixes were stripped; the game's key has since changed."""
        old_key = "ubisoft metroid prime 4 beyond"
        [status] = queries.watch_status(shelf, [{"game": old_key, "platform": "SWITCH", "target": 4500}])
        assert (status["game"], status["hit"]) == (old_key, True)

    def test_a_watch_follows_a_recorded_redirect(self, shelf) -> None:
        """A re-key match_key alone cannot undo (e.g. the old key held Flipkart marketing)."""
        shelf.executemany(
            "INSERT INTO game_redirect VALUES (?, 'SWITCH', ?)",
            [
                ("metroid prime 4 beyond premium", "metroid prime 4 b"),
                ("metroid prime 4 b", "metroid prime 4 beyond"),
            ],
        )
        item = {"game": "metroid prime 4 beyond premium", "platform": "SWITCH", "target": 4500}
        [status] = queries.watch_status(shelf, [item])
        assert (status["game"], status["hit"]) == ("metroid prime 4 beyond premium", True)

    def test_a_game_that_exists_never_follows_a_redirect(self, shelf) -> None:
        """A "New only" watch on a game whose only copy is used finds nothing -- not a redirect's price."""
        add_listing(shelf, 8, "amazon", "Hades II - Used", platform="SWITCH", condition="PRE_OWNED")
        add_price(shelf, 8, 1, 1999, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        shelf.execute("INSERT INTO game_redirect VALUES ('hades ii', 'SWITCH', 'metroid prime 4 beyond')")
        item = {"game": "hades ii", "platform": "SWITCH", "target": 9e9, "condition": "NEW"}
        [status] = queries.watch_status(shelf, [item])
        assert (status["best"], status["hit"]) == (None, False)  # not Metroid's price

    def test_a_redirect_cycle_ends_instead_of_hanging(self, shelf) -> None:
        shelf.executemany(
            "INSERT INTO game_redirect VALUES (?, 'SWITCH', ?)", [("loop a", "loop b"), ("loop b", "loop a")]
        )
        [status] = queries.watch_status(shelf, [{"game": "loop a", "platform": "SWITCH", "target": 1}])
        assert status["best"] is None

    def test_hits_only_at_or_below_target_and_in_stock(self, shelf) -> None:
        status = queries.watch_status(
            shelf,
            [
                {"game": "metroid prime 4 beyond", "platform": "SWITCH", "target": 4500},
                {"game": "kirby air riders", "platform": "SWITCH2", "target": 5000},
            ],
        )
        assert [(s["game"], s["hit"]) for s in status] == [
            ("metroid prime 4 beyond", True),  # hits sort first
            ("kirby air riders", False),
        ]

    def test_a_cheap_but_sold_out_offer_is_not_a_hit(self, shelf) -> None:
        """₹3,999 is under target but out of stock; ₹4,499 is the best you can buy."""
        [status] = queries.watch_status(
            shelf, [{"game": "metroid prime 4 beyond", "platform": "SWITCH", "target": 4000}]
        )
        assert status["hit"] is False

    def test_watches_on_old_split_groups_follow_the_consolidated_game(self, conn) -> None:
        """Tales of Vesperia, live: three spellings were three games. After a rematch
        there is one game with every offer, and a watch made on ANY of the old groups
        keeps its own target and condition and sees all of them."""
        offers = [
            (11, "amazon", "NSW™, NSW2™ Tales of Vesperia [Definitive Edition] (Europe)", "EU", 3250),
            (12, "amazon", "Tales of Vesperia Definitive Edition(tbd)", "IN", 2999),
            (13, "nistore", "Tales Of Vesperia - Definitive Edition (Switch)", "IN", 3499),
        ]
        old_keys = [
            "nswtm nsw2tm tales vesperia",
            "tales vesperia definitive tbd",
            "tales vesperia definitive",
        ]
        for (lid, store, title, region, price), key in zip(offers, old_keys, strict=True):
            add_listing(conn, lid, store, title, region=region)
            add_price(conn, lid, 1, price, at="2026-01-01T00:00:00Z")
            conn.execute(
                "INSERT INTO game (canonical_title, platform, region) VALUES (?, 'SWITCH', ?)", (key, region)
            )
            conn.execute("UPDATE listing SET game_id = last_insert_rowid() WHERE id = ?", (lid,))
        matcher.rematch(conn)

        [game] = queries.games(conn, queries.ListingQuery(q="vesperia"))["rows"]
        assert (game["offers"], game["stores"], game["best_price"]) == (3, 2, 2999)

        watches = [
            {"game": "nswtm nsw2tm tales vesperia", "platform": "SWITCH", "target": 3000, "condition": "NEW"},
            {"game": "tales vesperia definitive tbd", "platform": "SWITCH", "target": 2500},
        ]
        status = {s["game"]: s for s in queries.watch_status(conn, watches)}
        assert {
            k: (s["target"], s.get("condition"), s["best"]["best_price"], s["hit"]) for k, s in status.items()
        } == {
            "nswtm nsw2tm tales vesperia": (3000, "NEW", 2999, True),
            "tales vesperia definitive tbd": (2500, None, 2999, False),
        }

    def test_india_only_ignores_an_import_for_best_price_alert_and_lowest_ever(self, shelf) -> None:
        """Play-Asia's rupee price is before customs and shipping (~30%): cheapest on
        paper, not in fact. A watch set to Indian shops only must not see it."""
        shelf.execute("INSERT INTO store VALUES ('playasia','Play-Asia','https://p','BROWSER','INR',1,1)")
        add_listing(shelf, 9, "playasia", "NSW™, NSW2™ Metroid Prime 4: Beyond (Asia)", region="ASIA_EN")
        add_price(shelf, 9, 1, 3500, at="2026-01-01T00:00:00Z")
        matcher.rematch(shelf)
        item = {"game": "metroid prime 4 beyond", "platform": "SWITCH", "target": 4000}
        [every] = queries.watch_status(shelf, [{**item, "shops": "ALL"}])
        [india] = queries.watch_status(shelf, [{**item, "shops": "INDIA"}])
        assert (every["best"]["best_store"], every["best"]["best_price"], every["hit"]) == (
            "Play-Asia",
            3500,
            True,
        )
        assert (india["best"]["best_store"], india["best"]["best_price"], india["hit"]) == (
            "Amazon",
            4499,
            False,
        )
        assert india["best"]["lowest_ever"] != 3500

    def test_a_game_with_no_offers_left_reports_none_rather_than_vanishing(self, shelf) -> None:
        [status] = queries.watch_status(shelf, [{"game": "gone", "platform": "SWITCH", "target": 1}])
        assert (status["best"], status["hit"]) == (None, False)


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
        assert queries.listings(conn, queries.ListingQuery(stores=("amazon",)))["total"] == 1

    def test_filters_by_condition(self, conn) -> None:
        result = queries.listings(conn, queries.ListingQuery(condition="PRE_OWNED"))
        assert [r["raw_title"] for r in result["rows"]] == ["Metroid Dread"]

    def test_filters_by_region(self, conn) -> None:
        assert queries.listings(conn, queries.ListingQuery(regions=("JP",)))["total"] == 1

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

    def test_returns_all_movers_without_a_60_row_cap(self, conn) -> None:
        for listing_id in range(1, 62):
            add_listing(conn, listing_id, "nistore", f"Game {listing_id}")
            add_price(conn, listing_id, 1, 1000, at="2026-08-01")
            add_price(conn, listing_id, 2, 900, at="2026-08-15")

        movers = queries.movers(conn)

        assert len(movers) == 61
        assert {m["id"] for m in movers} == set(range(1, 62))

    def test_shows_only_changes_above_one_percent(self, conn) -> None:
        prices = {1: 1010, 2: 1011, 3: 990, 4: 989}
        for listing_id, current_price in prices.items():
            add_listing(conn, listing_id, "nistore", f"Game {listing_id}")
            add_price(conn, listing_id, 1, 1000, at="2026-08-01")
            add_price(conn, listing_id, 2, current_price, at="2026-08-15")

        movers = queries.movers(conn)
        assert {m["id"] for m in movers} == {2, 4}

        listings = queries.listings(conn, queries.ListingQuery(limit=10))["rows"]
        by_id = {row["id"]: row["change_pct"] for row in listings}
        assert by_id[1] is None
        assert by_id[2] > 1
        assert by_id[3] is None
        assert by_id[4] < -1

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

    def test_counts_respect_other_filters_but_not_their_own(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_listing(conn, 2, "amazon", "Mario", platform="SWITCH2", region="JP")
        add_listing(conn, 3, "amazon", "Kirby", platform="SWITCH2")
        add_price(conn, 1, 1, 100, at="2026-08-01")
        add_price(conn, 2, 1, 100, at="2026-08-01", in_stock=0)
        add_price(conn, 3, 1, 100, at="2026-08-01")

        def counts(**kw: object) -> tuple[dict[str, int], dict[str, int]]:
            f = queries.facets(conn, queries.ListingQuery(**kw))  # type: ignore[arg-type]
            return {s["id"]: s["n"] for s in f["stores"]}, {r["region"]: r["n"] for r in f["regions"]}

        # Platform narrows both; zero-count entries stay listed.
        assert counts(platform="SWITCH2") == ({"amazon": 2, "nistore": 0}, {"IN": 1, "JP": 1})
        # A store filter does not narrow the store counts, but does the regions.
        assert counts(stores=("nistore",)) == ({"amazon": 2, "nistore": 1}, {"IN": 1, "JP": 0})
        assert counts(regions=("JP",)) == ({"amazon": 1, "nistore": 0}, {"IN": 2, "JP": 1})
        # in_stock goes through the `latest` join.
        assert counts(in_stock_only=True, q="a") == ({"amazon": 0, "nistore": 1}, {"IN": 1, "JP": 0})


class TestHistory:
    def test_returns_a_listings_price_series_oldest_first(self, conn) -> None:
        add_listing(conn, 1, "nistore", "Zelda")
        add_price(conn, 1, 1, 4499, at="2026-08-01")
        add_price(conn, 1, 2, 3599, at="2026-08-15")
        series = queries.history(conn, 1)
        assert [p["inr_price"] for p in series] == [4499, 3599]


# --------------------------------------------------------------------- oracle

#: The SQL as it shipped, frozen. This is the ORACLE: the rewrite is correct iff
#: it returns what this returns.
#:
#: Deliberately a literal and not an import from queries.py. An oracle that
#: changes when production changes is not an oracle -- it would agree with any
#: rewrite, including a wrong one.
_ORACLE_LATEST_CTE = """
WITH latest AS (
  SELECT listing_id, inr_price, native_price, native_currency, in_stock, captured_at,
         ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY captured_at DESC) AS rn
  FROM price_point
)
"""

_ORACLE_MOVERS = """
WITH ranked AS (
  SELECT listing_id, inr_price, native_currency, in_stock, captured_at,
         ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY captured_at DESC) AS rn
  FROM price_point
)
SELECT l.id, l.raw_title, l.url, l.region, s.name AS store,
       cur.native_currency AS currency,
       cur.inr_price AS now_price, prev.inr_price AS prev_price,
       cur.in_stock, cur.captured_at
FROM ranked cur
JOIN ranked prev ON prev.listing_id = cur.listing_id AND prev.rn = 2
JOIN listing l ON l.id = cur.listing_id
JOIN store s ON s.id = l.store_id
WHERE cur.rn = 1 AND cur.inr_price <> prev.inr_price
"""


def _oracle_listings(conn: sqlite3.Connection, q: queries.ListingQuery) -> dict:
    """The shipped listings() query, reproduced against the frozen CTE."""
    where: list[str] = []
    params: list = []
    if q.q:
        where.append(r"l.raw_title LIKE ? ESCAPE '\'")
        params.append(f"%{queries._escape_like(q.q)}%")
    for column, value in (("l.platform", q.platform), ("l.condition", q.condition)):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    for column, values in (("l.store_id", q.stores), ("l.region", q.regions)):
        if values:
            where.append(f"{column} IN ({', '.join('?' * len(values))})")
            params.extend(values)
    if q.in_stock_only:
        where.append("latest.in_stock = 1")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    from_clause = f"""
        FROM listing l
        JOIN store s ON s.id = l.store_id
        JOIN latest ON latest.listing_id = l.id AND latest.rn = 1
        LEFT JOIN latest previous ON previous.listing_id = l.id AND previous.rn = 2
        {clause}
    """
    total = conn.execute(f"{_ORACLE_LATEST_CTE} SELECT COUNT(*) AS n {from_clause}", params).fetchone()["n"]
    rows = [
        dict(r)
        for r in conn.execute(
            f"{_ORACLE_LATEST_CTE} SELECT l.id, l.raw_title, l.url, l.region, l.platform, l.condition, "
            f"s.name AS store, latest.inr_price, latest.native_price, latest.native_currency, "
            f"latest.in_stock, latest.captured_at, "
            f"CASE WHEN previous.inr_price IS NOT NULL AND previous.inr_price != 0 "
            f"AND latest.inr_price IS NOT NULL "
            # The 1% movement floor (queries.MIN_CHANGE_PCT), as a literal for the
            # same reason the CTE is one: an imported threshold would agree with
            # any value production chose.
            f"AND ABS(((latest.inr_price - previous.inr_price) / previous.inr_price) * 100.0) > 1.0 "
            f"THEN ((latest.inr_price - previous.inr_price) / previous.inr_price) * 100.0 "
            f"ELSE NULL END AS change_pct {from_clause} "
            f"ORDER BY {q.sort_column()} {q.sort_direction()}, l.id ASC LIMIT ? OFFSET ?",
            [*params, q.safe_limit(), q.safe_offset()],
        )
    ]
    return {"total": total, "rows": rows, "offset": q.safe_offset(), "limit": q.safe_limit()}


@pytest.fixture
def populated(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Every awkward case grounding named, in one database."""
    add_listing(conn, 1, "nistore", "Zelda Tears of the Kingdom")
    add_listing(conn, 2, "amazon", "Mario Kart World", platform="SWITCH2")
    add_listing(conn, 3, "nistore", "Metroid Prime", region="JP", condition="PRE_OWNED")
    add_listing(conn, 4, "amazon", "Splatoon 3")  # exactly ONE price point
    add_listing(conn, 5, "nistore", "Pikmin 4")  # NO price points at all
    add_listing(conn, 6, "amazon", "Kirby Forgotten Land")  # NULL inr_price

    add_price(conn, 1, 1, 4999, at="2026-01-01T00:00:00Z")
    add_price(conn, 1, 2, 3999, at="2026-01-02T00:00:00Z")
    add_price(conn, 2, 1, 5999, at="2026-01-01T00:00:00Z")
    add_price(conn, 2, 2, 5999, at="2026-01-02T00:00:00Z")  # unchanged: not a mover
    add_price(conn, 3, 1, 2499, at="2026-01-01T00:00:00Z", in_stock=0)
    add_price(conn, 3, 2, 1999, at="2026-01-02T00:00:00Z", in_stock=0)
    add_price(conn, 4, 1, 6999, at="2026-01-01T00:00:00Z")
    conn.execute(
        "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, "
        "native_price, inr_price, in_stock) VALUES (6,1,'2026-01-01T00:00:00Z','USD',59.99,NULL,1)"
    )
    conn.execute(
        "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, "
        "native_price, inr_price, in_stock) VALUES (6,2,'2026-01-02T00:00:00Z','USD',49.99,NULL,1)"
    )
    return conn


def test_change_sort_shows_only_actual_movers(populated: sqlite3.Connection) -> None:
    result = queries.listings(populated, queries.ListingQuery(sort="change"))
    assert result["total"] == 2
    assert {row["id"] for row in result["rows"]} == {1, 3}


def _case_id(q: queries.ListingQuery) -> str:
    """Readable pytest ids, so a failure names the parameter combination."""
    filters = "-".join(x for x in (q.q, q.platform, q.condition, *q.regions, *q.stores) if x)
    stock = "instock" if q.in_stock_only else ""
    page = f"l{q.limit}o{q.offset}" if (q.limit, q.offset) != (100, 0) else ""
    return "-".join(x for x in (q.sort, q.direction, filters, stock, page) if x)


def _matrix() -> list[queries.ListingQuery]:
    out = [queries.ListingQuery()]
    for sort in ("price", "title", "store", "seen"):
        for direction in ("asc", "desc"):
            out.append(queries.ListingQuery(sort=sort, direction=direction))
    out += [
        queries.ListingQuery(q="mario"),
        queries.ListingQuery(q="%"),
        queries.ListingQuery(platform="SWITCH2"),
        queries.ListingQuery(regions=("JP",)),
        queries.ListingQuery(stores=("amazon",)),
        queries.ListingQuery(condition="PRE_OWNED"),
        queries.ListingQuery(in_stock_only=True),
        queries.ListingQuery(in_stock_only=True, sort="price", direction="desc"),
        queries.ListingQuery(limit=2, offset=0, sort="price"),
        queries.ListingQuery(limit=2, offset=2, sort="price"),
        queries.ListingQuery(limit=2, offset=99),
    ]
    return out


class TestMatchesTheShippedQuery:
    """The acceptance criterion: identical rows, not a timing target.

    The failure this guards against is specific -- projecting the latest price
    as a scalar subquery instead of joining the row. That passes a
    default-parameters comparison and breaks only on in_stock_only, sort=price
    and sort=seen, which is why this is a matrix and not one assertion.
    """

    @pytest.mark.parametrize("query", _matrix(), ids=_case_id)
    def test_listings_matches_the_oracle(
        self, populated: sqlite3.Connection, query: queries.ListingQuery
    ) -> None:
        assert queries.listings(populated, query) == _oracle_listings(populated, query)

    def test_movers_matches_the_oracle(self, populated: sqlite3.Connection) -> None:
        expected = [dict(r) for r in populated.execute(_ORACLE_MOVERS)]
        actual = queries.movers(populated)
        # movers() adds pct/fx_suspect and coerces in_stock; compare the SQL half.
        assert {r["id"] for r in actual} == {r["id"] for r in expected}
        by_id = {r["id"]: r for r in expected}
        for row in actual:
            assert row["now_price"] == by_id[row["id"]]["now_price"]
            assert row["prev_price"] == by_id[row["id"]]["prev_price"]
            assert row["captured_at"] == by_id[row["id"]]["captured_at"]

    def test_the_fixture_actually_exercises_the_awkward_cases(self, populated: sqlite3.Connection) -> None:
        """A matrix over a fixture that has no edge cases proves nothing."""
        rows = queries.listings(populated, queries.ListingQuery())["rows"]
        ids = {r["id"] for r in rows}
        assert 5 not in ids, "a listing with no price points must be excluded"
        assert 4 in ids, "a listing with one price point must still be listed"
        assert 6 in ids, "a NULL inr_price must not drop the listing"
        assert {m["id"] for m in queries.movers(populated)} == {1, 3}

    def test_a_tie_on_captured_at_resolves_to_the_later_insert(self, conn: sqlite3.Connection) -> None:
        """The one deliberate behaviour change, asserted against the NEW rule.

        Two runs inside the same second give two rows the same captured_at.
        Previously "latest" was whichever the planner emitted first -- undefined,
        so the oracle cannot arbitrate this case. AUTOINCREMENT makes id
        monotonic, so the tie-break resolves to the later insert.
        """
        add_listing(conn, 1, "nistore", "Zelda Tears of the Kingdom")
        add_price(conn, 1, 1, 4999, at="2026-01-01T00:00:00Z")
        add_price(conn, 1, 2, 3499, at="2026-01-01T00:00:00Z")  # same second

        rows = queries.listings(conn, queries.ListingQuery())["rows"]
        assert rows[0]["inr_price"] == 3499


class TestMultiValueFilters:
    """Stores and regions are sets.

    Comparing two shops, or Asia against Japan, is the normal question a price
    tracker gets asked. Single-select could only answer it one shop at a time.
    """

    @pytest.fixture
    def spread(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        add_listing(conn, 1, "nistore", "Zelda", region="IN")
        add_listing(conn, 2, "amazon", "Mario", region="JP")
        add_listing(conn, 3, "nistore", "Metroid", region="ASIA_EN")
        add_listing(conn, 4, "amazon", "Kirby", region="US")
        for listing_id in (1, 2, 3, 4):
            add_price(conn, listing_id, 1, 1000 * listing_id, at="2026-01-01T00:00:00Z")
        return conn

    @staticmethod
    def _ids(result: dict) -> set[int]:
        return {row["id"] for row in result["rows"]}

    def test_no_selection_returns_everything(self, spread: sqlite3.Connection) -> None:
        assert self._ids(queries.listings(spread, queries.ListingQuery())) == {1, 2, 3, 4}

    def test_one_store_behaves_exactly_as_before(self, spread: sqlite3.Connection) -> None:
        """The backward-compatible case: a bookmarked ?store=amazon still works."""
        result = queries.listings(spread, queries.ListingQuery(stores=("amazon",)))
        assert self._ids(result) == {2, 4}
        assert result["total"] == 2

    def test_several_stores(self, spread: sqlite3.Connection) -> None:
        result = queries.listings(spread, queries.ListingQuery(stores=("amazon", "nistore")))
        assert self._ids(result) == {1, 2, 3, 4}
        assert result["total"] == 4

    def test_several_regions(self, spread: sqlite3.Connection) -> None:
        result = queries.listings(spread, queries.ListingQuery(regions=("JP", "ASIA_EN")))
        assert self._ids(result) == {2, 3}

    def test_stores_and_regions_combine_with_AND(self, spread: sqlite3.Connection) -> None:
        """Amazon OR nistore, AND (JP OR ASIA_EN) -- not four independent ORs."""
        result = queries.listings(spread, queries.ListingQuery(stores=("amazon",), regions=("JP", "ASIA_EN")))
        assert self._ids(result) == {2}

    def test_an_unknown_id_simply_matches_nothing(self, spread: sqlite3.Connection) -> None:
        result = queries.listings(spread, queries.ListingQuery(stores=("ghost",)))
        assert result["total"] == 0

    def test_total_counts_the_filtered_set_not_the_page(self, spread: sqlite3.Connection) -> None:
        """total and rows must agree, or the count under the table lies."""
        result = queries.listings(spread, queries.ListingQuery(stores=("amazon", "nistore"), limit=2))
        assert result["total"] == 4
        assert len(result["rows"]) == 2

    def test_a_store_id_cannot_inject_sql(self, spread: sqlite3.Connection) -> None:
        """Values are bound; only the placeholder COUNT comes from the tuple."""
        hostile = ("amazon", "'); DROP TABLE listing; --")
        assert self._ids(queries.listings(spread, queries.ListingQuery(stores=hostile))) == {2, 4}
        assert spread.execute("SELECT COUNT(*) c FROM listing").fetchone()["c"] == 4
