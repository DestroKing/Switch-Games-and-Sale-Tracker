"""Validated human review operations for game releases and listing matches."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Iterator

from switch_tracker.core.db import now_iso
from switch_tracker.core.matcher import match_key
from switch_tracker.market import audit, identity
from switch_tracker.market.models import Format


class ReviewError(ValueError):
    """A review request cannot be applied to the current market catalogue."""


def _exists(conn: sqlite3.Connection, table: str, entity_id: int) -> sqlite3.Row | None:
    if table not in {"listing", "release"}:
        raise ValueError("unsupported review entity")
    return conn.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()


def _release_final(conn: sqlite3.Connection, release_id: int) -> int:
    seen: set[int] = set()
    current = release_id
    while True:
        if current in seen:
            raise ReviewError("Release aliases contain a cycle")
        seen.add(current)
        row = conn.execute("SELECT target_id FROM release_alias WHERE release_id=?", (current,)).fetchone()
        if row is None:
            return current
        current = int(row[0])


def _rematch(conn: sqlite3.Connection) -> None:
    identity.rematch(conn)


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Atomically pair review changes with their audit row, even in autocommit mode."""
    conn.execute("SAVEPOINT market_review")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK TO market_review")
        conn.execute("RELEASE market_review")
        raise
    else:
        conn.execute("RELEASE market_review")


def confirm(conn: sqlite3.Connection, listing_id: int, release_id: int, note: str = "") -> None:
    with _transaction(conn):
        listing = _exists(conn, "listing", listing_id)
        release = _exists(conn, "release", release_id)
        if listing is None:
            raise ReviewError(f"Listing {listing_id} does not exist")
        if release is None:
            raise ReviewError(f"Release {release_id} does not exist")
        if listing["platform"] != release["platform"]:
            raise ReviewError("A listing and release must have the same platform")
        before = conn.execute("SELECT * FROM listing_match WHERE listing_id=?", (listing_id,)).fetchone()
        conn.execute(
            "INSERT INTO listing_match (listing_id, release_id, tier, reasons, decided_at) "
            "VALUES (?, ?, 'CONFIRMED', ?, ?) ON CONFLICT(listing_id) DO UPDATE SET "
            "release_id=excluded.release_id, tier='CONFIRMED', reasons=excluded.reasons, decided_at=excluded.decided_at",
            (listing_id, release_id, json.dumps(["confirmed by review"]), now_iso()),
        )
        conn.execute("UPDATE release SET verified=1 WHERE id=?", (release_id,))
        conn.execute("DELETE FROM match_rejection WHERE listing_id=? AND release_id=?", (listing_id, release_id))
        audit.record(conn, "listing", listing_id, "confirm", dict(before) if before else None,
                     {"release_id": release_id, "tier": "CONFIRMED"}, note)
    _rematch(conn)


def reject(conn: sqlite3.Connection, listing_id: int, release_id: int, note: str = "") -> None:
    with conn:
        listing = _exists(conn, "listing", listing_id)
        release = _exists(conn, "release", release_id)
        if listing is None:
            raise ReviewError(f"Listing {listing_id} does not exist")
        if release is None:
            raise ReviewError(f"Release {release_id} does not exist")
        before = conn.execute("SELECT * FROM listing_match WHERE listing_id=?", (listing_id,)).fetchone()
        conn.execute(
            "INSERT INTO match_rejection (listing_id, release_id, at) VALUES (?, ?, ?) "
            "ON CONFLICT(listing_id, release_id) DO NOTHING",
            (listing_id, release_id, now_iso()),
        )
        if before is not None and before["release_id"] == release_id:
            conn.execute(
                "UPDATE listing_match SET release_id=NULL, tier='UNMATCHED', reasons=?, decided_at=? "
                "WHERE listing_id=?",
                (json.dumps(["rejected by review"]), now_iso(), listing_id),
            )
        audit.record(conn, "listing", listing_id, "reject", dict(before) if before else None,
                     {"rejected_release_id": release_id}, note)
    _rematch(conn)


def reset(conn: sqlite3.Connection, listing_id: int, note: str = "") -> None:
    with conn:
        listing = _exists(conn, "listing", listing_id)
        if listing is None:
            raise ReviewError(f"Listing {listing_id} does not exist")
        before = conn.execute("SELECT * FROM listing_match WHERE listing_id=?", (listing_id,)).fetchone()
        if before is None or before["tier"] != "CONFIRMED":
            raise ReviewError(f"Listing {listing_id} has no confirmed match to reset")
        conn.execute("DELETE FROM listing_match WHERE listing_id=?", (listing_id,))
        audit.record(conn, "listing", listing_id, "reset", dict(before), None, note)
    _rematch(conn)


