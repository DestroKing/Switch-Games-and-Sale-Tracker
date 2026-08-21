"""The schema must open the database the TypeScript version already writes.

The Python build points at the same data/tracker.db. Migration is therefore a
non-event -- but only if the 7 tables stay byte-identical. One accidental
column rename and the existing price history becomes unreadable.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db

# Copied verbatim out of src/core/db.ts. A database created by the TypeScript
# build looks exactly like this; the Python build must accept it untouched.
LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS store (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL,
  kind TEXT NOT NULL, currency TEXT NOT NULL, tier INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS game (
  id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_title TEXT NOT NULL,
  platform TEXT NOT NULL, region TEXT NOT NULL,
  UNIQUE (canonical_title, platform, region));
CREATE TABLE IF NOT EXISTS listing (
  id INTEGER PRIMARY KEY AUTOINCREMENT, store_id TEXT NOT NULL REFERENCES store(id),
  sku TEXT NOT NULL, game_id INTEGER REFERENCES game(id), url TEXT NOT NULL,
  raw_title TEXT NOT NULL, platform TEXT NOT NULL, region TEXT NOT NULL,
  condition TEXT NOT NULL DEFAULT 'NEW', image_url TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, UNIQUE (store_id, sku));
CREATE TABLE IF NOT EXISTS fx_rate (
  base TEXT NOT NULL, quote TEXT NOT NULL, rate REAL NOT NULL,
  rate_date TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (base, quote, rate_date));
CREATE TABLE IF NOT EXISTS run (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS price_point (
  id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listing(id),
  run_id INTEGER NOT NULL REFERENCES run(id), captured_at TEXT NOT NULL,
  native_currency TEXT NOT NULL, native_price REAL NOT NULL, inr_price REAL NOT NULL,
  fx_rate_date TEXT, in_stock INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS run_store (
  run_id INTEGER NOT NULL REFERENCES run(id), store_id TEXT NOT NULL REFERENCES store(id),
  status TEXT NOT NULL, listings_found INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0, detail TEXT, PRIMARY KEY (run_id, store_id));
"""


@pytest.fixture
def fresh(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "tracker.db")
    db.ensure_schema(conn)
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


class TestSchema:
    def test_creates_the_seven_original_tables(self, fresh: sqlite3.Connection) -> None:
        expected = {"store", "game", "listing", "price_point", "fx_rate", "run", "run_store"}
        assert expected <= _tables(fresh)

    def test_creates_the_one_additive_table(self, fresh: sqlite3.Connection) -> None:
        assert "run_event" in _tables(fresh)

    def test_enables_wal_so_the_dashboard_can_read_during_a_collection(
        self, fresh: sqlite3.Connection
    ) -> None:
        assert fresh.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

    def test_enforces_foreign_keys(self, fresh: sqlite3.Connection) -> None:
        assert fresh.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_creates_the_history_query_indexes(self, fresh: sqlite3.Connection) -> None:
        rows = fresh.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        names = {r[0] for r in rows}
        assert {"idx_pp_listing_time", "idx_pp_run", "idx_listing_game", "idx_listing_unmatched"} <= names

    def test_is_idempotent(self, tmp_path: Path) -> None:
        conn = db.connect(tmp_path / "t.db")
        db.ensure_schema(conn)
        db.ensure_schema(conn)
        assert fresh_ok(conn)


def fresh_ok(conn: sqlite3.Connection) -> bool:
    return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


