"""What does Play-Asia's search page actually offer for turning the page?

A throwaway diagnostic for one open question: the collector reaches page 1 of
each search URL and stops, because the numeric page-number clicker finds nothing
to click. Before choosing a fix we need to see what the page really has.

Standalone on purpose -- imports nothing from switch_tracker, so it runs against
any checkout, including a zip copied to another machine.

    uv run python scripts/diagnose_playasia_pager.py

Writes playasia-page1.html beside the working directory for closer inspection.
Delete this file once Play-Asia's pagination is settled.
"""

import asyncio
from pathlib import Path

URL = "https://www.play-asia.com/en/search/nintendo+switch+games"

#: The shipped profile's card list, in order. from_selectors() takes the FIRST
#: one that yields rows, so the order is what decides which is actually used.
CARD_SELECTORS = [
    ".product-item", ".search-item", "div.item",
    ".item-list-view .item", ".item", "[class*='product']",
]

PAGER_PROBE = """
() => {
  const out = {candidates: [], hrefsWithPage: [], productHrefs: 0, totalText: ''};
  for (const el of document.querySelectorAll('a, button, li, span, div')) {
    const text = (el.innerText || '').trim();
    if (!text || text.length > 12) continue;
    if (!/^(\\d{1,3}|next|prev|>|<|\\u203a|\\u00bb|last|more)$/i.test(text)) continue;
    out.candidates.push({
      text, tag: el.tagName.toLowerCase(),
      cls: String(el.className || '').slice(0, 55),
      href: el.getAttribute('href') || '',
      visible: el.offsetParent !== null,
    });
  }
  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href') || '';
    if (/page|offset|start|[?&]p=/i.test(h)) out.hrefsWithPage.push(h.slice(0, 110));
  }
  // Product URLs end /<digits>/<code>, e.g. /en/some-game/13/70joyt
  out.productHrefs = new Set(
    [...document.querySelectorAll("a[href*='/en/']")]
      .map(a => a.getAttribute('href'))
      .filter(h => /\\/\\d+\\/[a-z0-9]+$/i.test(h))
  ).size;
  const m = (document.body.innerText || '').match(/[^\\n]{0,40}(results?|items?|products?)[^\\n]{0,40}/i);
  out.totalText = m ? m[0].trim() : '';
  return out;
}
"""


_CARD_FINDER = """
() => {
  // A product card is the smallest element containing BOTH a link and a price.
  //
  // Link shape alone is not enough on this site: Play-Asia uses the SAME
  // /slug/<digits>/<code> URL form for mega-menu CATEGORY links as for
  // products, so 96 of the 138 "product links" on page 1 are navigation. A
  // rupee figure is the signal that cannot be confused.
  const PRICE = /(?:\\u20b9|Rs\\.?|INR)\\s*[\\d,]+/;
  const inChrome = el => el.closest(
    'nav, header, footer, [class*="mega"], [class*="nav"], [class*="menu"], [class*="slick"]');

  const links = [...document.querySelectorAll("a[href*='/en/']")]
    .filter(a => /\\/\\d+\\/[a-z0-9]+$/i.test(a.getAttribute('href') || ''))
    .filter(a => !inChrome(a));

  const sig = el => {
    const cls = [...el.classList].filter(c => !/^(ng-|is-|js-|slick)/.test(c)).slice(0, 3);
    return cls.length ? el.tagName.toLowerCase() + '.' + cls.join('.') : el.tagName.toLowerCase();
  };

  const tally = new Map();
  const cards = [];
  for (const link of links) {
    let el = link.parentElement, depth = 1;
    while (el && el !== document.body && depth < 8) {
      if (PRICE.test(el.innerText || '')) {        // smallest ancestor with a price
        tally.set(sig(el), (tally.get(sig(el)) || 0) + 1);
        cards.push(el);
        break;
      }
      el = el.parentElement; depth++;
    }
  }

  const ancestors = [...tally.entries()]
    .map(([selector, count]) => ({selector, count}))
    .sort((a, b) => b.count - a.count);

  const inside = {};
  if (cards.length) {
    const card = cards[0];
    const link = card.querySelector("a[href*='/en/']");
    inside['card'] = sig(card);
    inside['matches'] = document.querySelectorAll(sig(card)).length;
    inside['link'] = link ? sig(link) : 'NOT FOUND';
    inside['href'] = link ? link.getAttribute('href') : '';
    const priceEl = [...card.querySelectorAll('*')]
      .filter(e => PRICE.test(e.textContent || '') && !e.children.length)[0];
    inside['price'] = priceEl ? sig(priceEl) : 'NOT FOUND';
    const titleEl = link && link.innerText.trim().length > 8
      ? link
      : [...card.querySelectorAll('*')].filter(e => e.innerText
          && e.innerText.trim().length > 12 && !e.children.length)[0];
    inside['title'] = titleEl ? sig(titleEl) : 'NOT FOUND';
    inside['text'] = (card.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 100);
  }

  // What do NAV links look like, versus product links? Needed to write a
  // reject rule that can actually tell them apart.
  const navSample = [...document.querySelectorAll('[class*="mega"] a[href*="/en/"]')]
    .slice(0, 4).map(a => a.getAttribute('href'));

  return {ancestors, inside, productLinks: links.length, navSample};
}
"""


