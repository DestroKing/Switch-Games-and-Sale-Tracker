"""Append-only audit records for human identity corrections."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from switch_tracker.core.db import now_iso


def record(
    conn: sqlite3.Connection,
    entity: str,
    entity_id: int | str,
    action: str,
    before: Any,
    after: Any,
    note: str = "",
) -> None:
    conn.execute(
        "INSERT INTO audit_log (at, entity, entity_id, action, before, after, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            now_iso(), entity, str(entity_id), action,
            None if before is None else json.dumps(before, ensure_ascii=False, sort_keys=True),
            None if after is None else json.dumps(after, ensure_ascii=False, sort_keys=True),
            note,
        ),
    )
