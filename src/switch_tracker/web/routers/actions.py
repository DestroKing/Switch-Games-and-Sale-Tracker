"""The dashboard's buttons.

Every action starts a WORKER PROCESS and returns immediately. The dashboard
never scrapes, never launches Chromium, and never blocks on a 600-second
collection -- so closing the tab cannot cancel one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from switch_tracker.config import overrides
from switch_tracker.web.deps import get_launcher
from switch_tracker.web.errors import ok, problem
from switch_tracker.web.runs import RunAlreadyActive, RunLauncher

Launcher = Annotated[RunLauncher, Depends(get_launcher)]

router = APIRouter(prefix="/actions", tags=["actions"])

_LAUNCHABLE = {"collect", "probe", "fx"}


def _start(launcher: RunLauncher, kind: str, *extra: str) -> JSONResponse:
    try:
        handle = launcher.start(kind, *extra)
    except RunAlreadyActive:
        # 409, not a queue. Two collections at once would fight over the same
        # SQLite writer and produce two runs nobody asked for.
        return problem(409, "A run is already going. Wait for it to finish.")
    except OSError as exc:
        return problem(500, f"Could not start the worker: {exc}")
    return ok({"run_id": handle.run_id, "kind": handle.kind})


@router.post("/collect")
def collect(launcher: Launcher) -> JSONResponse:
    return _start(launcher, "collect")


@router.post("/probe")
def probe(launcher: Launcher) -> JSONResponse:
    return _start(launcher, "probe")


@router.post("/fx")
def fx(launcher: Launcher) -> JSONResponse:
    return _start(launcher, "fx")


@router.post("/inspect/{store_id}")
def inspect(store_id: str, launcher: Launcher) -> JSONResponse:
    """Open the click-to-pick tool in a REAL, VISIBLE browser window.

    The one capability that cannot live inside the dashboard's own tab: a
    human has to click on the store's actual page. It is the same mechanism as
    every other action -- the exe re-invoking itself -- which is precisely why
    it is not a special case here.
    """
    known = {s.id for s in overrides.active_stores()}
    if store_id not in known:
        return problem(404, f"Unknown store: {store_id}")
    return _start(launcher, "inspect", store_id)


@router.post("/reset-corrections")
def reset_corrections() -> JSONResponse:
    """Wipe stores.local.json. No worker needed; it is one file."""
    overrides.reset()
    return ok({"reset": True})
