"""A collection run.

Stores are independent hosts with nothing to do with each other, so they run
concurrently -- but HTTP stores and browser stores cost wildly different
amounts of memory and CPU, so they get separate pools and separate deadlines.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence

from switch_tracker.adapters.base import Adapter
from switch_tracker.core.concurrency import bounded_gather
from switch_tracker.core.db import now_iso
from switch_tracker.core.models import AdapterKind, Failed, Ok, Partial, RawListing, StoreConfig
from switch_tracker.events.writer import EventWriter
from switch_tracker.fx.rates import FxService


def select_stores(
    stores: Sequence[StoreConfig], only: tuple[str, ...]
) -> list[StoreConfig]:
    """Which stores are in scope for a run.

    ONE definition, deliberately module-level rather than a method. The worker
    needs this answer BEFORE a CollectService exists, to decide whether to
    launch Chromium at all -- and if the gate and the work list computed scope
    separately they would eventually disagree. That disagreement has a specific,
    silent shape: the gate says "no browser store" while the work list contains
    one, so the store records "no adapter" and collects nothing.

    ``only`` empty  -> every ENABLED store; exactly the behaviour that existed
                       before selection was a concept.
    ``only`` given  -> exactly those ids, and ``enabled`` is NOT consulted.
                       Naming a store is the intent; the store you most want to
                       run in isolation is often one probe has just disabled.

    Input order is preserved in both branches. bounded_gather starts tasks in
    list order against a bounded pool, and Play-Asia ships first in the browser
    group so it claims a slot immediately -- honouring the caller's argument
    order instead would quietly undo that.
    """
    if not only:
        return [s for s in stores if s.enabled]
    wanted = set(only)
    return [s for s in stores if s.id in wanted]


class CollectService:
    #: HTTP stores are bounded tightly regardless of catalogue size: the
    #: client's own per-request timeout and retry budget caps every page it
    #: fetches either way.
    DEFAULT_HTTP_DEADLINE_S = 180.0
    #: A browser store pages for as long as the site's own signal keeps
    #: working, so its budget has to cover a genuinely large catalogue rather
    #: than a guess about any one store's page count.
    DEFAULT_BROWSER_DEADLINE_S = 600.0

    DEFAULT_HTTP_CONCURRENCY = 8
    #: Was 2. With only two slots, two large catalogues landing in both at
    #: once left every other browser store waiting for the entire run. Raised
    #: enough that a couple of big stores cannot block the rest, still well
    #: below the browser store count so this is not a Chromium context per
    #: store at once.
    DEFAULT_BROWSER_CONCURRENCY = 4

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        adapters: dict[AdapterKind, Adapter],
        fx: FxService | None,
        http_deadline_s: float = DEFAULT_HTTP_DEADLINE_S,
        browser_deadline_s: float = DEFAULT_BROWSER_DEADLINE_S,
        http_concurrency: int = DEFAULT_HTTP_CONCURRENCY,
        browser_concurrency: int = DEFAULT_BROWSER_CONCURRENCY,
    ) -> None:
        self._conn = conn
        self._adapters = adapters
        self._fx = fx
        self.http_deadline_s = http_deadline_s
        self.browser_deadline_s = browser_deadline_s
        self.http_concurrency = http_concurrency
        self.browser_concurrency = browser_concurrency

    async def run(
        self,
        stores: Sequence[StoreConfig],
        run_id: int | None = None,
        *,
        only: tuple[str, ...] = (),
    ) -> int:
        """Collect ``stores``, narrowed by ``only``.

        ``only`` is keyword-only: every existing caller passes ``stores``
        positionally, and a third positional would read as ``run_id`` at a
        glance.

        ``stores`` stays the FULL list even when a selection is given --
        _sync_store_table projects every store's enabled flag into the store
        table, so pre-filtering here would stop disabled stores being synced.
        Scope is an input to this method, not a filter applied before it.
        """
        active = select_stores(stores, only)
        self._sync_store_table(stores)

        if run_id is None:
            cursor = self._conn.execute("INSERT INTO run (started_at) VALUES (?)", (now_iso(),))
            run_id = int(cursor.lastrowid or 0)

        events = EventWriter(self._conn, run_id)
        events.run_started(len(active))

        if only:
            # Without this the console shows a one-store run and no reason for
            # it, which reads like twelve stores silently vanished.
            found = [s.id for s in active]
            missing = [store_id for store_id in only if store_id not in set(found)]
            detail = f"Collecting only: {', '.join(found) or 'nothing'}"
            if missing:
                detail += f" (unknown, skipped: {', '.join(missing)})"
            events.warning(detail)

        # Refresh rates BEFORE anything else, so every price in this run
        # converts at one rate rather than drifting mid-run.
        if self._fx is not None:
            currencies = [s.currency for s in active]
            try:
                await self._fx.refresh(currencies)
            except Exception as exc:  # noqa: BLE001
                # Native price is still the captured fact; a run without FX is
                # degraded, not useless.
                events.warning(f"exchange rates unavailable: {exc}")

        http_stores = [s for s in active if s.kind is not AdapterKind.BROWSER]
        browser_stores = [s for s in active if s.kind is AdapterKind.BROWSER]

        async def process(store: StoreConfig) -> None:
            await self._process_store(store, run_id, events)

        # Both pools run at once -- HTTP stores were never waiting on browser
        # stores, so there is no reason to start them staggered.
        await asyncio.gather(
            bounded_gather(http_stores, self.http_concurrency, process),
            bounded_gather(browser_stores, self.browser_concurrency, process),
        )

        self._conn.execute("UPDATE run SET finished_at = ? WHERE id = ?", (now_iso(), run_id))
        events.run_finished()
        return run_id

    async def _process_store(self, store: StoreConfig, run_id: int, events: EventWriter) -> None:
        started = asyncio.get_running_loop().time()
        adapter = self._adapters.get(store.kind)

        events.store_started(store.id, str(store.kind))

        def elapsed_ms() -> int:
            return int((asyncio.get_running_loop().time() - started) * 1000)

        if adapter is None:
            self._record(run_id, store.id, "skipped", 0, elapsed_ms(), f"no adapter for {store.kind}")
            events.store_finished(
                store.id, status="skipped", count=0, duration_ms=elapsed_ms(),
                detail=f"no adapter for {store.kind}",
            )
            return

        deadline = (
            self.browser_deadline_s if store.kind is AdapterKind.BROWSER else self.http_deadline_s
        )

        try:
            outcome = await asyncio.wait_for(adapter.fetch(store, events), timeout=deadline)
        except TimeoutError:
            reason = f"gave up after {int(deadline)}s ({store.id})"
            self._record(run_id, store.id, "failed", 0, elapsed_ms(), reason)
            events.store_finished(
                store.id, status="failed", count=0, duration_ms=elapsed_ms(), detail=reason
            )
            return
        except Exception as exc:  # noqa: BLE001 - an adapter fault is a store fault, not a run fault
            reason = f"{type(exc).__name__}: {exc}"
            self._record(run_id, store.id, "failed", 0, elapsed_ms(), reason)
            events.store_finished(
                store.id, status="failed", count=0, duration_ms=elapsed_ms(), detail=reason
            )
            return

        if isinstance(outcome, Failed):
            self._record(run_id, store.id, "failed", 0, elapsed_ms(), outcome.reason)
            events.store_finished(
                store.id, status="failed", count=0, duration_ms=elapsed_ms(), detail=outcome.reason
            )
            return

        saved = self._persist(run_id, store, outcome.listings)
        status = "ok" if isinstance(outcome, Ok) else "partial"
        detail = outcome.reason if isinstance(outcome, Partial) else None
        self._record(run_id, store.id, status, saved, elapsed_ms(), detail)
        events.store_finished(
            store.id, status=status, count=saved, duration_ms=elapsed_ms(), detail=detail
        )

    def _sync_store_table(self, stores: Sequence[StoreConfig]) -> None:
        """Config is the source of truth; the table is a projection of it."""
        self._conn.executemany(
            "INSERT INTO store (id, name, base_url, kind, currency, tier, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, base_url=excluded.base_url, "
            "kind=excluded.kind, currency=excluded.currency, tier=excluded.tier, "
            "enabled=excluded.enabled",
            [
                (s.id, s.name, s.base_url, str(s.kind), s.currency, s.tier, 1 if s.enabled else 0)
                for s in stores
            ],
        )

    def _persist(self, run_id: int, store: StoreConfig, listings: Sequence[RawListing]) -> int:
        """Upsert the listing, ALWAYS append a price point.

        first_seen and image_url are deliberately left alone on conflict: the
        first is a fact about when this listing appeared, and overwriting it
        every run would erase it.
        """
        now = now_iso()
        saved = 0
        self._conn.execute("BEGIN")
        try:
            for item in listings:
                row = self._conn.execute(
                    "INSERT INTO listing (store_id, sku, url, raw_title, platform, region, "
                    "condition, image_url, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, sku) DO UPDATE SET url=excluded.url, "
                    "raw_title=excluded.raw_title, platform=excluded.platform, "
                    "region=excluded.region, condition=excluded.condition, "
                    "last_seen=excluded.last_seen RETURNING id",
                    (
                        store.id, item.sku, item.url, item.title, str(item.platform),
                        str(item.region), str(item.condition), item.image_url, now, now,
                    ),
                ).fetchone()
                if row is None:
                    continue

                inr, rate_date = (
                    self._fx.to_inr(item.native_price, item.native_currency)
                    if self._fx is not None
                    else (item.native_price if item.native_currency == "INR" else None, None)
                )
                self._conn.execute(
                    "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, "
                    "native_price, inr_price, fx_rate_date, in_stock) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["id"], run_id, now, item.native_currency, item.native_price,
                        inr, rate_date, 1 if item.in_stock else 0,
                    ),
                )
                saved += 1
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return saved

    def _record(
        self, run_id: int, store_id: str, status: str, found: int, ms: int, detail: str | None
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_store (run_id, store_id, status, listings_found, "
            "duration_ms, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, store_id, status, found, ms, detail),
        )
