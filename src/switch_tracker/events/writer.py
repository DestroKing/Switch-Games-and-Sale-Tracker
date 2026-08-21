"""Worker side of progress reporting."""

from __future__ import annotations

import sqlite3

from switch_tracker.core.db import now_iso
from switch_tracker.events.models import EventKind


class EventWriter:
    """Appends progress rows for one run.

    Writes are autocommitted and deliberately kept OUTSIDE the persistence
    transaction: progress has to be visible while a run is happening, not
    delivered in a batch once it ends.
    """

    def __init__(self, conn: sqlite3.Connection, run_id: int) -> None:
        self._conn = conn
        self._run_id = run_id

    def _emit(self, kind: EventKind, **fields: object) -> None:
        try:
            self._conn.execute(
                "INSERT INTO run_event (run_id, at, kind, store_id, status, count, page, "
                "duration_ms, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._run_id,
                    now_iso(),
                    str(kind),
                    fields.get("store_id"),
                    fields.get("status"),
                    fields.get("count"),
                    fields.get("page"),
                    fields.get("duration_ms"),
                    fields.get("detail"),
                ),
            )
        except sqlite3.Error:
            # Progress reporting is worth having; it is not worth losing a
            # multi-minute collection over. A dropped event costs a moment of
            # stale UI, nothing more.
            return

    def run_started(self, store_count: int) -> None:
        self._emit(EventKind.RUN_STARTED, count=store_count)

    def store_started(self, store_id: str, kind: str) -> None:
        self._emit(EventKind.STORE_STARTED, store_id=store_id, detail=kind)

    def page(self, store_id: str, page: int, count: int) -> None:
        """Satisfies the adapters' ProgressSink protocol."""
        self._emit(EventKind.PAGE, store_id=store_id, page=page, count=count)

    def store_finished(
        self, store_id: str, *, status: str, count: int, duration_ms: int, detail: str | None
    ) -> None:
        self._emit(
            EventKind.STORE_FINISHED,
            store_id=store_id,
            status=status,
            count=count,
            duration_ms=duration_ms,
            detail=detail,
        )

    def warning(self, detail: str, store_id: str | None = None) -> None:
        self._emit(EventKind.WARNING, store_id=store_id, detail=detail)

    def run_finished(self, detail: str | None = None) -> None:
        self._emit(EventKind.RUN_FINISHED, detail=detail)
