"""A deliberately polite HTTP client.

These are small shops.  One concurrent request per host and a real delay
between them costs us nothing -- the collector runs unattended, not in front
of a user -- and it keeps us off anyone's block list.

Ported from src/core/http.ts, with two changes:

  * It is a class, not module-level globals.  The TypeScript version kept a
    module-level map of per-host promise chains that was never evicted; that
    was harmless in a short-lived CLI but this process now serves a dashboard
    for hours.  An instance also lets tests use a real gap of 0.3s instead of
    waiting 1.2s per request.
  * ``follow_redirects`` is set explicitly.  httpx does not follow redirects
    by default, unlike fetch with redirect:"follow" which the TS client used.
    Without it a 301 returns the redirect's own HTML body and every caller
    downstream reports a parse failure, which looks like a parsing bug.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class HttpResult:
    ok: bool
    status: int
    body: str
    #: Header names lower-cased, so WooCommerce's ``x-wp-total`` -- the only
    #: authoritative "did we get everything" signal any adapter has -- can be
    #: read without guessing at the server's capitalisation.
    headers: dict[str, str]


class PoliteClient:
    def __init__(
        self,
        *,
        min_gap_s: float = 1.2,
        timeout_s: float = 20.0,
        max_attempts: int = 3,
        backoff_base_s: float = 1.5,
    ) -> None:
        self.min_gap_s = min_gap_s
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        # Quadratic backoff, ported from http.ts. Injectable purely so the
        # retry tests do not have to spend 7.5 real seconds proving that a
        # delay happened between attempts.
        self.backoff_base_s = backoff_base_s
        # One lock per host, so requests to the same shop queue behind each
        # other while different shops proceed in parallel.
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_hit: dict[str, float] = {}

    async def aclose(self) -> None:
        """Nothing to release today; present so callers can be written correctly now."""

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def _throttle(self, host: str) -> None:
        """A per-host LOCK alone is not enough -- it serialises but does not space.

        The gap needs a remembered timestamp as well, or a shop gets three
        back-to-back requests the instant the previous one returns.
        """
        loop = asyncio.get_running_loop()
        wait = self.min_gap_s - (loop.time() - self._last_hit.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_hit[host] = loop.time()

    async def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResult:
        """Fetch a URL. Never raises -- every failure comes back as data.

        An adapter that sees an exception cannot put a readable reason into
        run_store.detail, and a store failing for an unreadable reason is the
        failure mode this whole project is built to avoid.
        """
        host = urlparse(url).netloc
        request_headers = {
            "user-agent": _USER_AGENT,
            "accept-language": "en-IN,en;q=0.9",
            **(headers or {}),
        }

        async with self._lock_for(host):
            last_error = ""
            for attempt in range(1, self.max_attempts + 1):
                await self._throttle(host)
                try:
                    async with httpx.AsyncClient(
                        timeout=self.timeout_s,
                        follow_redirects=True,
                        # A shop is a public host; a corporate proxy in the
                        # environment must not be consulted for it, and on a
                        # locked-down machine it would block the request.
                        trust_env=False,
                    ) as client:
                        response = await client.get(url, headers=request_headers)
                except Exception as exc:  # noqa: BLE001 - every failure must become data
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    # 429 and 5xx are worth retrying; 403/404 are an answer,
                    # not a hiccup.
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = f"HTTP {response.status_code}"
                    else:
                        return HttpResult(
                            ok=response.is_success,
                            status=response.status_code,
                            body=response.text,
                            headers={k.lower(): v for k, v in response.headers.items()},
                        )
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.backoff_base_s * attempt * attempt)

            return HttpResult(ok=False, status=0, body=last_error, headers={})

    async def get_json(self, url: str) -> Any | None:
        result = await self.get(url, {"accept": "application/json"})
        if not result.ok:
            return None
        try:
            return json.loads(result.body)
        except ValueError:
            return None
