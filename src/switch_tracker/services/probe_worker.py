"""Worker: detect each store's real backend and write corrections."""

from __future__ import annotations

from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.core.http import PoliteClient
from switch_tracker.events.writer import EventWriter
from switch_tracker.services.probe import ProbeService


async def run(run_id: int) -> int:
    conn = db.connect()
    db.ensure_schema(conn)
    events = EventWriter(conn, run_id)

    stores = overrides.active_stores()
    events.run_started(len(stores))

    report = await ProbeService(PoliteClient()).run(stores)
    for line in report.lines:
        events.warning(line)
    events.warning(
        f"Applied: {report.corrected} corrected, {report.disabled} disabled. "
        "Saved to stores.local.json -- press Reset corrections to undo everything."
    )

    events.run_finished()
    conn.execute("UPDATE run SET finished_at = datetime('now') WHERE id = ?", (run_id,))
    return 0
