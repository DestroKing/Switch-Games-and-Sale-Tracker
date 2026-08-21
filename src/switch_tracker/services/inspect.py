"""Worker: the click-to-pick selector tool, in a REAL, VISIBLE browser window.

The one capability that cannot live inside the dashboard's own tab -- a human
has to click on the store's actual page.  It is still launched exactly like
every other action (the exe re-invoking itself), so it is not a special case
in the architecture, only in being visible.

Clicks are resolved through ``elementsFromPoint`` rather than the click event's
own target: many product cards wrap the whole tile in one absolutely-positioned
overlay link, so a plain click always hits that overlay and never the title or
price text visually underneath it.  Reading the entire element stack at the
click point recovers the real element.
"""

from __future__ import annotations

import asyncio
from typing import Any

from switch_tracker.adapters.browser import overrides as profile_overrides
from switch_tracker.adapters.browser.provider import BrowserProvider
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.events.writer import EventWriter

STEPS = (
    ("card", "Alt+click the WHOLE PRODUCT CARD -- the box around one listing."),
    ("title", "Alt+click that card's TITLE text."),
    ("price", "Alt+click that card's PRICE text."),
    ("link", "Alt+click that card's LINK (often the title itself, or the image)."),
)

_PICKER = """
() => {
  let hovered = null;

  const candidatesFor = (el) => {
    const tag = el.tagName.toLowerCase();
    const tried = new Map();
    const add = (css) => {
      if (tried.has(css)) return;
      try { tried.set(css, { css, matches: document.querySelectorAll(css).length }); }
      catch { /* not valid CSS here */ }
    };
    // Ordered stable-first: an id beats a data attribute beats a class name.
    if (el.id) add('#' + CSS.escape(el.id));
    for (const attr of ['data-testid','data-cy','data-component-type','data-id',
                        'data-product-id','data-asin','data-sku','data-pid']) {
      const v = el.getAttribute(attr);
      if (v !== null) { add(`${tag}[${attr}='${CSS.escape(v)}']`); add(`[${attr}]`); }
    }
    const classes = [...el.classList].map((c) => CSS.escape(c));
    if (classes.length) add(`${tag}.${classes.join('.')}`);
    add(tag);
    return [...tried.values()];
  };

  document.addEventListener('mouseover', (e) => {
    if (hovered) hovered.style.outline = '';
    hovered = e.target;
    hovered.style.outline = '2px solid #ff2d78';
  }, true);

  document.addEventListener('click', (e) => {
    if (!e.altKey) return;   // plain clicks still dismiss banners and navigate
    e.preventDefault();
    e.stopPropagation();

    const stack = document.elementsFromPoint(e.clientX, e.clientY)
      .filter((el) => el.tagName !== 'HTML' && el.tagName !== 'BODY')
      .slice(0, 8);

    const seen = new Set();
    const candidates = [];
    for (const el of stack) {
      for (const c of candidatesFor(el)) {
        if (seen.has(c.css)) continue;
        seen.add(c.css);
        candidates.push(c);
      }
    }
    window.__reportPick({ candidates });
  }, true);
}
"""


async def run(run_id: int, store_id: str) -> int:
    conn = db.connect()
    db.ensure_schema(conn)
    events = EventWriter(conn, run_id)
    events.run_started(1)

    store = next((s for s in overrides.active_stores() if s.id == store_id), None)
    if store is None or not store.search_urls:
        events.warning(f"{store_id} has no page to open.")
        events.run_finished()
        conn.execute("UPDATE run SET finished_at = datetime('now') WHERE id = ?", (run_id,))
        return 1

    provider = BrowserProvider(headless=False)
    step_index = 0
    card_selector: str | None = None
    finished = asyncio.Event()

    try:
        context = await provider.new_context()
        page = await context.new_page()

        async def coverage(css: str) -> float:
            """How many of the sampled cards actually contain this selector."""
            if card_selector is None:
                return 0.0
            return float(
                await page.evaluate(
                    """([cardSel, css]) => {
                        const cards = Array.from(document.querySelectorAll(cardSel)).slice(0, 8);
                        if (!cards.length) return 0;
                        let hits = 0;
                        for (const card of cards) {
                          try { if (card.querySelector(css)) hits++; } catch { /* skip */ }
                        }
                        return hits / cards.length;
                    }""",
                    [card_selector, css],
                )
            )

        async def report_pick(pick: dict[str, Any]) -> None:
            nonlocal step_index, card_selector
            if step_index >= len(STEPS):
                step_index = 0
            field, _ = STEPS[step_index]
            candidates = pick.get("candidates") or []

            if field == "card":
                # A card selector has to REPEAT. Candidates arrive stable-first,
                # so the first that matches a sane number of times wins.
                winner = next((c for c in candidates if 2 <= c["matches"] <= 500), None)
                if winner is None:
                    best = candidates[0]["matches"] if candidates else 0
                    events.warning(
                        f"Nothing there repeats across the page (best: {best} matches) -- "
                        "try the tile's outer box."
                    )
                    return
                card_selector = winner["css"]
                profile_overrides.add_selector(store_id, "card", winner["css"])
                events.warning(f"card: {winner['css']} ({winner['matches']} on this page) -- saved.")
            else:
                scored = [(await coverage(c["css"]), c["css"]) for c in candidates]
                scored.sort(reverse=True)
                if not scored or scored[0][0] == 0:
                    events.warning("That is not inside the saved card -- click inside a tile.")
                    return
                score, css = scored[0]
                profile_overrides.add_selector(store_id, field, css)
                events.warning(f"{field}: {css} (in {round(score * 100)}% of sampled cards) -- saved.")

            step_index += 1
            if step_index >= len(STEPS):
                events.warning(
                    "All four saved. Run 'Collect prices' to try them, or keep Alt+clicking "
                    "to add fallbacks for listings that look different."
                )
                step_index = 0
            else:
                events.warning(f"{step_index + 1}/4 -- {STEPS[step_index][1]}")

        await page.expose_function("__reportPick", report_pick)
        await page.add_init_script(_PICKER)
        page.on("close", lambda _: finished.set())

        await page.goto(store.search_urls[0].replace("{p}", "1"))
        events.warning(f"Opened {store.name}. 1/4 -- {STEPS[0][1]}")
        events.warning("Plain clicks still work normally. Close the window when you are done.")

        await finished.wait()
    finally:
        await provider.close()

    events.run_finished()
    conn.execute("UPDATE run SET finished_at = datetime('now') WHERE id = ?", (run_id,))
    return 0
