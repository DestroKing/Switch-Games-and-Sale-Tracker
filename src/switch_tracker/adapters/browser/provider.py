"""Acquiring a browser.

The DIP seam that keeps packaging out of adapter logic. Frozen, Chromium
ships inside the bundle and a PyInstaller runtime hook has already pointed
PLAYWRIGHT_BROWSERS_PATH at it; unfrozen, Playwright finds its own cache.
Neither case is the adapter's business.
"""

from __future__ import annotations

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

try:
    from playwright_stealth import Stealth

    async def _apply_stealth(page):
        await Stealth().apply_stealth_async(page)
except ImportError:
    import playwright_stealth

    async def _apply_stealth(page):
        if hasattr(playwright_stealth, "stealth_async"):
            await playwright_stealth.stealth_async(page)
        elif hasattr(playwright_stealth, "stealth"):
            await playwright_stealth.stealth(page)

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

    async def browser(self) -> Browser:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                channel="chrome",
                headless=self._headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                    "--start-maximized",
                ],
            )
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
        
        # Apply stealth to new pages as they are opened in the context
        context.on("page", lambda page: page.on("domcontentloaded", lambda: _apply_stealth(page)))
        return context

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None