class TestExistingDatabase:
    """The whole reason migration is a non-event."""

    def test_opens_a_typescript_written_database_without_damaging_it(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy.db"
        legacy = sqlite3.connect(path)
        legacy.executescript(LEGACY_SCHEMA)
        legacy.execute(
            "INSERT INTO store VALUES ('nistore','NI','https://nistore.in','WOOCOMMERCE','INR',2,1)"
        )
        legacy.execute(
            "INSERT INTO listing (store_id,sku,url,raw_title,platform,region,condition,"
            "first_seen,last_seen) VALUES ('nistore','SKU1','u','Zelda','SWITCH','IN','NEW','t','t')"
        )
        legacy.execute("INSERT INTO run (started_at) VALUES ('t')")
        legacy.execute(
            "INSERT INTO price_point (listing_id,run_id,captured_at,native_currency,"
            "native_price,inr_price,in_stock) VALUES (1,1,'t','INR',4499,4499,1)"
        )
        legacy.commit()
        legacy.close()

        conn = db.connect(path)
        db.ensure_schema(conn)

        assert fresh_ok(conn)
        assert conn.execute("SELECT raw_title FROM listing").fetchone()[0] == "Zelda"
        assert conn.execute("SELECT native_price FROM price_point").fetchone()[0] == 4499
        assert "run_event" in _tables(conn)

    def test_adds_the_condition_column_to_a_database_that_predates_it(self, tmp_path: Path) -> None:
        """CREATE TABLE IF NOT EXISTS never alters a table that already exists."""
        path = tmp_path / "old.db"
        old = sqlite3.connect(path)
        old.executescript(LEGACY_SCHEMA.replace("condition TEXT NOT NULL DEFAULT 'NEW',", ""))
        old.commit()
        old.close()

        conn = db.connect(path)
        db.ensure_schema(conn)

        columns = {r[1] for r in conn.execute("PRAGMA table_info(listing)")}
        assert "condition" in columns


class TestActiveRunGuard:
    """Layer 2 of the triple concurrency guard -- the authoritative one."""

    def test_permits_one_unfinished_run(self, fresh: sqlite3.Connection) -> None:
        fresh.execute("INSERT INTO run (started_at) VALUES ('t1')")
        fresh.commit()

    def test_rejects_a_second_unfinished_run(self, fresh: sqlite3.Connection) -> None:
        """A refresh or a second tab must not be able to start a parallel run."""
        fresh.execute("INSERT INTO run (started_at) VALUES ('t1')")
        with pytest.raises(sqlite3.IntegrityError):
            fresh.execute("INSERT INTO run (started_at) VALUES ('t2')")

    def test_permits_a_new_run_once_the_previous_one_finished(self, fresh: sqlite3.Connection) -> None:
        fresh.execute("INSERT INTO run (started_at) VALUES ('t1')")
        fresh.execute("UPDATE run SET finished_at = 't2' WHERE id = 1")
        fresh.execute("INSERT INTO run (started_at) VALUES ('t3')")
        assert fresh.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 2


class TestNullableInrPrice:
    """The single deliberate schema deviation (LLD fix #2)."""

    def test_a_price_point_may_record_no_inr_conversion(self, fresh: sqlite3.Connection) -> None:
        """When no FX rate is stored, recording NO number beats recording a wrong one.

        The TypeScript to_inr returns the native figure with no rate date, so
        a USD price lands in inr_price as though it were rupees.
        """
        fresh.execute("INSERT INTO store VALUES ('s','S','u','SHOPIFY','USD',1,1)")
        fresh.execute(
            "INSERT INTO listing (store_id,sku,url,raw_title,platform,region,condition,"
            "first_seen,last_seen) VALUES ('s','K','u','T','SWITCH','US','NEW','t','t')"
        )
        fresh.execute("INSERT INTO run (started_at) VALUES ('t')")
        fresh.execute(
            "INSERT INTO price_point (listing_id,run_id,captured_at,native_currency,"
            "native_price,inr_price,in_stock) VALUES (1,1,'t','USD',59.99,NULL,1)"
        )
        assert fresh.execute("SELECT inr_price FROM price_point").fetchone()[0] is None


class TestThreadSharing:
    """The dashboard shares one connection across Starlette's threadpool."""

    def test_a_connection_can_be_used_from_another_thread(self, fresh: sqlite3.Connection) -> None:
        """Python's sqlite3 refuses this by default, which breaks the dashboard.

        Starlette runs sync endpoints in a threadpool and the SSE tail uses
        asyncio.to_thread, so the connection is legitimately touched from
        several threads.
        """
        import threading

        result: list[int] = []

        def read() -> None:
            result.append(fresh.execute("SELECT COUNT(*) FROM listing").fetchone()[0])

        thread = threading.Thread(target=read)
        thread.start()
        thread.join()
        assert result == [0]

    def test_the_interpreter_actually_serializes_sqlite_access(self) -> None:
        """Sharing is only safe because SQLite takes the lock. Assert, do not assume."""
        db.assert_threadsafe()
