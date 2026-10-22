# switch-tracker — walkthrough

**What it does:** visits 23 online shops (22 Indian retailers plus Play-Asia for imports),
finds every physical Nintendo Switch and Switch 2 game they sell, records the price, and
does it again later so you can see what changed, where each game is cheapest, and when a
game you watch drops under your target.

| You want to… | Read |
|---|---|
| understand the whole thing | §1, then §3 |
| change one thing | §1.2, Appendix A, then the §3 or §4 section for it |
| fix something that isn't working | [`troubleshooting.md`](troubleshooting.md) |
| a quick answer | §7, the FAQ |
| set it up | the [README](../README.md) |

Unfamiliar words are in Appendix B.

---

## 1. The big picture

### 1.1 What it is

One Python program, started with one command. It gives you:

- a **dashboard** at `http://127.0.0.1:4173`, reachable only from your own PC;
- one **database file** that grows a little every time prices are collected.

No server to deploy, no account, nothing in the cloud.

### 1.2 Where the code lives

```
src/switch_tracker/
├── __main__.py      The front door: picks a role from the command line (§1.4)
├── paths.py         Every writable path is decided here, and only here
├── settings.py      Port, headful browser, collect-on-launch
├── selection.py     "Collect only these stores", shared by dashboard and worker
├── schedule.py      collect-now, the daily task, scheduled-run notifications (§3.10)
├── spike.py         Self-check for things that break only in the packaged .exe
├── resources.py     Reads bundled files (templates, CSS, JS)
├── config/          stores.py (the shop list) and overrides.py (corrections) (§3.1)
├── core/            models, db, http (polite client), parse (classifier and prices),
│                    skus, matcher, concurrency
├── adapters/        How to read a shop: shopify.py, woocommerce.py, browser/ (§3.2, §3.6)
├── services/        The jobs: collect, probe, fx_refresh, inspect, plus their workers
├── fx/rates.py      USD→INR exchange rates (§3.4)
├── events/          Live progress: the worker writes rows, the dashboard reads them
└── web/             The dashboard: app, guard, queries, runs, watchlist, routers/,
                     templates/, static/ (app.js, app.css)
```

Outside `src/`:

| Path | What |
|---|---|
| `tests/` | 752 tests (§A.1) |
| `scripts/` | Live-site and data checks: `check_stores.py`, `scrape_check.py`, `category_check.py`, `diagnose_extraction.py`, `check_data.py` ([troubleshooting.md](troubleshooting.md) §2–3) |
| `START.bat`, `setup.ps1`, `run.ps1` | What a Windows user double-clicks |
| `BUILD-EXE.bat`, `switch_tracker.spec`, `packaging/` | Building the `.exe` (§3.11) |
| `docs/python-rewrite-*.md` | The plan and designs written before the code |

If you read only three files: `__main__.py` (what the program is), `core/models.py` (the
vocabulary), `services/collect.py` (the main job).

### 1.3 Where your data lives

Not in the project folder. Everything goes to one data directory:

| Platform | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\switch-tracker\` |
| macOS / Linux | `~/.local/share/switch-tracker/` |
| Anywhere | set `TRACKER_DATA_DIR` |

| File | Holds | Safe to delete? |
|---|---|---|
| `tracker.db` (+ `-wal`, `-shm`) | All price history. Three files, one database (§2.3) | Only if you mean it; delete all three together |
| `backups/` | A copy after every collection, newest 7 kept | Yes. To restore, close the app and copy one over `tracker.db` |
| `watchlist.local.json` | Watched games and targets (§4.3) | Only if you mean it |
| `matches.local.json` | Your title aliases (§3.9). You create it | Yes |
| `stores.local.json` | Corrections from **Check stores** (§3.1) | Yes, rebuilt by Check stores |
| `profiles.local.json` | Selectors saved by the click-to-pick tool (§3.11) | Yes, but you re-pick them |
| `settings.json` | Port, headful, collect-on-launch | Yes, defaults return |
| `run.lock` | Process id of a running worker (§3.8) | Yes, when nothing runs |
| `diagnostics/` | Screenshots, HTML and redirect traces from failing stores | Yes, always |

The JSON files survive deleting `tracker.db`, on purpose.

### 1.4 The one design idea: the dashboard never scrapes

Scraping takes minutes and a browser can hang. The dashboard must stay responsive. So the
program is one executable with several roles, picked by its first argument:

| Command | Role |
|---|---|
| `serve` (default) | the dashboard |
| `collect`, `probe`, `fx`, `inspect` | **workers**: collect prices, detect shop platforms, refresh rates, open the click-to-pick tool |
| `match`, `collect-now`, `schedule`, `spike` | for you: regroup games, collect from the command line, manage the daily task, self-check |

When you press a button, the dashboard **starts a second copy of itself** as a worker and
goes straight back to serving pages. The two never talk directly: the worker writes to
the database, and the dashboard reads it.

```
 browser ──▶ DASHBOARD (serve) ──spawns──▶ WORKER (collect)
                 │ reads                       │ writes
                 └───────▶ tracker.db ◀────────┘
