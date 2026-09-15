"""Pulling products off a rendered page, hardest-to-break first.

  1. JSON-LD   -- schema.org Product/ItemList in a <script>. Survives
                  redesigns because it exists for search engines, not layout.
  2. Embedded  -- the site's own hydration state (Flipkart's __INITIAL_STATE__).
  3. Selectors -- CSS, per-store profiles. The least durable thing on the page.
  4. Text      -- a rupee figure inside a matched card, found by pattern
                  rather than by class.

Ordering is the whole design.  Flipkart in particular ships obfuscated class
names that rotate without notice, so anchoring on CSS first would guarantee
breakage.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Page

from switch_tracker.adapters.browser.profiles import StoreProfile
from switch_tracker.core.parse import first_rupee_price, parse_price


@dataclass(frozen=True, slots=True)
class Extracted:
    title: str
    price: float
    href: str
    in_stock: bool
    #: The whole card's visible text, when the selector layer produced this row.
    #:
    #: Exists because some storefronts state a listing's CONDITION outside its
    #: title -- GameLand puts "Pre-owned" in a badge and in the category strip
    #: beside the product name, so ``infer_condition(title)`` reads NEW for a
    #: shelf of used cartridges.
    #:
    #: Empty for the JSON-LD and hydration-state layers: neither has a "card",
    #: and inventing one from the structured record would be guessing. Callers
    #: must therefore treat "" as "no context available" and fall back to the
    #: title, never as "the card said nothing".
    context: str = ""


async def extract(page: Page, store_id: str, profile: StoreProfile) -> tuple[list[Extracted], str]:
    """Try each layer in order; report which one produced the rows."""
    rows = await from_json_ld(page)
    if rows:
        return rows, "json-ld"

    if store_id == "flipkart":
        rows = await from_flipkart_state(page)
        if rows:
            return rows, "embedded-state"

    rows = await from_selectors(page, profile)
    return rows, "selectors" if rows else "none"


# ------------------------------------------------------------------ layer 1


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    """Flatten arrays, @graph nodes and ItemList elements into plain nodes."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
        return
    if isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in node:
                yield from _walk(node[key])


async def from_json_ld(page: Page) -> list[Extracted]:
    try:
        blobs = await page.locator('script[type="application/ld+json"]').all_text_contents()
    except Exception:  # noqa: BLE001 - a missing layer is not an error, just an empty layer
        return []

    out: list[Extracted] = []
    for blob in blobs:
        try:
            data = json.loads(blob)
        except ValueError:
            # One malformed block must not discard the valid ones beside it.
            continue
        for node in _walk(data):
            node_type = str(node.get("@type", ""))
            if "product" not in node_type.lower():
                continue
            offers = node.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            offer = offer if isinstance(offer, dict) else {}

            price = parse_price(offer.get("price") or offer.get("lowPrice"))
            name = str(node.get("name") or "")
            href = str(node.get("url") or offer.get("url") or "")
            if not name or price is None or not href:
                continue

            availability = str(offer.get("availability") or "")
            out.append(
                Extracted(
                    title=name,
                    price=price,
                    href=href,
                    in_stock="outofstock" not in availability.lower().replace(" ", "")
                    and "soldout" not in availability.lower().replace(" ", ""),
                )
            )
    return out


# ------------------------------------------------------------------ layer 2

_FLIPKART_WALK = """
() => {
  const state = window.__INITIAL_STATE__;
  if (!state) return [];
  const found = [];
  const seen = new Set();
  const walk = (n, depth) => {
    if (!n || typeof n !== 'object' || depth > 12 || seen.has(n)) return;
    seen.add(n);
    const title = n.title ?? n.productTitle ?? n.name;
    const price = n.finalPrice?.value ?? n.price?.value ?? n.sellingPrice?.value;
    const url = n.baseUrl ?? n.url ?? n.pageUri;
    if (typeof title === 'string' && typeof price === 'number' && typeof url === 'string') {
      found.push({ title, price, href: url,
                   inStock: n.availability?.intent !== 'OUT_OF_STOCK' });
    }
    for (const v of Object.values(n)) walk(v, depth + 1);
  };
  walk(state, 0);
  return found;
}
"""


