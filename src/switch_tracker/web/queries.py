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
    region: str = ""
    store: str = ""
    condition: str = ""
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


_LATEST_CTE = """
WITH latest AS (
  SELECT listing_id, inr_price, native_price, native_currency, in_stock, captured_at,
         ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY captured_at DESC) AS rn
  FROM price_point
)
"""


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
        ("l.region", query.region),
        ("l.store_id", query.store),
        ("l.condition", query.condition),
    ):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    if query.in_stock_only:
        where.append("latest.in_stock = 1")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    from_clause = f"""
        FROM listing l
        JOIN store s ON s.id = l.store_id
        JOIN latest ON latest.listing_id = l.id AND latest.rn = 1
        {clause}
    """

    total = conn.execute(f"{_LATEST_CTE} SELECT COUNT(*) AS n {from_clause}", params).fetchone()["n"]

    rows = _rows(
        conn.execute(
            f"{_LATEST_CTE} SELECT l.id, l.raw_title, l.url, l.region, l.platform, l.condition, "
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
            """
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
