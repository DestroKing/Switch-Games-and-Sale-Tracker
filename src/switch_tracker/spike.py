"""Task 1 -- the de-risking spike (LLD section 4).

Proves the four things that work in development and fail only after freezing:

  1. certifi / TLS      -- an outbound HTTPS request succeeds
  2. template bundling  -- Jinja2 loads a template via importlib.resources
  3. uvicorn under freeze -- the ASGI server binds and serves a real request
  4. Playwright driver  -- the bundled Node driver launches a real browser

Run unfrozen:  uv run python -m switch_tracker spike
Run frozen:    dist/switch-tracker/switch-tracker spike
The output is identical in both; that is the whole point of the exercise.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
import sys
import threading
from dataclasses import dataclass

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from switch_tracker import paths, resources


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(resources.templates_dir())),
        autoescape=select_autoescape(("html",)),
    )


def build_app() -> FastAPI:
    app = FastAPI()
    env = _jinja()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return env.get_template("spike.html").render(
            source=resources.templates_dir(),
            frozen=getattr(sys, "frozen", False),
            data_dir=paths.data_dir(),
        )

    return app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def check_tls() -> Check:
    """1. An outbound HTTPS call. Fails in a frozen build with certifi unbundled."""
    try:
        # follow_redirects is NOT httpx's default. The TypeScript client sets
        # redirect:"follow" (http.ts:47); Frankfurter answers 301 via Cloudflare.
        # Omitting this makes every redirecting store fail with an unparseable body.
        r = httpx.get(
            "https://api.frankfurter.app/latest?from=USD&to=INR", timeout=20, follow_redirects=True
        )
        rate = r.json()["rates"]["INR"]
        return Check("TLS / certifi", True, f"Frankfurter USD->INR = {rate}")
    except Exception as e:  # noqa: BLE001 - a spike reports every failure shape
        return Check("TLS / certifi", False, f"{type(e).__name__}: {e}")


def check_templates() -> Check:
    """2. Template bundling. Fails in a frozen build with data files unbundled."""
    try:
        html = _jinja().get_template("spike.html").render(source="spike", frozen=False, data_dir="x")
        return Check("Template bundling", "Packaging spike" in html, f"rendered {len(html)} bytes")
    except Exception as e:  # noqa: BLE001
        return Check("Template bundling", False, f"{type(e).__name__}: {e}")


def check_uvicorn() -> Check:
    """3. uvicorn under freeze. Uses the app OBJECT, never the string-import form."""
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(build_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            threading.Event().wait(0.1)
        else:
            return Check("uvicorn serving", False, "server never reported started")
        # trust_env=False: a loopback request must never consult HTTP_PROXY.
        # On a machine with a corporate proxy it otherwise returns the block page.
        with httpx.Client(trust_env=False, timeout=10) as client:
            body = client.get(f"http://127.0.0.1:{port}/").text
        return Check("uvicorn serving", "Packaging spike" in body, f"served {len(body)} bytes on :{port}")
    except Exception as e:  # noqa: BLE001
        return Check("uvicorn serving", False, f"{type(e).__name__}: {e}")
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def _playwright_probe() -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                viewport={"width": 1440, "height": 960},
            )
            page = await context.new_page()
            await page.goto("https://example.com", wait_until="domcontentloaded", timeout=45_000)
            title = await page.title()
            tz = await page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            return f'title="{title}" timezone={tz} version={browser.version}'
        finally:
            await browser.close()


def check_playwright() -> Check:
    """4. The Playwright Node driver + browser. The one thing PyInstaller cannot pack naively."""
    try:
        return Check("Playwright driver", True, asyncio.run(_playwright_probe()))
    except Exception as e:  # noqa: BLE001
        return Check("Playwright driver", False, f"{type(e).__name__}: {e}")


def run() -> int:
    print("\nswitch-tracker packaging spike")
    print(f"  python {sys.version.split()[0]}  frozen={getattr(sys, 'frozen', False)}")
    print(f"  ssl    {ssl.OPENSSL_VERSION}")
    print(f"  data   {paths.data_dir()}\n")

    checks = [check_tls(), check_templates(), check_uvicorn(), check_playwright()]
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name.ljust(width)}  {c.detail}")

    failed = [c.name for c in checks if not c.ok]
    print()
    if failed:
        print(f"  {len(failed)} of {len(checks)} FAILED: {', '.join(failed)}\n")
        return 1
    print(f"  all {len(checks)} checks passed\n")
    return 0
