# TODO

Tracking the current batch of fixes. Status as of 2026-09-22.

## Root cause for most of this: stale build

Three of the four reported problems are **already fixed in this repo** and only
reproduce in an older packaged build:

| Reported | Fixed by | Evidence it is already fixed |
|---|---|---|
| `hgworld: 0 listings — /collections/.../products.json: no parseable JSON` | `182a2cb` | That is the **Shopify** adapter's message; `stores.py:79` declares hgworld `WOOCOMMERCE`. Confirmed live: `hgworld.in/products.json` → **403**, `hgworld.in/wp-json/wc/store/products` → valid JSON with `prices`. |
| `flipkart: p4 ERR_TOO_MANY_REDIRECTS`, walk continued to p8 | `c5c121d` | `adapter.py:192-217` retries the page in a fresh tab, then **breaks**. The reported log continued to p5–p8 and never logged the retry line, so that code did not run. |
| Change column shows `+0.0` for unchanged prices | `553a8b0` | `queries.py:183-188` filters unchanged rows out when sorting by Change; `app.js:576` renders `—` for zero/null. No `+` sign exists anywhere in current code. |

- [ ] **Rebuild the exe** (`BUILD-EXE.bat`) and re-run — expected to clear all three.
- [ ] Confirm with `scripts/check_stores.py hgworld flipkart` before rebuilding.

## Genuinely still open

- [ ] **`probe` can mis-detect Shopify (root cause of the bad hgworld override).**
      `probe.py:176-178` `_contains()` substring-matches the raw body for
      `"products"`. Any WordPress/Woo page whose inline JS contains that literal
      is detected as Shopify, and `run()` then writes `kind=SHOPIFY` into
      `stores.local.json`, overriding the hand-verified config. Fix: shape-check
      the parsed JSON instead of substring-matching text.

- [ ] **"Load 100 more" scrolls back to top.** `app.js:634` reassigns
      `$("list").innerHTML` on append, destroying and rebuilding the whole
      table. Append the new rows to the existing `<tbody>` instead.

## Notes / deferred

- Sorting by **Change** deliberately narrows the list to real movers
  (`queries.py:183-188`), so `total` drops when that sort is active. Intended,
  but worth a UI hint if it reads as a bug.
- Flipkart `p8` yielded 0 new rows; `ProductivityTracker` needs 4 consecutive
  unproductive pages before stopping, so it walked one page past exhaustion.
  Harmless (dedupe drops them) — leave unless page cost matters.
