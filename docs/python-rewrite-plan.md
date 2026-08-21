# switch-tracker — Python/FastAPI rewrite plan

Not implemented yet. This is the spec the rewrite gets evaluated against —
every capability in "What the current version actually does" either needs an
equivalent in Python, or a deliberate, written-down reason it was dropped.
Target: Indian product companies. Already have Java/Spring Boot professionally;
this is meant to be a second stack that's genuinely different, not another
OOP language with different keywords.

## What this actually is

A **personal, local** price tracker for one person's own buying decisions —
not a product, not multi-tenant, no accounts. It watches Indian retailers
(plus Play-Asia as an import comparison, currently parked) for **physical
Nintendo Switch / Switch 2 cartridges** and builds price history over time,
with the eventual goal of catching real sales as they happen instead of
missing them.

**Hard scope boundary, enforced at classification, not at data-entry:**
games only. Consoles, Joy-Cons/Pro Controllers, cases, screen protectors,
amiibo, cooling pads, eShop codes, gift cards, Switch Online memberships,
and repair/mod/"game loading" services are all explicitly excluded, even
when a store files them under the same category as its actual games. Games
for *other* consoles (PS4/PS5/Xbox/PC/3DS/Wii/GameCube/etc.) are excluded
too, even on stores hinted "this is a Switch-only shop" — an explicit console
name in a title always wins over a hint that says otherwise. The rewrite
must keep an equivalent classifier; scraping without it just relabels
"everything this store sells" as "Switch games."

**Why it exists at all — the two pieces that still haven't been built are
the actual point of the project:**
1. **The matcher** (not built) — the same cartridge at four stores is
   currently four unrelated rows (`listing.game_id` sits NULL for every one
   of them). Fuzzy-matching listings into one canonical "game" is what turns
   this from "a list of things stores sell" into "where is the cheapest copy
   of X right now."
2. **The alert engine** (not built) — the reason price *history* matters at
   all: detect a genuine price drop on a listing against its own trailing
   median, and suppress it when it's actually the whole store repricing or
   the rupee moving against a foreign currency on the same day across many
   listings at once (a currency move is not a sale — the `movers` endpoint
   already flags this cluster pattern, but nothing acts on it yet). Telegram
   was the originally intended delivery channel. Everything about storing
   native price + derived INR + the FX rate date exists specifically to make
   this possible later — don't lose that data shape in a rewrite for
   convenience.

## Current capabilities (what the rewrite has to match or consciously drop)

This is the working TypeScript/Bun version as it stands today, in enough
detail to check off against, not a summary that hides what would be lost.

### Store adapters (three, dispatched by `kind`)

- **Shopify** (`/products.json` or `/collections/<handle>/products.json`,
  paginated at 250/page, no auth) — reads `product_type` + `tags` + `title`
  as classification context, one variant's price/availability per product,
  scoped to specific collection handles when a store's catalogue isn't
  games-only.
- **WooCommerce** (the public, unauthenticated Store API —
  `/wp-json/wc/store/v1/products`, falling back to `/wp-json/wc/store/products`
  for older installs) — reads `x-wp-total` from the response header for a
  real, structured "how many products actually match this query" count (see
  Completeness below); category slugs are resolved to their real numeric WP
  term id via `/wp-json/wp/v2/product_cat?slug=X` first, because filtering by
  raw slug silently returns zero results on some installs even when the
  category is real and populated — falls back to the raw slug only if that
  lookup itself comes back empty.
- **Browser** (Playwright/Chromium, headless by default, `HEADFUL=1` env var
  to watch it) — for storefronts with no public product API (Amazon,
  Flipkart, and several small Next.js-built Indian retailers). Extraction is
  layered, most-durable-first:
  1. JSON-LD (`<script type="application/ld+json">`, schema.org
     Product/ItemList) — survives redesigns because it exists for search
     engines, not layout.
  2. Site's own embedded hydration state (Flipkart's `__INITIAL_STATE__`,
     walked structurally rather than by assumed shape, since Flipkart's own
     shape changes).
  3. CSS selectors, per-store profiles.
  4. Regex rupee-figure extraction from a matched card's raw text, when no
     price selector matches.
  Also handles: cookie/interstitial dismiss clicks, out-of-stock text
  detection (emulating Playwright's `:has-text()` locator syntax against
  plain-DOM `querySelector`, since that syntax isn't real CSS and silently
  no-ops otherwise), image-request blocking for speed, a stealth patch for
  `navigator.webdriver`, and two distinct pagination strategies: URL
  `{p}`-templated for stores where that actually works, or click-based via a
  configured "next page" selector for stores whose pagination is entirely
  client-side with no URL change at all (confirmed present on at least two
  real stores — a URL param there does nothing, silently returning page 1's
  content forever).

