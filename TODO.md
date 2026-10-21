# TODO

What is done, what is next, and what is waiting on a decision. Status as of
2026-10-21. History of *how* things were found lives in git and in
`docs/walkthrough.md`; this file is only the current state.

**Gate** (all must pass before anything is "done"): `uv run pytest`,
`uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`,
`uv run mypy`, `node --check src/switch_tracker/web/static/app.js`.

---

## 1. Done this cycle

Committed:

- `45d4835` Two test failures fixed (Windows-env subprocess, frozen-oracle 1% floor);
  walkthrough brought up to date.
- `1550b14` `ruff format` across the tree (whitespace only).
- `34e8ef6` Cross-store **game matching** + Games view; **watchlist** with targets and
  desktop notifications; per-listing **price history**; `collect-now` /
  `schedule --at HH:MM`. 12 bugs found and fixed before commit (6 by an
  independent review).

Not yet committed (this batch):

- **Security** (from a `sharp-edges` review):
  - `web/guard.py`: Host allowlist on every request (DNS rebinding) and Origin +
    Sec-Fetch-Site on every POST/PUT/DELETE (cross-site requests). Pure ASGI,
    runs before routing. Tested by a route walk, so new routes are covered by default.
  - Stored-XSS: only `http`/`https` listing URLs are saved (`collect._persist`),
    and `safeHref()` in `app.js` refuses anything else; `esc()` now escapes `'`.
  - Port validated to 1-65535; settings booleans must be real booleans;
    `TRACKER_DB=""` no longer means the current folder.
  - 500 responses no longer echo exception text (local paths); detail goes to the log.
  - Watchlist capped at 500 entries; set-aside corrupt files get unique names.
- **UX** (from a `ux-heuristics` review in a real browser):
  - Game rows named after a NEW copy, not the cheapest (often "- Pre-Owned") listing.
  - Unwatching offers **Undo** (restores the target); saving a target says "saved";
    keyboard focus survives the watchlist repaint.
  - "Fix a broken store" needs an explicit **Open** (arrow keys used to open browsers).
  - Count line: "312 games" / "Showing 100 of 312"; explains the Change-sort narrowing.
  - Heading matches its toggle ("Every listing"); ▸ targets 24x24 (WCAG 2.5.8);
    filter popover fits a 390px phone.
- **Structure** (Python Packaging Authority src-layout guidance): `src/` now holds
  only the importable package. The retired TypeScript implementation that sat
  interleaved inside it (20 files) and its two root `*.local.json` files were
  **deleted** -- nothing ran them; they remain in git history. Every code comment
  that cited a TypeScript file was rewritten to keep its reasoning without the
  reference. `.idea/` is no longer tracked (local copy kept); `.gitignore` covers
  it and stray root `*.local.json`.
- **Dead files removed** (each verified unreferenced first): `scripts/diagnose.py`
  (byte-identical duplicate), `diagnose_playasia_pager.py`, `diagnose_playasia_sort.py`,
  `scrape_check_playasia.py`, `scrape_check_e2zstore.py`, `static/htmx.min.js`
  (51 KB, zero uses), and dead functions `settings.save`, `parse.infer_platform`,
  `profiles.SELECTOR_FIELDS`, `errors.error_fragment`.

---

## 2. Next up, in order

Ranked by value against regression risk, merging four skill-driven reviews
(`product-designer`, `ponytail-audit`, `ux-heuristics`, `sharp-edges`). Risk
calibration: the last feature batch produced about **1 bug per 100 new lines**;
*silent* risk means a bug that yields a plausible wrong answer.

| # | Item | Gain | Size | Risk | Notes |
|---|---|---|---|---|---|
| 1 | **Lowest-ever price** on Games + Watchlist rows ("lowest ever ₹X", "at its low") | High | S | Low, loud | Answers "is this a good price?" from history that exists; a MIN, far safer than deal detection |
| 2 | **Automatic database backups** after each collection (`VACUUM INTO`, keep last N) | High | S | Low | `tracker.db` is the one irreplaceable file and nothing backs it up |
| 3 | **Missed-day scheduling**: a logon trigger plus "skip if collected < 20 h ago" | Med | S-M | Med | Plain DAILY skips a day the PC was off. Check `schtasks /SC ONLOGON` needs no admin before relying on it |
| 4 | **Toast from the scheduled run** (Windows notification via built-in PowerShell) | Med | M | Med | Today a 07:30 hit is unseen until a tab opens; stays on-machine, no outside service |
| 5 | Read-only **schedule status** line ("Daily at 07:30 · last ran …" from `schtasks /query`) | Med | S | Low | Replaces the dropped "schedule control" (a write endpoint that creates OS tasks) |
| 6 | **Static read-only snapshot** for the internet + scoped phone layout | High | M-L | Med, loud | Export Games + Watchlist only; strip `run_store.detail` and local paths; CSP; http(s) URLs only. Host choice pending (§3) |
| 7 | **Filters in the URL** (refresh/back/bookmark) | Med | M | Med, loud | Pays off more once the snapshot has shareable links |
| 8 | Out-of-stock sort hint (separator row or header note) | Low | S | Low | "Best price ▲" lists in-stock first; reads as a bug |
| 9 | Facet counts that respect the other active filters | Low | M | Med, silent | Store counts ignore the console filter today |
| 10 | Test hygiene: un-awaited `AsyncMock` warning in `test_flipkart_recovery.py` | Low | S | Low | |
| 11 | **Detected deals** (drop vs trailing median, FX-suppressed) | Med-High | L | **High, silent** | Only if #1 proves not enough; ship as a flag before it ever alerts |

