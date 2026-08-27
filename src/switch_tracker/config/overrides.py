"""Corrections discovered by probing, layered over the shipped store list.

They live in a JSON file under the data directory, never in stores.py.  Having
the probe rewrite a Python source file it also imports means one bad edit
silently corrupts the store list; a separate file keeps the shipped defaults
intact and makes "what did I change" a one-line diff.

The path comes from :mod:`switch_tracker.paths`, never from a bare relative
string.  The TypeScript version used ``"stores.local.json"`` unqualified, so
it resolved against the current working directory -- fine for a CLI started in
the project folder, wrong for a double-clicked exe.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import replace
from typing import Any

from switch_tracker import paths
from switch_tracker.config.stores import STORES
from switch_tracker.core.models import AdapterKind, StoreConfig

_FIELDS = ("kind", "enabled", "note")


def read() -> dict[str, dict[str, Any]]:
    """Corrections on disk, or an empty mapping.

    A corrupt file is ignored rather than fatal: the shipped defaults are
    always a usable fallback, and taking the whole app down over a broken
    corrections file would be a worse outcome than running unconnected.
    """
    path = paths.overrides_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write(data: dict[str, dict[str, Any]]) -> None:
    paths.overrides_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def set_override(
    store_id: str,
    *,
    kind: AdapterKind | None = None,
    enabled: bool | None = None,
    note: str | None = None,
) -> None:
    data = read()
    entry = data.get(store_id, {})
    if kind is not None:
        entry["kind"] = str(kind)
    if enabled is not None:
        entry["enabled"] = enabled
    if note is not None:
        entry["note"] = note
    data[store_id] = entry
    write(data)


def reset() -> None:
    write({})


def has_been_probed() -> bool:
    return paths.overrides_path().exists()


def active_stores() -> tuple[StoreConfig, ...]:
    """The store list the rest of the app should use.

    Note this iterates the SHIPPED list and looks corrections up by id, rather
    than iterating the corrections. A stale entry naming a store that no
    longer exists is therefore ignored instead of inventing a phantom store.
    """
    corrections = read()
    result = []
    for store in STORES:
        patch = corrections.get(store.id)
        if not patch:
            result.append(store)
            continue
        changes: dict[str, Any] = {}
        if "kind" in patch:
            # An unknown kind means a correction written by an older build for
            # an adapter this one does not have (JSON_API, MANUAL). Ignoring
            # it falls back to the shipped kind, which is the safe direction.
            with contextlib.suppress(ValueError):
                changes["kind"] = AdapterKind(patch["kind"])
        if isinstance(patch.get("enabled"), bool):
            changes["enabled"] = patch["enabled"]
        if isinstance(patch.get("note"), str):
            changes["note"] = patch["note"]
        result.append(replace(store, **changes) if changes else store)
    return tuple(result)
