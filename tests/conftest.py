"""Shared fixtures.

The HTTP tests run against a real local server rather than a mocked transport.
Redirect-following and the politeness gap are properties of the real client
and its real socket behaviour; a mock would let both regress unnoticed.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@dataclass
class Recorder:
    """Scripted responses plus a log of what the client actually did."""

    hits: list[str] = field(default_factory=list)
    # path -> list of (status, body, headers) served in order, last one repeats
    script: dict[str, list[tuple[int, str, dict[str, str]]]] = field(default_factory=dict)

    #: path -> {page number: response}. Serving BY PAGE NUMBER rather than by
    #: call order matters: the WooCommerce adapter probes the same path with
    #: ?per_page=1 to discover which API version a store speaks, and a
    #: call-ordered queue would let that probe eat page 1 of the real script.
    paged: dict[str, dict[int, tuple[int, str, dict[str, str]]]] = field(default_factory=dict)

    def plan(self, path: str, *responses: tuple[int, str, dict[str, str]]) -> None:
        self.script[path] = list(responses)

    def plan_pages(self, path: str, *pages: tuple[int, str, dict[str, str]]) -> None:
        """Script a paginated endpoint, indexed by its ?page= parameter."""
        self.paged[path] = {i: response for i, response in enumerate(pages, start=1)}

    @staticmethod
    def _page_number(query: str) -> int | None:
        for part in query.split("&"):
            if part.startswith("page="):
                with contextlib.suppress(ValueError):
                    return int(part[len("page=") :])
        return None

    def next_for(self, full_path: str) -> tuple[int, str, dict[str, str]]:
        path, _, query = full_path.partition("?")

        if path in self.paged:
            page = self._page_number(query)
            if page is None:
                # A version-discovery probe (?per_page=1), not a real page.
                # Answer plausibly without disturbing the scripted pages.
                return (200, "[{}]", {"content-type": "application/json"})
            return self.paged[path].get(page, (200, "[]", {"content-type": "application/json"}))

        queued = self.script.get(path)
        if not queued:
            return (200, '{"ok":true}', {"content-type": "application/json"})
        return queued.pop(0) if len(queued) > 1 else queued[0]


@pytest.fixture
def server() -> Iterator[tuple[str, Recorder]]:
    recorder = Recorder()

    class Handler(BaseHTTPRequestHandler):
        # Name fixed by BaseHTTPRequestHandler's dispatch, not our choice.
        def do_GET(self) -> None:
            recorder.hits.append(self.path)
            status, body, headers = recorder.next_for(self.path)
            payload = body.encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: object) -> None:
            """Silence the default stderr logging; a pristine test run matters."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", recorder
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def html_page(server):  # type: ignore[no-untyped-def]
    """Serve a chunk of HTML at a path and hand back its URL."""
    base, recorder = server

    def serve(path: str, html: str) -> str:
        recorder.plan(path, (200, html, {"content-type": "text/html; charset=utf-8"}))
        return f"{base}{path}"

    return serve
