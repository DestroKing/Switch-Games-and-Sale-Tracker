"""Worker: a full collection run.

This process, and only this process, imports Playwright -- and only when a
browser store is actually enabled.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from switch_tracker import paths, settings
from switch_tracker.adapters.registry import build_registry
from switch_tracker.config import overrides
from switch_tracker.core import db, matcher
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, StoreConfig
from switch_tracker.fx.rates import FxService
from switch_tracker.services.collect import CollectService, select_stores

if TYPE_CHECKING:
    from switch_tracker.market.ingest import MarketObserver


def market_observer(enabled: bool) -> MarketObserver | None:
    """The market tracker's hook, or None: switched off, removed, or unable to open.

    Imported here, not at the top, so a price-only install never loads the
    package. Any failure costs the market data of this run, never the run.
    """
    if not enabled:
        return None
    try:
        from switch_tracker.market.ingest import MarketObserver

        return MarketObserver.open(backup_dir=paths.backups_dir())
    except Exception as exc:  # noqa: BLE001 - ImportError when removed; RuntimeError on a newer market.db
        print(f"market tracker off for this run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


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

    observer = market_observer(config.market_tracker)
    try:
        service = CollectService(
            conn,
            adapters=build_registry(client, provider),
            fx=FxService(conn, client),
            aliases=matcher.load_aliases(),
            backup_dir=paths.backups_dir(),
            observer=observer,
        )
        # The FULL store list plus the selection -- see CollectService.run:
        # the store table projects every store's enabled flag, so pre-filtering
        # here would stop disabled stores being synced.
        await service.run(stores, run_id=run_id, only=only)
    finally:
        if observer is not None:
            observer.close()
        if provider is not None:
            await provider.close()
    return 0
