"""Every dashboard read, as SQL.

Filtering, sorting and aggregation happen in the database, never in the page.
Shipping 200 rows and sorting them in the browser gives you the cheapest of
those 200 while looking exactly like the cheapest overall -- a wrong answer
wearing a right one's clothes.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Whitelisted, because these land in SQL TEXT rather than as parameters.
SORT_COLUMNS = {
    "price": "latest.inr_price",
    "title": "l.raw_title",
    "store": "s.name",
    "seen": "latest.captured_at",
    "change": "change_pct",
}

#: How many listings must move by the same rounded percentage, in the same
#: currency, before it reads as the currency moving rather than the shops.
FX_CLUSTER_THRESHOLD = 8

#: Show a price movement only when its absolute percentage change exceeds this.
MIN_CHANGE_PCT = 1.0


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
    #: A game key (``game.canonical_title``): only that game's listings, across
    #: every region it was matched in. How a Games row expands into its offers.
    game: str = ""
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
    run = conn.execute("SELECT id, started_at, finished_at FROM run ORDER BY id DESC LIMIT 1").fetchone()
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
_CHANGE_PCT = "((latest.inr_price - previous.inr_price) / previous.inr_price) * 100.0"


def _filters(query: ListingQuery) -> tuple[list[str], list[Any]]:
    """WHERE terms shared by listings() and games(), so the two views can never
    disagree about what a filter means. Expects aliases ``l`` and ``latest``."""
    where: list[str] = []
    params: list[Any] = []

    if query.q:
        # ESCAPE rather than strip. Removing % and _ from the term would turn
        # a search for "%" into an empty term that matches every
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
    if query.game:
        where.append("l.game_id IN (SELECT id FROM game WHERE canonical_title = ?)")
        params.append(query.game)
    return where, params


def listings(conn: sqlite3.Connection, query: ListingQuery) -> dict[str, Any]:
    where, params = _filters(query)
    if query.sort == "change":
        # Sorting by movement is most useful as a view of actual movers.
        # Apply this before COUNT and LIMIT so pagination stays consistent.
        where.append("previous.inr_price IS NOT NULL")
        where.append("previous.inr_price != 0")
        where.append("latest.inr_price != previous.inr_price")
        where.append(f"ABS({_CHANGE_PCT}) > ?")
        params.append(MIN_CHANGE_PCT)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    # `latest` is a JOINED ROW, not a projected value. It has to be: in_stock_only
    # filters on it, and sort=price / sort=seen order by it. Selecting the price
    # as a scalar subquery instead would look right and silently break all three.
    # An inner join, so a listing with no price points stays excluded as before.
    from_clause = f"""
        FROM listing l
        JOIN store s ON s.id = l.store_id
        JOIN price_point latest ON latest.id = {_LATEST_ID}
        LEFT JOIN price_point previous ON previous.id = {_PREVIOUS_ID}
        {clause}
    """

    total = conn.execute(f"SELECT COUNT(*) AS n {from_clause}", params).fetchone()["n"]

    sort_column = query.sort_column()
    if query.sort == "change":
        # NULL means there is no previous observation yet. Keep those rows at the
        # bottom in both directions rather than letting SQLite put them first
        # when sorting ascending.
        order_by = f"change_pct IS NULL ASC, change_pct {query.sort_direction()}, l.id ASC"
    else:
        order_by = f"{sort_column} {query.sort_direction()}, l.id ASC"

    rows = _rows(
        conn.execute(
            f"SELECT l.id, l.raw_title, l.url, l.region, l.platform, l.condition, "
            f"s.name AS store, latest.inr_price, latest.native_price, latest.native_currency, "
            f"latest.in_stock, latest.captured_at, "
            f"CASE "
            f"    WHEN previous.inr_price IS NOT NULL "
            f"         AND previous.inr_price != 0 "
            f"         AND latest.inr_price IS NOT NULL "
            f"         AND ABS({_CHANGE_PCT}) > {MIN_CHANGE_PCT} "
            f"    THEN {_CHANGE_PCT} "
            f"    ELSE NULL "
            f"END AS change_pct "
            f"{from_clause} "
            f"ORDER BY {order_by} LIMIT ? OFFSET ?",
            [*params, query.safe_limit(), query.safe_offset()],
        )
    )
    return {"total": total, "rows": rows, "offset": query.safe_offset(), "limit": query.safe_limit()}


#: Whitelisted for the same reason as SORT_COLUMNS: they land in SQL text.
#: "title" sorts the DISPLAYED title, not the match key -- by key, "The Legend
#: of Zelda" filed under L and "Pokémon" under "pokemon", neither where a
#: reader would look. "price" is special-cased in games(); see there.
GAME_SORT_COLUMNS = {"price": "best_price", "title": "title COLLATE NOCASE", "offers": "offers"}

#: The name a game row shows: the shortest NEW listing title in the group,
#: pre-owned only when nothing new exists. It used to be the CHEAPEST listing's
#: title, so a row read "Super Mario Bros. Wonder - Pre-Owned" -- and a
#: watchlist entry then named itself after a used copy. A scalar subquery, not
#: an aggregate, so the single-MIN() bare-column rule below still holds.
_DISPLAY_TITLE = """(
    SELECT d.raw_title FROM listing d JOIN game dg ON dg.id = d.game_id
    WHERE dg.canonical_title = g.canonical_title AND d.platform = l.platform
    ORDER BY d.condition = 'PRE_OWNED', length(d.raw_title), d.raw_title
    LIMIT 1
)"""

#: Sorts in-stock offers ahead of every out-of-stock one, then by price. An
#: out-of-stock ₹999 is not "the cheapest copy" of anything you can buy; it is
#: still shown when it is the ONLY offer, which is why this ranks rather than
#: filters.
_BEST_RANK = "(1 - latest.in_stock) * 1e9 + latest.inr_price"


def games(conn: sqlite3.Connection, query: ListingQuery) -> dict[str, Any]:
    """One row per matched game: its best offer, and how many shops carry it.

    Grouped by title + platform and NOT region, deliberately. The game table
    keys region (Play-Asia's regional SKUs are genuinely different products),
    but "where is this cheapest" is a question ACROSS regions -- an import is
    exactly the alternative being compared. Each row still names its best
    offer's region, so nothing is hidden.

    The best_* columns rely on SQLite's documented bare-column rule: in an
    aggregate query with EXACTLY ONE min() or max(), the other selected columns
    come from the row that produced it. That is what makes "the store and URL
    of the cheapest offer" one pass instead of a second self-join -- and why
    there is no MAX() here: adding one (a price range, say) silently voids the
    rule, and best_store starts naming an arbitrary row. A test pins it.
    """
    where, params = _filters(query)
    # Offers with NO rupee price (no exchange rate yet) are deliberately NOT
    # filtered out: they still count as offers, so this row's "Offers" agrees
    # with the list its ▸ expands to (listings() keeps them too). MIN() skips
    # their NULL rank, so they can never be chosen as the best offer.
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    grouped = f"""
        SELECT g.canonical_title AS game, l.platform,
               MIN({_BEST_RANK}) AS best_rank,
               latest.inr_price AS best_price, latest.in_stock AS best_in_stock,
               {_DISPLAY_TITLE} AS title, l.url AS best_url, l.region AS best_region,
               l.condition AS best_condition, s.name AS best_store,
               COUNT(*) AS offers, COUNT(DISTINCT l.store_id) AS stores
        FROM listing l
        JOIN store s ON s.id = l.store_id
        JOIN game g ON g.id = l.game_id
        JOIN price_point latest ON latest.id = {_LATEST_ID}
        {clause}
        GROUP BY g.canonical_title, l.platform
    """
    total = conn.execute(f"SELECT COUNT(*) AS n FROM ({grouped})", params).fetchone()["n"]
    column = GAME_SORT_COLUMNS.get(query.sort, GAME_SORT_COLUMNS["price"])
    # Games you can buy come first in BOTH price directions. Ordering by
    # best_rank alone did that ascending only: descending, its +1e9 offset put
    # every out-of-stock-only game at the very top of "most expensive first".
    # A game with no rupee price at all goes last too: SQLite would otherwise
    # sort its NULL price FIRST ascending, above every real one.
    in_stock_first = "best_price IS NULL, best_in_stock DESC, " if column == "best_price" else ""
    # Lowest price EVER recorded for the game, across every store and every
    # run, in the condition being viewed (so a "New only" watch is compared
    # with new copies' history). Computed OUTSIDE the grouped query on purpose:
    # inside it would sit next to the best-offer MIN() and its bind parameter
    # would land ahead of the filter parameters.
    condition_clause = "AND x.condition = ?" if query.condition else ""
    history = f"""
        FROM price_point pp
        JOIN listing x ON x.id = pp.listing_id
        JOIN game xg ON xg.id = x.game_id
        WHERE xg.canonical_title = sub.game AND x.platform = sub.platform {condition_clause}
    """
    history_params = [query.condition] * 2 if query.condition else []
    rows = _rows(
        conn.execute(
            f"SELECT sub.*, (SELECT MIN(pp.inr_price) {history}) AS lowest_ever, "
            f"(SELECT COUNT(DISTINCT pp.run_id) {history}) AS runs_seen "
            f"FROM ({grouped}) AS sub "
            f"ORDER BY {in_stock_first}{column} {query.sort_direction()}, game ASC, platform ASC "
            "LIMIT ? OFFSET ?",
            [*history_params, *params, query.safe_limit(), query.safe_offset()],
        )
    )
    for row in rows:
        del row["best_rank"]
        row["best_in_stock"] = bool(row["best_in_stock"])
        # "At its lowest" only means something with history: on a game seen in
        # one collection, every price is trivially the lowest ever.
        row["at_lowest"] = bool(
            row["runs_seen"] >= 2
            and row["best_in_stock"]
            and row["best_price"] is not None
            and row["lowest_ever"] is not None
            and row["best_price"] <= row["lowest_ever"]
        )
    return {"total": total, "rows": rows, "offset": query.safe_offset(), "limit": query.safe_limit()}


def watch_status(
    conn: sqlite3.Connection, items: list[dict[str, Any]], aliases: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Each watched game with its current best offer, and whether it hit target.

    A hit needs the best offer to be IN STOCK: "₹2,999, sold out" is not a
    price anyone can act on, and alerting on it would train the user to ignore
    the alert.

    ``aliases`` is the matcher's map (match key -> key it groups under). A key
    watched BEFORE an alias was added is resolved through it, or adding the
    alias that fixes a split would silently orphan the watch.
    """
    aliases = aliases or {}
    # ponytail: one games() query per watched item. Watchlists are tens of
    # games, not thousands; batch into one query if that ever stops being true.
    out = []
    for item in items:
        key = aliases.get(item["game"], item["game"])
        # A "New only" watch is the same games() query with the condition
        # filter set, so best price, stock and lowest-ever all agree with it.
        condition = "NEW" if item.get("condition") == "NEW" else ""
        found = games(conn, ListingQuery(game=key, platform=item["platform"], condition=condition, limit=1))[
            "rows"
        ]
        best = found[0] if found else None
        target = item.get("target")
        hit = bool(
            best
            and best["best_in_stock"]
            and best["best_price"] is not None  # no rupee price yet: nothing to compare
            and target is not None
            and best["best_price"] <= target
        )
        out.append({**item, "best": best, "hit": hit})
    # Hits first: they are the reason the panel exists.
    out.sort(key=lambda r: (not r["hit"], (r["best"] or {}).get("title") or r["game"]))
    return out


def movers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
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

    # Ignore tiny currency and store changes in the movers panel and its counts.
    rows = [row for row in rows if abs(pct_of(row)) > MIN_CHANGE_PCT]

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
    return enriched


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