Verification runs (2026-10-21, on the office network, into a throwaway data dir):

- [x] **Live collection + matching on real data.** 6 stores collected (Amazon 762,
      mcubegames 484, hadiro 294, Flipkart 195, consolegarage 34, sheenu 16):
      1,774 listings -> 1,383 games, **246 matched across 2+ stores**, no wrong
      merge found. Splits seen come from titles the shops truncate ("...twin pa"),
      Amazon publisher prefixes ("Warner Bros Interactive Entertainment ..."), and
      typos -- alias territory. **Found and fixed a real bug:** the WooCommerce
      Store API sends HTML-encoded names (`&#8211;`), which showed as literal text
      and split games ("mario kart world 8211").
- [~] **Flipkart live walk:** Ok, 195 listings, no struck page -- so the
      second-pass recovery was not exercised this time. Still open.
- [x] **Exe rebuilt** (841 MB). Packaged self-check: templates, server, Playwright
      PASS; TLS FAILS -- identically from source, so it is this network (HTTPS
      interception by an untrusted corporate CA), not the build.
- [ ] Scheduled task -- deliberately not exercised.
- Network caveat: on the office network 7 browser stores were reset
      (`ERR_CONNECTION_RESET`) and probe found 10 HTTP stores unreachable -- all 23
      work from the user's own network. That run exposed a real bug, now FIXED:
      probe used to write `enabled: false` for an unreachable store, so one probe on a
      bad network silently stopped working stores being collected. It now leaves
      them alone and re-enables any an older probe disabled that way.

Follow-ups from the live data and the final review:

- [ ] Matcher: strip known publisher prefixes Amazon prepends; consider truncated
      titles (medium risk, **silent** -- a wrong strip merges different games).
- [ ] `run.ps1` opens `http://127.0.0.1:4173` regardless of the configured port
      (now a 403 instead of a connection error if they differ).

---

## 3. Waiting on a decision

| Decision | Recommendation | Why it is yours |
|---|---|---|
| **Host for the snapshot** (needed only when #6 is built) | A non-GitHub static host, e.g. Cloudflare Pages by direct upload (no git involved) | Needs an account you create. Org policy forbids writes to github.com, which rules out GitHub Pages; `origin` points at github.com, so do not push |
| **Watchlist per condition** ("new copies only") | Your call | Today a target compares against the cheapest copy of ANY condition, so a used copy under target counts as a hit |

Decided: TypeScript tree deleted; `.idea/` untracked; `scrape_check.py` kept
separate from `check_stores.py` (see Dropped).

---

## 4. Dropped, with reasons

- **Merging `scrape_check.py` into `check_stores.py`** -- ~40% of `scrape_check` is
  unique (`--diagnose-pager`, per-page timing, paging-mechanism printout), so a merge
  would MOVE ~120 lines rather than delete them, into a live-only tool the test suite
  cannot verify. Distinct jobs: `check_stores` = all-store sweep, `scrape_check` =
  one-store deep dive.

- **Dashboard control that creates scheduled tasks** -- a web write endpoint that
  makes OS tasks is a security liability; replaced by #5 (read-only status).
- **CSV export** -- single user, and the database is plain SQLite.
- **Skip the `previous` price join when unused** -- unmeasured; revisit if slow.
- **Movers filtering in SQL** -- only matters at thousands of movers.
- **Flipkart profile flag replacing `store.id == "flipkart"`** -- the "second shop"
  trigger in the HLD has not fired.
- **Flipkart `read_claimed_total` shortfall check** -- inert for Flipkart (claims ~132
  while 232 rows are seen); remove rather than keep code that detects nothing.
- **Landed cost for imports** -- a wrong shipping/customs figure looks real; only
  as a user-set, display-only surcharge if ever.
- **Store health over time** -- the collector tiles already surface zero-listing stores.
- **`httpx2`** (Starlette's TestClient deprecation) -- would add a dependency; act
  when Starlette actually removes httpx support.

## 5. Known, accepted

- Desktop notifications fire only while a dashboard tab is open (until #4).
- The matcher errs towards splitting; missed merges are fixed with aliases.
- Sorting by Change narrows the list to real movers -- now explained in the count line.
- The scheduled task refuses to register while `TRACKER_DATA_DIR`/`TRACKER_DB` is set
  (the task would not see them).
