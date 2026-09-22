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
    total = conn.execute(
        f"{_ORACLE_LATEST_CTE} SELECT COUNT(*) AS n {from_clause}", params).fetchone()["n"]
    rows = [dict(r) for r in conn.execute(
        f"{_ORACLE_LATEST_CTE} SELECT l.id, l.raw_title, l.url, l.region, l.platform, l.condition, "
        f"s.name AS store, latest.inr_price, latest.native_price, latest.native_currency, "
        f"latest.in_stock, latest.captured_at, "
        f"CASE WHEN previous.inr_price IS NOT NULL AND previous.inr_price != 0 "
        f"AND latest.inr_price IS NOT NULL "
        f"THEN ((latest.inr_price - previous.inr_price) / previous.inr_price) * 100.0 "
        f"ELSE NULL END AS change_pct {from_clause} "
        f"ORDER BY {q.sort_column()} {q.sort_direction()}, l.id ASC LIMIT ? OFFSET ?",
        [*params, q.safe_limit(), q.safe_offset()])]
    return {"total": total, "rows": rows, "offset": q.safe_offset(), "limit": q.safe_limit()}


@pytest.fixture
def populated(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Every awkward case grounding named, in one database."""
    add_listing(conn, 1, "nistore", "Zelda Tears of the Kingdom")
    add_listing(conn, 2, "amazon", "Mario Kart World", platform="SWITCH2")
    add_listing(conn, 3, "nistore", "Metroid Prime", region="JP", condition="PRE_OWNED")
    add_listing(conn, 4, "amazon", "Splatoon 3")           # exactly ONE price point
    add_listing(conn, 5, "nistore", "Pikmin 4")            # NO price points at all
    add_listing(conn, 6, "amazon", "Kirby Forgotten Land") # NULL inr_price

    add_price(conn, 1, 1, 4999, at="2026-01-01T00:00:00Z")
    add_price(conn, 1, 2, 3999, at="2026-01-02T00:00:00Z")
    add_price(conn, 2, 1, 5999, at="2026-01-01T00:00:00Z")
    add_price(conn, 2, 2, 5999, at="2026-01-02T00:00:00Z")   # unchanged: not a mover
    add_price(conn, 3, 1, 2499, at="2026-01-01T00:00:00Z", in_stock=0)
    add_price(conn, 3, 2, 1999, at="2026-01-02T00:00:00Z", in_stock=0)
    add_price(conn, 4, 1, 6999, at="2026-01-01T00:00:00Z")
    conn.execute(
        "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, "
        "native_price, inr_price, in_stock) VALUES (6,1,'2026-01-01T00:00:00Z','USD',59.99,NULL,1)")
    conn.execute(
        "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, "
        "native_price, inr_price, in_stock) VALUES (6,2,'2026-01-02T00:00:00Z','USD',49.99,NULL,1)")
    return conn


def test_change_sort_shows_only_actual_movers(populated: sqlite3.Connection) -> None:
    result = queries.listings(populated, queries.ListingQuery(sort="change"))
    assert result["total"] == 2
    assert {row["id"] for row in result["rows"]} == {1, 3}


def _case_id(q: queries.ListingQuery) -> str:
    """Readable pytest ids, so a failure names the parameter combination."""
    filters = "-".join(
        x for x in (q.q, q.platform, q.condition, *q.regions, *q.stores) if x)
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

    def test_the_fixture_actually_exercises_the_awkward_cases(
        self, populated: sqlite3.Connection
    ) -> None:
        """A matrix over a fixture that has no edge cases proves nothing."""
        rows = queries.listings(populated, queries.ListingQuery())["rows"]
        ids = {r["id"] for r in rows}
        assert 5 not in ids, "a listing with no price points must be excluded"
        assert 4 in ids, "a listing with one price point must still be listed"
        assert 6 in ids, "a NULL inr_price must not drop the listing"
        assert {m["id"] for m in queries.movers(populated)} == {1, 3}

    def test_a_tie_on_captured_at_resolves_to_the_later_insert(
        self, conn: sqlite3.Connection
    ) -> None:
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
        result = queries.listings(
            spread, queries.ListingQuery(stores=("amazon",), regions=("JP", "ASIA_EN")))
        assert self._ids(result) == {2}

    def test_an_unknown_id_simply_matches_nothing(self, spread: sqlite3.Connection) -> None:
        result = queries.listings(spread, queries.ListingQuery(stores=("ghost",)))
        assert result["total"] == 0

    def test_total_counts_the_filtered_set_not_the_page(self, spread: sqlite3.Connection) -> None:
        """total and rows must agree, or the count under the table lies."""
        result = queries.listings(
            spread, queries.ListingQuery(stores=("amazon", "nistore"), limit=2))
        assert result["total"] == 4
        assert len(result["rows"]) == 2

    def test_a_store_id_cannot_inject_sql(self, spread: sqlite3.Connection) -> None:
        """Values are bound; only the placeholder COUNT comes from the tuple."""
        hostile = ("amazon", "'); DROP TABLE listing; --")
        assert self._ids(queries.listings(spread, queries.ListingQuery(stores=hostile))) == {2, 4}
        assert spread.execute("SELECT COUNT(*) c FROM listing").fetchone()["c"] == 4
