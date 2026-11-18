"""Collection -> market.db: scans, listings, state spans and absences.

Runs as CollectService's observer, after the store's fetch and beside -- never
instead of -- the price tracker's own save. One store is one transaction, so
a fault leaves market.db exactly as it was and the price run untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from switch_tracker.core.db import now_iso
from switch_tracker.core.models import AdapterKind, Failed, FetchOutcome, Ok, StoreConfig
from switch_tracker.market import db as market_db
from switch_tracker.market.coverage import scope_of, verdict

#: Shipped defaults, applied when a storefront is first seen; editable later.
#: A marketplace's sellers are not one independent Indian shop.
_MARKETPLACES = frozenset({"amazon_in", "flipkart"})
_SHIPS_FROM_ABROAD = frozenset({"playasia"})


def _is_web_url(url: str) -> bool:
    # Same rule as services.collect: only a web link may become an href.
    return urlsplit(url).scheme.lower() in ("http", "https")


class MarketObserver:
    def __init__(self, conn: sqlite3.Connection, *, backup_dir: Path | None = None) -> None:
        self._conn = conn
        #: None = no backup (tests). The worker passes paths.backups_dir().
        self._backup_dir = backup_dir

    @classmethod
    def open(cls, backup_dir: Path | None = None) -> MarketObserver:
        return cls(market_db.open_db(), backup_dir=backup_dir)

    def close(self) -> None:
        self._conn.close()

    def store_done(self, run_id: int, store: StoreConfig, outcome: FetchOutcome, started_at: str) -> None:
        self._conn.execute("BEGIN")
        try:
            self._ingest(run_id, store, outcome, started_at)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def run_done(self, run_id: int) -> None:
        if self._backup_dir is not None:
            market_db.backup(self._conn, self._backup_dir, run_id)

    def _ingest(self, run_id: int, store: StoreConfig, outcome: FetchOutcome, started_at: str) -> None:
        conn, now = self._conn, now_iso()
        kind, definition = scope_of(store)
        result = verdict(outcome, kind)

        self._sync_storefront(store)
        scope_id = conn.execute(
            "INSERT INTO scope (storefront_id, kind, definition, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(storefront_id, definition) DO UPDATE SET kind = excluded.kind RETURNING id",
            (store.id, str(kind), definition, now),
        ).fetchone()[0]

        failed = isinstance(outcome, Failed)
        coverage = None if isinstance(outcome, Failed) else outcome.coverage
        listings = () if isinstance(outcome, Failed) else outcome.listings
        scan = conn.execute(
            "INSERT OR IGNORE INTO scan (scope_id, legacy_run_id, started_at, finished_at, outcome, "
            "coverage, pages_attempted, pages_completed, claimed_total, raw_seen, end_reached, "
            "listings_seen, evidence, failure) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                scope_id,
                run_id,
                started_at,
                now,
                "FAILED" if failed else "OK" if isinstance(outcome, Ok) else "PARTIAL",
                str(result.status),
                coverage and coverage.pages_attempted,
                coverage and coverage.pages_completed,
                coverage and coverage.claimed_total,
                coverage and coverage.raw_seen,
                None if coverage is None else int(coverage.end_reached),
                len(listings),
                result.evidence,
                outcome.reason if isinstance(outcome, Failed) else None,
            ),
        ).fetchone()
        if scan is None:
            return  # this run was already ingested for this scope
        scan_id = scan[0]

        touched: set[int] = set()
        for item in listings:
            if not _is_web_url(item.url):
                continue
            listing_id = conn.execute(
                "INSERT INTO listing (storefront_id, sku, scope_id, url, title, platform, region, "
                "condition, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(storefront_id, sku) DO UPDATE SET scope_id = excluded.scope_id, "
                "url = excluded.url, title = excluded.title, platform = excluded.platform, "
                "region = excluded.region, condition = excluded.condition, last_seen = excluded.last_seen "
                "RETURNING id",
                (
                    store.id,
                    item.sku,
                    scope_id,
                    item.url,
                    item.title,
                    str(item.platform),
                    str(item.region),
                    str(item.condition),
                    now,
                    now,
                ),
            ).fetchone()[0]
            if listing_id in touched:
                continue  # one observation per listing per scan
            touched.add(listing_id)
            state = "IN_STOCK" if item.in_stock else "OUT_OF_STOCK"
            self._observe(listing_id, state, item.native_price, item.native_currency, scan_id, now)

        # Absence: only a COMPLETE walk of the very scope the listing was last
        # seen in, judged against every RAW product it saw -- a row the
        # classifier dropped was still on the store.
        if coverage is not None and result.status.absence_eligible:
            for listing_id, sku in conn.execute(
                "SELECT id, sku FROM listing WHERE storefront_id = ? AND scope_id = ?", (store.id, scope_id)
            ).fetchall():
                if listing_id not in touched and sku not in coverage.seen_skus:
                    self._observe(listing_id, "NOT_LISTED", None, None, scan_id, now)

    def _observe(
        self, listing_id: int, state: str, price: float | None, currency: str | None, scan_id: int, now: str
    ) -> None:
        """Extend the newest span if nothing changed; otherwise open a new one."""
        last = self._conn.execute(
            "SELECT id, state, price, currency FROM state_span WHERE listing_id = ? ORDER BY id DESC LIMIT 1",
            (listing_id,),
        ).fetchone()
        if last is not None and (last["state"], last["price"], last["currency"]) == (state, price, currency):
            self._conn.execute(
                "UPDATE state_span SET last_scan_id = ?, last_confirmed_at = ?, "
                "confirmations = confirmations + 1 WHERE id = ?",
                (scan_id, now, last["id"]),
            )
            return
        self._conn.execute(
            "INSERT INTO state_span (listing_id, state, price, currency, first_scan_id, last_scan_id, "
            "started_at, last_confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (listing_id, state, price, currency, scan_id, scan_id, now, now),
        )

    def _sync_storefront(self, store: StoreConfig) -> None:
        """Name, URL and stock signal follow the config; retailer grouping is the user's, once set."""
        self._conn.execute(
            "INSERT OR IGNORE INTO retailer (id, name, kind) VALUES (?, ?, ?)",
            (store.id, store.name, "MARKETPLACE" if store.id in _MARKETPLACES else "INDEPENDENT"),
        )
        self._conn.execute(
            "INSERT INTO storefront (id, retailer_id, name, base_url, stock_signal, ships_from_abroad) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
            "base_url = excluded.base_url, stock_signal = excluded.stock_signal",
            (
                store.id,
                store.id,
                store.name,
                store.base_url,
                "INFERRED" if store.kind is AdapterKind.BROWSER else "REPORTED",
                int(store.id in _SHIPS_FROM_ABROAD),
            ),
        )
