"""Ingestion: what a collection run writes to market.db.

Driven through the real CollectService with faked adapters, as
tests/test_service_collect.py does: what matters is what reaches the file,
and the hook is part of that.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from switch_tracker.core import db
from switch_tracker.core.models import (
    AdapterKind,
    Condition,
    Coverage,
    Failed,
    FetchOutcome,
    Ok,
    Partial,
    Platform,
    RawListing,
    Region,
    StoreConfig,
)
from switch_tracker.market import db as market_db
from switch_tracker.market.ingest import MarketObserver
from switch_tracker.services.collect import CollectService


def row(sku: str, *, in_stock: bool = True, price: float = 3999.0, url: str = "") -> RawListing:
    return RawListing(
        "s1",
        sku,
        url or f"https://s1.in/p/{sku}",
        f"Game {sku}",
        "INR",
        price,
        in_stock,
        Platform.SWITCH,
        Region.IN,
        Condition.NEW,
    )


def complete(*skus: str, extra: frozenset[str] = frozenset()) -> Coverage:
    seen = frozenset(skus) | extra
    return Coverage(1, 1, True, None, len(seen), seen)


def ok(*rows: RawListing, extra: frozenset[str] = frozenset()) -> Ok:
    return Ok(rows, complete(*(r.sku for r in rows), extra=extra))


class Scripted:
    """An adapter that returns the next outcome on each run."""

    def __init__(self, kind: AdapterKind, *outcomes: FetchOutcome) -> None:
        self.kind = kind
        self._outcomes = list(outcomes)

    async def fetch(self, store: StoreConfig, sink: object) -> FetchOutcome:
        return self._outcomes.pop(0)


STORE = StoreConfig("s1", "S1", "https://s1.in", AdapterKind.SHOPIFY, "INR", 2, True)


@pytest.fixture
def legacy(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "tracker.db")
    db.ensure_schema(conn)
    return conn


@pytest.fixture
def market(tmp_path: Path) -> sqlite3.Connection:
    return market_db.open_db(tmp_path / "market.db")


async def collect(
    legacy: sqlite3.Connection,
    market: sqlite3.Connection,
    *outcomes: FetchOutcome,
    store: StoreConfig = STORE,
    **kw: object,
) -> None:
    """One collection run per outcome, all against the same two files."""
    adapter = Scripted(store.kind, *outcomes)
    observer = MarketObserver(market, **kw)  # type: ignore[arg-type]
    for _ in outcomes:
        await CollectService(legacy, adapters={store.kind: adapter}, fx=None, observer=observer).run([store])


def spans(market: sqlite3.Connection, sku: str) -> list[tuple[str, int]]:
    return [
        (r["state"], r["confirmations"])
        for r in market.execute(
            "SELECT state, confirmations FROM state_span s JOIN listing l ON l.id = s.listing_id "
            "WHERE l.sku = ? ORDER BY s.id",
            (sku,),
        )
    ]


class TestScans:
    async def test_every_store_run_is_a_scan_with_its_verdict(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A")))
        scan = market.execute("SELECT * FROM scan").fetchone()
        assert (scan["outcome"], scan["coverage"]) == ("OK", "COMPLETE")
        assert scan["legacy_run_id"] == legacy.execute("SELECT id FROM run").fetchone()["id"]
        assert scan["listings_seen"] == 1
        assert "end of pagination" in scan["evidence"]

    async def test_a_failed_store_is_a_failed_scan_not_a_missing_one(self, legacy, market) -> None:
        await collect(legacy, market, Failed("HTTP 403"))
        scan = market.execute("SELECT * FROM scan").fetchone()
        assert (scan["outcome"], scan["coverage"], scan["failure"]) == ("FAILED", "FAILED", "HTTP 403")

    async def test_the_storefront_and_its_scope_are_created_once(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A")), ok(row("A")))
        assert market.execute("SELECT COUNT(*) FROM storefront").fetchone()[0] == 1
        assert market.execute("SELECT COUNT(*) FROM scope").fetchone()[0] == 1
        assert market.execute("SELECT COUNT(*) FROM scan").fetchone()[0] == 2

    async def test_marketplaces_and_importers_start_out_marked(self, legacy, market) -> None:
        """Never counted as an independent Indian shop, from the first scan on."""
        for store_id in ("amazon_in", "playasia"):
            await collect(
                legacy, market, Ok((replace(row("A"), store_id=store_id),)), store=replace(STORE, id=store_id)
            )
        kinds = dict(market.execute("SELECT id, kind FROM retailer").fetchall())
        assert kinds["amazon_in"] == "MARKETPLACE"
        abroad = market.execute("SELECT ships_from_abroad FROM storefront WHERE id = 'playasia'").fetchone()[
            0
        ]
        assert abroad == 1

    async def test_browser_stock_is_inferred_not_reported(self, legacy, market) -> None:
        browser = replace(STORE, kind=AdapterKind.BROWSER)
        await collect(legacy, market, Ok((row("A"),)), store=browser)
        assert market.execute("SELECT stock_signal FROM storefront").fetchone()[0] == "INFERRED"

    async def test_a_changed_configuration_is_a_new_scope(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A")))
        await collect(legacy, market, ok(row("A")), store=replace(STORE, collections=("switch",)))
        assert market.execute("SELECT COUNT(*) FROM scope").fetchone()[0] == 2


class TestHistory:
    async def test_an_unchanged_state_extends_the_open_span(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A")), ok(row("A")), ok(row("A")))
        assert spans(market, "A") == [("IN_STOCK", 3)]

    async def test_a_change_opens_a_new_span_and_keeps_the_old(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A")), ok(row("A", in_stock=False)), ok(row("A")))
        assert spans(market, "A") == [("IN_STOCK", 1), ("OUT_OF_STOCK", 1), ("IN_STOCK", 1)]

    async def test_a_price_change_is_history_too(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A", price=3999)), ok(row("A", price=2999)))
        prices = [r[0] for r in market.execute("SELECT price FROM state_span ORDER BY id")]
        assert prices == [3999, 2999]

    async def test_a_span_records_its_scans_and_times(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A")), ok(row("A")))
        span = market.execute("SELECT * FROM state_span").fetchone()
        first, last = (r[0] for r in market.execute("SELECT id FROM scan ORDER BY id"))
        assert (span["first_scan_id"], span["last_scan_id"]) == (first, last)
        assert span["started_at"] <= span["last_confirmed_at"]

    async def test_a_non_web_link_is_never_stored(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A", url="javascript:alert(1)")))
        assert market.execute("SELECT COUNT(*) FROM listing").fetchone()[0] == 0


class TestAbsence:
    async def test_a_complete_scan_without_the_listing_marks_it_not_listed(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A"), row("B")), ok(row("A")))
        assert spans(market, "B") == [("IN_STOCK", 1), ("NOT_LISTED", 1)]

    async def test_absence_is_confirmed_by_later_complete_scans(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A"), row("B")), ok(row("A")), ok(row("A")))
        assert spans(market, "B") == [("IN_STOCK", 1), ("NOT_LISTED", 2)]

    async def test_reappearance_opens_a_new_span_and_keeps_the_absence(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A"), row("B")), ok(row("A")), ok(row("A"), row("B")))
        assert spans(market, "B") == [("IN_STOCK", 1), ("NOT_LISTED", 1), ("IN_STOCK", 1)]

    @pytest.mark.parametrize(
        "second",
        [
            Partial((row("A"),), "time budget", complete("A")),
            Failed("HTTP 500"),
            Ok((row("A"),)),  # no coverage evidence: UNKNOWN
            Ok((row("A"),), replace(complete("A"), end_reached=False)),
        ],
        ids=["partial", "failed", "no-evidence", "no-end"],
    )
    async def test_anything_short_of_complete_never_creates_an_absence(
        self, legacy, market, second: FetchOutcome
    ) -> None:
        await collect(legacy, market, ok(row("A"), row("B")), second)
        assert spans(market, "B") == [("IN_STOCK", 1)]

    async def test_a_product_the_classifier_dropped_is_not_absent(self, legacy, market) -> None:
        """The raw walk saw B; only the classifier stopped keeping it. Not proof it is gone."""
        await collect(legacy, market, ok(row("A"), row("B")), ok(row("A"), extra=frozenset({"B"})))
        assert spans(market, "B") == [("IN_STOCK", 1)]

    async def test_a_complete_scan_of_another_scope_proves_nothing(self, legacy, market) -> None:
        await collect(legacy, market, ok(row("A"), row("B")))
        await collect(legacy, market, ok(row("A")), store=replace(STORE, collections=("switch",)))
        assert spans(market, "B") == [("IN_STOCK", 1)]

    async def test_other_storefronts_are_never_reconciled(self, legacy, market) -> None:
        other = replace(STORE, id="s2")
        await collect(legacy, market, Ok((replace(row("B"), store_id="s2"),), complete("B")), store=other)
        await collect(legacy, market, ok(row("A")))
        assert spans(market, "B") == [("IN_STOCK", 1)]

    async def test_browse_scopes_never_create_absences(self, legacy, market) -> None:
        browser = replace(STORE, kind=AdapterKind.BROWSER)
        await collect(legacy, market, ok(row("A"), row("B")), ok(row("A")), store=browser)
        assert spans(market, "B") == [("IN_STOCK", 1)]


class TestIsolation:
    async def test_a_raising_market_never_fails_the_price_run(self, legacy, market) -> None:
        market.close()  # every market write now raises
        await collect(legacy, market, ok(row("A")))
        status = legacy.execute("SELECT status, listings_found FROM run_store").fetchone()
        assert (status["status"], status["listings_found"]) == ("ok", 1)
        assert legacy.execute("SELECT COUNT(*) FROM price_point").fetchone()[0] == 1
        assert legacy.execute("SELECT finished_at FROM run").fetchone()["finished_at"] is not None
        warnings = [r[0] for r in legacy.execute("SELECT detail FROM run_event WHERE kind = 'warning'")]
        assert any("market tracker" in w for w in warnings)

    async def test_a_failed_market_write_leaves_nothing_half_written(self, legacy, market) -> None:
        market.execute(
            "CREATE TRIGGER boom BEFORE INSERT ON state_span WHEN NEW.listing_id > 1 "
            "BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )
        await collect(legacy, market, ok(row("A"), row("B")))
        assert market.execute("SELECT COUNT(*) FROM listing").fetchone()[0] == 0
        assert market.execute("SELECT COUNT(*) FROM scan").fetchone()[0] == 0

    async def test_a_timed_out_store_is_still_a_failed_scan(self, legacy, market) -> None:
        class Hangs:
            kind = AdapterKind.SHOPIFY

            async def fetch(self, store: StoreConfig, sink: object) -> FetchOutcome:
                import asyncio

                await asyncio.sleep(10)
                raise AssertionError

        observer = MarketObserver(market)
        service = CollectService(
            legacy, adapters={AdapterKind.SHOPIFY: Hangs()}, fx=None, observer=observer, http_deadline_s=0.01
        )
        await service.run([STORE])
        scan = market.execute("SELECT coverage, failure FROM scan").fetchone()
        assert scan["coverage"] == "FAILED"
        assert "gave up" in scan["failure"]
        assert legacy.execute("SELECT status FROM run_store").fetchone()["status"] == "failed"

    async def test_market_db_is_backed_up_at_the_end_of_a_run(self, legacy, market, tmp_path: Path) -> None:
        await collect(legacy, market, ok(row("A")), backup_dir=tmp_path / "backups")
        [copy] = (tmp_path / "backups").glob("market-run*.db")
        assert sqlite3.connect(copy).execute("SELECT COUNT(*) FROM scan").fetchone()[0] == 1
