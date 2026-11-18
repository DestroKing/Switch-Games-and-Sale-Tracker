"""market.db: its own file, its own migrations, never the price history's.

The market tracker must be removable by deleting a package and a file. That
only holds if nothing it stores lives in tracker.db, and if its schema can be
upgraded without ever touching the legacy one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from switch_tracker import paths
from switch_tracker.market import db


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACKER_MARKET_DB", raising=False)
    monkeypatch.delenv("TRACKER_DB", raising=False)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return db.open_db(tmp_path / "market.db")


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class TestLocation:
    def test_lives_beside_tracker_db_as_its_own_file(self, data_dir: Path) -> None:
        assert db.db_path() == data_dir / "market.db"

    def test_env_override_wins(self, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACKER_MARKET_DB", str(data_dir / "elsewhere.db"))
        assert db.db_path() == data_dir / "elsewhere.db"

    def test_an_empty_override_is_ignored_not_the_current_directory(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_MARKET_DB", "")
        assert db.db_path() == data_dir / "market.db"

    def test_opening_it_never_creates_or_touches_tracker_db(self, data_dir: Path) -> None:
        db.open_db()
        assert (data_dir / "market.db").exists()
        assert not (data_dir / "tracker.db").exists()


class TestMigrations:
    def test_fresh_database_reaches_the_latest_version(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)

    def test_creates_the_market_tables_and_no_legacy_ones(self, conn: sqlite3.Connection) -> None:
        tables = _tables(conn)
        assert {
            "retailer",
            "storefront",
            "scope",
            "scan",
            "game",
            "release",
            "release_code",
            "listing",
            "listing_match",
            "match_rejection",
            "state_span",
            "evidence",
            "audit_log",
        } <= tables
        assert not {"price_point", "run", "run_store", "store"} & tables

    def test_reopening_is_a_no_op(self, tmp_path: Path) -> None:
        db.open_db(tmp_path / "m.db").execute(
            "INSERT INTO retailer (id, name, kind) VALUES ('r', 'R', 'INDEPENDENT')"
        )
        again = db.open_db(tmp_path / "m.db")
        assert again.execute("SELECT COUNT(*) FROM retailer").fetchone()[0] == 1

    def test_a_failing_migration_leaves_nothing_half_applied(self, tmp_path: Path) -> None:
        conn = db.connect(tmp_path / "m.db")
        broken = ("CREATE TABLE a (x INTEGER);", "CREATE TABLE b (y INTEGER); THIS IS NOT SQL;")
        with pytest.raises(sqlite3.Error):
            db.migrate(conn, broken)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "a" in _tables(conn)
        assert "b" not in _tables(conn)
        # And it can be retried once fixed, from where it stopped.
        db.migrate(conn, (broken[0], "CREATE TABLE b (y INTEGER);"))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2

    def test_a_database_newer_than_this_code_is_refused(self, tmp_path: Path) -> None:
        conn = db.connect(tmp_path / "m.db")
        conn.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
        with pytest.raises(RuntimeError, match="newer"):
            db.migrate(conn)


class TestConstraints:
    """The rules the data-correctness section depends on, held by the database."""

    def _storefront(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO retailer (id, name, kind) VALUES ('r', 'R', 'INDEPENDENT')")
        conn.execute(
            "INSERT INTO storefront (id, retailer_id, name, base_url, stock_signal) "
            "VALUES ('s', 'r', 'S', 'https://s.example', 'REPORTED')"
        )

    def test_a_storefront_must_belong_to_a_known_retailer(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO storefront (id, retailer_id, name, base_url, stock_signal) "
                "VALUES ('s', 'nobody', 'S', 'https://s.example', 'REPORTED')"
            )

    def test_retailer_kind_is_closed(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO retailer (id, name, kind) VALUES ('r', 'R', 'PROBABLY_FINE')")

    def test_one_listing_per_storefront_sku(self, conn: sqlite3.Connection) -> None:
        self._storefront(conn)
        row = (
            "INSERT INTO listing (storefront_id, sku, url, title, platform, region, condition, "
            "first_seen, last_seen) VALUES ('s', 'X1', 'https://s.example/x', 'X', 'SWITCH', 'IN', "
            "'NEW', 't', 't')"
        )
        conn.execute(row)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(row)

    def test_a_barcode_identifies_at_most_one_release(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO game (id, title, key) VALUES (1, 'G', 'g')")
        for rid, edition in ((1, "STANDARD"), (2, "DELUXE")):
            conn.execute(
                "INSERT INTO release (id, game_id, platform, edition, created_at) "
                f"VALUES ({rid}, 1, 'SWITCH', '{edition}', 't')"
            )
        conn.execute("INSERT INTO release_code (code, release_id, source) VALUES ('EAN:1', 1, 'manual')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO release_code (code, release_id, source) VALUES ('EAN:1', 2, 'manual')")

    def test_release_dimensions_are_unique_so_editions_never_collapse(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO game (id, title, key) VALUES (1, 'G', 'g')")
        conn.execute("INSERT INTO release (game_id, platform, created_at) VALUES (1, 'SWITCH', 't')")
        conn.execute("INSERT INTO release (game_id, platform, created_at) VALUES (1, 'SWITCH2', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO release (game_id, platform, created_at) VALUES (1, 'SWITCH', 't')")

    def test_unknown_platform_is_not_a_release(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO game (id, title, key) VALUES (1, 'G', 'g')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO release (game_id, platform, created_at) VALUES (1, 'UNKNOWN', 't')")

    def test_evidence_needs_a_web_source(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO game (id, title, key) VALUES (1, 'G', 'g')")
        conn.execute("INSERT INTO release (id, game_id, platform, created_at) VALUES (1, 1, 'SWITCH', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO evidence (release_id, claim, kind, reliability, source_url, observed_at, "
                "added_at) VALUES (1, 'OUT_OF_PRINT', 'OTHER', 'COMMUNITY', 'javascript:alert(1)', 't', 't')"
            )


class TestBackup:
    def test_keeps_only_the_newest_copies_and_nothing_else(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        folder = tmp_path / "backups"
        folder.mkdir()
        (folder / "tracker-run000001-x.db").write_text("legacy backup, not ours")
        made = [db.backup(conn, folder, run_id=i, keep=2) for i in range(1, 5)]
        kept = sorted(p.name for p in folder.glob("market-run*.db"))
        assert kept == sorted(p.name for p in made[-2:])
        assert (folder / "tracker-run000001-x.db").exists()