```

What this buys you:

- **Close the tab:** the collection carries on.
- **Refresh:** you rejoin the running job, you don't start a second one.
- **Restart the app:** the progress replays, because it is on disk.

`tests/test_import_boundary.py` fails the build if the dashboard ever imports scraping
code, so this can't erode. That is also why some imports sit inside functions
(Appendix A.3).

### 1.5 One press of *Collect prices*

1. `app.js` posts to `/actions/collect` (with `?only=a,b` for selected stores).
2. `web/routers/actions.py` rejects unknown store ids with a 404 *before* a run exists.
3. `web/runs.py` (`RunLauncher.start`) clears any dead run, refuses if one is active
   (409), inserts a `run` row, spawns `collect --run-id N`, and writes `run.lock`.
   The dashboard is done in milliseconds.
4. The worker (`services/collect_worker.py`) loads the store list and launches Chromium
   only if a selected store needs it.
5. `services/collect.py` refreshes the exchange rate once, then runs the stores in two
   pools: **8 feed stores** at once, with a **360 s** deadline each, and **4 browser
   stores** at once, with **1,500 s** each.
6. Each store is fenced: a timeout or crash becomes *that store's* failure, recorded in
   `run_store`. The other stores carry on.
7. Results are saved: the listing is upserted, and a price point is always appended (§3.7).
8. Matching regroups the games (§3.9), the run is marked finished, and a backup is made.
9. All along, the worker writes `run_event` rows. The browser has a stream open, and the
   dashboard forwards each row as it lands (§3.8).

---

## 2. The tech stack

### 2.1 The choices

| Layer | Choice | Rejected | Why |
|---|---|---|---|
| Language | Python 3.12 | staying on TypeScript | Learning a second stack; the HLD records this as a non-technical choice |
| Packages | uv | pip, Poetry | Fast, and records exact versions |
| Web | FastAPI + uvicorn | Flask, Django | Async; validates input from type hints; streams |
| HTML | Jinja2 | string building | Escapes HTML by default |
| Database | SQLite, raw SQL | PostgreSQL, an ORM | One file and one user; the SQL *is* the logic |
| HTTP | httpx | requests | Async |
| Browser | Playwright (Chromium, ~400 MB download) | Selenium, BeautifulSoup | Runs the page's JavaScript and can call back into Python |
| Front end | Plain JS and CSS | React | No build step for one page |
| Live progress | Server-Sent Events | polling, WebSockets | One-way, reconnects by itself |
| Packaging | PyInstaller, one folder | one file, Docker | Has to ship a browser |
| Checks | pytest (+ xdist), ruff, mypy strict | — | Fixtures, one fast linter, types checked before running |
| Rates | Frankfurter (ECB) | paid APIs | Free, no key, dated rates |

Two local quirks:

- **`uv.lock` is not committed.** It was generated behind a private package mirror, so it
  would point everyone else at URLs they can't reach. `pyproject.toml` bounds the versions
  instead (see `.gitignore`).
- **The HTTP client is polite**: one request at a time per shop, 1.2 s apart
  (`core/http.py`). These are small shops.

### 2.2 Local only, and the cross-site guard

The server binds `127.0.0.1`, so other machines can't reach it. Other *websites* still
can, through your browser. `web/guard.py` blocks two attacks:

| Check | On | Stops |
|---|---|---|
| `Host` must be `127.0.0.1:<port>` or `localhost:<port>` | every request | DNS rebinding |
| `Origin` must match the Host and be present; `Sec-Fetch-Site`, if sent, must be `same-origin` | every POST/PUT/DELETE | a web page making your browser press buttons |

The rule that follows from this: **a GET never changes anything.** A test fires forged
requests at every state-changing route, so new routes are covered automatically. There
is no switch to turn the guard off for tests.

### 2.3 SQLite in WAL mode

`core/db.py` turns on WAL so the dashboard can read while a worker writes, with a 5 s
`busy_timeout`. WAL is why the database is three files.

---

## 3. Collecting prices

### 3.1 Stores and corrections

`config/stores.py` lists 24 shops. 23 are enabled: 11 WooCommerce, 2 Shopify and 10 browser.
Zozila is disabled because it is a gift-card marketplace. Each entry says how to read the shop
(`kind`), its currency, and usually which categories to fetch (`collections` for feeds,
`search_urls` for browser stores). `tier` only orders the store list on the dashboard.

- **`kind` is a guess, and probe corrects it.** **Check stores** runs `probe`, which asks
  each shop what it runs on and writes corrections to `stores.local.json`. It never edits
  `stores.py`: a tool must not rewrite the code it imports. The two are merged when read,
  and a correction for a store that no longer exists is ignored.
- **Scope to categories.** Fetching only a shop's games categories keeps the classifier's
  job small.
- **HG World is the exception.** Its firewall refuses the Store API's category filter by
  every route, so it is fetched whole (about 1,700 products), and it has **no
  `platform_hint`**. With the classifier as the only filter, a hint would turn its terse
  accessory titles into games. designinfo, an electronics shop, has no hint for the same
  reason.

### 3.2 Three ways to read a shop

| Kind | How | Knows it got everything? |
|---|---|---|
| `SHOPIFY` | `/products.json` | Inferred: a short page is the last |
| `WOOCOMMERCE` | The public Store API | Yes: `x-wp-total` gives the count |
| `BROWSER` | Drives a real Chromium | Best effort: scraped "showing X of Y" text |

Every adapter returns one of three outcomes (`core/models.py`):

- `Ok`.
- `Partial`: it got rows, but some are probably missing, and it names the cause.
- `Failed(reason)`: the reason is what you see on the store tile, so it names the real cause
  (`HTTP 403`, `invalid JSON`), never a misleading "no products".

WooCommerce details worth knowing:

- Names arrive HTML-encoded (`&#8211;`) and are decoded.
- A page that times out is retried as 4 pages of 25.
- If that fails, the page is skipped while the shop's count says more products exist.
  Two failures in a row stop the walk.
