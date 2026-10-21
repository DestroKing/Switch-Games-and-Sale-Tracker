# TODO

## Current batch — 2026-10-21, in order

1. [x] **Sync `main`** — fast-forwarded to `origin/main` (`f4bebcb`: uncapped
       movers, 1% movement floor, store filter on the movers panel).
2. [x] **Green test suite** — 542 passed. Two real problems fixed, both in tests:
   - `test_entrypoint.py` built a from-scratch env (`PATH=/usr/bin:/bin`). On
     Windows that drops `SYSTEMROOT`, and `import asyncio` dies in Winsock
     (`WinError 10106`) before the test begins. Now inherits `os.environ`.
   - `test_queries.py` oracle never learned the 1% floor from `cbfc39b`, so an
     unchanged price was `0.0` in the oracle and `NULL` in production (15
     failures). Oracle now carries the rule as a literal.
3. [x] **`ruff format` gate** — 27 files reformatted (whitespace only) plus one
       stale `# noqa: E501` removed. 542 still pass. Commit it on its own so the
       churn stays out of real diffs.
4. [x] **Rewrite `docs/walkthrough.md`** — everything since `5fce210` folded
       into the sections it belongs to, not appended.
5. [~] **Improvements** — biggest gains done (below); the rest of the backlog is
       still to discuss.
   - [x] **Cross-store matching** — `core/matcher.py`. Re-runnable pass at the end
         of every collection, once on `serve` for an ungrouped DB, and on demand
         via `switch-tracker match`. Aliases in `matches.local.json`. Games view
         is now the default table.
   - [x] **Scheduled collection** — `switch-tracker collect-now` (through the
         same RunLauncher guards, waits for the worker) and
         `schedule --at HH:MM | --off` (Windows Task Scheduler; cron line
         elsewhere). Known gap: missed days are skipped (`ponytail:` note).
   - [x] **Watchlist + targets** — `watchlist.local.json`, `/api/watchlist`,
         panel above the collector, tab-title count, desktop notification
         while a tab is open. Hit = best IN-STOCK offer ≤ target.
   - [x] **Price history per row** — ▸ on any listing; SVG sparkline plus a
         readable summary (now / lowest-ever / highest).
   - [x] Fixed on the way: facet checkbox listeners stacked one per
         collection (N runs → N searches per tick); `.movers-toolbar` CSS.
6. [ ] **Hosting** — see "Putting it on the internet" in the session notes; decide
       on the shape before building anything.

## Improvement backlog (unprioritised until discussed)

Security
- [ ] Reject cross-site POSTs to `/actions/*` (check `Origin`/`Sec-Fetch-Site`)
      and pin the `Host` header. Today any web page you visit can POST to
      `127.0.0.1:4173/actions/reset-corrections` and the server will act on it.
      Prerequisite for any hosting.

Correctness / data
- [x] Matcher — done (see item 5).
- [ ] Detected deals: drop vs. trailing median, suppressed for `fx_suspect`
      clusters. (Targeted alerts are done via the watchlist.)
- [ ] Scheduled task: `StartWhenAvailable` via task XML so a PC that was off
      at the scheduled time still collects that day.
- [ ] A dashboard control for the schedule — the frozen exe is windowless, so
      `schedule --at` gives no on-screen feedback (it logs to windowed.log).
- [ ] Confirm the Flipkart second pass on a live walk (carried over, below).
- [ ] Flipkart `read_claimed_total` shortfall check is inert (carried over, below).

Performance
- [ ] `/api/movers` is now uncapped and the page fetches all of it on every
      boot. Fine at hundreds; at thousands of movers push the store filter and
      the preview limit into SQL.
- [ ] `listings()` always LEFT JOINs `previous` (a second seek per row) even
      when `change_pct` is not being sorted on. Measure before touching.

Code health
- [ ] `store.id == "flipkart"` now appears 4× in `adapter.py` plus once in
      `extract.py`. Still one *shop*, so the HLD's "second shop" trigger for a
      strategy seam has not fired — but a `profile.navigation_retry` flag
      would remove the id checks from the walk.
