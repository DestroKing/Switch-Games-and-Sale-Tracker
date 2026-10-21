"""The watchlist: read it with current prices, add or retarget a game, drop one."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from switch_tracker.core import matcher
from switch_tracker.web import queries, watchlist
from switch_tracker.web.errors import problem
from switch_tracker.web.routers.data import Conn

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchItem(BaseModel):
    game: str = Field(min_length=1, max_length=300)
    platform: str = Field(pattern=r"^(SWITCH|SWITCH2)$")
    #: None = "tell me what it costs", with no alert.
    target: float | None = Field(default=None, gt=0, le=100_000)


def _status(conn: sqlite3.Connection) -> list[dict[str, object]]:
    # Read per request, not cached: matches.local.json is hand-edited, and a
    # stale copy would orphan exactly the watch the user just fixed an alias for.
    return queries.watch_status(conn, watchlist.read(), matcher.load_aliases())


@router.get("")
def read(conn: Conn) -> list[dict[str, object]]:
    return _status(conn)


@router.put("", response_model=None)
def upsert(item: WatchItem, conn: Conn) -> list[dict[str, object]] | JSONResponse:
    try:
        watchlist.upsert(item.game, item.platform, item.target)
    except watchlist.WatchlistFull as exc:
        return problem(400, str(exc))
    return _status(conn)


@router.delete("")
def remove(game: str, platform: str, conn: Conn) -> list[dict[str, object]]:
    watchlist.remove(game, platform)
    return _status(conn)
