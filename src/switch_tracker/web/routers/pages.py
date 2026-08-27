"""The dashboard shell."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from switch_tracker import paths, resources
from switch_tracker.config import overrides
from switch_tracker.core.models import AdapterKind
from switch_tracker.web.deps import get_conn, get_launcher
from switch_tracker.web.runs import RunLauncher

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(resources.templates_dir()))

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Launcher = Annotated[RunLauncher, Depends(get_launcher)]


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: Conn, launcher: Launcher) -> HTMLResponse:
    stores = overrides.active_stores()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_run": launcher.active(),
            # Only stores that a human can actually fix by clicking: it needs
            # a browser profile and pages to open.
            "fixable": [s for s in stores if s.kind is AdapterKind.BROWSER and s.search_urls],
            # Every store, DISABLED ONES INCLUDED: naming a store overrides its
            # enabled flag, and a store probe has just disabled is exactly the
            # one worth running in isolation.
            "collectable": list(stores),
            "probed": overrides.has_been_probed(),
            "onedrive_warning": paths.onedrive_hazard(),
            "data_dir": paths.data_dir(),
        },
    )
