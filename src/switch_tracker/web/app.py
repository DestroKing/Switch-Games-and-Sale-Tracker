"""The dashboard process.

This module and everything it imports must NEVER pull in Playwright or an
adapter.  tests/test_import_boundary.py asserts that in a subprocess, and it
is the test that keeps the whole design honest: the moment the UI can scrape,
a hung Chromium takes the dashboard down with it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from switch_tracker import resources, settings
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.web import deps
from switch_tracker.web.errors import json_error_handler
from switch_tracker.web.routers import actions, data, events, pages


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # A worker killed mid-run, or a machine that slept, would otherwise leave
    # the app permanently convinced a collection is in progress.
    deps.get_launcher().reap_stale()
    yield


def create_app() -> FastAPI:
    # Fail loudly at startup rather than racing quietly under load.
    db.assert_threadsafe()

    app = FastAPI(title="switch-tracker", docs_url=None, redoc_url=None, lifespan=_lifespan)

    app.mount("/static", StaticFiles(directory=str(resources.static_dir())), name="static")
    app.include_router(pages.router)
    app.include_router(data.router)
    app.include_router(actions.router)
    app.include_router(events.router)
    app.add_exception_handler(Exception, json_error_handler)
    return app


def serve(collect_on_launch: bool | None = None) -> int:
    """Run the dashboard. Blocks until stopped."""
    import uvicorn

    config = settings.load()
    app = create_app()

    should_collect = config.collect_on_launch if collect_on_launch is None else collect_on_launch

    # ... but never before the stores have been checked once.
    #
    # Collecting against unverified store kinds produces a screen of failures
    # that look like broken code and are really just a store list nobody has
    # corrected yet. The old terminal menu existed largely to steer people
    # away from exactly this, and a dashboard that does it automatically on
    # first launch would be worse, not better.
    if should_collect and not overrides.has_been_probed():
        should_collect = False
        print("  First run: press 'Check stores' before collecting.")

    if should_collect:
        # No daemon and no scheduler -- but price history only accumulates
        # when a run happens, and opening the app is the moment the user has
        # already decided to care. Failure here is non-fatal: stale data on
        # screen beats no screen, with the reason visible in the health strip.
        try:
            deps.get_launcher().start("collect")
        except Exception as exc:  # noqa: BLE001
            print(f"  (could not start the launch collection: {exc})")

    print(f"\n  Dashboard: http://127.0.0.1:{config.port}")
    print("  Close this window to stop it.\n")

    # The app OBJECT, never the "module:app" string form -- string import does
    # not survive freezing.
    uvicorn.run(app, host="127.0.0.1", port=config.port, log_level="warning")
    return 0