- [ ] `test_flipkart_recovery.py` leaks an un-awaited `AsyncMock` coroutine
      (RuntimeWarning at `adapter.py:468`).
- [ ] Starlette deprecation: `TestClient` over `httpx` → install `httpx2`
      before the next Starlette major removes it.
- [ ] Delete the TypeScript tree (`src/*.ts`, `src/web/`, root `*.local.json`)?
      It is still being edited (`server.ts` in `cd9af2f`) as a "legacy
      reference", which is maintenance for code nothing runs.
- [ ] `.movers-toolbar` (new in `f4bebcb`) has no CSS in `app.css`.

- [ ] `htmx.min.js` is loaded on every page and has zero `hx-` uses. Delete.

Functionality
- [x] Scheduled collection — done (see item 5).
- [x] Watchlist + target price — done (see item 5).
- [ ] Landed cost for imports: Play-Asia INR excludes shipping/customs.
- [ ] CSV export of the current filtered view.

UI
- [ ] Filter/sort state in the URL: refresh, back, bookmark all lose it today.
- [x] Per-listing price history — done (see item 5).
- [ ] Hint when sorting by Change narrows the list (carried over, below).

## Previous batch — status as of 2026-09-22

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
- [x] Confirmed on a live full walk: **79 → 184 listings**, 232 raw rows, p1→p8
      with p5 struck-and-skipped, ending naturally when p8 extracted nothing.

### Why this cannot be fixed by re-encoding the URL

The p5 and p6 traces from the same run normalise the identical request two
different ways:

| Page | 301 target | Result |
|---|---|---|
| p5 | `sid=4rr,fa6,32v` — `%2C` **decoded** | self-loops 19× |
| p6 | `sid=4rr%2Cfa6%2C32v` — `sid` **left encoded** | **200** |

Only the comma form loops, but which form comes back is not a property of what
we sent. There is no encoding to choose — only a page to retry.

### Open, low priority

- [x] **Recover the struck page.** Done. After the walk ends, a second pass
      re-attempts every page it lost, one attempt each — the elapsed walk is
      the backoff, and p6's trace proves the edge serves 200 to the identical
      request once the session verdict expires. Bounded by the same deadline.
      Failures are now held in `struck` and only folded into `problems` if the
      second pass does not get them back, so a fully recovered walk reports
      **Ok** rather than Partial. Expect ~184 → ~223 on a run losing one page.
- [ ] Confirm the recovery pass on a live Flipkart walk.
- [ ] `read_claimed_total` now reports **~132** for Flipkart where earlier runs
      read ~273. Since `raw_seen` (232) exceeds it, the
      `raw_seen < claimed_total * 0.9` shortfall check is inert for this store.
      Already documented as best-effort scraped prose, not authoritative — but
      it is currently not detecting anything.

## Genuinely still open

- [x] **`probe` can mis-detect Shopify (root cause of the bad hgworld override).**
      `probe.py:176-178` `_contains()` substring-matches the raw body for
      `"products"`. Any WordPress/Woo page whose inline JS contains that literal
      is detected as Shopify, and `run()` then writes `kind=SHOPIFY` into
      `stores.local.json`, overriding the hand-verified config. Fix: shape-check
      the parsed JSON instead of substring-matching text.

- [x] **"Load 100 more" scrolls back to top.** Fixed in `340ddab`: append
      now inserts into the existing `<tbody>` and restores keyboard focus.

## Notes / deferred

- Sorting by **Change** deliberately narrows the list to real movers
  (`queries.py:183-188`), so `total` drops when that sort is active. Intended,
  but worth a UI hint if it reads as a bug.
- Flipkart `p8` yielded 0 new rows; `ProductivityTracker` needs 4 consecutive
  unproductive pages before stopping, so it walked one page past exhaustion.
  Harmless (dedupe drops them) — leave unless page cost matters.