async def from_flipkart_state(page: Page) -> list[Extracted]:
    """Read Flipkart's own hydration state.

    Walked STRUCTURALLY -- looking for any node carrying a title, a numeric
    price and a URL -- rather than by an assumed path, because Flipkart's own
    shape changes and a hard-coded path would break on their next deploy.
    """
    try:
        rows = await page.evaluate(_FLIPKART_WALK)
    except Exception:  # noqa: BLE001
        return []
    return [
        Extracted(str(r["title"]), float(r["price"]), str(r["href"]), bool(r["inStock"]))
        for r in rows
        if r.get("title") and r.get("href")
    ]


# --------------------------------------------------------------- layers 3+4

_CARD_SCRAPE = """
(nodes, cfg) => {
  const pick = (n, sels) => {
    for (const s of sels) {
      try {
        const t = n.querySelector(s)?.textContent?.trim();
        if (t) return t;
      } catch { /* not valid CSS in this context */ }
    }
    return '';
  };
  return nodes.map((n) => ({
    title: pick(n, cfg.title)
        || n.querySelector('a[title]')?.getAttribute('title')
        || n.querySelector('img')?.getAttribute('alt')
        || '',
    priceText: pick(n, cfg.price),
    cardText: n.textContent ?? '',
    // textContent with SEPARATORS restored. textContent concatenates its text
    // nodes with nothing between them, so a "Pre-owned" badge sitting flush
    // against the product name yields "Pre-OwnedZelda TotK" -- and the
    // word-boundary anchors in core/parse's PRE_OWNED patterns then fail to
    // match on a card that plainly says it. Real markup usually has whitespace
    // between the tags; minified markup does not, and which one a store ships
    // is not something to leave a data field depending on.
    //
    // A TreeWalker rather than innerText: innerText is defined in terms of
    // RENDERED text, so it forces a layout pass per card, and this codebase
    // already found that cost worth caching around (see claimed_total in
    // adapter.py). This walks the same nodes textContent does and only changes
    // the glue.
    //
    // Kept SEPARATE from cardText rather than replacing it. cardText feeds the
    // layer-4 rupee-pattern price fallback for all ten stores; this field is
    // read by one. No reason to put nine stores' prices through a change made
    // for one store's badge.
    spacedText: (() => {
      const walker = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
      const parts = [];
      while (walker.nextNode()) {
        const t = (walker.currentNode.nodeValue ?? '').trim();
        if (t) parts.push(t);
      }
      return parts.join(' ');
    })(),
    href: (() => {
      for (const s of cfg.link) {
        try {
          const h = n.querySelector(s)?.getAttribute('href');
          if (h) return h;
        } catch { /* ignore */ }
      }
      return n.getAttribute('href') ?? '';
    })(),
    oos: (cfg.outOfStock ?? []).some((s) => {
      // ':has-text(...)' is Playwright locator syntax, NOT real CSS. Passing
      // it to a native querySelector throws, and that caught exception is
      // easy to miss -- it silently disabled out-of-stock detection for every
      // store at once. Emulated here as a plain substring match instead.
      const m = /^:has-text\\((['"])(.+)\\1\\)$/.exec(s);
      if (m) return (n.textContent ?? '').includes(m[2] ?? '');
      try { return Boolean(n.querySelector(s)); } catch { return false; }
    }),
  }));
}
"""


async def from_selectors(page: Page, profile: StoreProfile) -> list[Extracted]:
    """CSS selectors, with the in-card rupee pattern as a price fallback."""
    config = {
        "title": list(profile.title),
        "price": list(profile.price),
        "link": list(profile.link),
        "outOfStock": list(profile.out_of_stock),
    }

    for card_selector in profile.card:
        try:
            count = await page.locator(card_selector).count()
        except Exception:  # noqa: BLE001
            continue
        if count == 0:
            continue

        try:
            raw_rows = await page.locator(card_selector).evaluate_all(_CARD_SCRAPE, config)
        except Exception:  # noqa: BLE001
            continue

        parsed: list[Extracted] = []
        for row in raw_rows:
            title = str(row.get("title") or "").strip()
            href = str(row.get("href") or "")
            if not title or not href:
                continue
            # Layer 4: if no price selector matched, hand the whole card's
            # text to the rupee pattern rather than giving up on the row.
            price = parse_price(row.get("priceText")) or first_rupee_price(str(row.get("cardText") or ""))
            if price is None:
                continue
            parsed.append(
                Extracted(
                    title,
                    price,
                    href,
                    not row.get("oos"),
                    context=str(row.get("spacedText") or row.get("cardText") or ""),
                )
            )

        if parsed:
            return parsed
    return []