def split(
    conn: sqlite3.Connection,
    listing_ids: Sequence[int],
    *,
    edition: str,
    region: str,
    format: Format,
    title: str | None = None,
    note: str = "",
) -> int:
    ids = list(dict.fromkeys(int(value) for value in listing_ids))
    if not ids:
        raise ReviewError("Select at least one listing to split")
    with conn:
        placeholders = ",".join("?" for _ in ids)
        listings = conn.execute(
            f"SELECT * FROM listing WHERE id IN ({placeholders}) ORDER BY id", ids
        ).fetchall()
        if len(listings) != len(ids):
            raise ReviewError("One or more selected listings do not exist")
        platforms = {row["platform"] for row in listings}
        if len(platforms) != 1:
            raise ReviewError("Selected listings must have the same platform")
        if title is not None:
            key = match_key(title)
            if not key:
                raise ReviewError("The supplied game title has no matchable words")
            conn.execute(
                "INSERT INTO game (title, key) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                (title.strip(), key),
            )
            game_id = int(conn.execute("SELECT id FROM game WHERE key=?", (key,)).fetchone()[0])
        else:
            existing = conn.execute(
                "SELECT r.game_id FROM listing_match lm JOIN release r ON r.id=lm.release_id "
                "WHERE lm.listing_id=?",
                (ids[0],),
            ).fetchone()
            if existing is None:
                raise ReviewError("The first listing has no game identity; provide a title")
            game_id = int(existing[0])
        release_id = identity.get_or_create_release(
            conn, game_id, next(iter(platforms)), edition, region,
            format if isinstance(format, Format) else Format(format),
        )
        conn.execute("UPDATE release SET verified=1 WHERE id=?", (release_id,))
        before = []
        for listing_id in ids:
            row = conn.execute("SELECT * FROM listing_match WHERE listing_id=?", (listing_id,)).fetchone()
            before.append({"listing_id": listing_id, "match": dict(row) if row else None})
            conn.execute(
                "INSERT INTO listing_match (listing_id, release_id, tier, reasons, decided_at) "
                "VALUES (?, ?, 'CONFIRMED', ?, ?) ON CONFLICT(listing_id) DO UPDATE SET "
                "release_id=excluded.release_id, tier='CONFIRMED', reasons=excluded.reasons, decided_at=excluded.decided_at",
                (listing_id, release_id, json.dumps(["confirmed by review"]), now_iso()),
            )
        audit.record(conn, "release", release_id, "split", before,
                     {"listing_ids": ids, "game_id": game_id, "edition": edition,
                      "region": region, "format": str(format)}, note)
    _rematch(conn)
    return release_id


def merge(conn: sqlite3.Connection, source_id: int, target_id: int, note: str = "") -> int:
    with conn:
        if source_id == target_id:
            raise ReviewError("A release cannot be merged into itself")
        source = _exists(conn, "release", source_id)
        target = _exists(conn, "release", target_id)
        if source is None:
            raise ReviewError(f"Source release {source_id} does not exist")
        if target is None:
            raise ReviewError(f"Target release {target_id} does not exist")
        final_target = _release_final(conn, target_id)
        final_row = _exists(conn, "release", final_target)
        if final_row is None or source["platform"] != final_row["platform"]:
            raise ReviewError("Merged releases must have the same platform")
        if final_target == source_id:
            raise ReviewError("This merge would create a release alias cycle")
        if conn.execute("SELECT 1 FROM release_alias WHERE release_id=?", (source_id,)).fetchone():
            raise ReviewError(f"Release {source_id} is already an alias")
        confirmed = [dict(row) for row in conn.execute(
            "SELECT * FROM listing_match WHERE release_id=? AND tier='CONFIRMED'", (source_id,)
        )]
        evidence_ids = [int(row[0]) for row in conn.execute(
            "SELECT id FROM evidence WHERE release_id=? ORDER BY id", (source_id,)
        )]
        codes = [str(row[0]) for row in conn.execute(
            "SELECT code FROM release_code WHERE release_id=? ORDER BY code", (source_id,)
        )]
        conn.execute(
            "INSERT INTO release_alias (release_id, target_id, at) VALUES (?, ?, ?)",
            (source_id, final_target, now_iso()),
        )
        conn.execute(
            "UPDATE listing_match SET release_id=?, decided_at=? WHERE release_id=? AND tier='CONFIRMED'",
            (final_target, now_iso(), source_id),
        )
        for code in codes:
            owner = conn.execute("SELECT release_id FROM release_code WHERE code=?", (code,)).fetchone()
            if owner is not None and int(owner[0]) == source_id:
                duplicate = conn.execute(
                    "SELECT 1 FROM release_code WHERE code=? AND release_id=?", (code, final_target)
                ).fetchone()
                if duplicate:
                    conn.execute("DELETE FROM release_code WHERE code=?", (code,))
                else:
                    conn.execute("UPDATE release_code SET release_id=? WHERE code=?", (final_target, code))
        conn.execute("UPDATE evidence SET release_id=? WHERE release_id=?", (final_target, source_id))
        audit.record(conn, "release", source_id, "merge",
                     {"target_id": target_id, "confirmed_matches": confirmed, "codes": codes},
                     {"target_id": final_target, "evidence_ids": evidence_ids}, note)
    _rematch(conn)
    return final_target
