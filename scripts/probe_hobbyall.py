"""Inspect Hobbyall's rendered storefront before adding it to the shipped store list.

This is deliberately a diagnostic, not a StoreProfile: it records what the
live page actually renders so selectors and pagination can be chosen from
evidence rather than guessed. It uses the same BrowserProvider (Chrome first,
stealth context, Chromium fallback) as the production adapter.

    uv run python scripts/probe_hobbyall.py
    uv run python scripts/probe_hobbyall.py --headful

The report and full HTML snapshots are written under the normal diagnostics
directory. No tracker data or store configuration is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

from playwright.async_api import Page

from switch_tracker import paths
from switch_tracker.adapters.browser.provider import BrowserProvider

BASE_URL = "https://hobbyall.in"
PRODUCT_URL = (
    "https://hobbyall.in/product/"
    "the-legend-of-zelda-ocarina-of-time-multi-language-PRD0174"
)
SEARCH_URLS = (
    f"{BASE_URL}/?s=nintendo+switch&post_type=product",
    f"{BASE_URL}/?s=nintendo+switch+2&post_type=product",
)

# Ordered from specific WooCommerce structures to broad diagnostic fallbacks.
CARD_SELECTORS = (
    "ul.products li.product",
    "li.product",
    "div.product-small.product",
    "div.product",
    "[class*='product-card']",
    "[class*='product-item']",
)
TITLE_SELECTORS = (
    ".woocommerce-loop-product__title",
    ".product-title",
    "[class*='product-title']",
    "h2",
    "h3",
)
PRICE_SELECTORS = (
    ".price ins .amount",
    ".price .amount",
    ".woocommerce-Price-amount",
    "[class*='price']",
)
LINK_SELECTORS = (
    "a.woocommerce-LoopProduct-link",
    "a.woocommerce-loop-product__link",
    "a[href*='/product/']",
)


async def inspect_page(page: Page, url: str, label: str) -> dict[str, object]:
    print(f"\n{'=' * 76}\n{label}: {url}")
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2_500)
    except Exception as exc:  # noqa: BLE001 - diagnostic must report navigation failures
        print(f"  NAVIGATION ERROR: {type(exc).__name__}: {exc}")
        return {"label": label, "url": url, "error": f"{type(exc).__name__}: {exc}"}

    status = response.status if response else None
    final_url = page.url
    title = await page.title()
    print(f"  HTTP status : {status}")
    print(f"  final URL   : {final_url}")
    print(f"  page title  : {title!r}")

    selectors: dict[str, int | str] = {}
    for selector in CARD_SELECTORS:
        try:
            selectors[selector] = await page.locator(selector).count()
        except Exception as exc:  # noqa: BLE001
            selectors[selector] = f"ERROR: {type(exc).__name__}"

    anchors = await page.locator("a[href]").evaluate_all(
        """els => els.map(a => ({
            text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
            href: a.href
        })).filter(a => a.href)"""
    )
    product_links = []
    seen: set[str] = set()
    for item in anchors:
        href = str(item["href"])
        if re.search(r"/product/[^/?#]+", href, re.I) and href not in seen:
            seen.add(href)
            product_links.append(
                {"text": str(item["text"])[:120], "href": href}
            )

    samples = await page.evaluate(
        """({cardSelectors, titleSelectors, priceSelectors, linkSelectors}) => {
          const first = selectors => {
            for (const selector of selectors) {
              try {
                const el = document.querySelector(selector);
                if (el) return {selector, text: (el.innerText || el.textContent || '').trim()};
              } catch (_) {}
            }
            return null;
          };
          let cards = [];
          let matchedBy = null;
          for (const selector of cardSelectors) {
            try {
              const found = [...document.querySelectorAll(selector)];
              if (found.length) { cards = found; matchedBy = selector; break; }
            } catch (_) {}
          }
          return {
            matchedBy,
            samples: cards.slice(0, 8).map(card => {
              const pick = selectors => {
                for (const selector of selectors) {
                  try {
                    const el = card.querySelector(selector);
                    if (el) return {
                      selector,
                      text: (el.innerText || el.textContent || '').trim(),
                      href: el.href || el.closest('a')?.href || null
                    };
                  } catch (_) {}
                }
                return null;
              };
              return {
                title: pick(titleSelectors),
                price: pick(priceSelectors),
                link: pick(linkSelectors),
                text: (card.innerText || '').trim().slice(0, 300)
              };
            })
          };
        }""",
        {
            "cardSelectors": list(CARD_SELECTORS),
            "titleSelectors": list(TITLE_SELECTORS),
            "priceSelectors": list(PRICE_SELECTORS),
            "linkSelectors": list(LINK_SELECTORS),
        },
    )

    pager = await page.evaluate(
        r"""() => [...document.querySelectorAll('a,button,[role="button"]')]
          .map(el => ({
            text: (el.innerText || el.getAttribute('aria-label') || '').trim(),
            href: el.href || '',
            aria: el.getAttribute('aria-label') || '',
            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 100),
            disabled: el.hasAttribute('disabled') ||
              el.getAttribute('aria-disabled') === 'true'
          }))
          .filter(x => /next|more|older|›|»|→/i.test(x.text + ' ' + x.aria) ||
            /page\/?\d+|\bpage=\d+/i.test(x.href))
          .slice(0, 30)"""
    )

    snapshot = {
        "label": label,
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "title": title,
        "card_selector_counts": selectors,
        "matched_card_selector": samples["matchedBy"],
        "sample_cards": samples["samples"],
        "product_links": product_links[:40],
        "pagination_candidates": pager,
    }
    print("  card selector counts:")
    for selector, count in selectors.items():
        print(f"    {count!s:>6}  {selector}")
    print(f"  chosen diagnostic selector: {samples['matchedBy']!r}")
    print("  sample cards:")
    print(json.dumps(samples["samples"], indent=2, ensure_ascii=False)[:12_000])
    print(f"  distinct /product/ links: {len(product_links)}")
    for item in product_links[:15]:
        print(f"    {item['text']!r} -> {item['href']}")
    print("  pagination candidates:")
    print(json.dumps(pager, indent=2, ensure_ascii=False))

    safe_label = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-")
    html_path = paths.diagnostics_dir() / f"hobbyall-{safe_label}.html"
    html_path.write_text(await page.content(), encoding="utf-8")
    print(f"  HTML snapshot: {html_path}")
    return snapshot


async def run(*, headful: bool) -> int:
    provider = BrowserProvider(headless=not headful)
    report: list[dict[str, object]] = []
    try:
        context = await provider.new_context()
        page = await context.new_page()
        for label, url in (
            ("home", BASE_URL),
            ("switch-search", SEARCH_URLS[0]),
            ("switch-2-search", SEARCH_URLS[1]),
            ("known-product", PRODUCT_URL),
        ):
            report.append(await inspect_page(page, url, label))
        print(f"\nBrowser engine: {provider.launched_channel}")
    finally:
        await provider.close()

    report_path = paths.diagnostics_dir() / "hobbyall-probe.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull report: {report_path}")
    return 0 if any(item.get("http_status") == 200 for item in report) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headful", action="store_true", help="show the browser")
    args = parser.parse_args(argv)
    return asyncio.run(run(headful=args.headful))


if __name__ == "__main__":
    sys.exit(main())
