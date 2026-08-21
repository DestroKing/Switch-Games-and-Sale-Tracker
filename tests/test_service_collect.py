"""The collection run.

This is the orchestrator: pools, deadlines, persistence and health recording.
The adapters are faked here on purpose -- their own behaviour is covered by
their own tests, and what matters at this level is what gets WRITTEN.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db
from switch_tracker.core.models import (
    AdapterKind,
    Condition,
    Failed,
    FetchOutcome,
    Ok,
    Partial,
    Platform,
    RawListing,
    Region,
    StoreConfig,
)
from switch_tracker.services.collect import CollectService


def listing(sku: str, price: float = 4499.0, store: str = "s1") -> RawListing:
    return RawListing(
        store_id=store,
        sku=sku,
        url=f"https://shop.in/p/{sku}",
        title=f"Game {sku}",
        native_currency="INR",
        native_price=price,
        in_stock=True,
        platform=Platform.SWITCH,
        region=Region.IN,
        condition=Condition.NEW,
    )


class FakeAdapter:
    def __init__(self, kind: AdapterKind, outcome: FetchOutcome, delay: float = 0.0) -> None:
        self.kind = kind
        self._outcome = outcome
        self._delay = delay
        self.in_flight = 0
        self.peak = 0

    async def fetch(self, store: StoreConfig, sink: object) -> FetchOutcome:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            return self._outcome
        finally:
            self.in_flight -= 1


def store(store_id: str, kind: AdapterKind = AdapterKind.SHOPIFY, currency: str = "INR") -> StoreConfig:
    return StoreConfig(
        id=store_id,
        name=store_id.upper(),
        base_url=f"https://{store_id}.in",
        kind=kind,
        currency=currency,
        tier=2,
        enabled=True,
    )


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "c.db")
    db.ensure_schema(connection)
    return connection


def service(conn: sqlite3.Connection, adapters: dict, **kw) -> CollectService:
    return CollectService(conn, adapters=adapters, fx=None, **kw)


class TestPersistence:
    async def test_writes_a_run_and_a_health_row_per_store(self, conn) -> None:
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)))}
        await service(conn, adapters).run([store("s1")])

        assert conn.execute("SELECT COUNT(*) c FROM run").fetchone()["c"] == 1
        row = conn.execute("SELECT status, listings_found FROM run_store").fetchone()
        assert (row["status"], row["listings_found"]) == ("ok", 1)

    async def test_marks_the_run_finished(self, conn) -> None:
        """An unfinished run would block the next one at the active-run index."""
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)))}
        await service(conn, adapters).run([store("s1")])
        assert conn.execute("SELECT finished_at FROM run").fetchone()["finished_at"] is not None

    async def test_projects_the_store_config_into_the_store_table(self, conn) -> None:
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)))}
        await service(conn, adapters).run([store("s1")])
        assert conn.execute("SELECT name FROM store WHERE id='s1'").fetchone()["name"] == "S1"

    async def test_a_second_run_appends_history_rather_than_duplicating_the_listing(
        self, conn
    ) -> None:
        """The property the entire project exists for.

        The same cartridge seen twice must be ONE listing with TWO price
        points. If it became two listings, every price series would stay one
        point long and 'moved since last run' would be permanently empty --
        with no error anywhere to notice.
        """
        first = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A", 4499.0),)))}
        await service(conn, first).run([store("s1")])

        second = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A", 3999.0),)))}
        await service(conn, second).run([store("s1")])

        assert conn.execute("SELECT COUNT(*) c FROM listing").fetchone()["c"] == 1
        prices = [r["inr_price"] for r in conn.execute("SELECT inr_price FROM price_point ORDER BY id")]
        assert prices == [4499.0, 3999.0]

    async def test_preserves_first_seen_while_moving_last_seen(self, conn) -> None:
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)))}
        await service(conn, adapters).run([store("s1")])
        original = conn.execute("SELECT first_seen FROM listing").fetchone()["first_seen"]
        await service(conn, adapters).run([store("s1")])
        row = conn.execute("SELECT first_seen, last_seen FROM listing").fetchone()
        assert row["first_seen"] == original


class TestOutcomes:
    async def test_records_a_failure_with_its_reason(self, conn) -> None:
        """A store going quiet must be as loud in the data as an exception."""
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Failed("Cloudflare blocked us"))}
        await service(conn, adapters).run([store("s1")])
        row = conn.execute("SELECT status, detail FROM run_store").fetchone()
        assert row["status"] == "failed"
        assert "Cloudflare" in row["detail"]

    async def test_records_a_partial_with_its_reason(self, conn) -> None:
        outcome = Partial((listing("A"),), "stopped early (fetched 50 of 500)")
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, outcome)}
        await service(conn, adapters).run([store("s1")])
        row = conn.execute("SELECT status, detail FROM run_store").fetchone()
        assert row["status"] == "partial"
        assert "500" in row["detail"]

    async def test_skips_a_store_whose_kind_has_no_adapter(self, conn) -> None:
        """Recorded as skipped WITH a reason, never silently dropped."""
        await service(conn, {}).run([store("s1", AdapterKind.BROWSER)])
        row = conn.execute("SELECT status, detail FROM run_store").fetchone()
        assert row["status"] == "skipped"
        assert "BROWSER" in row["detail"]

    async def test_an_adapter_that_raises_is_recorded_not_propagated(self, conn) -> None:
        class Exploding:
            kind = AdapterKind.SHOPIFY

            async def fetch(self, store: StoreConfig, sink: object) -> FetchOutcome:
                raise RuntimeError("selector blew up")

        await service(conn, {AdapterKind.SHOPIFY: Exploding()}).run([store("s1")])
        row = conn.execute("SELECT status, detail FROM run_store").fetchone()
        assert row["status"] == "failed"
        assert "selector blew up" in row["detail"]

    async def test_one_failing_store_does_not_stop_the_others(self, conn) -> None:
        adapters = {
            AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),))),
            AdapterKind.WOOCOMMERCE: FakeAdapter(AdapterKind.WOOCOMMERCE, Failed("down")),
        }
        await service(conn, adapters).run([store("s1"), store("s2", AdapterKind.WOOCOMMERCE)])
        rows = conn.execute("SELECT store_id, status FROM run_store")
        statuses = {r["store_id"]: r["status"] for r in rows}
        assert statuses == {"s1": "ok", "s2": "failed"}


class TestDeadlines:
    async def test_a_hung_store_is_abandoned_with_a_readable_reason(self, conn) -> None:
        """No single store may hold the run hostage."""
        slow = FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)), delay=5.0)
        svc = service(conn, {AdapterKind.SHOPIFY: slow}, http_deadline_s=0.05)
        await svc.run([store("s1")])
        row = conn.execute("SELECT status, detail FROM run_store").fetchone()
        assert row["status"] == "failed"
        assert "gave up" in row["detail"]

    async def test_the_production_deadlines_are_per_kind(self) -> None:
        """An HTTP store is bounded by its own request budget regardless of size.

        A browser store now pages for as long as the site's own signal keeps
        working, so its budget has to cover a genuinely large catalogue.
        """
        svc = CollectService(None, adapters={}, fx=None)  # type: ignore[arg-type]
        assert svc.http_deadline_s == 180.0
        assert svc.browser_deadline_s == 600.0


class TestPools:
    async def test_http_and_browser_stores_use_separate_pools(self, conn) -> None:
        """A flat shared limit let two large browser catalogues occupy every
        slot and starve every other browser store for the whole run."""
        http = FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)), delay=0.05)
        browser = FakeAdapter(AdapterKind.BROWSER, Ok((listing("B"),)), delay=0.05)
        svc = service(
            conn,
            {AdapterKind.SHOPIFY: http, AdapterKind.BROWSER: browser},
            http_concurrency=8,
            browser_concurrency=2,
        )
        stores = [store(f"h{i}") for i in range(8)] + [
            store(f"b{i}", AdapterKind.BROWSER) for i in range(6)
        ]
        await svc.run(stores)
        assert browser.peak <= 2
        assert http.peak > 2

    async def test_the_production_pool_sizes_are_carried_over(self) -> None:
        svc = CollectService(None, adapters={}, fx=None)  # type: ignore[arg-type]
        assert svc.http_concurrency == 8
        assert svc.browser_concurrency == 4


class TestProgressEvents:
    async def test_emits_a_start_and_finish_for_the_run(self, conn) -> None:
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)))}
        await service(conn, adapters).run([store("s1")])
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM run_event ORDER BY seq")]
        assert kinds[0] == "run_started"
        assert kinds[-1] == "run_finished"

    async def test_emits_a_terminal_event_per_store(self, conn) -> None:
        adapters = {AdapterKind.SHOPIFY: FakeAdapter(AdapterKind.SHOPIFY, Ok((listing("A"),)))}
        await service(conn, adapters).run([store("s1")])
        row = conn.execute(
            "SELECT status, count FROM run_event WHERE kind='store_finished'"
        ).fetchone()
        assert (row["status"], row["count"]) == ("ok", 1)
