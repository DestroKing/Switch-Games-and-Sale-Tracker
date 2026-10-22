"""Sanity-check the collected data, after a collection. Read-only.

check_stores.py asks "does each shop still scrape?". This asks the other
question: "is what was saved right?" -- per store, titles a shop cut short,
latest prices that are zero/negative or have no rupee figure, listings the
matcher could not group; then how many games are compared across stores, and
any watched game the watchlist can no longer find.

    uv run python scripts/check_data.py
    uv run python scripts/check_data.py --db path/to/tracker.db
    uv run python scripts/check_data.py --review       what a rematch would change, and
                                                        games that may still be split

Exit code 1 when something needs looking at, so it can gate a release.
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from switch_tracker import paths
from switch_tracker.core import db, matcher
from switch_tracker.web import queries, watchlist

#: The usual cause: this window still has troubleshooting.md section 1's scratch
#: folder set, so it reads a different database from the dashboard's.
_WHICH_DB = (
    "\nIf the dashboard does show prices, this window is pointed elsewhere: close it, or clear"
    "\nTRACKER_DATA_DIR / TRACKER_DB (Command Prompt: set TRACKER_DATA_DIR=), or pass --db."
    if os.environ.get("TRACKER_DATA_DIR") or os.environ.get("TRACKER_DB")
    else ""
)

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
-- Each store's latest run is found once, not once per price row: per row, it
-- rescanned the store's whole history and slowed down as the database grew.
last_run AS (
  SELECT x.store_id, MAX(pp.run_id) AS run_id
  FROM price_point pp JOIN listing x ON x.id = pp.listing_id GROUP BY x.store_id
),
current AS (
  SELECT p.listing_id FROM price_point p JOIN listing l ON l.id = p.listing_id
  JOIN last_run r ON r.store_id = l.store_id AND r.run_id = p.run_id
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


def review(conn: sqlite3.Connection, limit: int) -> None:
    """Read-only. What `switch-tracker match` would change today, and what it still leaves split.

    The second list is the review queue: pairs the matcher deliberately won't
    merge on its own, because "one or two extra words" is also how a Deluxe or a
    sequel looks. Settle a real one with an alias in matches.local.json.
    """
    listings = conn.execute(
        "SELECT l.id, l.store_id, l.raw_title, l.platform, l.region, g.canonical_title AS stored "
        "FROM listing l LEFT JOIN game g ON g.id = l.game_id"
    ).fetchall()
    by_id = {r["id"]: r for r in listings}
    assigned = matcher.assign(listings, matcher.load_aliases())

    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for lid, key_platform in assigned.items():
        groups[key_platform].append(lid)

    def sample(ids: list[int]) -> None:
        for lid in sorted(ids, key=lambda i: by_id[i]["store_id"])[:3]:
            print(f"      {by_id[lid]['store_id']:14}{by_id[lid]['raw_title'][:90]!r}")

    merges = [
        (kp, ids, olds)
        for kp, ids in groups.items()
        if len(olds := {(by_id[i]["stored"] or "(ungrouped)", by_id[i]["platform"]) for i in ids}) > 1
    ]
    relabelled = [lid for lid, (_, platform) in assigned.items() if platform != by_id[lid]["platform"]]
    print(f"\nA rematch would merge {len(merges)} group(s) and relabel {len(relabelled)} platform(s):")
    for (key, platform), ids, olds in sorted(merges)[:limit]:
        print(f"  {platform:8}{key!r}  <-  {sorted(o[0] for o in olds)}")
        sample(ids)
    if len(merges) > limit:
        print(f"  ... and {len(merges) - limit} more (--limit)")
    for lid in relabelled[:limit]:
        print(f"  {by_id[lid]['platform']} -> {assigned[lid][1]}: {by_id[lid]['raw_title'][:90]!r}")

    # Possibly the same game: one key is the other plus one or two words that are
    # not a number, a variant word, or a named edition ("Divine Edition").
    index: dict[tuple[str, frozenset[str]], list[str]] = defaultdict(list)
    for key, platform in groups:
        index[(platform, frozenset(key.split()))].append(key)
    pairs = set()
    for key, platform in groups:
        words = frozenset(key.split())
        titles = " ".join(by_id[i]["raw_title"].lower() for i in groups[(key, platform)])
        for n in (1, 2):
            for extra in itertools.combinations(sorted(words), n):
                if any(w in matcher.VARIANT_WORDS or any(c.isdigit() for c in w) for w in extra):
                    continue
                if any(re.search(rf"\b{re.escape(w)}\W+edition\b", titles) for w in extra):
                    continue
                for other in index.get((platform, words - set(extra)), []):
                    if len(other.split()) >= 2:
                        pairs.add((platform, other, key))
    print(f"\nPossibly the same game, still separate: {len(pairs)} pair(s). Same game? Add an alias:")
    for platform, short, long in sorted(pairs)[:limit]:
        print(f"  {platform:8}{short!r}  vs  {long!r}")
        sample(groups[(short, platform)][:1] + groups[(long, platform)][:1])
    if len(pairs) > limit:
        print(f"  ... and {len(pairs) - limit} more (--limit)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, help="default: the app's own database")
    parser.add_argument("--review", action="store_true", help="preview a rematch and list possible splits")
    parser.add_argument("--limit", type=int, default=60, help="rows per --review list (default 60)")
    args = parser.parse_args(argv)

    target = args.db or paths.db_path()
    print(f"Database: {target}\n")
    # Read-only: never create a database here; an empty one would only hide the mistake.
    if not target.exists():
        print(
            "No database at that path -- start the dashboard and press Collect prices"
            " (check_stores.py only tests the shops; it saves nothing)." + _WHICH_DB
        )
        return 1
    conn = db.connect(target)
    db.ensure_schema(conn)
    rows = conn.execute(_PER_STORE).fetchall()
    if not rows:
        print(
            "No listings in it yet -- press Collect prices in the dashboard first"
            " (check_stores.py only tests the shops; it saves nothing)." + _WHICH_DB
        )
        return 1

    print(f"{'store':16}{'listings':>9}{'cut':>6}{'bad price':>11}{'no INR':>8}{'ungrouped':>11}")
    for r in rows:
        print(
            f"{r['store_id']:16}{r['listings']:>9}{r['cut_titles']:>6}{r['bad_prices']:>11}"
            f"{r['no_rupee_price']:>8}{r['ungrouped']:>11}"
        )

    # Not a failure, but these never reach Games: their title keyed to nothing.
    ungrouped = conn.execute(
        "SELECT store_id, raw_title FROM listing WHERE game_id IS NULL AND platform != 'UNKNOWN'"
        " ORDER BY store_id, raw_title"
    ).fetchall()
    if ungrouped:
        print("\nUngrouped (shown in Every listing, never in Games):")
        for r in ungrouped[:30]:
            print(f"  {r['store_id']:16}{r['raw_title']!r}")
        if len(ungrouped) > 30:
            print(f"  ... and {len(ungrouped) - 30} more")

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

    if args.review:
        review(conn, args.limit)

    problems = sum(r["cut_titles"] + r["bad_prices"] for r in rows)
    print(
        "\nOK"
        if not problems
        else "\nSomething to look at -- see docs/troubleshooting.md, 'After a collection'."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
