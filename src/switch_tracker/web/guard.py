"""Only the dashboard's own page may talk to the dashboard.

The server binds 127.0.0.1 and has no login, which stops OTHER MACHINES -- not
other WEBSITES. Two attacks get through a loopback bind on their own:

  * Cross-site requests. Any page the user visits can make the browser send a
    form-style POST to http://127.0.0.1:4173/actions/collect (or
    /reset-corrections, or /inspect/...). A "simple" cross-site POST needs no
    CORS preflight, so the request lands and runs even though the attacking
    page can never read the reply.
  * DNS rebinding. A hostile hostname that later resolves to 127.0.0.1 makes
    the attacker's page SAME-ORIGIN with whatever it reaches, so it can read
    every /api/* response and use the watchlist's PUT/DELETE.

Two checks close both, and they are deliberately strict -- every rule here
rejects, none merely warns:

  1. Host, on EVERY method: exactly ``127.0.0.1:<port>`` or ``localhost:<port>``.
     A rebound hostname arrives with the attacker's Host header.
  2. For anything that is not GET/HEAD/OPTIONS: Origin must be
     ``http://<that same Host>``, and Sec-Fetch-Site, when sent, must be
     ``same-origin``. A MISSING Origin is rejected too: every browser sends one
     on a state-changing fetch, and nothing that is not a browser uses this API.

GETs are checked by Host only, because a plain navigation sends no Origin. The
price for that is a rule on the routes, not here: a GET must never change
state. Never add CORS middleware or Access-Control-Allow-Origin to this app.

Pure ASGI rather than a BaseHTTPMiddleware, so it wraps the SSE progress
stream without buffering it, and so ``check`` is a plain function tests can
call with nothing but a dict of headers.
"""

from __future__ import annotations

from collections.abc import Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

from switch_tracker.web.errors import problem

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def allowed_hosts(port: int) -> frozenset[str]:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if port == 80:
        # Browsers omit the scheme's default port from Host and Origin, so on
        # port 80 the page itself sends a bare "127.0.0.1" -- refusing it
        # would lock the dashboard out of its own address.
        hosts |= {"127.0.0.1", "localhost"}
    return frozenset(hosts)


def check(method: str, headers: Mapping[str, str], hosts: frozenset[str]) -> str | None:
    """Why this request must be refused, or None if it may proceed.

    ``headers`` keys are lower-case, as ASGI delivers them.
    """
    host = headers.get("host", "").strip().lower()
    if host not in hosts:
        return "This dashboard only answers to its own address."
    if method.upper() in SAFE_METHODS:
        return None
    if headers.get("origin", "").strip().lower() != f"http://{host}":
        return "Changes can only be made from the dashboard page itself."
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.strip().lower() != "same-origin":
        return "Changes can only be made from the dashboard page itself."
    return None


class LocalOnly:
    """Refuse, with a 403, every request ``check`` rejects -- before routing.

    Before routing on purpose: an unknown path, /static and the SSE stream are
    all covered, and a forged POST to a route that does not exist gets 403, not
    a 404 that would confirm the path is free.
    """

    def __init__(self, app: ASGIApp, port: int) -> None:
        self._app = app
        self._hosts = allowed_hosts(port)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # lifespan (startup/shutdown) carries no request to check.
            await self._app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        reason = check(scope["method"], headers, self._hosts)
        if reason is not None:
            await problem(403, reason)(scope, receive, send)
            return
        await self._app(scope, receive, send)
