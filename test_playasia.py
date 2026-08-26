import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from playwright.async_api import async_playwright

try:
    from playwright_stealth import Stealth
    async def apply_stealth(page):
        await Stealth().apply_stealth_async(page)
except ImportError:
    import playwright_stealth
    async def apply_stealth(page):
        if hasattr(playwright_stealth, 'stealth_async'):
            await playwright_stealth.stealth_async(page)
        elif hasattr(playwright_stealth, 'stealth'):
            await playwright_stealth.stealth(page)

from switch_tracker.adapters.browser.extract import extract
from switch_tracker.adapters.browser.profiles import StoreProfile
from switch_tracker.core.models import StoreConfig

PLAYASIA_CONFIG = StoreConfig(
    id="playasia",
    name="Play-Asia",
    base_url="https://www.play-asia.com",
    kind=None,
    currency="INR",  # Updated to reflect INR reference currency
    tier=1,
    enabled=True,
    search_urls=(
        "https://www.play-asia.com/en/search/nintendo+switch+games",
        "https://www.play-asia.com/en/search/nintendo+switch+2+games",
    ),
)

PLAYASIA_PROFILE = StoreProfile(
    card=(
        ".product-item",
        "div.item",
        ".item-list-view .item",
        "[class*='product']",
    ),
    title=(
        ".item-name a",
        ".product-name a",
        "a.title",
        "h3 a",
        "a[href*='/en/']",
    ),
    price=(
        ".price-value",
        ".item-price .amount",
        ".product-price",
        ".price",
    ),
    link=(
        ".item-name a",
        ".product-item a",
        "a[href*='/en/']",
    ),
    out_of_stock=(
        ":has-text('Sold out')",
        ":has-text('Out of Stock')",
        ".sold-out",
    ),
    ready="body",
    next_page=(),
)

def clean_price(raw_price_str: str) -> float:
    if not raw_price_str:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', str(raw_price_str))
    try:
        val = float(cleaned)
        # INR values will be higher numerical figures than USD, so keep safety minimum low
        if val < 50.0: 
            return 0.0
        return val
    except ValueError:
        return 0.0

async def run_test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1920,1080"],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1440, "height": 960},
        )

        # Inject Play-Asia cookies to pre-select India and INR reference currency
        await context.add_cookies([
            {"name": "currency", "value": "INR", "domain": ".play-asia.com", "path": "/"},
            {"name": "country", "value": "IN", "domain": ".play-asia.com", "path": "/"}
        ])

        page = await context.new_page()
        await apply_stealth(page)

        global_seen_keys = set()
        master_unique_items = []

        # Iterate through both Switch and Switch 2 catalog search endpoints
        for target_url in PLAYASIA_CONFIG.search_urls:
            print(f"\n--- STARTING SWEEP FOR: {target_url} ---")
            await page.goto(target_url, wait_until="networkidle", timeout=45000)
            
            page_num = 1
            max_safety_limit = 5  # Capped at 5 pages per category for testing
            
            while page_num <= max_safety_limit:
                print(f"-> Scraping Page {page_num} of {max_safety_limit}")
                
                for _ in range(2):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await page.wait_for_timeout(600)

                rows, method = await extract(page, PLAYASIA_CONFIG.id, PLAYASIA_PROFILE)
                
                page_unique = []
                local_seen = set()
                for item in rows:
                    clean_href = str(item.href).strip() if item.href else ""
                    
                    if not clean_href or "/search/" in clean_href or "/category/" in clean_href:
                        continue
                    if not any(char.isdigit() for char in clean_href):
                        continue

                    key = clean_href
                    if key not in local_seen:
                        local_seen.add(key)
                        page_unique.append(item)

                new_additions = []
                for item in page_unique:
                    key = str(item.href).strip()
                    if key not in global_seen_keys:
                        global_seen_keys.add(key)
                        master_unique_items.append(item)
                        new_additions.append(item)

                print(f"   Raw: {len(rows)} | Valid Unique: {len(page_unique)} | New Additions: {len(new_additions)}")

                if len(new_additions) == 0:
                    print(f"-> Plateau reached on Page {page_num}. Moving to next URL.")
                    break

                if page_num >= max_safety_limit:
                    print(f"-> Reached page limit for this target.")
                    break

                next_page_target = page_num + 1
                clicked = await page.evaluate("""
                    (targetNum) => {
                        const buttons = Array.from(document.querySelectorAll('a, button, li, span'));
                        const targetBtn = buttons.find(el => {
                            const txt = el.innerText.trim();
                            return txt === String(targetNum) || txt.toLowerCase() === 'next' || txt === '>';
                        });
                        if (targetBtn && targetBtn.offsetParent !== null) {
                            targetBtn.click();
                            return true;
                        }
                        return false;
                    }
                """, next_page_target)

                if clicked:
                    await page.wait_for_timeout(4000)
                    page_num += 1
                else:
                    break

        print(f"\n--- COMBINED CATALOG SWEEP SUMMARY ---")
        print(f"Total cumulative unique items gathered: {len(master_unique_items)}")

        print(f"\n--- SAMPLE ENTRIES WITH INR PRICES (Showing up to 20) ---")
        for idx, item in enumerate(master_unique_items[:20], 1):
            title = str(item.title).strip() if item.title is not None else "No Title"
            raw_price = str(item.price).strip() if item.price is not None else "No Price"
            sanitized = clean_price(raw_price)
            link = str(item.href).strip() if item.href is not None else "No Link"
            print(f"{idx:3d}. [Raw: {raw_price} | Cleaned INR: {sanitized}] {title[:60]}...")
            print(f"     URL: {link}")

        print("\n-> SUCCESS: Switch & Switch 2 combined INR sweep completed successfully!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_test())