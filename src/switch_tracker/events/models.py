"""The progress record.

Carries strictly more than run_store.detail did -- every field of it, plus a
live per-page counter that previously existed only as stdout and vanished the
moment the terminal scrolled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EventKind(StrEnum):
    RUN_STARTED = "run_started"
    STORE_STARTED = "store_started"
    PAGE = "store_progress"
    STORE_FINISHED = "store_finished"
    RUN_FINISHED = "run_finished"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class RunEvent:
    #: Monotonic within a run. This is the replay cursor a reconnecting
    #: browser sends back, and the reason a closed tab loses nothing.
    seq: int
    run_id: int
    at: str
    kind: EventKind
    store_id: str | None = None
    status: str | None = None
    count: int | None = None
    page: int | None = None
    duration_ms: int | None = None
    detail: str | None = None