### Classification & parsing (`core/parse.ts`)

- **Price parsing** handles the ~6 ways Indian storefronts write a price
  (`₹4,499.00`, `Rs. 4499`, `INR 4,499`, `4.499,00`), including the
  comma-vs-decimal ambiguity: a lone comma with no decimal point anywhere in
  the string is always a thousands separator, never a decimal point.
- **Platform**: `SWITCH | SWITCH2 | UNKNOWN`, inferred from title/context
  text with an explicit "other console named" list (PlayStation/Xbox/Wii
  U/3DS/GameCube/Steam/PC/etc.) that overrides a store's `platformHint` —
  a hint means "assume Switch when nothing is said," never "assume Switch
  even when a different console is named."
- **Product kind**: `GAME | HARDWARE | ACCESSORY | DIGITAL | SERVICE |
  UNKNOWN` — hardware/accessory/digital/service exclusions run *before*
  platform matching, or "Nintendo Switch Pro Controller" would match on the
  word "Switch" and sail through as a game.
- **Condition**: `NEW | PRE_OWNED` — inferred per listing from the same
  context text (title + whatever categories/tags the store returns), not a
  static per-store flag. A store's own "Pre-Owned Games" category name
  (a real category on at least one current store) flows through
  automatically; absent any explicit marker, a listing defaults to `NEW`.
- **Region**: `IN | ASIA_EN | ASIA_ZH | JP | US | EU | UNKNOWN` — first-class,
  not a tag (see Non-negotiables below), inferred from title text with a
  store-level default fallback.
- **Title normalisation** for the (not-yet-built) matcher's first pass:
  strips console/format/condition noise words, brackets, parenthetical
  region markers.

### Store scoping & self-correction (`cli/probe.ts`)

- Detects each configured store's real backend by hitting its API directly
  (Shopify `/products.json`, both known WooCommerce Store API paths) before
  falling back to a homepage fingerprint check that distinguishes "real
  Shopify with `/products.json` deliberately blocked by the merchant" from
  "not Shopify/Woo at all, needs a browser adapter" — these need different
  fixes and get different findings.
  Findings: `SHOPIFY | WOOCOMMERCE | UNREACHABLE | SHOPIFY_LOCKED |
  UNKNOWN_HTML` — the last three are diagnoses, not adapter kinds, and are
  never written to config as if they were fetchable.
  Corrections are written to a `stores.local.json` override file, never to
  the checked-in source list — probe is allowed to fix its own mistakes on
  every run without ever touching version-controlled config.
- For any store with no `collections` scoping configured yet, lists that
  store's real categories (WooCommerce `product_cat` or Shopify
  `collections.json`), paginated deep enough to actually reach a category
  that's alphabetically buried past the first page (seen in practice: a
  store with 100+ categories where the one relevant category was on page 2).
  Nintendo/Switch/game-word-relevant categories are surfaced first
  regardless of where they'd otherwise sort, specifically so scoping a newly
  found mixed-catalogue store is a copy-paste into config, not a manual API
  round-trip. Skipped once a store already has `collections` set — a
  one-time discovery aid, not a per-run cost.
- Runs all stores concurrently (bounded pool, default 8) since they're
  independent hosts; prints in stable original order once everything's
  back. Every run's full output (including the category dump) is also
  written to a log file, since it's regularly too long to usefully scroll a
  terminal buffer for.

### Selector discovery tool (`cli/inspect.ts`)

