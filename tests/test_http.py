"""The collector's politeness and resilience rules.

These shops are small. One request at a time per host with a real gap between
them costs nothing -- the collector runs unattended, not in front of a user --
and keeps the project off anyone's block list.
"""

from __future__ import annotations

import time

import pytest

from switch_tracker.core.http import PoliteClient


@pytest.fixture
def client() -> PoliteClient:
    # A real but small gap: the behaviour under test is "a gap is enforced",
    # not the production value of 1.2s.
    return PoliteClient(min_gap_s=0.30, timeout_s=5.0, max_attempts=3, backoff_base_s=0.01)


class TestPoliteness:
    async def test_leaves_a_gap_between_requests_to_the_same_host(
        self, client: PoliteClient, server: tuple[str, object]
    ) -> None:
        base, _ = server
        started = time.monotonic()
        await client.get(f"{base}/a")
        await client.get(f"{base}/b")
        assert time.monotonic() - started >= 0.30

    async def test_the_production_defaults_match_the_ported_values(self) -> None:
        """The tests run with a small gap; production must keep the real one."""
        production = PoliteClient()
        assert production.min_gap_s == 1.2
        assert production.timeout_s == 20.0
        assert production.max_attempts == 3
        assert production.backoff_base_s == 1.5


class TestRedirects:
    async def test_follows_redirects(self, client: PoliteClient, server: tuple[str, object]) -> None:
        """httpx does NOT follow redirects by default; the TS client sets redirect:"follow".

        Frankfurter answers 301 via Cloudflare. Without this, every redirecting
        store returns an unparseable body and looks like a parsing bug.
        """
        base, recorder = server
        recorder.plan("/start", (301, "", {"Location": f"{base}/end"}))
        recorder.plan("/end", (200, '{"arrived":true}', {"content-type": "application/json"}))

        result = await client.get(f"{base}/start")

        assert result.ok
        assert "arrived" in result.body


class TestRetries:
    async def test_retries_a_429(self, client: PoliteClient, server: tuple[str, object]) -> None:
        base, recorder = server
        recorder.plan("/x", (429, "slow down", {}), (200, "fine", {}))
        result = await client.get(f"{base}/x")
        assert result.ok
        assert recorder.hits.count("/x") == 2

    async def test_retries_a_500(self, client: PoliteClient, server: tuple[str, object]) -> None:
        base, recorder = server
        recorder.plan("/x", (503, "oops", {}), (200, "fine", {}))
        result = await client.get(f"{base}/x")
        assert result.ok

    @pytest.mark.parametrize("status", [403, 404])
    async def test_does_not_retry_a_real_answer(
        self, client: PoliteClient, server: tuple[str, object], status: int
    ) -> None:
        """403 and 404 are answers, not hiccups. Retrying them is just rudeness."""
        base, recorder = server
        recorder.plan("/x", (status, "no", {}))
        result = await client.get(f"{base}/x")
        assert not result.ok
        assert result.status == status
        assert recorder.hits.count("/x") == 1

    async def test_gives_up_after_max_attempts_without_raising(
        self, client: PoliteClient, server: tuple[str, object]
    ) -> None:
        """An adapter must never see an exception from the client.

        Every failure has to arrive as data so it can reach run_store.detail
        and be readable on the dashboard.
        """
        base, recorder = server
        recorder.plan("/x", (500, "always broken", {}))
        result = await client.get(f"{base}/x")
        assert not result.ok
        assert recorder.hits.count("/x") == 3

    async def test_an_unreachable_host_returns_a_result_not_an_exception(
        self, client: PoliteClient
    ) -> None:
        result = await client.get("http://127.0.0.1:9/nothing")
        assert not result.ok
        assert result.status == 0
        assert result.body


class TestHeaders:
    async def test_lowercases_response_headers(
        self, client: PoliteClient, server: tuple[str, object]
    ) -> None:
        """WooCommerce's x-wp-total is the only authoritative completeness signal.

        Case varies by server, so callers must be able to read one spelling.
        """
        base, recorder = server
        recorder.plan("/p", (200, "[]", {"X-WP-Total": "213"}))
        result = await client.get(f"{base}/p")
        assert result.headers["x-wp-total"] == "213"


class TestGetJson:
    async def test_parses_json(self, client: PoliteClient, server: tuple[str, object]) -> None:
        base, recorder = server
        recorder.plan("/j", (200, '{"products":[1,2]}', {"content-type": "application/json"}))
        assert await client.get_json(f"{base}/j") == {"products": [1, 2]}

    async def test_returns_none_on_unparseable_body(
        self, client: PoliteClient, server: tuple[str, object]
    ) -> None:
        base, recorder = server
        recorder.plan("/j", (200, "<html>not json</html>", {}))
        assert await client.get_json(f"{base}/j") is None

    async def test_returns_none_on_an_error_status(
        self, client: PoliteClient, server: tuple[str, object]
    ) -> None:
        base, recorder = server
        recorder.plan("/j", (404, "gone", {}))
        assert await client.get_json(f"{base}/j") is None
