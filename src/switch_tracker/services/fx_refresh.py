"""Worker: refresh exchange rates on demand."""

from __future__ import annotations

from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.core.http import PoliteClient
from switch_tracker.events.writer import EventWriter
from switch_tracker.fx.rates import FxService


async def run(run_id: int) -> int:
    conn = db.connect()
    db.ensure_schema(conn)
    events = EventWriter(conn, run_id)
    events.run_started(0)

    client = PoliteClient()
    service = FxService(conn, client)
    currencies = [s.currency for s in overrides.active_stores() if s.enabled]

    rates = await service.refresh(currencies)
    if rates:
        for rate in rates:
            events.warning(f"{rate.base} to INR = {rate.rate} (ECB {rate.rate_date})")
    else:
        events.warning("No non-rupee stores are enabled, so there is nothing to convert.")

    events.run_finished()
    conn.execute("UPDATE run SET finished_at = datetime('now') WHERE id = ?", (run_id,))
    return 0
