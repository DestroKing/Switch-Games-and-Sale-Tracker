"""Server-sent events: a READ-ONLY view of a run that is happening elsewhere.

The work is in another process writing to run_event. This endpoint tails that
table and re-broadcasts. Three consequences follow, and they are the reason
the design is shaped this way:

  * Closing the tab cannot cancel a run -- nothing here owns the work.
  * Refreshing does not start a second one.
  * A restarted dashboard replays identically, because the state is on disk.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from switch_tracker.events.reader import EventReader
from switch_tracker.web.deps import get_conn

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(prefix="/api/runs", tags=["events"])

#: Imperceptible against a run measured in minutes, and one indexed query.
POLL_INTERVAL_S = 0.25
#: Stop tailing a run that never terminates, so a forgotten tab cannot poll
#: this process forever.
MAX_STREAM_S = 3600


async def _stream(conn: sqlite3.Connection, run_id: int, after_seq: int) -> AsyncIterator[str]:
    reader = EventReader(conn)
    cursor = after_seq
    waited = 0.0

    while waited < MAX_STREAM_S:
        # to_thread: sqlite3 is blocking, and this loop shares an event loop
        # with every other request the dashboard is serving.
        events = await asyncio.to_thread(reader.since, run_id, cursor)
        for event in events:
            cursor = event.seq
            payload = json.dumps(asdict(event), default=str)
            # The SSE id lets the browser's own reconnect resume the cursor.
            yield f"id: {event.seq}\nevent: {event.kind}\ndata: {payload}\n\n"

        if await asyncio.to_thread(reader.is_finished, run_id):
            return

        await asyncio.sleep(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S

    yield 'event: warning\ndata: {"detail":"stream timed out; reload to resume"}\n\n'


@router.get("/{run_id}/events")
async def events(run_id: int, conn: Conn, request_from: int = 0) -> StreamingResponse:
    return StreamingResponse(
        _stream(conn, run_id, request_from),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
