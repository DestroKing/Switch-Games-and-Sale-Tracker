"""Shared request dependencies.

The dashboard process holds ONE connection and uses it read-only. All writing
happens in worker processes; WAL lets both happen at once.
"""

from __future__ import annotations

import sqlite3

from switch_tracker.core import db
from switch_tracker.web.runs import PidLock, RunLauncher

_conn: sqlite3.Connection | None = None
_launcher: RunLauncher | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = db.connect()
        db.ensure_schema(_conn)
    return _conn


def get_launcher() -> RunLauncher:
    from switch_tracker import paths

    global _launcher
    if _launcher is None:
        _launcher = RunLauncher(get_conn(), PidLock(paths.lock_path()))
    return _launcher


def reset() -> None:
    """For tests: drop the cached connection and launcher."""
    global _conn, _launcher
    if _conn is not None:
        _conn.close()
    _conn = None
    _launcher = None
