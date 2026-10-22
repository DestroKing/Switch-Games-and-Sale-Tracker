"""The watchlist: read it with current prices, add or retarget a game, drop one."""

from __future__ import annotations

import sqlite3
from typing import Literal

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
    #: None = "tell me what it costs", with no alert. OMITTED = keep the current
    #: target (see watchlist.upsert), which is what the Any/New toggle relies on.
    target: float | None = Field(default=None, gt=0, le=100_000)
    #: Which copies count: ANY (new or pre-owned) or NEW only. Omitted = keep
    #: the watch's current setting (see watchlist.upsert).
    condition: Literal["ANY", "NEW"] | None = None
    #: Which shops count: ALL, or INDIA (no shop that ships from abroad).
    #: Omitted = keep the watch's current setting, as for condition.
    shops: Literal["ALL", "INDIA"] | None = None


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
        # An OMITTED target means "keep it", an explicit null means "clear it".
        # Pydantic gives both as None; model_fields_set is what tells them apart.
        target = item.target if "target" in item.model_fields_set else watchlist.KEEP
        watchlist.upsert(item.game, item.platform, target, item.condition, item.shops)
    except watchlist.WatchlistFull as exc:
        return problem(400, str(exc))
    return _status(conn)


@router.delete("")
def remove(game: str, platform: str, conn: Conn) -> list[dict[str, object]]:
    watchlist.remove(game, platform)
    return _status(conn)
