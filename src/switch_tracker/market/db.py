"""market.db: the market tracker's own file, schema and backups.

A separate file rather than tables in tracker.db, so that removing the
feature is deleting a file, and so that no market migration can ever be the
thing that damages the price history.

Migrations are an append-only tuple applied under ``PRAGMA user_version``.
Never edit a shipped entry: a database that already ran it will not run it
again, so an edit would silently fork the schema between installs.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from switch_tracker import paths
from switch_tracker.core.db import connect

# v1: the whole model, designed in one piece (docs/market-tracker-design.md, 3.3).
#
# No foreign key ever points into tracker.db -- it is another file. Storefronts
# are keyed by the price tracker's store id string, and scans carry its run id
# as a plain integer, so either side can be deleted without the other failing.
_V1 = """
CREATE TABLE retailer (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  -- A marketplace is never counted as an independent retailer.
  kind         TEXT NOT NULL CHECK (kind IN ('INDEPENDENT', 'MARKETPLACE')),
  verification TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification IN ('VERIFIED', 'UNVERIFIED')),
  note         TEXT NOT NULL DEFAULT '',
  verified_at  TEXT
);

-- One scanned site. Several storefronts of one business share a retailer, which
-- is what stops them counting as several independent shops.
CREATE TABLE storefront (
  id                TEXT PRIMARY KEY,
  retailer_id       TEXT NOT NULL REFERENCES retailer(id),
  name              TEXT NOT NULL,
  base_url          TEXT NOT NULL,
  -- REPORTED: the store's API states stock. INFERRED: a page showed no sold-out marker.
  stock_signal      TEXT NOT NULL CHECK (stock_signal IN ('REPORTED', 'INFERRED')),
  ships_from_abroad INTEGER NOT NULL DEFAULT 0
);

-- What a scan covered. A changed store configuration is a NEW scope, so an
-- absence can never be reconciled across two different definitions.
CREATE TABLE scope (
  id            INTEGER PRIMARY KEY,
  storefront_id TEXT NOT NULL REFERENCES storefront(id),
  kind          TEXT NOT NULL
                CHECK (kind IN ('CATALOGUE', 'CATEGORY', 'SEARCH', 'BROWSE', 'MANUAL', 'UNKNOWN')),
  definition    TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  UNIQUE (storefront_id, definition)
);

CREATE TABLE scan (
  id              INTEGER PRIMARY KEY,
  scope_id        INTEGER NOT NULL REFERENCES scope(id),
  legacy_run_id   INTEGER,
  started_at      TEXT NOT NULL,
  finished_at     TEXT NOT NULL,
  -- The adapter's own word, kept beside the verdict so the two can disagree visibly.
  outcome         TEXT NOT NULL CHECK (outcome IN ('OK', 'PARTIAL', 'FAILED')),
  coverage        TEXT NOT NULL CHECK (coverage IN ('COMPLETE', 'PARTIAL', 'FAILED', 'UNKNOWN')),
  pages_attempted INTEGER,
  pages_completed INTEGER,
  claimed_total   INTEGER,
  raw_seen        INTEGER,
  end_reached     INTEGER,
  listings_seen   INTEGER NOT NULL DEFAULT 0,
  evidence        TEXT NOT NULL DEFAULT '',
  failure         TEXT,
  -- Re-ingesting the same collection run is a no-op, not a second scan.
  UNIQUE (scope_id, legacy_run_id)
);
CREATE INDEX idx_scan_scope_time ON scan(scope_id, finished_at);

CREATE TABLE game (
  id    INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  key   TEXT NOT NULL UNIQUE
);

-- A physical release. Edition, region and format are part of its identity, so
-- a Deluxe, a Japanese pressing or a Game-Key Card can never collapse into the
-- standard cartridge.
CREATE TABLE release (
  id         INTEGER PRIMARY KEY,
  game_id    INTEGER NOT NULL REFERENCES game(id),
  platform   TEXT NOT NULL CHECK (platform IN ('SWITCH', 'SWITCH2')),
  edition    TEXT NOT NULL DEFAULT 'STANDARD',
  region     TEXT NOT NULL DEFAULT 'UNKNOWN',
  format     TEXT NOT NULL DEFAULT 'UNKNOWN'
             CHECK (format IN ('FULL_GAME_CARD', 'GAME_KEY_CARD', 'CODE_IN_BOX', 'DOWNLOAD_CODE', 'UNKNOWN')),
  publisher  TEXT,
  -- 0 until a human confirms it: auto-matched identities lower confidence.
  verified   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE (game_id, platform, edition, region, format)
);

-- EAN/UPC or publisher product code ("EAN:0045496...", "PC:HAC-P-AXN7A").
CREATE TABLE release_code (
  code       TEXT PRIMARY KEY,
  release_id INTEGER NOT NULL REFERENCES release(id),
  source     TEXT NOT NULL
);

CREATE TABLE listing (
  id            INTEGER PRIMARY KEY,
  storefront_id TEXT NOT NULL REFERENCES storefront(id),
  sku           TEXT NOT NULL,
  -- The scope it was last seen in: the only scope that may reconcile its absence.
  scope_id      INTEGER REFERENCES scope(id),
  url           TEXT NOT NULL,
  title         TEXT NOT NULL,
  platform      TEXT NOT NULL,
  region        TEXT NOT NULL,
  condition     TEXT NOT NULL,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  UNIQUE (storefront_id, sku)
);

