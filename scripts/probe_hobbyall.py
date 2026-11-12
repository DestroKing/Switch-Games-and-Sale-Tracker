"""Inspect Hobbyall's rendered catalogue and product detail pages.

Diagnostic only: no shipped StoreConfig/StoreProfile is changed.
Run with: uv run python scripts/probe_hobbyall.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from urllib.parse import urljoin

from playwright.async_api import Page

from switch_tracker import paths
from switch_tracker.adapters.browser.provider import BrowserProvider

BASE_URL = "https://hobbyall.in"
PRODUCT_URL = (
    f"{BASE_URL}/product/"
    "the-legend-of-zelda-ocarina-of-time-multi-language-PRD0174"
)
# The site's own navigation exposes these category routes. WordPress-style
# ?s=...&post_type=product URLs are not understood by this custom storefront.
CATALOG_URLS = (
    ("home", BASE_URL),
    ("nintendo-category", f"{BASE_URL}/?category=nintendo"),
    ("games-category", f"{BASE_URL}/?category=games"),
)
CARD_SELECTOR = "div.group.bg-white.rounded-2xl"
PRODUCT_HREF = re.compile(r"/product/[^/?#]+", re.I)


async def inspect_catalog(page: Page, url: str, label: str) -> dict[str, object]:
    print(f"\n{'=' * 76}\n{label}: {url}")
    requests: list[dict[str, object]] = []
    api_responses: list[dict[str, object]] = []

    def record_request(request: object) -> None:
        request_url = getattr(request, "url", "")
        if request_url and "/api/" in request_url.lower():
            requests.append({
                "url": request_url,
                "method": getattr(request, "method", ""),
                "post_data": getattr(request, "post_data", None),
            })

    async def record_response(response: object) -> None:
        response_url = getattr(response, "url", "")
        if not response_url or "/api/products" not in response_url.lower():
            return
        record: dict[str, object] = {
            "url": response_url,
            "status": getattr(response, "status", None),
        }
        try:
            payload = await response.json()
            record["payload_type"] = type(payload).__name__
            if isinstance(payload, dict):
                record["top_level_keys"] = list(payload)[:80]
                for key, value in payload.items():
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        record["list_key"] = key
                        record["list_count"] = len(value)
                        record["sample_product_keys"] = list(value[0])[:80]
                        record["sample_product"] = value[0]
                        record["product_ids"] = [
                            str(item.get("id") or item.get("_id") or item.get("slug") or item.get("sku") or "")
                            for item in value[:1000]
                        ]
                        break
                for key, value in payload.items():
                    if not isinstance(value, (dict, list)):
                        record[f"meta_{key}"] = value
                    elif isinstance(value, dict):
                        record[f"meta_{key}"] = {
                            k: v for k, v in value.items()
                            if not isinstance(v, (dict, list))
                        }
            elif isinstance(payload, list):
                record["list_count"] = len(payload)
                record["sample_product"] = payload[0] if payload else None
                record["product_ids"] = [
                    str(item.get("id") or item.get("_id") or item.get("slug") or item.get("sku") or "")
                    for item in payload[:1000] if isinstance(item, dict)
                ]
        except Exception as exc:
            record["json_error"] = f"{type(exc).__name__}: {exc}"
        api_responses.append(record)

    page.on("request", record_request)
    page.on("response", record_response)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2_500)
    except Exception as exc:  # diagnostic should preserve navigation failures
        page.remove_listener("request", record_request)
        print(f"  NAVIGATION ERROR: {type(exc).__name__}: {exc}")
        return {"label": label, "requested_url": url, "error": f"{type(exc).__name__}: {exc}"}
    page.remove_listener("request", record_request)
    page.remove_listener("response", record_response)

    result = await page.evaluate(
        """({cardSelector}) => {
          const clean = el => (el?.innerText || el?.textContent || '').trim().replace(/\\s+/g, ' ');
          const unique = values => [...new Set(values.filter(Boolean))];
          const cards = [...document.querySelectorAll(cardSelector)]
            .filter(card => card.querySelector('a[href*="/product/"]'));
          const products = cards.map(card => {
            const link = card.querySelector('a[href*="/product/"]');
            const title = card.querySelector('h3, h2, [class*="title"]');
            const current = card.querySelector('p.text-primary, [class*="text-primary"][class*="font-black"]');
            const old = card.querySelector('p.line-through, [class*="line-through"]');
            const image = card.querySelector('img');
            const badge = card.querySelector('span.absolute');
            const platform = card.querySelector('p.text-slate-400.font-bold, p[class*="uppercase"][class*="tracking-wider"]');
            return {
              title: clean(title),
              price: clean(current),
              original_price: clean(old),
              condition_badge: clean(badge),
              platform_label: clean(platform),
              image_alt: image?.alt || '',
              image_url: image?.currentSrc || image?.src || '',
              url: link?.href || ''
            };
          });
          const forms = [...document.forms].map(form => ({
            action: form.action, method: form.method,
            inputs: [...form.querySelectorAll('input')].map(x => ({
              name: x.name, type: x.type, placeholder: x.placeholder, value: x.value
            }))
          }));
          const categoryLinks = [...document.querySelectorAll('a[href]')]
            .filter(a => /category=|\\/category\\//i.test(a.href))
            .map(a => ({text: clean(a), href: a.href}));
          const controls = [...document.querySelectorAll('button,[role="button"],a')]
            .map(el => ({
              text: clean(el).slice(0, 80),
              aria: el.getAttribute('aria-label') || '',
              title: el.getAttribute('title') || '',
              href: el.href || '',
              disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true'
            }))
            .filter(x => /next|load more|show more|page/i.test(x.text + ' ' + x.aria + ' ' + x.title));
          const body = clean(document.body);
          const countMatches = [...body.matchAll(/(?:showing|of)\\s+(\\d+)\\s+(?:products|items)/ig)]
            .map(x => Number(x[1]));
          return {
            card_count: products.length,
            products: products.slice(0, 160),
            category_links: unique(categoryLinks.map(x => JSON.stringify(x))).map(x => JSON.parse(x)),
            forms, pagination_or_load_more_controls: controls,
            claimed_catalog_counts: countMatches,
            body_text_excerpt: body.slice(0, 1400)
          };
        }""",
        {"cardSelector": CARD_SELECTOR},
    )
    snapshot = {
        "label": label, "requested_url": url, "final_url": page.url,
        "http_status": response.status if response else None,
        "title": await page.title(), **result,
        "api_requests": requests[:100],
        "api_products_responses": api_responses[:20],
    }
    print(f"  HTTP {snapshot['http_status']} | {snapshot['title']!r}")
    print(f"  product cards: {snapshot['card_count']}")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2)[:18_000])
    safe = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-")
    (paths.diagnostics_dir() / f"hobbyall-{safe}.html").write_text(
        await page.content(), encoding="utf-8"
    )
    return snapshot


async def inspect_product(page: Page) -> dict[str, object]:
    print(f"\n{'=' * 76}\nproduct detail: {PRODUCT_URL}")
    try:
        response = await page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2_000)
    except Exception as exc:
        return {"label": "product-detail", "error": f"{type(exc).__name__}: {exc}"}
    data = await page.evaluate(
        """() => {
          const clean = el => (el?.innerText || el?.textContent || '').trim().replace(/\\s+/g, ' ');
          const h1 = document.querySelector('h1');
          const main = document.querySelector('main') || document.body;
          // The product detail's primary information is in the column beside
          // the gallery. Restrict price/stock extraction to that panel so
          // related-product cards cannot pollute the primary price.
          const panel = h1?.closest('div[class*="lg:col-span-5"]') || main;
          const priceBox = [...panel.querySelectorAll('div')]
            .find(el => el.classList.contains('p-4.5') && el.classList.contains('bg-slate-50'));
          const currentPrice = panel.querySelector('span.text-2xl, span[class*="text-2xl"]');
          const originalPrice = panel.querySelector('span.line-through, span[class*="line-through"]');
          const stockNodes = [...panel.querySelectorAll('span,p')]
            .map(clean).filter(x => /in stock|out of stock|only\\s+\\d+\\s+left/i.test(x));
          const images = [...main.querySelectorAll('img')].map(img => ({
            alt: img.alt, src: img.currentSrc || img.src
          })).filter(x => x.src);
          const labels = [...panel.querySelectorAll('span,p')]
            .map(clean).filter(x => x && x.length < 100);
          const text = clean(panel);
          return {
            title: clean(h1),
            current_price: clean(currentPrice),
            original_price: clean(originalPrice),
            price_box_text: clean(priceBox),
            stock_text: stockNodes,
            brand_text: labels.find(x => /^by\\s+/i.test(x)) || '',
            platform_and_condition_labels: labels.slice(0, 12),
            images: images.slice(0, 12),
            product_panel_excerpt: text.slice(0, 2600),
            has_add_to_cart: [...panel.querySelectorAll('button')].some(b => /add to cart/i.test(clean(b)))
          };
        }"""
    )
    data.update({
        "label": "product-detail", "requested_url": PRODUCT_URL,
        "final_url": page.url, "http_status": response.status if response else None,
        "title_tag": await page.title(),
    })
    print(json.dumps(data, ensure_ascii=False, indent=2)[:12_000])
    (paths.diagnostics_dir() / "hobbyall-product-detail.html").write_text(
        await page.content(), encoding="utf-8"
    )
    return data


async def run(*, headful: bool) -> int:
    provider = BrowserProvider(headless=not headful)
    report: list[dict[str, object]] = []
    try:
        context = await provider.new_context()
        page = await context.new_page()
        for label, url in CATALOG_URLS:
            report.append(await inspect_catalog(page, url, label))
        report.append(await inspect_product(page))
        print(f"\nBrowser engine: {provider.launched_channel}")
    finally:
        await provider.close()
    report_path = paths.diagnostics_dir() / "hobbyall-probe.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nFull report: {report_path}")
    return 0 if any(item.get("http_status") == 200 for item in report) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headful", action="store_true", help="show the browser")
    args = parser.parse_args(argv)
    return asyncio.run(run(headful=args.headful))


if __name__ == "__main__":
    sys.exit(main())
