"""Read-only JSON endpoints. Ported from server.ts, SQL and all."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from switch_tracker import selection
from switch_tracker.web import queries
from switch_tracker.web.deps import get_conn

#: FastAPI's Annotated form. The bare Depends()-in-default idiom is a mutable
#: default in every other context, which is why linters flag it.
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/summary")
def summary(conn: Conn) -> dict[str, int]:
    return queries.summary(conn)


@router.get("/health")
def health(conn: Conn) -> dict[str, object]:
    return queries.health(conn)


@router.get("/movers")
def movers(conn: Conn) -> list[dict[str, object]]:
    return queries.movers(conn)


@router.get("/facets")
def facets(conn: Conn) -> dict[str, list[dict[str, object]]]:
    return queries.facets(conn)


@router.get("/history")
def history(id: int, conn: Conn) -> list[dict[str, object]]:
    """A single listing's price series -- the chart under an expanded row."""
    return queries.history(conn, id)


def _query(
    q: str,
    platform: str,
    region: str,
    store: str,
    condition: str,
    in_stock: bool,
    game: str,
    sort: str,
    dir: str,
    limit: int,
    offset: int,
) -> queries.ListingQuery:
    return queries.ListingQuery(
        q=q,
        platform=platform,
        regions=selection.parse_ids(region),
        stores=selection.parse_ids(store),
        condition=condition,
        in_stock_only=in_stock,
        game=game,
        sort=sort,
        direction=dir,
        limit=limit,
        offset=offset,
    )


@router.get("/games")
def games(
    conn: Conn,
    q: str = "",
    platform: str = "",
    region: str = "",
    store: str = "",
    condition: str = "",
    in_stock: bool = False,
    sort: str = "price",
    dir: str = "asc",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """One row per matched game. Takes exactly the filters /listings does."""
    return queries.games(
        conn, _query(q, platform, region, store, condition, in_stock, "", sort, dir, limit, offset)
    )


@router.get("/listings")
def listings(
    conn: Conn,
    q: str = "",
    platform: str = "",
    #: Comma-separated, e.g. ?store=amazon_in,playasia -- the same encoding
    #: /actions/collect?only=a,b uses, so the app has ONE way to spell "a set of
    #: ids". Kept singular in the URL so existing single-value links and
    #: bookmarks (?store=amazon_in) keep working untouched.
    region: str = "",
    store: str = "",
    condition: str = "",
    in_stock: bool = False,
    #: A game key from /api/games: just that game's offers.
    game: str = "",
    sort: str = "price",
    dir: str = "asc",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return queries.listings(
        conn, _query(q, platform, region, store, condition, in_stock, game, sort, dir, limit, offset)
    )