A guided, four-step Alt+click flow for fixing a browser-scraped store with
no API: click a product card, then its title, then its price, then its
link. Scores each click against real page structure (a card selector is
judged by how many elements it matches across a sane range; title/price/link
selectors are judged by coverage across a sample of real cards) and
auto-writes the winning selector to a `profiles.local.json` override —
prepended ahead of the built-in guesses rather than replacing them, so a
correction never has to also carry the rest of a working profile. Loops
back after four steps so a human can supply fallback candidates for a
selector that's inconsistent across cards. Uses
`document.elementsFromPoint()` rather than the click event's own target, so
clicking through an overlay link (a full-card `<a>` wrapping everything)
still resolves to the actual element underneath.

### Pagination completeness — three different answers for three different adapter shapes

This was a real, reported bug (see Hard-won lessons) and the fix is now
three different mechanisms because the underlying stores genuinely offer
three different levels of truth:

- **WooCommerce**: the Store API's own `x-wp-total` response header is an
  authoritative count for the query just run. Fetched-so-far vs. that number
  is a hard, correct completeness check — returns `partial` status with the
  real numbers in the reason string when short.
- **Shopify**: paging already stops on a real signal (a page returned with
  fewer than the requested page size), so there's no separate "did we get
  everything" check needed beyond that.
- **Browser-scraped stores**: no structured total exists. Two independent
  signals, both best-effort:
  - The page-stop condition itself: a page counts as unproductive if fewer
    than 15% of its rows are genuinely new (not just repeated or
    slowly-reshuffling "related items" filler), and it takes four
    consecutive unproductive pages — not one, not two — before the loop
    gives up. (The original strict "exactly zero new rows, twice in a row"
    version was fooled by filler content that reshuffles slightly page to
    page and so rarely lands on exactly zero even once real content is
    exhausted — this is what silently truncated two real stores' catalogues
    before being caught.)
  - A generic "showing X of Y results/items/products" text scrape
    (`readClaimedTotal`), tried against a handful of common phrasings. When
    a store's page happens to say this, the raw row count seen is compared
    against it and surfaced in the run's result — not authoritative, but
    better than silence.
  Every store, regardless of kind, also has a shared, generous, purely
  last-resort page-count ceiling (not a per-store number) that exists only
  to stop a genuinely broken loop that produces neither real stopping
  signal — it is never meant to be the thing that actually ends a healthy
  run.

### Concurrency & scheduling

- Two separate concurrency pools sized for what they actually cost: HTTP
  stores (Shopify/WooCommerce, concurrency 8) and browser stores (real
  Chromium contexts, concurrency 4) — a flat shared limit previously let two
  large browser catalogues (Amazon, Flipkart) occupy every slot and starve
  every other browser store for the entire run.
- Per-*kind* time budgets, not per-store: 180s for HTTP stores, 600s for
  browser stores — an HTTP store's own request-level timeout/retry budget
  already bounds it regardless of catalogue size; a browser store now pages
  for as long as the site's own pagination signal keeps working, so its
  budget has to cover a genuinely large catalogue rather than a guessed
  page count.
- One collector-politeness HTTP client shared across all HTTP adapters:
  serialized per host (not globally), with a minimum gap between requests
  to the same host and capped retries on 429/5xx (403/404 treated as a real
  answer, not a hiccup worth retrying).
- No in-process scheduler. A Windows Task Scheduler entry
  (`schedule-task.ps1`) or a plain crontab line runs `collect` unattended on
  a fixed cadence; the app itself does nothing while not explicitly invoked.

### Data model

```
store       (id, name, base_url, kind, currency, tier, enabled)
game        (id, canonical_title, platform, region)      -- UNIQUE(title, platform, region)
listing     (id, store_id, sku, game_id NULLABLE, url, raw_title,
             platform, region, condition, image_url, first_seen, last_seen)
                                                          -- UNIQUE(store_id, sku)
price_point (id, listing_id, run_id, captured_at,
             native_currency, native_price, inr_price, fx_rate_date, in_stock)
fx_rate     (base, quote, rate, rate_date, fetched_at)   -- PK(base, quote, rate_date)
run         (id, started_at, finished_at)
run_store   (run_id, store_id, status, listings_found, duration_ms, detail)
                                                          -- PK(run_id, store_id)
```

