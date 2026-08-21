"""Launching workers, and refusing to launch two.

The terminal version of this trap was real: collect finishes, you press Enter
once to clear a pause, then again out of habit, and a multi-minute network
operation restarts with no confirmation. A browser offers three ways to do the
same thing -- double-click, refresh, second tab -- so the guard has three
layers and the authoritative one lives in the database.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db
from switch_tracker.web.runs import PidLock, RunAlreadyActive, RunLauncher


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "r.db")
    db.ensure_schema(connection)
    return connection


@pytest.fixture
def lock(tmp_path: Path) -> PidLock:
    return PidLock(tmp_path / "run.lock")


def launcher(conn: sqlite3.Connection, lock: PidLock, spawned: list[list[str]] | None = None):
    sink = spawned if spawned is not None else []

    def fake_spawn(command: list[str]) -> int:
        sink.append(command)
        # Our own PID, because a REAL spawn returns a live process. Returning
        # a made-up number would make the lock look stale the instant it was
        # written, and reap_stale would helpfully undo the run we just made.
        return os.getpid()

    return RunLauncher(conn, lock, spawn=fake_spawn)


class TestStarting:
    def test_creates_a_run_and_spawns_a_worker(self, conn, lock) -> None:
        spawned: list[list[str]] = []
        handle = launcher(conn, lock, spawned).start("collect")

        assert handle.run_id == 1
        assert handle.pid == os.getpid()
        assert spawned and "collect" in spawned[0]
        assert "--run-id" in spawned[0]

    def test_passes_the_run_id_to_the_worker(self, conn, lock) -> None:
        """The worker must write into the run the dashboard already created."""
        spawned: list[list[str]] = []
        handle = launcher(conn, lock, spawned).start("collect")
        assert str(handle.run_id) in spawned[0]


class TestConcurrencyGuard:
    def test_refuses_a_second_run_while_one_is_active(self, conn, lock) -> None:
        started = launcher(conn, lock)
        started.start("collect")
        with pytest.raises(RunAlreadyActive):
            started.start("collect")

    def test_refuses_across_launcher_instances(self, conn, lock) -> None:
        """A refresh creates a new request, not a new database."""
        launcher(conn, lock).start("collect")
        with pytest.raises(RunAlreadyActive):
            launcher(conn, lock).start("probe")

    def test_permits_a_new_run_after_the_previous_finished(self, conn, lock) -> None:
        first = launcher(conn, lock)
        handle = first.start("collect")
        first.finish(handle.run_id)
        assert launcher(conn, lock).start("collect").run_id == 2

    def test_reports_the_active_run(self, conn, lock) -> None:
        assert launcher(conn, lock).active() is None
        handle = launcher(conn, lock).start("collect")
        assert launcher(conn, lock).active() == handle.run_id

    def test_a_failed_spawn_releases_everything_it_took(self, conn, lock) -> None:
        """Otherwise one bad launch wedges the app until the file is deleted."""

        def exploding_spawn(command: list[str]) -> int:
            raise OSError("cannot start worker")

        failing = RunLauncher(conn, lock, spawn=exploding_spawn)
        with pytest.raises(OSError, match="cannot start worker"):
            failing.start("collect")

        assert lock.read_pid() is None
        assert launcher(conn, lock).active() is None
        row = conn.execute("SELECT status, detail FROM run_store").fetchone()
        assert row is None or row["status"] == "failed"


class TestStalePidReaping:
    def test_a_lock_held_by_a_dead_process_is_reclaimed(self, conn, lock) -> None:
        """A machine that slept or a worker that was killed must not wedge the app.

        A PID check is a fact. A timeout would be a guess -- and a legitimate
        600-second browser run would trip any sane one.
        """
        conn.execute("INSERT INTO run (started_at) VALUES ('t0')")
        lock.write_pid(999_999)  # a PID that cannot be running

        reclaimed = launcher(conn, lock)
        reclaimed.reap_stale()

        assert lock.read_pid() is None
        row = conn.execute("SELECT finished_at FROM run WHERE id = 1").fetchone()
        assert row["finished_at"] is not None

    def test_the_interrupted_run_is_marked_failed_with_a_reason(self, conn, lock) -> None:
        conn.execute("INSERT INTO run (started_at) VALUES ('t0')")
        conn.execute("INSERT INTO store VALUES ('s','S','u','SHOPIFY','INR',2,1)")
        lock.write_pid(999_999)

        launcher(conn, lock).reap_stale()

        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM run_event WHERE run_id=1")]
        assert "run_finished" in kinds

    def test_a_live_lock_is_left_alone(self, conn, lock) -> None:
        conn.execute("INSERT INTO run (started_at) VALUES ('t0')")
        lock.write_pid(os.getpid())  # very much alive
        launcher(conn, lock).reap_stale()
        assert lock.read_pid() == os.getpid()

    def test_start_reaps_before_giving_up(self, conn, lock) -> None:
        """A dead lock must not make the button permanently unusable."""
        conn.execute("INSERT INTO run (started_at) VALUES ('t0')")
        lock.write_pid(999_999)
        handle = launcher(conn, lock).start("collect")
        assert handle.run_id == 2


class TestPidLock:
    def test_round_trips_a_pid(self, lock: PidLock) -> None:
        lock.write_pid(1234)
        assert lock.read_pid() == 1234

    def test_reads_nothing_when_absent(self, lock: PidLock) -> None:
        assert lock.read_pid() is None

    def test_treats_a_corrupt_lock_as_absent(self, lock: PidLock) -> None:
        """A truncated file must not be more permanent than a real lock."""
        lock.path.write_text("not a pid")
        assert lock.read_pid() is None

    def test_knows_its_holder_is_alive(self, lock: PidLock) -> None:
        lock.write_pid(os.getpid())
        assert lock.holder_alive() is True

    def test_knows_its_holder_is_gone(self, lock: PidLock) -> None:
        lock.write_pid(999_999)
        assert lock.holder_alive() is False
