"""Does Play-Asia's search support sorting, and does sorting change the URL?

Why it matters: the catalogue is 139 click-paged pages (~5,200 cartridges) and a
run can afford roughly 60 of them. Which 60 you get is decided by the search's
default ordering. If sorting is expressible in the URL, the shipped search_url
can ask for a genuinely useful half -- cheapest first, or newest first -- instead
of an arbitrary one.

Rather than guessing parameter names, this finds the real sort control and USES
it, then reports whether the URL changed. A changed URL means a parameter we can
ship; an unchanged URL means the sort is an in-page XHR and would have to be
clicked on every run.

    uv run python scripts/diagnose_playasia_sort.py

Standalone: imports nothing from switch_tracker. Deliberately loads few pages --
this site has bot detection, and a probe is not a reason to hammer it.
"""

import asyncio
from pathlib import Path

URL = "https://www.play-asia.com/en/search/nintendo+switch+games"

FIND_SORT_UI = """
() => {
  const out = {selects: [], sortLinks: [], sortButtons: []};

  for (const sel of document.querySelectorAll('select')) {
    const label = (sel.getAttribute('name') || '') + ' ' + (sel.getAttribute('id') || '')
                + ' ' + (sel.className || '') + ' ' + (sel.getAttribute('aria-label') || '');
    out.selects.push({
      label: label.trim().slice(0, 70),
      visible: sel.offsetParent !== null,
      options: [...sel.options].slice(0, 12).map(o => ({text: o.text.trim(), value: o.value})),
    });
  }

  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href') || '';
    if (/sort|order|price_?(asc|desc)|newest|relevance/i.test(h)) out.sortLinks.push(h.slice(0, 110));
  }

  for (const b of document.querySelectorAll('button, [role="button"], li')) {
    const t = (b.innerText || '').trim();
    if (t && t.length < 30 && /sort|price|newest|popular|relevance|release/i.test(t)) {
      out.sortButtons.push({text: t, cls: String(b.className || '').slice(0, 45)});
    }
  }
  return out;
}
"""

FIRST_PRODUCT = """
() => {
  const a = [...document.querySelectorAll("a[href*='/en/']")]
    .find(x => /\\/\\d+\\/[a-z0-9]+$/i.test(x.getAttribute('href') || ''));
  const card = document.querySelector('div.pa-modern-product-item');
  return {
    href: a ? a.getAttribute('href') : '(none)',
    text: card ? (card.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 70) : '(no card)',
  };
}
"""


#: The first few prices in grid order. If the sort applied, an ascending run
#: is obvious here in a way a single title is not.
_FIRST_PRICES = """
() => [...document.querySelectorAll('div.pa-modern-product-item')]
  .slice(0, 6)
  .map(c => {
    const m = (c.innerText || '').match(/(?:\\u20b9|Rs\\.?|INR)\\s*([\\d,]+)/);
    return m ? m[1] : '?';
  })
"""


async def main() -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=True)
        except Exception:  # noqa: BLE001
            browser = await p.chromium.launch(headless=True)
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

        print(f"\n  loading {URL}")
        await page.goto(URL, wait_until="networkidle", timeout=60_000)
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await page.wait_for_timeout(1500)

        ui = await page.evaluate(FIND_SORT_UI)

        print("\n  === <select> elements on the page ===")
        if not ui["selects"]:
            print("    none")
        for s in ui["selects"]:
            vis = "" if s["visible"] else "  [hidden]"
            print(f"    {s['label']!r}{vis}")
            for o in s["options"]:
                print(f"        {o['text']!r:34} value={o['value']!r}")

        print("\n  === links whose href mentions sort/order ===")
        for h in list(dict.fromkeys(ui["sortLinks"]))[:10]:
            print(f"    {h}")
        if not ui["sortLinks"]:
            print("    none")

        print("\n  === sort-ish buttons ===")
        for b in ui["sortButtons"][:12]:
            print(f"    {b['text']!r:28} class={b['cls']!r}")
        if not ui["sortButtons"]:
            print("    none")

        # The decisive test: drive the control and see whether the URL moves.
        before_url = page.url
        before = await page.evaluate(FIRST_PRODUCT)
        print(f"\n  before sorting: {before['href']}")
        print(f"                  {before['text']}")

        target = next(
            (s for s in ui["selects"]
             if s["visible"] and any(
                 "price" in o["text"].lower() or "sort" in s["label"].lower()
                 for o in s["options"])),
            None,
        )
        if target is None:
            print("\n  NO usable sort <select> found - cannot test URL behaviour.")
        else:
            option = next((o for o in target["options"]
                           if "price" in o["text"].lower()), target["options"][-1])
            print(f"\n  selecting {option['text']!r} ...")
            try:
                await page.select_option("select", value=option["value"])
                await page.wait_for_timeout(4000)
                after = await page.evaluate(FIRST_PRODUCT)
                print(f"  URL changed   : {page.url != before_url}")
                if page.url != before_url:
                    print(f"  new URL       : {page.url}")
                print(f"  results moved : {after['href'] != before['href']}")
                print(f"  now first     : {after['text']}")
            except Exception as exc:  # noqa: BLE001
                print(f"  could not drive it: {type(exc).__name__}: {exc}")

        # The decisive test. "#fc=o:3" is a FRAGMENT, so the server never sees
        # it -- but page.goto() preserves it, and if Play-Asia's JS initialises
        # from location.hash then a direct navigation applies the sort. That
        # would make it shippable in search_urls at zero cost. If the results
        # are identical to an unsorted load, the sort is post-load-only state
        # and would have to be clicked on every run.
        print("\n  === direct navigation with the sort fragment ===")
        for label, suffix in (("unsorted", ""), ("price ascending", "#fc=o:3")):
            await page.goto(URL + suffix, wait_until="networkidle", timeout=60_000)
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(3500)
            first = await page.evaluate(FIRST_PRODUCT)
            prices = await page.evaluate(_FIRST_PRICES)
            print(f"    {label:16} first: {first['text'][:58]}")
            print(f"    {'':16} prices: {prices}")

        html = await page.content()
        await browser.close()
        return html


OUTPUT = Path("playasia-sort.html")
OUTPUT.write_text(asyncio.run(main()), encoding="utf-8")
print(f"\n  full HTML -> {OUTPUT}")