- The walk stops itself at **300 s** and keeps what it has, safely inside the 360 s deadline.
  A test checks the budget stays below the deadline.

### 3.3 Is it a game?

`core/parse.py` `classify()` sorts every product into **game**, **hardware**,
**accessory**, **digital** or **service**. Only games are kept. Exclusions run *before*
the platform check, because "Nintendo Switch Pro Controller" says "Switch".

The rules, each one added because a real title broke the previous version:

| Rule | Why |
|---|---|
| Exclusions read the **title** only, not tags or categories | consolegarage tags every game "SWITCH OLED". Reading tags dropped 58 of its 92 games |
| The **title's console** beats the category's | HG World files Switch 1 games under Switch 2 |
| Another console beats a bare "switch" | "The Crew 2 PS4 \| … \| Seamless Switch" is a PS4 game |
| "Lite" and "OLED" together mean compatibility, not a console | "Mario Kart 8 Deluxe (Switch/Lite/OLED)" is a game |
| Joy-Con and DLC count only in the name, before the first `\|` | "Nintendo Switch Sports \| Joy-Con Compatible" is a game |
| What a box *includes* is not what it *is*: "(Includes …)" and brackets naming a game card are ignored | "Ring Fit Adventure (Motion controller + Gamecard)" is a game |
| A bare console name is hardware | "Nintendo Switch 2 (US)" is the console |
| "Bundled with" means a console bundle; "bundle with" doesn't | Flipkart writes "Bundle with Six Titles" into a real game |
| Named exclusions only: joysticks, wheels, projectors, bags, apparel, Pokémon GO Plus | Broad words like "gamepad", "accessory", "mouse" and "throttle" appear in real game titles |

**The store hint.** A Switch-only shop can sell "Hogwarts Legacy" with no console in the
title. `platform_hint` says "assume Switch when the text names no console". It's applied
last, so a title naming another console is never turned into a Switch game.

To see what a feed store dropped and why: `check_stores.py <store> --rejected`.

### 3.4 Prices and exchange rates

Indian shops write prices many ways, and the three real bugs here all produced a
*believable* number instead of an error:

| Input | Was read as | Fix |
|---|---|---|
| `Rs. 4499` | ₹0.45 (the dot of "Rs.") | Remove currency words first |
| `3,599` | ₹3.60 | A comma with no dot is a thousands separator |
| "Supe**rs**tars 3 modes" | ₹3 | `Rs`/`INR` must be whole words |

So `parse_price` returns `None` on failure, never `0`.

Exchange rates refresh once at the start of a run, so a whole run uses one rate. If no
rate exists, `to_inr()` stores **NULL**, never the dollar figure as rupees: a missing
number can be fixed later, a wrong one can't be told apart from a real price.

### 3.5 SKUs: telling products apart

