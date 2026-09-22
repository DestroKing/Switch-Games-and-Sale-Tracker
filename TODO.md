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

## HG World: the real cause, found by `--probe` (resolved)

The stale override was only half of it. Cloudflare **403s the Store API's
`category=` parameter on this host by every available route** — term id, slug,
v1 path, legacy path, `per_page` 100 and 10, and `collection-data?category=`.

It is the parameter, not the word: `?note=category` answers 200. It is not rate
limiting: a bare baseline repeated *after* the refusals still answers 200 with
`x-wp-total=1596`. Both apparent escapes are dead ends —

| Route | Status | Why it fails |
|---|---|---|
| `?category_id=<id>` | 200 | WordPress ignores unknown params — returns the **unfiltered** catalogue (verified: SteamOS PC, DJI mics) |
| `wp/v2/product?product_cat=<id>` | 200 | Filters correctly (all 10 were Switch games) but carries **no price field** |

- [x] Fetch hgworld **unscoped** (~16 pages, 1596 products) and let the
      classifier sieve. `WooAdapter.fetch` already does this for
      `collections=()`; no adapter change was needed.
- [x] **Drop `platform_hint`** — mandatory companion, not cosmetic. Unscoped,
      the classifier is the only sieve, and a hint means "assume Switch when
      the text names no console", which relabels this general retailer's
      accessories as games. Same reasoning as `designinfo`.
- [x] Both properties pinned by tests, so re-adding either regresses loudly.

## Flipkart: a moving redirect loop, and a `break` that made it worse

The `--probe`-style redirect trace settled this. Flipkart answers a **valid**
page URL with a `301` to the byte-identical URL, 19 hops, until Chromium gives
up with `ERR_TOO_MANY_REDIRECTS`. Hop 1 is a legitimate `%2C`→`,`
normalisation; every hop after it is the same URL redirecting to itself.

It is a **session verdict, not a bad URL** — the page it strikes moves between
runs:

| Run | Outcome |
|---|---|
| `--pages 3` | p1–p3 all clean |
| full (older build) | p3 clean, **p4 struck**, p5–p8 collected normally |
| full (current) | p1–p2 clean, **p3 struck** |

That third run exposed the real bug: the flipkart branch `break`s on a failed
page, so it stopped at p3 and returned 79 listings where the older
continue-anyway build got 228.

- [x] Retry now **waits** before re-issuing (`_REDIRECT_LOOP_BACKOFF_S`). A
      fresh tab alone re-issues instantly and collects the same verdict.
- [x] A struck page is **skipped, not fatal** — the walk carries on.
- [x] Bounded at `_MAX_NAV_FAILURES = 3` *consecutive* failures, because only a
      streak separates "one struck page" from "session blocked outright"; the
      latter must stop rather than walk to `page_cap`.
- [x] Both shapes covered by runnable mock tests in `test_flipkart_recovery.py`
      (no browser needed).
- [ ] Re-run `check_stores.py flipkart` to confirm it now reaches ~273 raw.

## Genuinely still open

- [x] **`probe` can mis-detect Shopify (root cause of the bad hgworld override).**
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
