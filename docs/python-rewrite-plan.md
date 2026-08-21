# switch-tracker — Python/FastAPI rewrite plan

Not implemented yet. Captured here so it doesn't get lost — see the
conversation that produced this for the reasoning behind each choice
(target: Indian product companies, already have Java/Spring Boot, want a
second stack that's genuinely different rather than another OOP language).

## What this actually is — read this before touching adapters

A **personal, local** price tracker for one person's own buying decisions —
not a product, not multi-tenant, no accounts. It watches Indian retailers
(plus Play-Asia as an import comparison) for **physical Nintendo Switch /
Switch 2 cartridges** and builds price history over time, with the eventual
goal of catching real sales as they happen instead of missing them.

**Hard scope boundary, enforced at classification, not at data-entry:**
games only. Consoles, Joy-Cons/Pro Controllers, cases, screen protectors,
amiibo, cooling pads, eShop codes, gift cards, Switch Online memberships,
and repair/mod/"game loading" services are all explicitly excluded, even
when a store files them under the same category as its actual games. Games
for *other* consoles (PS4/PS5/Xbox/PC/3DS/etc.) are excluded too, even on
stores that are hinted "this is a Switch-only shop" — an explicit console
name in a title always wins over a hint that says otherwise. The rewrite
must keep an equivalent classifier; scraping without it just relabels
"everything this store sells" as "Switch games."

**Why it exists at all — the two pieces that haven't been built yet are the
actual point:**
1. **The matcher** (not built) — the same cartridge at four stores is
   currently four unrelated rows. Fuzzy-matching listings into one canonical
   "game" is what turns this from "a list of things stores sell" into "where
   is the cheapest copy of X right now."
2. **The alert engine** (not built) — the reason price *history* matters at
   all: detect a genuine price drop on a listing against its own trailing
   median, and suppress it when it's actually the whole store repricing or
   the rupee moving against a foreign currency on the same day across many
   listings at once (a currency move is not a sale). Telegram was the
   originally intended delivery channel. Everything about storing native
   price + derived INR + the FX rate date exists specifically to make this
   possible later — don't lose that data shape in a rewrite for convenience.

**Design decisions carried over as non-negotiable, not stylistic:**
- Native currency + native price is the captured fact; INR is *derived* at
  read time from an ECB rate, never captured as if it were the price. A
  store that only ever shows a converted rupee figure (Play-Asia, USD) would
  otherwise make a currency wobble look like a catalogue-wide sale.
- Region is first-class, not a tag — Play-Asia's Asia-English/Asia-Chinese/
  Japan/Western SKUs of the same title are different, non-interchangeable
  products (different disc region/language), not aliases to collapse.
- A listing's `game_id`-equivalent is nullable. Collection and matching are
  separate, independently re-runnable passes — improving the matcher later
  must never require re-scraping data already on disk.
- Filtering/sorting/aggregation for the dashboard happens in the database
  query, never by sorting whatever page of rows the frontend already has —
  "cheapest first" over 100 loaded rows is a different, wrong answer from
  "cheapest first" over the whole table.

**Operating philosophy — this shaped nearly every bug found in the current
version, so it should shape the rewrite from day one instead of being
relearned the hard way:**
- The tool should keep itself correct with minimal manual maintenance:
  auto-detect each store's real API instead of hand-maintained guesses,
  auto-discover the right category to scope a mixed-catalogue store to
  instead of trusting a platform-only hint, and give a human a fast,
  purpose-built way to fix a broken selector by clicking rather than reading
  minified source.
- **Never hardcode a per-store numeric limit that encodes a fact about that
  store's catalogue on the day someone looked at it** (a page count, a
  fixed timeout) — those go stale the moment the catalogue changes size,
  silently truncating data with no error. Prefer the site's own real
  stopping signal (an empty page, a disabled/missing "next" control)
  with only a generous, universal, never-store-specific ceiling as a
  last-resort guard against a truly broken loop.
- A store returning fewer rows than it should, or the wrong rows, or the
  right rows with the wrong price, are three *different* bug classes that
  each need different evidence to diagnose — see "hard-won lessons" below.
  Don't assume "it returned something" means "it returned the right
  something."

## Hard-won lessons from building the TypeScript version

Each of these cost real debugging time once; the rewrite gets them for
free if it keeps the same shape of fix:

- **Price parsing**: a lone comma with no decimal point anywhere in a price
  string is *always* a thousands separator on these sites ("₹3,599" is
  three thousand five hundred ninety-nine, never 3.599) — a naive "last
  separator wins" heuristic silently divided real prices by ~1000.
- **Category scoping isn't optional for general retailers.** A store that
  also sells other consoles, accessories, camera gear, gift cards, etc.
  will leak all of it through a platform hint unless scoped to its actual
  games category via the store's own category/collection filter — and that
  filter's *value* isn't reliably the slug shown in the URL on every
  install; resolving to the category's real numeric id first and filtering
  by that is what actually works across different store setups.
- **A store can have zero relevant category at all** (no games/accessories
  split, e.g. a camera-and-audio retailer that happens to also carry a
  little Nintendo hardware) — in that case, don't set a platform hint either;
  require an explicit console mention in the title instead, since the
  fallback-to-hint behavior that rescues terse titles on a genuinely
  Switch-only store is exactly what leaks false positives on a general one.
- **Pagination controls that don't change the URL at all exist** — some
  storefronts render page 2+ entirely client-side behind a button click with
  no navigation; naively adding a page-number query parameter can silently
  return page 1's content every time with no error.
- **CSS pseudo-selectors like `:has-text(...)` don't exist for a plain DOM
  `querySelector`** — that's Playwright/jQuery-locator syntax; running it
  through native `querySelector` inside a page context throws, and a caught
  exception there is easy to miss, silently disabling whatever check relied
  on it (this broke every store's out-of-stock detection at once).
- **A store returning *something* isn't evidence it's correct.** A wrong
  price, wrong title, or wrong product sneaking through a classifier gap
  produces a "successful" result with no error to notice — needs an actual
  look at real markup/data to catch, not just a row count.
- **Diagnostics captured on every run (not just failures) are worth the
  cost exactly once, while actively debugging** — leaving that on
  permanently is pure overhead (a full-page screenshot per store per run)
  once a store is actually working.

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
- `uv` — package manager + venv + lockfile (`pyproject.toml`/`uv.lock`);
  can also install/manage the Python interpreter itself
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
  host," via tasks + semaphores instead of a manual host-queue

**Real-time dashboard updates**
- Server-Sent Events via FastAPI's `StreamingResponse` — every button
  streams its live output back to the page while it runs

**Frontend**
- Jinja2 — server-renders HTML
- htmx — buttons trigger a request, the response fragment swaps in; no
  build step, no virtual DOM. Keeps the project teaching FastAPI/Python
  architecture deeply instead of also teaching a new frontend framework
  at the same time.
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

- Folder/module structure (routers, services, repository layer)
- Exact shape of the SSE progress events (per-store lines vs. structured
  JSON events the frontend renders into rows)
- Whether the element-picker approach in the current `inspect.ts` (see the
  browser-store fixing work) carries over as-is or gets rebuilt using
  Playwright's Python API idioms