async def main() -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            engine = "chrome"
        except Exception:  # noqa: BLE001 - a diagnostic must run on either engine
            browser = await p.chromium.launch(headless=True)
            engine = "chromium"

        # Same context and cookies the real adapter uses, or the page could
        # legitimately differ from what the collector sees.
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-IN", timezone_id="Asia/Kolkata",
            viewport={"width": 1440, "height": 960},
        )
        await ctx.add_cookies([
            {"name": "currency", "value": "INR", "domain": ".play-asia.com", "path": "/"},
            {"name": "country", "value": "IN", "domain": ".play-asia.com", "path": "/"},
        ])
        page = await ctx.new_page()

        print(f"\n  engine: {engine}\n  loading {URL}")
        await page.goto(URL, wait_until="networkidle", timeout=60_000)
        # All the way to the bottom: a pager that only renders after the grid
        # finishes loading would be invisible to a shallower scroll.
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(700)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        print("\n  === card selectors, in profile order ===")
        for sel in CARD_SELECTORS:
            try:
                n = await page.locator(sel).count()
            except Exception as exc:  # noqa: BLE001
                n = f"error {type(exc).__name__}"
            print(f"    {sel:32} -> {n}")

        probe = await page.evaluate(PAGER_PROBE)

        # If a card selector reports ~2x this, each product is in the DOM twice
        # (grid + list view) and dedupe-by-SKU is correctly collapsing them.
        print(f"\n  === distinct product links on this page: {probe['productHrefs']} ===")
        if probe["totalText"]:
            print(f"  page says: {probe['totalText']!r}")

        print("\n  === pagination-shaped controls ===")
        if not probe["candidates"]:
            print("    NONE - no numeric/next control found. Likely infinite scroll.")
        for c in probe["candidates"][:30]:
            vis = "" if c["visible"] else "   [HIDDEN]"
            print(f"    {c['text']!r:7} {c['tag']:6} class={c['cls']!r:42} "
                  f"href={c['href'][:45]!r}{vis}")

        # The best outcome: real page links mean the fix is putting {p} in the
        # store's search_urls, not writing a better clicker.
        # Given the real product links, what element repeats around them? That
        # is the card selector -- derived from the page rather than guessed.
        cards = await page.evaluate(_CARD_FINDER)
        print(f"\n  === product links OUTSIDE nav/menu: {cards['productLinks']} ===")
        print("  === card selectors (smallest ancestor holding a price) ===")
        if not cards["ancestors"]:
            print("    none found")
        for a in cards["ancestors"][:10]:
            print(f"    x{a['count']:<4} {a['selector']}")

        print("\n  === inside one product card ===")
        for label, found in cards["inside"].items():
            print(f"    {label:9} {found}")

        print("\n  === sample NAV hrefs (to tell them from products) ===")
        for h in cards["navSample"]:
            print(f"    {h}")

        print("\n  === links mentioning page/offset ===")
        seen = list(dict.fromkeys(probe["hrefsWithPage"]))
        for h in seen[:15]:
            print(f"    {h}")
        if not seen:
            print("    none - URL-based paging probably unavailable")

        html = await page.content()
        await browser.close()
        # Returned, not written here: file IO blocks the event loop, and ruff's
        # ASYNC rules flag it. The caller writes it synchronously below, which
        # satisfies the linter by removing the problem rather than muting it.
        return html


OUTPUT = Path("playasia-page1.html")
OUTPUT.write_text(asyncio.run(main()), encoding="utf-8")
print(f"\n  full HTML -> {OUTPUT}")
