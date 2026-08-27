"""Every dashboard read, as SQL.

Filtering, sorting and aggregation happen in the database, never in the page.
Shipping 200 rows and sorting them in the browser gives you the cheapest of
those 200 while looking exactly like the cheapest overall -- a wrong answer
wearing a right one's clothes.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

# Whitelisted, because these land in SQL TEXT rather than as parameters.
SORT_COLUMNS = {
    "price": "latest.inr_price",
    "title": "l.raw_title",
    "store": "s.name",
    "seen": "latest.captured_at",
}

#: How many listings must move by the same rounded percentage, in the same
#: currency, before it reads as the currency moving rather than the shops.
FX_CLUSTER_THRESHOLD = 8


@dataclass(frozen=True, slots=True)
class ListingQuery:
    q: str = ""
    platform: str = ""
    condition: str = ""
    #: Store ids and regions are SETS -- a listing view is far more useful when
    #: you can compare two shops, or Asia against Japan, than when you can look
    #: at exactly one. Empty means "no filter", the same as an empty string does
    #: for the single-valued fields above.
    #:
    #: platform and condition stay single-valued on purpose: their controls are
    #: three-way segmented buttons where the first option already means "all",
    #: so a set would add a state the UI cannot express.
    stores: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    in_stock_only: bool = False
    sort: str = "price"
    direction: str = "asc"
    limit: int = 100
    offset: int = 0

    def sort_column(self) -> str:
        return SORT_COLUMNS.get(self.sort, SORT_COLUMNS["price"])

    def sort_direction(self) -> str:
        return "DESC" if self.direction.lower() == "desc" else "ASC"

    def safe_limit(self) -> int:
        return max(1, min(self.limit, 500))

    def safe_offset(self) -> int:
        return max(0, self.offset)


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _escape_like(term: str) -> str:
    """Make a user's search term literal inside a LIKE pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM listing) AS listings, "
        "(SELECT COUNT(DISTINCT store_id) FROM listing) AS stores, "
        "(SELECT COUNT(*) FROM price_point) AS points, "
        "(SELECT COUNT(*) FROM listing WHERE game_id IS NULL) AS unmatched"
    ).fetchone()
    return dict(row)


def has_ever_collected(conn: sqlite3.Connection) -> bool:
    """Has a COLLECTION ever run against this database?

    ``run_store`` is the right table to ask, and ``run`` is not: probe, fx and
    inspect all create a ``run`` row, so a user who has only ever pressed
    "Check stores" would look like they had already collected. Only
    CollectService writes ``run_store``.

    Derived from real state rather than from a "have I done this yet" flag in
    settings, so a deleted or moved database correctly bootstraps itself again
    instead of staying permanently convinced it has already collected.
    """
    return conn.execute("SELECT 1 FROM run_store LIMIT 1").fetchone() is not None