Each listing needs an id that stays the same across runs (`UNIQUE(store_id, sku)`).
`core/skus.py` uses the Amazon ASIN, Flipkart's `pid`, or the last part of the URL path.
It ignores the query string, because tracking parameters would mint a new product every run.

The opposite failure: feed stores use the shop's own SKU, which is typed by hand.
consolegarage gave seven games the SKU `CGGM`, which merged seven price histories into one.
`one_product_per_sku` now swaps a shared SKU for each product's own id. A unique SKU is
kept, so existing histories carry on.

### 3.6 Browser stores

**Reading a page** (`adapters/browser/extract.py`) tries four layers, most durable
first, and reports which one worked:

1. JSON-LD (structured data for search engines)
2. The page's own data (Flipkart's `__INITIAL_STATE__`, searched by shape, not by path)
3. CSS selectors from the store's profile
4. A ₹ figure anywhere in the card

A cut title ("…Nintendo Swit...") is replaced by the full `title` attribute when that
starts with it.

**Stopping** (`pagination.py`): stop when under 15% of a page is new, for 4 pages in a
row. Late pages are padded with recycled "related" items, so "nothing new" rarely
happens exactly.

**Turning pages by clicking** (`adapter.py`): a click must *prove* the results changed,
by comparing a fingerprint of the result cards before and after. A pager selector once
clicked a footer link containing ">", returned success, and re-read page 1 forever. For
Play-Asia the cards are scoped to the results grid (`#pa-modern-products-container`).
Otherwise loading placeholders made a page look turned before it loaded. Deep pages get
20 s to load.

**Flipkart's struck pages.** Flipkart sometimes answers a valid page with a redirect to
itself until Chromium gives up. Retrying the same request doesn't help, so the adapter:

1. waits 8 s and retries once in a fresh tab;
2. if that fails, skips the page and carries on;
3. stops after 3 failures in a row;
4. after the walk, retries every skipped page once more.

Only pages still missing make the run `Partial`. Each failed navigation writes
`diagnostics/flipkart-p<N>-navigation.json`.

**Per-shop quirks are data, not code.** `profiles.py` holds about 25 `StoreProfile` fields:

