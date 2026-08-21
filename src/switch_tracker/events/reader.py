"""Dashboard side of progress reporting.

The UI process never runs a collection; it reads this table and re-broadcasts
what it finds. That indirection is what lets the work survive the browser.
"""

from __future__ import annotations

import sqlite3

from switch_tracker.events.models import EventKind, RunEvent


class EventReader:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def since(self, run_id: int, after_seq: int) -> list[RunEvent]:
        """Every event for a run after a cursor, oldest first.

        ``after_seq`` is what makes reconnection lossless: a browser that
        dropped its connection reports the last seq it rendered and receives
        exactly what it missed.
        """
        rows = self._conn.execute(
            "SELECT seq, run_id, at, kind, store_id, status, count, page, duration_ms, detail "
            "FROM run_event WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        ).fetchall()
        return [
            RunEvent(
                seq=row["seq"],
                run_id=row["run_id"],
                at=row["at"],
                kind=EventKind(row["kind"]),
                store_id=row["store_id"],
                status=row["status"],
                count=row["count"],
                page=row["page"],
                duration_ms=row["duration_ms"],
                detail=row["detail"],
            )
            for row in rows
        ]

    def is_finished(self, run_id: int) -> bool:
        """Whether the stream can close instead of polling forever."""
        row = self._conn.execute(
            "SELECT 1 FROM run_event WHERE run_id = ? AND kind = ? LIMIT 1",
            (run_id, str(EventKind.RUN_FINISHED)),
        ).fetchone()
        return row is not None
