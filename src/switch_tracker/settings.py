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


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


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
        port=_as_int(os.environ.get("PORT") or data.get("port"), 4173),
        collect_on_launch=bool(data.get("collect_on_launch", True)),
        headful=os.environ.get("HEADFUL") == "1" or bool(data.get("headful", False)),
    )


def save(settings: Settings) -> None:
    (paths.data_dir() / _FILE).write_text(
        json.dumps(
            {
                "port": settings.port,
                "collect_on_launch": settings.collect_on_launch,
                "headful": settings.headful,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
