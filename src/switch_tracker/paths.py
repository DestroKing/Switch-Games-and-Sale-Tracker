"""Every mutable path in the application resolves here, and nowhere else.

The TypeScript original stored ``stores.local.json`` as a bare relative path,
so it resolved against the current working directory.  For a CLI launched from
the project folder that is invisible; for a double-clicked ``.exe`` it lands
wherever Explorer happened to be.  Centralising the resolution makes that class
of bug unrepresentable rather than merely fixed.

Read-only resources that ship *inside* the bundle (templates, CSS, the vendored
htmx) are NOT here — those go through :mod:`importlib.resources`, which works
identically frozen and unfrozen.  ``sys._MEIPASS`` deliberately does not appear
anywhere in this codebase: it exists only in a frozen build, so any code path
using it silently diverges between development and the shipped exe.
"""

from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path

_APP_DIR_NAME = "switch-tracker"


@cache
def data_dir() -> Path:
    """The one writable directory: database, overrides, diagnostics, logs."""
    override = os.environ.get("TRACKER_DATA_DIR")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = (Path(local) if local else Path.home() / "AppData" / "Local") / _APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / _APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return Path(os.environ["TRACKER_DB"]) if "TRACKER_DB" in os.environ else data_dir() / "tracker.db"


def overrides_path() -> Path:
    return data_dir() / "stores.local.json"


def profiles_path() -> Path:
    return data_dir() / "profiles.local.json"


def lock_path() -> Path:
    return data_dir() / "run.lock"


def diagnostics_dir() -> Path:
    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def onedrive_hazard() -> str | None:
    """README's known corruption hazard, surfaced instead of left as folklore.

    The OneDrive sync client locks the SQLite file mid-write.  Returns a
    message for the dashboard health strip, or None when the path is safe.
    """
    if "onedrive" in str(data_dir()).lower():
        return (
            f"Data directory is inside OneDrive ({data_dir()}). The sync client can lock "
            "the database mid-write and corrupt it. Set TRACKER_DATA_DIR to a local path."
        )
    return None