`run_store` is the health table — a store silently returning zero rows is
the failure mode that quietly rots a tracker over time, so its absence gets
recorded exactly as loudly as an exception would (`status`, a free-text
`detail` for the reason, and timing, per store per run).

### FX rates

Frankfurter (ECB reference rates, no key required) fetched per unique
non-INR currency in use, stored with its own publication date (a weekend
fetch legitimately returns Friday's rate — that's correct, not stale, and is
stored and reused as such). `native_price × rate-on-that-date = inr_price`,
computed at collection time and stored alongside the rate date used, so a
later query never has to guess which rate applied.

### Dashboard (local-only, `127.0.0.1` bound)

API: `/api/summary` (headline counts), `/api/health` (per-store status for
the latest run), `/api/movers` (price changes since each listing's previous
observation, with FX-suspect clustering — many listings in the same
currency moving by the same rounded percentage on the same day gets flagged
as the currency moving, not a sale), `/api/listings` (search/filter/sort/
paginate — all in SQL against the full table, never sorting a page of
already-loaded rows), `/api/facets` (store/platform/region/condition counts
to populate filter controls from what's actually in the database), `/api/history`
(a single listing's price-point time series).

UI: search box (debounced), console filter (Switch / Switch 2 / both),
condition filter (New / Pre-Owned / both), store dropdown, region dropdown,
in-stock-only checkbox, sortable columns (title/store/price), "load more"
pagination, a collector-health strip (one tile per store, count + status
colour + failure detail), a movers table with an FX-suspect banner when
triggered, region/SW2/pre-owned/out-of-stock tags inline on listing rows.

### CLI / menu

A single interactive menu (`bun run src/menu.ts`, also the default with no
arguments) that reads the database before drawing itself, so the
recommended next action reflects what's actually happened rather than a
fixed tutorial order (the common mistake it exists to prevent: collecting
before probing, which produces a screen of failures that look like broken
code and are really just a store list that was never corrected). Options:
check stores, collect prices, open dashboard, fix a broken store (spawns
`inspect.ts` in a real visible browser window — see Known constraint below),
update exchange rate, register the scheduled task, reset store corrections.
A bare Enter defaults to the suggested action — deliberately *not* allowed
to silently repeat the same probe/collect action that was just run, since
that's a real trap: hitting Enter once to clear a "press Enter to go back"
pause and then Enter again out of habit at the very next prompt used to
silently re-launch a second collection run with zero confirmation.

### Distribution

`build-exe.ps1` compiles a single Windows `.exe` via Bun's own compiler; the
one-shot entry point it runs (`launch.ts`) collects (non-fatally — a failed
collection still opens the dashboard against whatever data already exists,
with the failure visible in the health strip rather than the whole thing
refusing to start), then serves the dashboard, then opens it in the default
browser.

## Not yet built (matches "why it exists" above — these are the actual point, not a footnote)

- **The matcher.** `listing.game_id` is nullable and currently always NULL —
  every listing across every store is its own unrelated row. Fuzzy title
  matching (using the existing `normaliseTitle()` output as a starting
  point) into a canonical `game` row is unbuilt.
- **The alert engine.** No Telegram (or any) delivery exists yet. The
  `movers`/FX-suspect logic is the analytical piece this depends on; nothing
  currently acts on it beyond displaying it on the dashboard.
- **One open, unresolved investigation carried over as-is:** a
  WooCommerce-backed store (DesignInfo) resolves its configured category
  slug to a real numeric term id that reports only 1 product via the API,
  while the same category's real storefront page shows 100+ — meaning
  either the slug in config doesn't actually correspond to the page the
  count was eyeballed from, or something about that store's term/count
  relationship doesn't work the way every other WooCommerce install checked
  so far does. Needs a live re-check against the real page before the
  rewrite either reproduces or fixes it — don't assume either explanation
  without fresh evidence.

## Non-negotiable design decisions (carried over, not stylistic)

- Native currency + native price is the captured fact; INR is *derived* at
  read time from an ECB rate, never captured as if it were the price. A
  store that only ever shows a converted rupee figure (Play-Asia, USD) would
  otherwise make a currency wobble look like a catalogue-wide sale.
- Region is first-class, not a tag — Play-Asia's Asia-English/Asia-Chinese/
  Japan/Western SKUs of the same title are different, non-interchangeable
  products (different disc region/language), not aliases to collapse.
- Condition (New/Pre-Owned) is likewise first-class on the listing, inferred
  from the store's own text rather than assumed per store — a store can
  (and at least one does) sell both out of the same catalogue.
- `listing.game_id` is nullable. Collection and matching are separate,
  independently re-runnable passes — improving the matcher later must never
  require re-scraping data already on disk.
- Filtering/sorting/aggregation for the dashboard happens in the database
  query, never by sorting whatever page of rows the frontend already has —
  "cheapest first" over 100 loaded rows is a different, wrong answer from
  "cheapest first" over the whole table.
- **Never hardcode a per-store numeric limit that encodes a fact about that
  store's catalogue on the day someone looked at it** (a page count, a fixed
  timeout) — those go stale the moment the catalogue changes size, silently
  truncating data with no error. Prefer the site's own real stopping signal
  (an empty page, a disabled/missing "next" control, a page that stops being
  productive) with only a generous, universal, never-store-specific ceiling
  as a last-resort guard against a truly broken loop.
- A store returning fewer rows than it should, or the wrong rows, or the
  right rows with the wrong price, are three *different* bug classes that
  each need different evidence to diagnose (see Hard-won lessons). Don't
  assume "it returned something" means "it returned the right something."

## Hard-won lessons from building the TypeScript version

Each of these cost real debugging time once; the rewrite gets them for free
if it keeps the same shape of fix.

- **Price parsing**: a lone comma with no decimal point anywhere in a price
  string is *always* a thousands separator on these sites ("₹3,599" is three
  thousand five hundred ninety-nine, never 3.599) — a naive "last separator
  wins" heuristic silently divided real prices by ~1000.
- **Category scoping isn't optional for general retailers.** A store that
  also sells other consoles, accessories, camera gear, gift cards, etc. will
  leak all of it through a platform hint unless scoped to its actual games
  category via the store's own category/collection filter — and that
  filter's *value* isn't reliably the slug shown in the URL on every
  install; resolving to the category's real numeric id first and filtering
  by that is what actually works across different store setups.
- **A store can have zero relevant category at all** (no games/accessories
  split, e.g. a camera-and-audio retailer that happens to also carry a
  little Nintendo hardware) — in that case, don't set a platform hint
  either; require an explicit console mention in the title instead, since
  the fallback-to-hint behavior that rescues terse titles on a genuinely
  Switch-only store is exactly what leaks false positives on a general one.
- **Pagination controls that don't change the URL at all exist** — some
  storefronts render page 2+ entirely client-side behind a button click with
  no navigation; naively adding a page-number query parameter can silently
  return page 1's content every time with no error.
- **A "stop paging" signal that's too strict is its own bug.** Requiring
  *exactly* zero new rows (even twice in a row) to conclude a catalogue is
  exhausted breaks the moment a site fills remaining pages with slowly
  reshuffling "related/recommended" filler — it almost never lands on
  precisely zero, so the loop pages on for a long time collecting mostly
  duplicates, which then vanish at dedupe and look like "the run finished
  fine" with a much smaller number than the real catalogue. A proportion-of-
  new-rows threshold, sustained over several pages, is what actually
  distinguishes "genuinely done" from "recycling filler."
- **CSS pseudo-selectors like `:has-text(...)` don't exist for a plain DOM
  `querySelector`** — that's Playwright/jQuery-locator syntax; running it
  through native `querySelector` inside a page context throws, and a caught
  exception there is easy to miss, silently disabling whatever check relied
  on it (this broke every store's out-of-stock detection at once).
- **A store returning *something* isn't evidence it's correct.** A wrong
  price, wrong title, or wrong product sneaking through a classifier gap
  produces a "successful" result with no error to notice — needs an actual
  look at real markup/data to catch, not just a row count. Where a
  structured total genuinely exists (WooCommerce's response header), use it
  instead of inferring one from behaviour.
- **Diagnostics captured on every run (not just failures) are worth the cost
  exactly once, while actively debugging** — leaving that on permanently is
  pure overhead (a full-page screenshot per store per run) once a store is
  actually working.
- **A UI default that silently repeats the last expensive action is a real
  trap, not a hypothetical one.** A menu that suggests "do this again" right
  after finishing it, combined with a blank Enter defaulting to that
  suggestion, means two habitual Enter presses in a row can re-trigger a
  multi-minute network operation with no confirmation and no visible cause.

## Why this stack

- Complements an existing Java/Spring Boot background rather than
  duplicating it — different paradigm (async/await, no inheritance-heavy
  OOP), and FastAPI + Python is currently in very high demand at Indian
  product companies specifically because of LLM/AI feature integration work.
- Everything below is chosen to teach real architecture (explicit API
  contracts, layered structure) rather than to minimize dependencies the way
  the current Bun/TS version does — that constraint doesn't apply here.
- No scheduling. No Windows Task Scheduler, no APScheduler. Every action
  (Check Stores, Collect Prices, Update FX Rate) is a dashboard button that
  triggers on demand — nothing runs unattended in the background.

## The stack

**Language & tooling**
- Python 3.12+
- `uv` — package manager + venv + lockfile (`pyproject.toml`/`uv.lock`); can
  also install/manage the Python interpreter itself
- `ruff` — lint + format in one tool
- `mypy` (or `pyright`) — type checking; FastAPI is built around type hints,
  this isn't optional tooling bolted on after the fact

**Web framework & API**
- FastAPI — routes, request/response validation
- Pydantic — ships with FastAPI, defines schemas
- Uvicorn — ASGI server that runs it

**Data layer**
- SQLite via the stdlib `sqlite3` module — no ORM. Keeps the existing
  project's philosophy (filtering/sorting/aggregation happens in SQL, not
  app code) and is more directly interview-relevant than an ORM abstraction.
  (SQLModel/SQLAlchemy noted as a later swap-in if this ever needs to feel
  more "production-typical.")

**Scraping / data collection**
- `httpx` — async HTTP client for the Shopify/WooCommerce-style stores
- Playwright for Python (official first-party bindings) — for JS-heavy
  stores and the inspect/profile-building flow
- `asyncio` — concurrency for "fetch N stores politely, rate-limited per
  host, with separate HTTP/browser pools," via tasks + semaphores instead of
  a manual host-queue

**Real-time dashboard updates**
- Server-Sent Events via FastAPI's `StreamingResponse` — every button
  streams its live output back to the page while it runs (replacing the
  current version's plain stdout console log as the only feedback
  mechanism)

**Frontend**
- Jinja2 — server-renders HTML
- htmx — buttons trigger a request, the response fragment swaps in; no
  build step, no virtual DOM. Keeps the project teaching FastAPI/Python
  architecture deeply instead of also teaching a new frontend framework at
  the same time.
- Plain CSS, same look as the current dashboard

**Testing**
- `pytest` + FastAPI's `TestClient` (built on httpx)

**Distribution (later, not day one)**
- PyInstaller or Nuitka if this ever needs to be a single .exe

## Known constraint carried over from the current version

"Fix a broken store" will always need to pop a separate real browser
window — Playwright needs an actual window for a human to click inside,
which can't happen inside the dashboard's own browser tab. Every other
button can genuinely live entirely on the page with live streamed output.

## Open questions for when this actually gets built

- Folder/module structure (routers, services, repository layer).
- Exact shape of the SSE progress events (per-store lines vs. structured
  JSON events the frontend renders into rows) — needs to carry at least
  everything `run_store.detail` carries today (status, count, timing, a
  free-text reason), plus whatever a live per-page "N so far" progress line
  needs.
- Whether the element-picker approach in the current `inspect.ts` carries
  over as-is or gets rebuilt using Playwright for Python's idioms.
- Whether the three different completeness mechanisms (WooCommerce header,
  Shopify page-size signal, browser best-effort text scrape) stay adapter-
  specific as they are now, or get unified behind one shared "confidence"
  concept the dashboard can display consistently across store kinds.
