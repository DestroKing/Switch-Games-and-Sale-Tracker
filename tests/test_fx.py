"""Exchange rates.

Native price is the captured fact; INR is DERIVED from a dated ECB rate. The
rate date is stored alongside every price point so a later query never has to
guess which rate applied -- and so the alert engine can eventually ask "did
four hundred prices move by the same ratio on the same day?", the question
that separates a currency reset from a real sale.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from switch_tracker.core import db
from switch_tracker.core.http import PoliteClient
from switch_tracker.fx.rates import FxService


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "fx.db")
    db.ensure_schema(connection)
    return connection


@pytest.fixture
def client() -> PoliteClient:
    return PoliteClient(min_gap_s=0.0, timeout_s=5.0, backoff_base_s=0.01)


def rates_response(rate: float, date: str) -> tuple[int, str, dict[str, str]]:
    body = json.dumps({"base": "USD", "date": date, "rates": {"INR": rate}})
    return (200, body, {"content-type": "application/json"})


class TestRefresh:
    async def test_stores_the_rate_under_its_publication_date(self, conn, client, server) -> None:
        """A weekend fetch legitimately returns Friday's rate.

        That is correct, not stale -- so it is stored and reused under the day
        the ECB published it, not the day we happened to ask.
        """
        base, recorder = server
        recorder.plan("/latest", rates_response(95.7, "2026-08-21"))
        service = FxService(conn, client, endpoint=base)

        await service.refresh(["USD"])

        row = conn.execute("SELECT base, quote, rate, rate_date FROM fx_rate").fetchone()
        actual = (row["base"], row["quote"], row["rate"], row["rate_date"])
        assert actual == ("USD", "INR", 95.7, "2026-08-21")

    async def test_never_asks_for_a_rupee_to_rupee_rate(self, conn, client, server) -> None:
        base, recorder = server
        service = FxService(conn, client, endpoint=base)
        await service.refresh(["INR"])
        assert recorder.hits == []

    async def test_fetches_each_currency_once(self, conn, client, server) -> None:
        base, recorder = server
        recorder.plan("/latest", rates_response(95.7, "2026-08-21"))
        service = FxService(conn, client, endpoint=base)
        await service.refresh(["USD", "INR", "USD"])
        assert len(recorder.hits) == 1

    async def test_an_unreachable_provider_is_survivable(self, conn, client) -> None:
        """A collection must continue without FX. The native price is still the fact."""
        service = FxService(conn, client, endpoint="http://127.0.0.1:9")
        assert await service.refresh(["USD"]) == []


class TestLatestRate:
    def test_rupees_convert_to_themselves(self, conn, client) -> None:
        service = FxService(conn, client)
        rate = service.latest_rate("INR")
        assert rate is not None
        assert rate.rate == 1.0

    def test_returns_the_most_recently_published_rate(self, conn, client) -> None:
        conn.execute("INSERT INTO fx_rate VALUES ('USD','INR',90.0,'2026-08-01','t')")
        conn.execute("INSERT INTO fx_rate VALUES ('USD','INR',95.7,'2026-08-21','t')")
        service = FxService(conn, client)
        rate = service.latest_rate("USD")
        assert rate is not None
        assert rate.rate == 95.7

    def test_returns_nothing_for_an_unknown_currency(self, conn, client) -> None:
        assert FxService(conn, client).latest_rate("JPY") is None


class TestToInr:
    def test_converts_using_the_stored_rate(self, conn, client) -> None:
        conn.execute("INSERT INTO fx_rate VALUES ('USD','INR',95.7,'2026-08-21','t')")
        inr, rate_date = FxService(conn, client).to_inr(59.99, "USD")
        assert inr == 5741.04  # 59.99 * 95.7, rounded to paise
        assert rate_date == "2026-08-21"

    def test_a_rupee_price_passes_through(self, conn, client) -> None:
        inr, _ = FxService(conn, client).to_inr(4499.0, "INR")
        assert inr == 4499.0

    def test_refuses_to_invent_a_conversion_when_no_rate_is_stored(self, conn, client) -> None:
        """The fix.

        rates.ts returns the NATIVE figure with no rate date when no rate
        exists, so $59.99 is recorded as if it were 59.99 rupees -- silently,
        and permanently, in a table whose whole purpose is price history.
        Recording no number is correct; recording a wrong one is not.
        """
        inr, rate_date = FxService(conn, client).to_inr(59.99, "USD")
        assert inr is None
        assert rate_date is None
