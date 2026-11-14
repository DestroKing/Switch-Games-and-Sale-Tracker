"""Conservative bridge from price collection to physical market observations.

A price adapter does not prove catalogue coverage or physical edition identity.
Keep every imported item unlinked until independent release verification exists.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from urllib.parse import urlsplit

from switch_tracker.core import market
from switch_tracker.core.models import RawListing, StoreConfig


def scope_for(store: StoreConfig) -> tuple[str, market.ScopeType]:
    """Scope changes when configured discovery URLs/collections change."""
    selectors = {"collections": list(store.collections), "search_urls": list(store.search_urls)}
    fingerprint = hashlib.sha256(
        json.dumps(selectors, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    scope_type = (
        market.ScopeType.CONFIGURED_COLLECTION
        if store.collections or store.search_urls
        else market.ScopeType.RETAILER_CATALOGUE
    )
    return f"adapter-feed:v1:{fingerprint}", scope_type


def record_result(
    conn: sqlite3.Connection,
    *,
    store: StoreConfig,
    run_id: int,
    listings: Sequence[RawListing],
    result: str,
    detail: str | None = None,
) -> int:
    """Record one adapter result without ever asserting complete market coverage.

    Even an Ok from a price adapter only proves that its own crawl returned;
    it does not prove every physical SKU or edition was enumerated.
    """
    scope_key, scope_type = scope_for(store)
    status = (
        market.CoverageStatus.FAILED
        if result in {"failed", "skipped"}
        else market.CoverageStatus.PARTIAL
    )
    conn.execute("SAVEPOINT market_import")
    try:
        scan_id = market.record_scan(
            conn,
            store_id=store.id,
            scope_key=scope_key,
            scope_type=scope_type,
            coverage_status=status,
            run_id=run_id,
            detail=detail or (
                "Price-adapter crawl; market completeness and release identity unverified"
            ),
        )
        if status is market.CoverageStatus.PARTIAL:
            seen: set[str] = set()
            for item in listings:
                if item.store_id != store.id:
                    continue
                parsed = urlsplit(item.url)
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                    continue
                if not item.sku.strip() or item.sku in seen:
                    continue
                seen.add(item.sku)
                item_id = market.upsert_retailer_item(
                    conn,
                    store_id=store.id,
                    scope_key=scope_key,
                    item_key=item.sku,
                    sku=item.sku,
                    url=item.url,
                    # A price listing cannot prove edition/region/format identity.
                    product_id=None,
                )
                market.record_observation(
                    conn,
                    scan_id=scan_id,
                    retailer_item_id=item_id,
                    state=(
                        market.ObservationState.IN_STOCK
                        if item.in_stock
                        else market.ObservationState.OUT_OF_STOCK
                    ),
                    price=item.native_price,
                    currency=item.native_currency,
                )
        conn.execute("RELEASE SAVEPOINT market_import")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT market_import")
        conn.execute("RELEASE SAVEPOINT market_import")
        raise
    return scan_id
