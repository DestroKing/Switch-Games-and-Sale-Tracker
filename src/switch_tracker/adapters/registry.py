"""Which adapter handles which store kind."""

from __future__ import annotations

from switch_tracker.adapters.base import Adapter
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind


def build_registry(
    client: PoliteClient,
    browser_provider: object | None = None,
) -> dict[AdapterKind, Adapter]:
    """Construct the adapters this process needs.

    The browser adapter is only built when a browser store is actually
    enabled, so a run of HTTP-only stores never imports Playwright or pays
    for launching Chromium.
    """
    from switch_tracker.adapters.shopify import ShopifyAdapter
    from switch_tracker.adapters.woocommerce import WooAdapter

    registry: dict[AdapterKind, Adapter] = {
        AdapterKind.SHOPIFY: ShopifyAdapter(client),
        AdapterKind.WOOCOMMERCE: WooAdapter(client),
    }

    if browser_provider is not None:
        from switch_tracker.adapters.browser.adapter import BrowserAdapter
        from switch_tracker.adapters.browser.provider import BrowserProvider

        assert isinstance(browser_provider, BrowserProvider)
        registry[AdapterKind.BROWSER] = BrowserAdapter(browser_provider)

    return registry
