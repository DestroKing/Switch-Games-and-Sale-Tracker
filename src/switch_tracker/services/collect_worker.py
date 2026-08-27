"""Worker: a full collection run.

This process, and only this process, imports Playwright -- and only when a
browser store is actually enabled.
"""

from __future__ import annotations

from collections.abc import Sequence

from switch_tracker import settings
from switch_tracker.adapters.registry import build_registry
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, StoreConfig
from switch_tracker.fx.rates import FxService
from switch_tracker.services.collect import CollectService, select_stores


def needs_browser(stores: Sequence[StoreConfig], only: tuple[str, ...]) -> bool:
    """Does this run require Chromium?

    Asked of the SELECTION, never of ``enabled``. The previous form was
    ``any(s.enabled and s.kind is BROWSER for s in stores)``, which is wrong the
    moment a run can be narrowed: selecting a disabled browser store left the
    provider unbuilt, so build_registry omitted the BROWSER adapter and the
    store recorded "no adapter for AdapterKind.BROWSER / skipped". Nothing
    raised -- the run simply collected nothing, for the one case that
    "explicit beats enabled" exists to serve.

    Still a real gate: an HTTP-only selection must not pay for launching a
    browser, which is the saving this check was added for.
    """
    return any(s.kind is AdapterKind.BROWSER for s in select_stores(stores, only))


async def run(run_id: int, only: tuple[str, ...] = ()) -> int:
    conn = db.connect()
    db.ensure_schema(conn)

    config = settings.load()
    stores = overrides.active_stores()
    client = PoliteClient()

    provider = None
    if needs_browser(stores, only):
        from switch_tracker.adapters.browser.provider import BrowserProvider

        provider = BrowserProvider(headless=not config.headful)

    try:
        service = CollectService(
            conn,
            adapters=build_registry(client, provider),
            fx=FxService(conn, client),
        )
        # The FULL store list plus the selection -- see CollectService.run:
        # the store table projects every store's enabled flag, so pre-filtering
        # here would stop disabled stores being synced.
        await service.run(stores, run_id=run_id, only=only)
    finally:
        if provider is not None:
            await provider.close()
    return 0
