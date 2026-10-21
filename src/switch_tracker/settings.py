"""Runtime settings.

Deliberately tiny. This is a personal, local, single-user tool: there is no
environment to configure for, no secrets, and nothing to tune per deployment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from switch_tracker import paths

_FILE = "settings.json"


@dataclass(frozen=True, slots=True)
class Settings:
    port: int = 4173
    #: Allow the app to BOOTSTRAP an empty database by collecting once on
    #: launch. Not "collect every launch": once any collection has run, opening
    #: the dashboard never starts another -- see web.app.launch_collect_decision.
    #: Setting this False suppresses even the bootstrap run.
    collect_on_launch: bool = True
    #: Show the browser while scraping. Debugging aid only.
    headful: bool = False


def _as_port(value: object, fallback: int) -> int:
    """A usable TCP port, or the fallback.

    Validated rather than just converted: port 0 binds a RANDOM port while the
    dashboard prints ":0", and the cross-site guard builds its allowed Host
    and Origin from this number -- so a bad value would lock the real page out
    of its own dashboard while looking configured.
    """
    try:
        port = int(str(value))
    except (TypeError, ValueError):
        return fallback
    return port if 1 <= port <= 65535 else fallback


def _as_bool(value: object, fallback: bool) -> bool:
    """Only a real JSON boolean counts. ``bool("false")`` is True, so a
    hand-typed ``"headful": "false"`` used to switch the setting ON."""
    return value if isinstance(value, bool) else fallback


def load() -> Settings:
    path = paths.data_dir() / _FILE
    data: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            data = {}

    return Settings(
        port=_as_port(os.environ.get("PORT") or data.get("port"), 4173),
        collect_on_launch=_as_bool(data.get("collect_on_launch"), True),
        headful=os.environ.get("HEADFUL") == "1" or _as_bool(data.get("headful"), False),
    )
