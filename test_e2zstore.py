import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.async_api import async_playwright
try:
    # Try class-based API first
    from playwright_stealth import Stealth
    async def apply_stealth(page):
        await Stealth().apply_stealth_async(page)
except ImportError:
    # Fallback for alternative module structures
    import playwright_stealth
    async def apply_stealth(page):
        if hasattr(playwright_stealth, 'stealth_async'):
            await playwright_stealth.stealth_async(page)
        elif hasattr(playwright_stealth, 'stealth'):
            await playwright_stealth.stealth(page)

from switch_tracker.adapters.browser.extract import extract
from switch_tracker.adapters.browser.profiles import StoreProfile
from switch_tracker.core.models import StoreConfig

E2ZSTORE_CONFIG = StoreConfig(
    id="e2zstore",
    name="e2zSTORE",
    base_url="https://e2zstore.com",
    kind=None,
    currency="INR",
    tier=1,
    enabled=True,
    search_urls=("https://e2zstore.com/category/nintendo-games/page/{p}/",),
)

E2ZSTORE_PROFILE = StoreProfile(
    card=(
        "div.product-small.product",
        "div.product",
        "li.product",
    ),
    title=(
        ".woocommerce-loop-product__title a",
        ".woocommerce-loop-product__title",
        ".product-title a",
    ),
    price=(
        "span.price ins .amount",
        "span.price .amount",
    ),
    link=(
        "a.woocommerce-LoopProduct-link",
        "a.woocommerce-loop-product__link",
        ".product-title a",
    ),
    out_of_stock=(
        ":has-text('Out of stock')",
        ".outofstock",
    ),
    ready="div.product, div.product-small.product, li.product",
    next_page=("a.next.page-number", "a.next", "ul.page-numbers a.next"),
)


async def wait_for_cloudflare(page, timeout_ms=20000):
    """Detects and attempts to clear Cloudflare Turnstile challenge if present."""
    try:
        title = await page.title()
        content = await page.content()

        if "Just a moment..." in title or "Performing security verification" in content:
            print("  -> Cloudflare challenge detected! Looking for Turnstile widget...")
            
            # Check frames for Cloudflare Turnstile checkbox
            for frame in page.frames:
                if "challenges.cloudflare.com" in frame.url:
                    checkbox = frame.locator("input[type='checkbox'], .mark, #challenge-stage")
                    if await checkbox.count() > 0:
                        print("  -> Turnstile widget found! Clicking checkbox...")
                        await checkbox.first.click()
                        break
            
            # Wait until Cloudflare passes and redirects back
            await page.wait_for_function(
                "() => !document.title.includes('Just a moment...')",
                timeout=timeout_ms,
            )
            print("  -> Cloudflare challenge cleared!")
    except Exception:
        print("  -> Cloudflare challenge timed out or failed to resolve automatically.")


async def click_next_humanized(page, selectors: tuple[str, ...]) -> bool:
    """Hover and click pagination element with natural delays to prevent bot detection."""
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            if await locator.count() == 0:
                continue
            if await locator.is_disabled():
                return False
            
            await locator.scroll_into_view_if_needed()
            await page.wait_for_timeout(random.randint(300, 600))

            box = await locator.bounding_box()
            if box:
                await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await page.wait_for_timeout(random.randint(200, 400))

            await locator.click(delay=random.randint(50, 150))
            return True
        except Exception:
            continue
    return False


async def run_test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",  # Uses installed Google Chrome instead of base Chromium
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080",
                "--start-maximized",
            ],
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1440, "height": 960},
        )

        page = await context.new_page()
        
        # Apply stealth dynamically based on package structure
        await apply_stealth(page)

        total_scraped = 0
        pages_to_test = 2

        print("--- STARTING E2ZSTORE TEST ---")

        for page_num in range(1, pages_to_test + 1):
            print(f"\nLoading Page {page_num}...")

            if page_num > 1 and E2ZSTORE_PROFILE.next_page:
                clicked = await click_next_humanized(page, E2ZSTORE_PROFILE.next_page)
                if not clicked:
                    print(f"Could not find or click 'Next' button on page {page_num}.")
                    break
                
                await page.wait_for_timeout(2000)
                await wait_for_cloudflare(page, timeout_ms=20000)
            else:
                target_url = E2ZSTORE_CONFIG.search_urls[0].replace("{p}", "1")
                print(f"Navigating to: {target_url}")
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                await wait_for_cloudflare(page, timeout_ms=20000)

            # Wait for products to load
            try:
                await page.wait_for_selector(E2ZSTORE_PROFILE.ready, timeout=20000)
            except Exception as exc:
                print(f"\n[ERROR] Ready selector timed out on Page {page_num}!")
                print(f"Current page title: '{await page.title()}'")
                await page.screenshot(path="e2zstore_error_dump.png", full_page=True)
                raise exc

            # Scroll down to hydrate content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            await page.wait_for_timeout(1000)

            # Scrape listings
            rows, method = await extract(page, E2ZSTORE_CONFIG.id, E2ZSTORE_PROFILE)
            total_scraped += len(rows)

            print(f"e2zstore: page {page_num} — {len(rows)} listings extracted (via {method})")
            print(f"Total listings collected so far: {total_scraped}")

            await page.wait_for_timeout(random.randint(1500, 2500))

        print(f"\n--- TEST FINISHED: Total extracted = {total_scraped} ---")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_test())