def health(conn: sqlite3.Connection) -> dict[str, Any]:
    """Per-store status for the latest run.

    A store silently returning zero rows is the failure that quietly rots a
    tracker over time, so its absence is recorded and displayed exactly as
    loudly as an exception would be.
    """
    run = conn.execute(
        "SELECT id, started_at, finished_at FROM run ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return {"run": None, "stores": []}

    stores = _rows(
        conn.execute(
            "SELECT rs.store_id, s.name, s.tier, rs.status, rs.listings_found, rs.duration_ms, "
            "rs.detail FROM run_store rs JOIN store s ON s.id = rs.store_id "
            "WHERE rs.run_id = ? ORDER BY s.tier, rs.listings_found DESC",
            (run["id"],),
        )
    )
    return {"run": dict(run), "stores": stores}


#: The n-th newest price_point ID for one listing, as a scalar subquery.
#:
#: This replaced a window function that ranked EVERY row of price history to
#: find rank 1. That cost is tied to total history, not to the listings on
#: screen, so every collection run made the dashboard slower: measured at 5,000
#: listings per run it went 1.1s at three months, 5.3s at one year, 39.6s at
#: three -- degrading superlinearly once the sort stopped fitting in cache.
#: This form seeks idx_pp_listing_time (listing_id, captured_at DESC) once per
#: listing and stays flat at ~15ms regardless of how much history exists.
#:
#: The ORDER BY carries `id DESC` as a tie-break. Two runs inside the same
#: second give two rows the same captured_at, and "the latest" was previously
#: whichever one the query planner happened to emit first. AUTOINCREMENT makes
#: id monotonic, so this resolves to "later insert wins", deterministically.
#:
#: CONTRACT: embeds `l.id`, so any query using it must alias `listing` as `l`.
#:
#: Formatted at import from a literal, never at call time -- one definition of
#: "newest row for a listing" with no runtime interpolation into SQL.
_NTH_LATEST_ID = """(
    SELECT pp.id FROM price_point pp
    WHERE pp.listing_id = l.id
    ORDER BY pp.captured_at DESC, pp.id DESC
    LIMIT 1 OFFSET {n}
)"""

_LATEST_ID = _NTH_LATEST_ID.format(n=0)
_PREVIOUS_ID = _NTH_LATEST_ID.format(n=1)


def listings(conn: sqlite3.Connection, query: ListingQuery) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []

    if query.q:
        # ESCAPE rather than strip. server.ts removes % and _ from the term,
        # which turns a search for "%" into an empty term that matches every
        # row -- the filter appears to have broken. Escaping makes a literal
        # "%" search for a literal "%", which correctly finds nothing.
        where.append(r"l.raw_title LIKE ? ESCAPE '\'")
        params.append(f"%{_escape_like(query.q)}%")
    for column, value in (
        ("l.platform", query.platform),
        ("l.condition", query.condition),
    ):
        if value:
            where.append(f"{column} = ?")
            params.append(value)

    for column, values in (
        ("l.store_id", query.stores),
        ("l.region", query.regions),
    ):
        if values:
            # The placeholder COUNT comes from the tuple length; every value is
            # still bound. Nothing the user typed is interpolated into SQL --
            # the same rule the sort whitelist exists to enforce.
            where.append(f"{column} IN ({', '.join('?' * len(values))})")
            params.extend(values)
    if query.in_stock_only:
        where.append("latest.in_stock = 1")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    # `latest` is a JOINED ROW, not a projected value. It has to be: in_stock_only
    # filters on it, and sort=price / sort=seen order by it. Selecting the price
    # as a scalar subquery instead would look right and silently break all three.
    # An inner join, so a listing with no price points stays excluded as before.
    from_clause = f"""
        FROM listing l
        JOIN store s ON s.id = l.store_id
        JOIN price_point latest ON latest.id = {_LATEST_ID}
        {clause}
    """

    total = conn.execute(f"SELECT COUNT(*) AS n {from_clause}", params).fetchone()["n"]

    rows = _rows(
        conn.execute(
            f"SELECT l.id, l.raw_title, l.url, l.region, l.platform, l.condition, "
            f"s.name AS store, latest.inr_price, latest.native_price, latest.native_currency, "
            f"latest.in_stock, latest.captured_at {from_clause} "
            # id as the tie-break keeps pagination stable across requests.
            f"ORDER BY {query.sort_column()} {query.sort_direction()}, l.id ASC LIMIT ? OFFSET ?",
            [*params, query.safe_limit(), query.safe_offset()],
        )
    )
    return {"total": total, "rows": rows, "offset": query.safe_offset(), "limit": query.safe_limit()}


def movers(conn: sqlite3.Connection, limit: int = 60) -> list[dict[str, Any]]:
    """Price changes since each listing's PREVIOUS OBSERVATION.

    ``fx_suspect`` is the synchronised-move check the schema was built to
    support: if many listings in the same currency all moved by the same
    ratio, that is the rupee moving, not the shops. Flagging it keeps a
    currency wobble from reading as a catalogue-wide sale.
    """
    rows = _rows(
        conn.execute(
            # The same seek as listings(), twice: offset 0 is the current
            # observation, offset 1 the one before it. This replaces a second
            # copy of the rank-all-history CTE -- the logic existed in two
            # places, so a fix applied to one left the other slow.
            #
            # A listing with only one price point has no row at offset 1, so the
            # inner join drops it, exactly as `rn = 2` did. A NULL inr_price
            # makes the <> comparison NULL and drops the row, also as before.
            f"""
            SELECT l.id, l.raw_title, l.url, l.region, s.name AS store,
                   cur.native_currency AS currency,
                   cur.inr_price AS now_price, prev.inr_price AS prev_price,
                   cur.in_stock, cur.captured_at
            FROM listing l
            JOIN store s ON s.id = l.store_id
            JOIN price_point cur ON cur.id = {_LATEST_ID}
            JOIN price_point prev ON prev.id = {_PREVIOUS_ID}
            WHERE cur.inr_price <> prev.inr_price
            """
        )
    )

    def pct_of(row: dict[str, Any]) -> float:
        return float(((row["now_price"] - row["prev_price"]) / row["prev_price"]) * 100)

    # Cluster by rounded percentage within a currency.
    clusters = Counter(f"{r['currency']}:{pct_of(r):.1f}" for r in rows)

    enriched = []
    for row in rows:
        pct = pct_of(row)
        key = f"{row['currency']}:{pct:.1f}"
        enriched.append(
            {
                **row,
                "pct": pct,
                "in_stock": bool(row["in_stock"]),
                # A rupee price cannot move because of the rupee.
                "fx_suspect": clusters[key] >= FX_CLUSTER_THRESHOLD and row["currency"] != "INR",
            }
        )

    enriched.sort(key=lambda r: r["pct"])
    return enriched[:limit]


def facets(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Filter options built from what is actually in the database."""
    return {
        "stores": _rows(
            conn.execute(
                "SELECT s.id, s.name, COUNT(l.id) AS n FROM store s "
                "JOIN listing l ON l.store_id = s.id GROUP BY s.id ORDER BY s.name"
            )
        ),
        "platforms": _rows(
            conn.execute("SELECT platform, COUNT(*) AS n FROM listing GROUP BY platform ORDER BY n DESC")
        ),
        "regions": _rows(
            conn.execute("SELECT region, COUNT(*) AS n FROM listing GROUP BY region ORDER BY n DESC")
        ),
        "conditions": _rows(
            conn.execute("SELECT condition, COUNT(*) AS n FROM listing GROUP BY condition ORDER BY n DESC")
        ),
    }


def history(conn: sqlite3.Connection, listing_id: int) -> list[dict[str, Any]]:
    """One listing's price series, oldest first."""
    return _rows(
        conn.execute(
            "SELECT captured_at, inr_price, native_price, native_currency, in_stock, fx_rate_date "
            "FROM price_point WHERE listing_id = ? ORDER BY captured_at ASC",
            (listing_id,),
        )
    )
