"""Exchange rates from Frankfurter (ECB reference rates, no API key).

Two consequences of using ECB rates are handled rather than papered over:

  * The ECB publishes on working days only, so a weekend fetch returns
    Friday's rate.  That is correct, not stale -- it is stored and reused
    under its own publication date.
  * The rate date stored on every price point is what later lets the alert
    engine ask "did four hundred prices move by the same ratio on the same
    day?", which is the question separating a currency reset from a sale.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from switch_tracker.core.db import now_iso
from switch_tracker.core.http import PoliteClient

_ENDPOINT = "https://api.frankfurter.app"


@dataclass(frozen=True, slots=True)
class FxRate:
    base: str
    quote: str
    rate: float
    #: ECB publication date, not the time we fetched it.
    rate_date: str


class FxService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client: PoliteClient,
        *,
        endpoint: str = _ENDPOINT,
    ) -> None:
        self._conn = conn
        self._client = client
        self._endpoint = endpoint

    async def refresh(self, currencies: list[str]) -> list[FxRate]:
        """Fetch one rate per unique non-rupee currency actually in use.

        Called at the START of a collection so every price in the run converts
        at one rate rather than drifting mid-run.
        """
        out: list[FxRate] = []
        for base in dict.fromkeys(currencies):
            if base == "INR":
                continue
            data = await self._client.get_json(f"{self._endpoint}/latest?from={base}&to=INR")
            if not isinstance(data, dict):
                continue
            rate = (data.get("rates") or {}).get("INR")
            date = data.get("date")
            if not isinstance(rate, (int, float)) or not isinstance(date, str):
                continue
            self._conn.execute(
                "INSERT OR REPLACE INTO fx_rate (base, quote, rate, rate_date, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (base, "INR", float(rate), date, now_iso()),
            )
            out.append(FxRate(base, "INR", float(rate), date))
        return out

    def latest_rate(self, base: str) -> FxRate | None:
        if base == "INR":
            return FxRate("INR", "INR", 1.0, now_iso()[:10])
        row = self._conn.execute(
            "SELECT rate, rate_date FROM fx_rate WHERE base = ? AND quote = 'INR' "
            "ORDER BY rate_date DESC LIMIT 1",
            (base,),
        ).fetchone()
        return FxRate(base, "INR", row["rate"], row["rate_date"]) if row else None

    def to_inr(self, native_price: float, currency: str) -> tuple[float | None, str | None]:
        """Derive the rupee figure, or decline to.

        When no rate is stored this returns (None, None) and the caller writes
        NULL. rates.ts returns the NATIVE price with no rate date instead, so
        $59.99 lands in inr_price as though it were 59.99 rupees -- silently,
        in the one table the entire project exists to accumulate. A missing
        number is recoverable; a wrong one is indistinguishable from a real
        price forever after.
        """
        fx = self.latest_rate(currency)
        if fx is None:
            return None, None
        return round(native_price * fx.rate, 2), fx.rate_date
