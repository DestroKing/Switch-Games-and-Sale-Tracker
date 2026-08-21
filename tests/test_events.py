"""Durable progress.

The point of writing progress to a table rather than streaming it from the
running job: a closed tab, a page refresh, or a restarted dashboard must all
lose nothing. The work is happening in another process; the browser is only
ever watching.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db
from switch_tracker.events.models import EventKind
from switch_tracker.events.reader import EventReader
from switch_tracker.events.writer import EventWriter


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "e.db")
    db.ensure_schema(connection)
    connection.execute("INSERT INTO run (started_at) VALUES ('t0')")
    return connection


class TestWriter:
    def test_records_a_run_starting(self, conn: sqlite3.Connection) -> None:
        EventWriter(conn, run_id=1).run_started(2)
        row = conn.execute("SELECT kind, count FROM run_event").fetchone()
        assert row["kind"] == EventKind.RUN_STARTED
        assert row["count"] == 2

    def test_records_per_page_progress(self, conn: sqlite3.Connection) -> None:
        """The live counter that only existed as ephemeral stdout before."""
        EventWriter(conn, run_id=1).page("nistore", page=3, count=214)
        row = conn.execute("SELECT store_id, page, count FROM run_event").fetchone()
        assert (row["store_id"], row["page"], row["count"]) == ("nistore", 3, 214)

    def test_records_everything_run_store_detail_carries(self, conn: sqlite3.Connection) -> None:
        """Status, count, timing and a free-text reason, per store per run."""
        EventWriter(conn, run_id=1).store_finished(
            "hgworld", status="partial", count=180, duration_ms=4200, detail="stopped early"
        )
        row = conn.execute("SELECT * FROM run_event").fetchone()
        assert row["status"] == "partial"
        assert row["count"] == 180
        assert row["duration_ms"] == 4200
        assert row["detail"] == "stopped early"

    def test_assigns_monotonically_increasing_sequence_numbers(self, conn: sqlite3.Connection) -> None:
        """seq is the replay cursor; gaps or reuse would lose or repeat events."""
        writer = EventWriter(conn, run_id=1)
        for i in range(5):
            writer.page("s", page=i, count=i)
        seqs = [r["seq"] for r in conn.execute("SELECT seq FROM run_event ORDER BY seq")]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == 5

    def test_a_failed_write_never_aborts_the_run(self, conn: sqlite3.Connection) -> None:
        """Diagnostics are worth having, but not worth losing a collection over."""
        conn.close()
        EventWriter(conn, run_id=1).page("s", page=1, count=1)


class TestReader:
    def test_reads_events_after_a_cursor(self, conn: sqlite3.Connection) -> None:
        writer = EventWriter(conn, run_id=1)
        for i in range(5):
            writer.page("s", page=i, count=i)

        reader = EventReader(conn)
        first_two = reader.since(run_id=1, after_seq=0)[:2]
        rest = reader.since(run_id=1, after_seq=first_two[-1].seq)

        assert len(rest) == 3
        assert [e.page for e in rest] == [2, 3, 4]

    def test_a_reconnecting_client_loses_nothing(self, conn: sqlite3.Connection) -> None:
        """The property that makes a closed tab harmless.

        The client reports the last seq it saw; everything after it replays.
        """
        writer = EventWriter(conn, run_id=1)
        writer.page("s", page=1, count=10)
        seen = EventReader(conn).since(run_id=1, after_seq=0)
        cursor = seen[-1].seq

        # ... tab closes, three more events happen, tab reopens ...
        writer.page("s", page=2, count=20)
        writer.page("s", page=3, count=30)
        writer.run_finished()

        missed = EventReader(conn).since(run_id=1, after_seq=cursor)
        assert [e.kind for e in missed] == [
            EventKind.PAGE,
            EventKind.PAGE,
            EventKind.RUN_FINISHED,
        ]

    def test_does_not_leak_events_from_another_run(self, conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE run SET finished_at = 't1' WHERE id = 1")
        conn.execute("INSERT INTO run (started_at) VALUES ('t2')")
        EventWriter(conn, run_id=1).page("a", page=1, count=1)
        EventWriter(conn, run_id=2).page("b", page=1, count=1)

        events = EventReader(conn).since(run_id=2, after_seq=0)
        assert [e.store_id for e in events] == ["b"]

    def test_reports_whether_a_run_has_finished(self, conn: sqlite3.Connection) -> None:
        """How the SSE stream knows to close rather than poll forever."""
        reader = EventReader(conn)
        writer = EventWriter(conn, run_id=1)
        writer.page("s", page=1, count=1)
        assert reader.is_finished(run_id=1) is False
        writer.run_finished()
        assert reader.is_finished(run_id=1) is True
