"""The dashboard process.

This module and everything it imports must NEVER pull in Playwright or an
adapter.  tests/test_import_boundary.py asserts that in a subprocess, and it
is the test that keeps the whole design honest: the moment the UI can scrape,
a hung Chromium takes the dashboard down with it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from switch_tracker import resources, settings
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.web import deps, queries
from switch_tracker.web.errors import json_error_handler
from switch_tracker.web.routers import actions, data, events, pages


@dataclass(frozen=True, slots=True)
class LaunchDecision:
    collect: bool
    message: str | None = None


def launch_collect_decision(
    *, configured: bool, override: bool | None, probed: bool, already_collected: bool
) -> LaunchDecision:
    """Should opening the dashboard start a collection?

    Only to BOOTSTRAP an empty database -- never on every launch.

    Automatically scraping fourteen shops each time the app opens is a cost the
    user did not ask for, and it is the behaviour least likely to match what
    they wanted: they may be opening the dashboard to read yesterday's prices,
    not to spend several minutes gathering today's. Once history exists,
    collecting is an explicit act -- the "Collect prices" button.

    Pure on purpose. The interesting part of ``serve`` is this decision, and a
    function taking four booleans can be tested exhaustively without binding a
    port or launching a worker.
    """
    if not (configured if override is None else override):
        return LaunchDecision(False)

    # Never before the stores have been checked once. Collecting against
    # unverified store kinds produces a screen of failures that look like
    # broken code and are really an uncorrected store list.
    if not probed:
        return LaunchDecision(False, "First run: press 'Check stores' before collecting.")

    if already_collected:
        return LaunchDecision(
            False,
            "Price history already exists, so nothing is being collected automatically. "
            "Press 'Collect prices' when you want a fresh run.",
        )

    return LaunchDecision(True)


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

    decision = launch_collect_decision(
        configured=config.collect_on_launch,
        override=collect_on_launch,
        probed=overrides.has_been_probed(),
        already_collected=queries.has_ever_collected(deps.get_conn()),
    )
    if decision.message:
        print(f"  {decision.message}")

    if decision.collect:
        # Bootstrapping an empty database, once. Failure here is non-fatal:
        # an empty screen with a readable reason beats no screen at all.
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
