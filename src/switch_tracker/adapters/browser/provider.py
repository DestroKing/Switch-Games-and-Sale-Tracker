"""Acquiring a browser.

The DIP seam that keeps packaging out of adapter logic. Frozen, Chromium
ships inside the bundle and a PyInstaller runtime hook has already pointed
PLAYWRIGHT_BROWSERS_PATH at it; unfrozen, Playwright finds its own cache.
Neither case is the adapter's business.
"""

from __future__ import annotations

from playwright.async_api import Browser, BrowserContext, Error, Playwright, async_playwright
from playwright_stealth import Stealth

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_STEALTH = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"


class BrowserProvider:
    """Owns one shared Chromium for the life of a worker process."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        #: Which engine actually launched. Set on first use, not at construction.
        self.launched_channel: str | None = None

    #: Real Chrome first: e2zstore and Play-Asia are only reliably scrapeable
    #: through it, because their bot checks treat plain Chromium's fingerprint
    #: differently. The bundled Chromium is the fallback so the frozen build
    #: still runs on a machine with no Chrome installed -- which is what the
    #: README promises and what PLAYWRIGHT_BROWSERS_PATH is bundled for.
    _LAUNCH_ARGS = (
        "--disable-blink-features=AutomationControlled",
        "--window-size=1920,1080",
        "--start-maximized",
    )

    async def browser(self) -> Browser:
        if self._browser is not None:
            return self._browser

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                channel="chrome",
                headless=self._headless,
                args=list(self._LAUNCH_ARGS),
            )
        except Error:
            # Chrome is absent or unlaunchable. Fall back rather than fail the
            # whole run: bundled Chromium scrapes most stores fine, and a
            # degraded collection beats no collection. Which one we got is
            # reported by `launched_channel` so a store failing only under
            # Chromium is diagnosable instead of mysterious.
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=list(self._LAUNCH_ARGS),
            )
            self.launched_channel = "chromium"
        else:
            self.launched_channel = "chrome"
        return self._browser

    async def new_context(self) -> BrowserContext:
        browser = await self.browser()
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1440, "height": 960},
            extra_http_headers={"accept-language": "en-IN,en;q=0.9"},
        )
        await context.add_init_script(_STEALTH)

        # Applied to the CONTEXT, not per page through an event handler.
        #
        # The previous wiring was
        #     context.on("page", lambda p: p.on("domcontentloaded",
        #                                       lambda: _apply_stealth(p)))
        # and _apply_stealth is a coroutine function, so the inner lambda built a
        # coroutine and handed it to a listener that discards whatever it returns.
        # Stealth therefore never ran; the only symptom was a RuntimeWarning about
        # a coroutine that was never awaited, which is easy to lose in Playwright's
        # own output. Applying to the context installs the evasions as init
        # scripts, so every page opened in it is patched before its first script
        # runs -- strictly earlier than domcontentloaded, by which point a
        # detection script has already executed and read the real values.
        await Stealth().apply_stealth_async(context)
        return context

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
