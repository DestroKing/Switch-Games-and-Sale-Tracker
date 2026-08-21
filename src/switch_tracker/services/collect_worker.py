"""Worker: a full collection run.

This process, and only this process, imports Playwright -- and only when a
browser store is actually enabled.
"""

from __future__ import annotations

from switch_tracker import settings
from switch_tracker.adapters.registry import build_registry
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind
from switch_tracker.fx.rates import FxService
from switch_tracker.services.collect import CollectService


async def run(run_id: int) -> int:
    conn = db.connect()
    db.ensure_schema(conn)

    config = settings.load()
    stores = overrides.active_stores()
    client = PoliteClient()

    needs_browser = any(s.enabled and s.kind is AdapterKind.BROWSER for s in stores)
    provider = None
    if needs_browser:
        from switch_tracker.adapters.browser.provider import BrowserProvider

        provider = BrowserProvider(headless=not config.headful)

    try:
        service = CollectService(
            conn,
            adapters=build_registry(client, provider),
            fx=FxService(conn, client),
        )
        await service.run(stores, run_id=run_id)
    finally:
        if provider is not None:
            await provider.close()
    return 0