- selectors and the `ready` wait;
- `next_page`, `scroll_passes`, `wait_until`;
- `cookies` (Play-Asia's rupee pricing lives in its session);
- `default_region` (GamePookie and Play-Asia are importers, so UNKNOWN, not IN);
- `default_condition` (everything at CeX is pre-owned);
- `condition_from_context` (GameLand puts "Pre-owned" in a badge);
- URL filters, page caps and time budgets.

The only store-specific code is Flipkart's: reading its page data, and the struck-page
recovery.

### 3.7 Saving and reading the data

```
store ──< listing ──< price_point      the history (append only)
              └── game_id ──> game      filled by the matcher (§3.9)
run ──< run_store, run_event           what happened, live progress
game_redirect                          old match keys → new (§3.9)
```

- **Upsert the listing, always append a price point.** History is never edited, and
  `first_seen` is never overwritten.
- **Only `http`/`https` URLs are saved**, and `app.js` checks again (`safeHref`), so a
  `javascript:` link from a shop can never run on the dashboard.
- **The newest price** is found per listing with an indexed subquery, not a window
  function over all history. The old form went from 1 s to 40 s as history grew; this
  one stays around 50 ms. A frozen copy of the old query in `test_queries.py` proves
  the rows are identical.
- **Change %** compares the newest and second-newest price. Moves of 1% or less
  (`MIN_CHANGE_PCT`) count as no change. Sorting by Change shows only real movers, so the
  count drops.
- **In stock means still listed.** A listing counts as buyable only if no fully
  successful run of its store has happened since its latest price (`_IN_STOCK`). A
  product the shop removed stops winning "best price".

### 3.8 One run at a time, live progress

Three guards stop two collections overlapping (`web/runs.py`):

1. a check for an unfinished run;
2. a unique index allowing only one unfinished run (`idx_run_active ON run((1))`), which
   survives races and crashes;
3. `run.lock` with the worker's process id, which catches a second copy of the app.

The greyed-out button is cosmetic.

**Progress** is rows in `run_event`, each with a sequence number. The dashboard streams
them as Server-Sent Events. A reconnecting browser sends the last number it saw, so
nothing is lost or repeated. Progress writes can't fail a collection.

**The automatic collection** happens only when the database has never collected (no
`run_store` rows). It isn't stored as a flag, so a deleted database bootstraps itself again.

### 3.9 Matching games across shops

`core/matcher.py` turns a title into a **match key**: lowercase, accents folded,
apostrophes and filler words dropped, console and region words removed.
"Pokémon Legends: Z-A (Nintendo Switch 2)" and "Pokemon Legends Z-A - Switch 2" both
become `pokemon legends z a`. Same key and platform means the same game.

- **It errs towards splitting.** A missed merge shows as two rows and is fixed with an
  alias. A wrong merge silently mixes two games' prices. So single letters stay in
  ("Z-A" vs "Z"), as do numbers and editions. The tests pin must-not-merge pairs as
  carefully as must-merge ones.
- **Brackets keep the product, lose the notes.** `[Definitive Edition]` and `(Boxed
  Code)` stay in the key; region, language and store notes inside brackets (`(Europe)`,
  `[AT-PEGI]`, `(tbd)`, `(Import)`, `(Includes …)`) don't. `™` and the physical format
  ("Game Card", "Game-Key Card") never count.
- **Amazon's publisher prefixes** ("Warner Bros Interactive Entertainment …") are
  stripped from the start of a title. Names real titles also start with (Sega, Capcom,
  Atlus, Activision and others) come off only when **another listing confirms** the
  rest: "Sega Sonic Forces" joins "Sonic Forces" because a shop sells "Sonic Forces",
  while "Sega Genesis Classics" stays whole.
- **The same words in another order** are one game ("FC 26 EA Sports", "EA Sports FC
  26"), except around "vs", where order is the game.
- **The platform is re-read from the title** during matching, the same way a collection
  reads it, so rows saved under older rules are repaired: Play-Asia's `NSW2™`, and
  "Switch™ 2 Edition" stored as Switch 1.
- **Marketing after a `|`** is dropped only if the part before it names the console *and*
  the rest names no edition, number or variant. "Fire Emblem | Engage" stays whole.
- **Titles that key to nothing** (the console's bare name, Japanese-only text) are never
  grouped. `check_data.py` lists them.
- **What it won't do: fuzzy matching.** "One or two extra words" is also how a Deluxe, a
  Divine Edition or a sequel looks ("Ben 10" vs "Ben 10 Power Trip"). Those pairs are
  listed by `check_data.py --review` for a person to settle with an alias.
- **Regions**: stored as separate games, but the Games view groups across regions, since
  an import is the comparison.
- **Re-keying leaves a forwarding address.** When a key disappears and all its listings
  moved to one new key, `game_redirect` records it, so a watch on the old key still
  finds its game.
- **Aliases** go in `matches.local.json` as `{"one title": "the other title"}`, pasted
  from the dashboard. Then run `switch-tracker match`.

`rematch` reads only stored columns, so **improving the matcher never needs a
re-scrape**. It runs after every collection, once at startup if games are missing, and
on `match`.

The **best offer** is the cheapest *buyable* copy: in stock ranks first. One `MIN()`
in `games()` picks it, and SQLite's bare-column rule returns that same row's store and URL.
A second `MIN`/`MAX` in that query would break this silently.

### 3.10 Collecting on a schedule

```
switch-tracker schedule --at 07:30    daily Windows task (prints a cron line elsewhere)
switch-tracker schedule --off         remove it
switch-tracker collect-now            what the task runs; fine by hand too
```

From source, prefix with `uv run python -m`.

- `collect-now` goes through the same `RunLauncher` as the button, so every guard in §3.8
  applies. It waits for the run to finish, so Task Scheduler's history is true.
- **A missed day catches up.** The task is registered from XML with `StartWhenAvailable`.
  It skips only if a *successful* collection has finished since that day's slot.
- It refuses with exit code 2 if stores were never checked. `schedule --at` refuses while
  `TRACKER_DATA_DIR`/`TRACKER_DB` are set, because the task wouldn't see them.
- **Notifications with no tab open:** after a scheduled run, each *new* watchlist hit
  shows a Windows notification. Game titles are passed as escaped data, never as code.
- The dashboard shows the schedule read-only (`/api/schedule`). Creating OS tasks from a
  web endpoint is exactly what the guard (§2.2) must never allow.

### 3.11 Repair tools and the .exe

- **Probe** (**Check stores**) detects each shop's platform by the *shape* of its reply
  (a JSON object with a `products` list is Shopify), never by a substring: a WordPress
  404 page once passed as Shopify. If a shop can't be reached, nothing is written, since a
  network failure says nothing about the shop. **Reset corrections** clears
  `stores.local.json`.
- **Inspect** (**Fix a broken store**) opens a visible browser. You Alt+click a product
  card, then its title, price and link. Each pick is scored before saving ("in 88% of
  sampled cards").
- **The .exe** bundles Chromium. Every writable path goes through `paths.py`, and bundled
  files through `importlib.resources`, so packaged and source runs behave the same.
  `switch-tracker spike` checks TLS, templates, the web server and Playwright the same
  way in both.

---

## 4. The dashboard

One page, built to answer two questions in seconds: **is the collector healthy, and did
anything get cheaper?** It is three files: `templates/index.html`, `static/app.css` and
`static/app.js`.

### 4.1 Layout, top to bottom

1. **Top bar**, sticky: run status and **Collect prices**.
2. **Actions**: everyday ones on the left; diagnostic and destructive ones pushed right,
   and **Reset corrections** asks first.
3. **Stats strip**: four figures.
4. **Watchlist** (§4.3): above the collector, because a hit matters more than a health tile.
5. **Collector**: one line per store, failures first, with a second line only for a store
   worth investigating. The schedule status sits under its heading.
6. **Progress**: appears during a run and stays afterwards with the outcome. The bar is
   indeterminate until a store finishes, since a fake percentage is worse than none.
7. **Moved since last run**: six rows, **Show all**, and a store filter built from stores
   that actually moved.
8. **The table**: Games, or Every listing.

### 4.2 Games and Every listing

- **Games** (default): one row per game, with its best price and store, an offer count,
  and **☆ Watch**.
  - The row is named after a *new* copy's title, not the cheapest (often pre-owned) one.
  - Under the price, "lowest ₹X" or a **lowest ever** tag (needs 2+ collections).
  - When sorted by price, a separator marks where the out-of-stock games start.
- **Every listing**: one row per shop listing, with a Change column.
- **▸ expands a row** in place: a game shows its offers, using the same filters; a
  listing shows its price history as a time-scaled line, plus a sentence a screen reader
  can read.
- **Sorting and Load more go to the server**: re-sorting the 100 rows on screen would
  give a wrong "cheapest". Load more appends without losing your place, and late replies
  are dropped.

### 4.3 The watchlist

- **☆ Watch** a game, then type a target price. It saves when you leave the box, and a
  note confirms it. Unwatching offers **Undo** for 12 seconds, target included.
- **Any / New only** per game: *New only* ignores pre-owned copies for the price, the
  stock check and the lowest-ever figure alike.
- **All / India only** per game: *India only* leaves out shops that ship from abroad
  (`ships_from_abroad` in `config/stores.py`; today only Play-Asia). Their rupee price is
  before customs and shipping, roughly 30% more, so it would look cheapest and set off
  alerts it shouldn't. It goes by where the shop ships from, not the game's region: an
  Indian importer's Japanese copy has already paid duty, so it counts.
- **Click a watched game's name** to see every offer for it in **Every listing**, at every
  shop, filtered by its game key (not a text search, so differently spelled copies are
  included). It shows as a removable "game" chip and survives refresh.
- **A hit** means the best *in-stock* offer is at or under target. Hits sort first, change
  the tab title, and show a desktop notification once each while a tab is open. A
  scheduled run notifies even with no tab (§3.10).
- **Stored in `watchlist.local.json`**, keyed by game key and platform, not by database id,
  so it survives a new database and matcher changes. Watches resolve through aliases and
  redirects (§3.9).
- The file is written under a lock, through a temporary file and a rename. A file the app
  can't read is set aside as `.json.bad-<n>`, never overwritten.

### 4.4 Filters

- Search, console, region, store, condition and stock. Active filters show as removable chips.
- Facet counts follow the *other* active filters. A facet ignores its own filter, so you can
  still widen a selection.
- **Filters live in the URL**, so refresh and bookmarks work. Only known values are read
  back. Paging isn't stored there.
- `/` focuses search, and Escape clears it.

### 4.5 Design and accessibility

- Every size, colour and radius comes from tokens in `app.css` `:root`. Darker surfaces
  look recessed and lighter ones raised, so depth needs almost no shadows.
- **Status is never colour alone**: ✓ ✕ ▲ glyphs, plus the word. A price drop reads `▼23.1%`.
  `--drop` and `--rise` are named for meaning, because on a price tracker "down" is good.
- Measured, not assumed:
  - every text node passes contrast;
  - control borders reach 3:1;
  - Tab reaches everything, with a visible focus ring;
  - nothing scrolls sideways from 1920px down to 320px;
  - sorting uses real buttons with `aria-sort`;
  - ▸ is a button with `aria-expanded`.
- Not done on purpose: gradients, an icon set, a light theme, decorative animation.
  The one animation, the run dot, respects reduced motion.

---

## 5. Principles that recur

1. **The dangerous failure is a plausible number.** ₹0.45, ₹3.60, dollars stored as
   rupees: none of them raised an error. So `None` is returned instead of a guess,
   `inr_price` can be NULL, and adapters return `Failed(reason)`, not an empty list.
2. **When unsure, write nothing.** Probe writes no correction for an unreachable shop. The
   matcher splits rather than merges. The redirect table records nothing for an ambiguous
   re-key.
3. **Enforce design with tests.** The import boundary, time budget under the deadline,
   must-not-merge pairs, and the frozen query oracle.
4. **Per-shop differences are data, per-shop mechanisms are code.** Profiles hold the
   data. Only Flipkart has code of its own.
5. **Comments record the bug that caused the rule**, so nobody "simplifies" it back.

---

## 6. Not built yet

- **Detected deals** (a drop against a game's own usual price). Dropped for now: the
  lowest-ever tag answers "is this a good price?" without the risk of a false deal.
- **A read-only copy on the internet** and a phone layout. Waiting on a hosting decision.
- **Back/forward between filter states** (`pushState`). Only if wanted.
- **Two prices in one string.** `parse_price("MRP ₹4,499 ₹3,999")` glues them into
  44993999. No current profile is known to produce such a string, and `price_looks_wrong`
  flags anything outside ₹299–₹12,000, but a selector pointed at a whole card could produce
  one.

---

## 7. FAQ

**Does closing the browser tab stop a collection?**
No. The collection runs in its own process (§1.4). Reopen the page and you rejoin it.

**Does `check_stores.py` save anything?**
No. It tests that each shop still scrapes, then discards the results. Only **Collect
prices**, `collect-now` and the scheduled run save. Run `check_data.py` after one of those.

**Why does one game show as two rows in Games?**
The shops spell it differently enough to make different keys. That's deliberate, since
splitting is the safe mistake (§3.9). Add an alias to `matches.local.json` and run
`switch-tracker match`.

**If I watch a game, which listing does it watch?**
All of them. A watch is on the **game** (its match key and platform), not on one listing.
"Pokemon Violet (Switch)", "Pokemon Violet for Nintendo Switch", "Pokémon Violet -
Nintendo Switch" and a pre-owned copy all key to `pokemon violet`. They form one row in
Games, and the watch tracks the cheapest buyable copy at any shop (or the cheapest new
one, with *New only*). A listing that becomes a different key, such as "Pokemon Scarlet &
Violet Double Pack" or a DLC bundle, is a different game with its own watch. If one copy
shows as its own row in Games, alias it (next question) and the watch covers it too.

**Why is a game I know a shop sells missing?**
In order of likelihood:
1. The classifier dropped it. `check_stores.py <store> --rejected` shows why.
2. Its title names no console and the shop has no hint. It's then stored as UNKNOWN and
   never grouped.
3. Its title keyed to nothing. `check_data.py` lists these.

**I fixed the classifier. Do old wrong rows disappear?**
No. Filtering happens at collection time, so a non-game let in earlier just stops being
updated and shows as out of stock. To clear everything, start a fresh database
([troubleshooting.md](troubleshooting.md) §5). Matcher fixes, by contrast, apply to old
data straight away.

**Why is a cheaper offer not the "best price"?**
It's out of stock, or the shop no longer lists it (§3.7). The best price has to be one you
can buy. Expand the row to see every offer.

**Why does Moved since last run show nothing?**
It needs two collections, and moves of 1% or less don't count.

**Why does sorting by Change show fewer rows?**
That sort shows only listings that actually moved.

**Why are new and pre-owned copies separate listings?**
They're different products at different prices. A watch can be set to *New only*.

**Why are regions kept apart?**
A Japanese and an Indian copy are different products in the data. The Games view still
groups them, so an import is compared with local stock.

**Why is Play-Asia's price in rupees?**
Its session cookies ask for INR (`profiles.py`), so the stored figure is the price Play-Asia
actually quotes in rupees, not a conversion. It does NOT include customs and shipping,
which you pay on delivery. Set a watch to *India only* to leave it out.

**Why didn't I get a notification?**
Notifications come from an open dashboard tab, or from the scheduled run. A hit is
announced once. It needs the best offer in stock and at or under target.

**Is it safe to delete `tracker.db`?**
It deletes your price history. Your watchlist, aliases, corrections and settings are in
separate files and survive. Delete `-wal` and `-shm` too.

**How do I add a shop?**
Add a `StoreConfig` to `config/stores.py` with a guessed `kind`, and a `platform_hint`
only if the shop sells nothing but Switch games. Then press **Check stores** and run
`check_stores.py <id>`. Browser shops also need a profile in `profiles.py`, which
**Fix a broken store** can help pick.

**Why no React, or another framework?**
One page for one user doesn't justify a build step. State lives in a few objects in
`app.js`, and every repaint reads from them, never from the page.

**Why is there no `uv.lock`?**
See §2.1: it would point at a private mirror.

**A test fails and prints nothing useful.**
Run that test alone with `-n 0` (no parallel workers) and `-vv`.

---

## Appendix A — Working on the code

### A.1 The gate

Nothing is done until all of these pass:

```
uv run pytest                            752 tests, about 1.3 min in parallel
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy
node --check src/switch_tracker/web/static/app.js
uv run python -m switch_tracker spike    packaging self-check
```

pytest uses one worker per core (pytest-xdist, set in `pyproject.toml`). Use `-n 0` to
debug with `print` or `--pdb`. Tests never touch the network or your real database.

Live checks against real shops are in [troubleshooting.md](troubleshooting.md) §2–3.

### A.2 Where the tests for X live

| You changed | Run |
|---|---|
| `core/parse.py` | `test_parse.py` (includes real feed titles) |
| `core/skus.py` | `test_skus.py` |
| `core/db.py` | `test_db.py` |
| `core/http.py` | `test_http.py` (real local server) |
| `core/matcher.py` | `test_matcher.py` |
| `config/stores.py` | `test_stores.py` |
| `adapters/shopify.py`, `woocommerce.py` | `test_adapter_shopify.py`, `test_adapter_woocommerce.py` |
| `adapters/browser/` | `test_adapter_browser.py`, `test_browser_extract.py`, `test_browser_logic.py`, `test_flipkart_recovery.py` |
| `services/collect.py`, `selection.py` | `test_service_collect.py` |
| `services/probe.py` | `test_service_probe.py` |
| `web/queries.py` | `test_queries.py` (holds the frozen oracle) |
| `web/runs.py` | `test_runs.py` |
| `web/app.py`, `routers/`, `guard.py`, `watchlist.py` | `test_web_app.py` |
| `events/`, `fx/`, `schedule.py`, `settings.py`, `__main__.py` | `test_events.py`, `test_fx.py`, `test_schedule.py`, `test_settings.py`, `test_entrypoint.py` |
| `scripts/check_data.py` | `test_check_data.py` |
| any import in `web/` | `test_import_boundary.py` |

```
uv run pytest tests/test_parse.py -k price -vv
```

### A.3 Things that will surprise you

- **Imports inside functions** in `__main__.py` and `collect_worker.py` are deliberate.
  They keep Playwright out of the dashboard (§1.4). Don't move them to the top.
- **`except Exception  # noqa: BLE001`** is deliberate too: one store must not end a run,
  and the lint rule makes each case carry a comment.
- **Every store hints `SWITCH`** except HG World and designinfo, including Switch 2
  categories. Switch 2 patterns are checked first, so they still win.
- **Classifier changes need a re-collect to show; matcher changes don't** (§7).
- **`queries.py`'s oracle is frozen on purpose.** A deliberate behaviour change has to be
  copied into it by hand, as a literal.

---

## Appendix B — Glossary

| Term | Meaning here |
|---|---|
| **adapter** | Code that knows one way to read a shop: Shopify, WooCommerce or browser (§3.2) |
| **best offer** | A game's cheapest in-stock, still-listed copy (§3.9) |
| **corrections** | Probe's fixes in `stores.local.json`, layered over `stores.py` (§3.1) |
| **facet** | A filter with counts, e.g. Store (3) |
| **fixture** | Test setup a test asks for by naming a parameter, e.g. a fresh database |
| **frozen** | Running as the packaged `.exe` |
| **game** | One title on one platform, grouped across shops by the matcher |
| **headful / headless** | Browser window visible / invisible |
| **listing** | One product at one shop |
| **match key** | The normalised title games are grouped on (§3.9) |
| **oracle** | A frozen copy of old behaviour that new code is compared against |
| **Partial** | "Got rows, but some are probably missing" (§3.2) |
| **price point** | One price for one listing in one run. Append-only: this is the history |
| **probe** | The job behind Check stores: detects each shop's platform (§3.11) |
| **profile** | A browser store's recipe in `profiles.py` (§3.6) |
| **run** | One collection, probe or rate refresh: a row in `run` |
| **SKU** | The per-shop product id that must stay stable (§3.5) |
| **SSE** | Server-Sent Events: one long response the server keeps writing progress into |
| **struck page** | A Flipkart page that failed to load and is retried later (§3.6) |
| **WAL** | SQLite mode that lets reads and writes happen together (§2.3) |
| **watch / hit** | A watched game; a hit is its best in-stock offer at or under target (§4.3) |
| **worker** | A copy of the program started to do one job (§1.4) |
