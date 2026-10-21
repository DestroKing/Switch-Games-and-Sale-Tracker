"""The watchlist: games you want to hear about, and the price that would do it.

A file in the data directory, not a table, for two reasons. The dashboard
keeps its database writes to run bookkeeping -- price data is written by
workers only -- and this is user preference, the same category as
stores.local.json. It also survives deleting tracker.db, which is exactly
when you would least want to re-enter every target.

Keyed by game key + platform, NOT by game id: a game's id is not stable
across matcher changes (a key that changes is a deleted game and a new one),
so a watchlist of ids would silently empty itself the first time the matcher
improved. Keys can change too -- an alias renames one -- which is why
queries.watch_status resolves each watched key through the aliases.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from switch_tracker import paths

#: FastAPI runs these sync endpoints on a THREAD POOL, so two quick clicks are
#: two concurrent read-modify-writes. Unlocked, the second could read the list
#: before the first wrote it (losing a watch), or read a half-written file as
#: empty and then write a one-item list over everything. One process serves
#: the dashboard, so an in-process lock is the whole of the problem.
#:
#: Re-entrant, and taken by read() too: on Windows os.replace() fails with
#: PermissionError while another thread has the target open, so an unlocked
#: GET reading mid-write could fail a concurrent PUT.
_LOCK = threading.RLock()


def _parse(item: Any) -> dict[str, Any] | None:
    # The file is hand-editable, so it is a trust boundary: a target typed as
    # "4000" (a string) would otherwise reach a numeric comparison and take the
    # whole watchlist down with a 500. Anything that is not a positive number
    # means "no target", which is the safe reading.
    if not (
        isinstance(item, dict) and isinstance(item.get("game"), str) and isinstance(item.get("platform"), str)
    ):
        return None
    target = item.get("target")
    if isinstance(target, bool) or not isinstance(target, (int, float)) or target <= 0:
        target = None
    return {
        "game": item["game"],
        "platform": item["platform"],
        "target": None if target is None else float(target),
    }


def read() -> list[dict[str, Any]]:
    path = paths.watchlist_path()
    with _LOCK:
        if not path.exists():
            return []
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable is treated as empty for READING only -- see _write().
            return []
    if not isinstance(loaded, list):
        return []
    return [parsed for parsed in map(_parse, loaded) if parsed is not None]


def _write(items: list[dict[str, Any]]) -> None:
    path = paths.watchlist_path()
    if path.exists():
        try:
            usable = isinstance(json.loads(path.read_text(encoding="utf-8")), list)
        except ValueError:
            usable = False
        if not usable:
            # read() saw this file as empty -- broken JSON, or valid JSON that is
            # not a list. Writing now would replace a hand-edited file with one
            # entry, so set it aside rather than over it.
            # Uniquely named (ns clock; sorts oldest first), so a second bad
            # edit never overwrites the first.
            path.replace(path.with_suffix(f".json.bad-{time.time_ns()}"))
    # Write-then-rename, so a reader never sees a truncated file: os.replace is
    # atomic on the same volume, where write_text empties the file first.
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


#: Each watched game costs the dashboard one query per page load, so an
#: unbounded list is a way to make it crawl. Far above any real watchlist.
MAX_ITEMS = 500


class WatchlistFull(Exception):
    """Adding one more would exceed MAX_ITEMS."""


def upsert(game: str, platform: str, target: float | None) -> list[dict[str, Any]]:
    with _LOCK:
        items = [i for i in read() if (i["game"], i["platform"]) != (game, platform)]
        if len(items) >= MAX_ITEMS:
            raise WatchlistFull(f"The watchlist is limited to {MAX_ITEMS} games.")
        items.append({"game": game, "platform": platform, "target": target})
        _write(items)
        return items


def remove(game: str, platform: str) -> list[dict[str, Any]]:
    with _LOCK:
        items = [i for i in read() if (i["game"], i["platform"]) != (game, platform)]
        _write(items)
        return items
