"""SQLite schema and connections.

The seven original tables are reproduced byte-identically from src/core/db.ts,
because the Python build opens the SAME data/tracker.db the TypeScript build
writes.  That makes migration a non-event -- and makes any accidental column
rename a silent loss of the accumulated price history, which is the one thing
this project exists to accumulate.

Two additive changes, both deliberate:

  * ``run_event`` -- durable progress, so a closed tab or a restarted
    dashboard loses nothing (HLD option 3).
  * ``idx_run_active`` -- a partial unique index permitting at most one
    unfinished run.  This is the authoritative half of the concurrency guard;
    the disabled button in the UI is cosmetic and must never be relied on.

One deviation: ``price_point.inr_price`` becomes nullable.  See fx/rates.py --
when no exchange rate is stored, recording NO number is correct and recording
the native figure as though it were rupees is not.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from switch_tracker import paths

#: 3 == SERIALIZED. Anything lower means SQLite is not taking the lock for us
#: and sharing a connection between threads would be a genuine data race.
_REQUIRED_THREADSAFETY = 3

# --- The 7 tables, verbatim from db.ts. Do not "tidy" these.
_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS store (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  base_url    TEXT NOT NULL,
  kind        TEXT NOT NULL,
  currency    TEXT NOT NULL,
  tier        INTEGER NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS game (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_title TEXT NOT NULL,
  platform        TEXT NOT NULL,
  region          TEXT NOT NULL,
  UNIQUE (canonical_title, platform, region)
);

CREATE TABLE IF NOT EXISTS listing (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id    TEXT NOT NULL REFERENCES store(id),
  sku         TEXT NOT NULL,
  game_id     INTEGER REFERENCES game(id),
  url         TEXT NOT NULL,
  raw_title   TEXT NOT NULL,
  platform    TEXT NOT NULL,
  region      TEXT NOT NULL,
  condition   TEXT NOT NULL DEFAULT 'NEW',
  image_url   TEXT,
  first_seen  TEXT NOT NULL,
  last_seen   TEXT NOT NULL,
  UNIQUE (store_id, sku)
);

CREATE INDEX IF NOT EXISTS idx_listing_game ON listing(game_id);
CREATE INDEX IF NOT EXISTS idx_listing_unmatched ON listing(game_id) WHERE game_id IS NULL;

CREATE TABLE IF NOT EXISTS fx_rate (
  base        TEXT NOT NULL,
  quote       TEXT NOT NULL,
  rate        REAL NOT NULL,
  rate_date   TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY (base, quote, rate_date)
);

CREATE TABLE IF NOT EXISTS run (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS price_point (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id      INTEGER NOT NULL REFERENCES listing(id),
  run_id          INTEGER NOT NULL REFERENCES run(id),
  captured_at     TEXT NOT NULL,
  native_currency TEXT NOT NULL,
  native_price    REAL NOT NULL,
  inr_price       REAL,
  fx_rate_date    TEXT,
  in_stock        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pp_listing_time ON price_point(listing_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_pp_run ON price_point(run_id);

CREATE TABLE IF NOT EXISTS run_store (
  run_id         INTEGER NOT NULL REFERENCES run(id),
  store_id       TEXT NOT NULL REFERENCES store(id),
  status         TEXT NOT NULL,
  listings_found INTEGER NOT NULL DEFAULT 0,
  duration_ms    INTEGER NOT NULL DEFAULT 0,
  detail         TEXT,
  PRIMARY KEY (run_id, store_id)
);
"""

# --- Additive: durable progress + the authoritative concurrency guard.
_ADDITIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_event (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      INTEGER NOT NULL REFERENCES run(id),
  at          TEXT    NOT NULL,
  kind        TEXT    NOT NULL,
  store_id    TEXT,
  status      TEXT,
  count       INTEGER,
  page        INTEGER,
  duration_ms INTEGER,
  detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_event_run_seq ON run_event(run_id, seq);

-- At most one unfinished run, enforced by the database rather than by hope.
-- A double-clicked button, a page refresh and a second browser tab all reach
-- this; only the first gets a row.
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_active ON run((1)) WHERE finished_at IS NULL;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or paths.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        target,
        isolation_level=None,
        # The dashboard shares one connection across threads by necessity:
        # Starlette runs sync endpoints in a threadpool, and the SSE tail uses
        # asyncio.to_thread so a blocking read cannot stall the event loop
        # serving every other request. Python's sqlite3 defaults to refusing
        # that outright.
        #
        # Safe here because sqlite3.threadsafety is 3 (SERIALIZED): SQLite
        # itself takes the lock. Asserted below rather than assumed, since a
        # differently-compiled interpreter could report 1 and this would
        # silently become a data race.
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # A worker writing while the dashboard reads is normal here; wait rather
    # than fail the moment the two overlap.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def assert_threadsafe() -> None:
    if sqlite3.threadsafety < _REQUIRED_THREADSAFETY:
        raise RuntimeError(
            f"This Python's sqlite3 reports threadsafety={sqlite3.threadsafety}; "
            f"{_REQUIRED_THREADSAFETY} (serialized) is required to share a connection "
            "across the dashboard's threads."
        )


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_LEGACY_SCHEMA)
    conn.executescript(_ADDITIVE_SCHEMA)
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Column additions that CREATE TABLE IF NOT EXISTS can never apply.

    A database written before a column existed keeps missing it forever
    otherwise.  Guarded by table_info rather than a bare ALTER, since
    re-running that on a database which already has the column throws.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(listing)")}
    if columns and "condition" not in columns:
        conn.execute("ALTER TABLE listing ADD COLUMN condition TEXT NOT NULL DEFAULT 'NEW'")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
