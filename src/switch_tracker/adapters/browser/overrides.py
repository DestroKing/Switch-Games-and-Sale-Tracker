"""Selectors found through the click-to-pick tool.

Stored in profiles.local.json under the data directory, for the same reason
store corrections are: a tool must never rewrite the source file it also
imports.  The picker writes here, so a correction is live on the very next
collection with no editing step in between.
"""

from __future__ import annotations

import json

from switch_tracker import paths

Overrides = dict[str, dict[str, list[str]]]


def read() -> Overrides:
    path = paths.profiles_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A broken corrections file must fall back to the built-in guesses,
        # not take collection down.
        return {}
    return loaded if isinstance(loaded, dict) else {}


def add_selector(store_id: str, field: str, css: str) -> None:
    data = read()
    for_store = data.setdefault(store_id, {})
    existing = for_store.setdefault(field, [])
    if css in existing:
        return
    existing.insert(0, css)
    paths.profiles_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def reset() -> None:
    paths.profiles_path().write_text("{}\n", encoding="utf-8")