CREATE TABLE listing_match (
  listing_id INTEGER PRIMARY KEY REFERENCES listing(id),
  release_id INTEGER REFERENCES release(id),
  tier       TEXT NOT NULL
             CHECK (tier IN ('CONFIRMED', 'EXACT_CODE', 'EXACT_KEY', 'PROBABLE', 'AMBIGUOUS', 'UNMATCHED')),
  -- JSON: why. Every match must be able to explain itself.
  reasons    TEXT NOT NULL,
  decided_at TEXT NOT NULL
);
CREATE INDEX idx_match_release ON listing_match(release_id);

-- A human said "not this one"; the matcher must never propose it again.
CREATE TABLE match_rejection (
  listing_id INTEGER NOT NULL REFERENCES listing(id),
  release_id INTEGER NOT NULL REFERENCES release(id),
  at         TEXT NOT NULL,
  PRIMARY KEY (listing_id, release_id)
);

-- History as run-length spans: an unchanged state extends the newest span, a
-- change opens a new one. Nothing is ever rewritten into the past, so a
-- reappearance cannot erase the unavailability before it.
CREATE TABLE state_span (
  id                INTEGER PRIMARY KEY,
  listing_id        INTEGER NOT NULL REFERENCES listing(id),
  state             TEXT NOT NULL
                    CHECK (state IN ('IN_STOCK', 'OUT_OF_STOCK', 'LISTED_STOCK_UNKNOWN', 'NOT_LISTED')),
  price             REAL,
  currency          TEXT,
  first_scan_id     INTEGER NOT NULL REFERENCES scan(id),
  last_scan_id      INTEGER NOT NULL REFERENCES scan(id),
  started_at        TEXT NOT NULL,
  last_confirmed_at TEXT NOT NULL,
  confirmations     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_span_listing ON state_span(listing_id, id);

-- Out-of-print evidence. Never deleted; conflicting rows are expected.
CREATE TABLE evidence (
  id           INTEGER PRIMARY KEY,
  release_id   INTEGER NOT NULL REFERENCES release(id),
  claim        TEXT NOT NULL CHECK (claim IN ('DISCONTINUED', 'OUT_OF_PRINT', 'IN_PRODUCTION', 'REPRINTED')),
  kind         TEXT NOT NULL CHECK (kind IN ('PUBLISHER_ANNOUNCEMENT', 'DISTRIBUTOR', 'RETAILER_NOTICE',
                                             'MANUFACTURER_PAGE', 'REGIONAL_RELEASE_INFO', 'OTHER')),
  reliability  TEXT NOT NULL CHECK (reliability IN ('OFFICIAL', 'TRADE', 'RETAILER', 'COMMUNITY')),
  -- Rendered as a link on the dashboard; only a web URL may become an href.
  source_url   TEXT NOT NULL CHECK (source_url LIKE 'http://%' OR source_url LIKE 'https://%'),
  observed_at  TEXT NOT NULL,
  published_at TEXT,
  note         TEXT NOT NULL DEFAULT '',
  added_at     TEXT NOT NULL
);
CREATE INDEX idx_evidence_release ON evidence(release_id);

-- Every manual correction, with what it replaced: matches, grouping, identities.
CREATE TABLE audit_log (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL,
  entity    TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action    TEXT NOT NULL,
  before    TEXT,
  after     TEXT,
  note      TEXT NOT NULL DEFAULT ''
);
"""



# v2: release merges are aliases, never destructive deletes. Listing scope lookup
# is the hot path for absence reconciliation.
_V2 = """
CREATE TABLE release_alias (
  release_id INTEGER PRIMARY KEY REFERENCES release(id),
  target_id  INTEGER NOT NULL REFERENCES release(id),
  at         TEXT NOT NULL,
  CHECK (release_id <> target_id)
);
CREATE INDEX idx_listing_scope ON listing(storefront_id, scope_id);
"""

MIGRATIONS: tuple[str, ...] = (_V1, _V2)

#: A week of daily collections, as for tracker.db.
BACKUPS_KEPT = 7


def db_path() -> Path:
    # Truthiness, as paths.db_path: an empty override must not become Path("").
    override = os.environ.get("TRACKER_MARKET_DB")
    return Path(override) if override else paths.data_dir() / "market.db"


def migrate(conn: sqlite3.Connection, migrations: Sequence[str] = MIGRATIONS) -> None:
    """Apply every migration past ``user_version``, each in its own transaction.

    BEGIN and COMMIT live INSIDE the script: executescript() commits any
    transaction already open before it starts, so one opened around it would
    protect nothing. ``user_version`` is part of the transaction, so a failed
    step leaves both the schema and the version exactly as they were.
    """
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > len(migrations):
        raise RuntimeError(
            f"market.db is at schema version {current}, newer than this build understands "
            f"({len(migrations)}). Use the newer build, or restore a backup."
        )
    for version, script in enumerate(migrations[current:], start=current + 1):
        try:
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def open_db(path: Path | None = None) -> sqlite3.Connection:
    conn = connect(path or db_path())
    migrate(conn)
    return conn


def backup(conn: sqlite3.Connection, directory: Path, run_id: int, keep: int = BACKUPS_KEPT) -> Path:
    """A consistent copy via VACUUM INTO; see core.db.backup for why not a file copy.

    Named ``market-run...`` so its rotation can never delete tracker.db's
    backups sharing the folder, nor anything else a user put there.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"market-run{run_id:06d}-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
    conn.execute("VACUUM INTO ?", (str(target),))
    copies = sorted(directory.glob("market-run[0-9][0-9][0-9][0-9][0-9][0-9]-*.db"))
    for old in copies[: max(0, len(copies) - keep)]:
        old.unlink(missing_ok=True)
    return target
