"""Sanity-check the collected data, after a collection. Read-only.

check_stores.py asks "does each shop still scrape?". This asks the other
question: "is what was saved right?" -- per store, titles a shop cut short,
latest prices that are zero/negative or have no rupee figure, listings the
matcher could not group; then how many games are compared across stores, and
any watched game the watchlist can no longer find.

    uv run python scripts/check_data.py
    uv run python scripts/check_data.py --db path/to/tracker.db

Exit code 1 when something needs looking at, so it can gate a release.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from switch_tracker.core import db, matcher
from switch_tracker.web import queries, watchlist

# The newest price per listing: what the dashboard shows today.
_PER_STORE = """
WITH latest AS (
  SELECT p.listing_id, p.native_price, p.inr_price
  FROM price_point p
  WHERE p.id = (SELECT id FROM price_point WHERE listing_id = p.listing_id
                ORDER BY captured_at DESC, id DESC LIMIT 1)
),
-- Listings each store showed in its most recent run. A cut title on a listing the
-- shop has since stopped showing is repaired the next time it appears, so only
-- these count.
current AS (
  SELECT p.listing_id FROM price_point p JOIN listing l ON l.id = p.listing_id
  WHERE p.run_id = (SELECT MAX(pp.run_id) FROM price_point pp JOIN listing x ON x.id = pp.listing_id
                    WHERE x.store_id = l.store_id)
)
SELECT l.store_id,
       COUNT(*)                                                                 AS listings,
       COALESCE(SUM((l.raw_title LIKE '%...' OR l.raw_title LIKE '%' || char(8230))
                    AND l.id IN (SELECT listing_id FROM current)), 0)       AS cut_titles,
       COALESCE(SUM(lt.native_price <= 0 OR lt.inr_price <= 0), 0)            AS bad_prices,
       COALESCE(SUM(lt.listing_id IS NOT NULL AND lt.inr_price IS NULL), 0)   AS no_rupee_price,
       COALESCE(SUM(l.game_id IS NULL AND l.platform != 'UNKNOWN'), 0)        AS ungrouped
FROM listing l LEFT JOIN latest lt ON lt.listing_id = l.id
GROUP BY l.store_id ORDER BY l.store_id
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, help="default: the app's own database")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.ensure_schema(conn)
    rows = conn.execute(_PER_STORE).fetchall()
    if not rows:
        print("No listings yet -- collect first.")
        return 1

    print(f"{'store':16}{'listings':>9}{'cut':>6}{'bad price':>11}{'no INR':>8}{'ungrouped':>11}")
    for r in rows:
        print(
            f"{r['store_id']:16}{r['listings']:>9}{r['cut_titles']:>6}{r['bad_prices']:>11}"
            f"{r['no_rupee_price']:>8}{r['ungrouped']:>11}"
        )

    shared = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT g.canonical_title, g.platform FROM game g JOIN listing l ON l.game_id = g.id
             GROUP BY g.canonical_title, g.platform HAVING COUNT(DISTINCT l.store_id) > 1)"""
    ).fetchone()[0]
    games = conn.execute("SELECT COUNT(DISTINCT canonical_title || '|' || platform) FROM game").fetchone()[0]
    print(f"\n{games} games, {shared} of them compared across 2+ stores.")

    # Informational: a game sold out everywhere has no offer either, which is not a bug.
    orphans = [
        w["game"]
        for w in queries.watch_status(conn, watchlist.read(), matcher.load_aliases())
        if w["best"] is None
    ]
    print(f"Watched games with no offer today: {len(orphans)}" + (f" -- {orphans}" if orphans else ""))

    problems = sum(r["cut_titles"] + r["bad_prices"] for r in rows)
    print(
        "\nOK"
        if not problems
        else "\nSomething to look at -- see docs/troubleshooting.md, 'After a collection'."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
