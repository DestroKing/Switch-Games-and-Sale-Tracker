# switch-tracker

Price tracker for Nintendo Switch and Switch 2 **physical cartridges** across
Indian retailers, plus Play-Asia as an import comparison.

TypeScript on Bun · SQLite (built into Bun) · Playwright for the three stores
that block plain HTTP requests.

---

## Quick start (Windows)

Double-click **`switch-tracker.bat`**. That's the whole thing.

On first run it installs everything (a few minutes, mostly Chromium). Every run
after that it opens a menu:

```
  SWITCH CARTRIDGE TRACKER
  ──────────────────────────────────────────────
  Last run 3 hr ago · 11 stores working, 2 not
  1,847 listings · 6 runs

  1  Check stores        re-detect and fix the store list
  2  Collect prices      fetch the latest prices
  3  Open dashboard      ← see what moved
  4  Fix a broken store
  5  Update exchange rate
  6  Run twice daily automatically
  7  Reset store corrections
  0  Quit

  Choose [3]:
```

The number in brackets is the suggested next step, and pressing Enter takes it.
The suggestion is read from the database rather than fixed, so it points at
probing before your first collection, at a second collection before the
dashboard is worth opening, and at the dashboard after that.

**You no longer edit any config by hand.** "Check stores" detects what each
shop actually speaks and writes the corrections to `stores.local.json` itself.
Delete that file (or pick option 7) to undo everything.

## 1. Setup

### Windows

Double-click `switch-tracker.bat`. It detects that nothing is installed yet,
runs setup, then drops you into the menu. There is no separate setup step to
remember and no order to get wrong.

It checks two machine requirements first, so you meet them as a sentence rather
than a crash:

- **Windows 10 build 17763 (version 1809) or later.**
- **A CPU with AVX2** — Intel 4th-gen Core or AMD Excavator and newer. Older
  hardware isn't excluded; it needs Bun's baseline build, which requires only
  SSE4.2, and the script installs that automatically. Without the check you'd
  get "Illegal Instruction" on first run, which reads like broken code.

Bun runs natively on Windows — no WSL, no Docker. `bun:sqlite` is inside the
runtime, so nothing compiles and Visual Studio Build Tools aren't needed.

**Before extracting:** right-click the zip → Properties → tick **Unblock**.
Windows marks downloaded files, and PowerShell refuses to run scripts carrying
that mark. Unblocking the zip clears it from everything inside.

Extract somewhere plain like `C:\switch-tracker`. Avoid OneDrive-synced folders
— the sync client locks files mid-write and objects to a SQLite database being
appended to twice a day.

### macOS / Linux / WSL

```bash
chmod +x setup.sh && ./setup.sh
bun run menu
```

### Docker — probably not what you want on Windows

The image works and suits a server, but Docker Desktop on Windows 10 runs on a
WSL 2 backend, so choosing it means installing Linux underneath plus a multi-GB
Docker install to avoid a 90 MB Bun binary that runs natively.

```bash
docker compose build && docker compose run --rm collect
```

### A truly self-contained .exe

Possible but awkward — see §8. The `.bat` already gives the same double-click
experience for 52 KB, so the exe only earns its keep if you're handing this to
someone else.

## 2. The commands behind the menu

Every menu item maps to a command you can run directly if you prefer:

| Menu | Command | What it does |
|---|---|---|
| 1 Check stores | `bun run probe` | Detects each store's real API, writes `stores.local.json` |
| 2 Collect prices | `bun run collect` | Fetches, stores prices, records per-store health |
| 3 Open dashboard | `bun run dashboard` | Serves `localhost:4173` |
| 5 Update rate | `bun run fx` | USD to INR from the ECB via Frankfurter |
| — | `bun run menu` | The menu itself |

Probe writes nothing to the database and is safe to re-run. Collect is
append-only: listings upsert on `(store_id, sku)` and each run adds a price
point, which is what builds history.

### The dashboard

```powershell
bun run start          # collect, then open the dashboard
bun run dashboard      # dashboard only, against existing data
```

Serves on `http://localhost:4173`, bound to `127.0.0.1` — local only, not
reachable from your network.

Three things on it:

- **Collector strip** — one tile per store from the last run, with the listing
  count as the headline. This is first on the page because a store returning
  zero rows *without erroring* is the failure that otherwise hides for weeks.
- **Moved since last run** — price changes against the previous observation.
  When many listings in one currency move by the same ratio on the same day,
  they get an FX tag and a note, because that is the rupee moving rather than
  the shops. Appears after your second collection run.
- **All listings** — searchable and filterable by console (Switch / Switch 2 /
  both), store, region and stock status. Click any column header to sort;
  clicking the active one flips direction. Filters and sort compose, so
  "Switch 2, in stock, cheapest first" is three clicks.

  Filtering and sorting run in SQL against the whole table, not in the browser
  against the loaded page. That distinction matters: sorting a page of 100
  already-fetched rows would give you the cheapest *of those hundred* while
  looking exactly like the cheapest overall.

### What it does and doesn't cover

It lists every Switch and Switch 2 listing the adapters find — which is not the
same as every game that exists. Three limits:

- **Stock, not catalogue.** Each store contributes what it sells. The union
  across 16 stores is wide, but a title nobody in India imports won't appear.
- **Games only, by design.** Consoles, Joy-Cons, Pro Controllers, docks, cases,
  screen protectors, amiibo, eShop codes and Switch Online memberships are all
  classified and dropped. Without that filter the price history slowly fills
  with hardware, since "Nintendo Switch Console" contains the console's name
  just as much as a game does.
- **Terse titles are handled.** Classification reads the title *plus* the
  store's own product type, tags and categories, and every Switch-only store
  carries a `platformHint`. So a bare "Hogwarts Legacy" filed under "Nintendo
  Switch Games" is kept rather than dropped for not naming its console.
- **Listings, not games.** Until the matcher exists, the same cartridge at four
  stores is four rows. Cross-store comparison is the next piece of work.

## 3. When a hard store returns nothing

Amazon, Flipkart and Croma are enabled. Their CSS selectors are still guesses —
this was written without network access, so none of those pages was ever
opened — but the adapter no longer depends on guessing correctly.

Extraction runs in four layers, most durable first:

1. **JSON-LD** — the schema.org `Product` data these sites publish for search
   engines. It survives redesigns precisely because it isn't layout.
2. **Embedded state** — Flipkart's `__INITIAL_STATE__`, walked for anything
   with a title and a price rather than assuming a path. Flipkart's class names
   are generated and rotate, so CSS is the wrong thing to trust there.
3. **CSS selectors** — several candidates per field, tried in order.
4. **Rupee-pattern text** — if no price selector matched inside a card, find the
   ₹ figure in the card's text.

If all four come up empty the page is written to `diagnostics\<store>.html` with
a screenshot, and the run reports the path. That's the important change: the old
version failed silently, which on a scraper is the worst possible failure mode —
a clean run, zero rows, no error, and no idea why.

To fix a store from the dump:

```powershell
bun run src/cli/inspect.ts flipkart
```

That opens the page in a real browser with Playwright Inspector. Click a product
card, then the title, price and link inside it, and **add** what you find to the
relevant list in `PROFILES` in `src\adapters\browser.ts`. Every field takes an
array, so adding a working selector doesn't mean deleting one that might work
again later.

Expect Croma to return few rows. Its cartridge range is genuinely thin — a small
number there is accurate, not broken.

## 4. Scheduling it

Once a collection run is reliably green, put it on a timer. Once or twice a day
is plenty — these are small shops, and the HTTP client already paces itself to
one request per host at a time.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\schedule-task.ps1
```

Registers a Task Scheduler entry for 07:30 and 21:30 daily, logging to
`collect.log`. It sets `StartWhenAvailable`, so a run missed because the PC was
asleep gets picked up when it wakes — on a desktop that's most of them.

```powershell
Start-ScheduledTask -TaskName switch-tracker              # run now
Get-ScheduledTaskInfo -TaskName switch-tracker            # last result
Unregister-ScheduledTask -TaskName switch-tracker -Confirm:$false
```

The log matters more than usual here: the scheduler gives you an exit code and
nothing else, and a store quietly returning zero rows is precisely the failure
you want to be able to read about afterwards.

### macOS / Linux — cron

```bash
crontab -e
30 7,21 * * * cd /path/to/switch-tracker && /home/you/.bun/bin/bun run collect >> collect.log 2>&1
```

Use the absolute path to `bun`; cron doesn't read your shell profile.

## 5. Project layout

```
switch-tracker.bat      double-click this — setup on first run, menu after
setup.ps1               what the .bat calls when nothing is installed
schedule-task.ps1       registers a twice-daily Task Scheduler entry
build-exe.ps1           compiles a standalone .exe
setup.sh                macOS / Linux / WSL setup
Dockerfile              Bun + Playwright + Chromium in one image
docker-compose.yml      one service per command
stores.local.json       written by "Check stores"; delete to reset
src/
  menu.ts               the menu — reads state, suggests the next step
  index.ts              CLI entry — menu | probe | collect | fx
  launch.ts             collect + serve, used by the compiled exe
  config/
    stores.ts           shipped store list
    overrides.ts        merges stores.local.json over it
  core/
    types.ts            domain types
    db.ts               SQLite schema
    http.ts             polite HTTP: one request per host, backoff, retry
    parse.ts            price parsing, product classification, regions
  adapters/
    shopify.ts          /products.json
    woocommerce.ts      Store API
    browser.ts          Playwright — 4 extraction layers + diagnostics
    index.ts            dispatch on store kind
  fx/rates.ts           Frankfurter (ECB), caching, INR conversion
  web/
    server.ts           local read-only dashboard server
    index.html          the dashboard itself
  cli/
    probe.ts            detect store APIs, write corrections
    collect.ts          the collection run
    inspect.ts          headed browser for reading real selectors
data\tracker.db         created on first run
diagnostics\            failed page dumps, when a browser store returns nothing
```

---

## 6. Where it stands

| Piece | Status |
|---|---|
| Schema, HTTP, parsing, FX | Written |
| Shopify + WooCommerce adapters | Written |
| Playwright adapter | Rewritten — 4 extraction layers, selectors still unverified |
| Amazon / Flipkart / Croma | Enabled |
| Play-Asia | Parked (`enabled: false`) |
| Dashboard + local server | Written |
| Menu + one-click launcher | Written |
| Auto-applied probe corrections | Written |
| Standalone .exe build | Script written, unproven — see §9 |
| Games The Shop (custom Next.js API) | Not written — needs probe output first |
| Matcher (canonical catalogue + fuzzy titles) | **Not written — next up** |
| Alert engine | Not written |

---

## 7. Two decisions not to quietly undo

**Native price is the truth; INR is derived.** Play-Asia quotes USD and offers a
rupee display conversion. Capturing that rupee figure as if it were a price
means a 2% currency slide shows up as a 2% price rise across the entire
catalogue at once — and a strengthening rupee looks exactly like a modest sale.
`price_point` stores the native price, the derived INR, and the ECB rate date
used for the conversion. That last column is what will let the alert engine ask
whether hundreds of prices moved by the same ratio on the same day, and stay
quiet when they did.

**`listing.game_id` is nullable.** Unmatched listings still get collected.
Matching is a separate, re-runnable pass over data already on disk, so improving
the matcher later never means re-scraping everything.

Region is a first-class column for a related reason: Play-Asia splits one title
across Asia-English, Asia-Chinese, Japan and Western SKUs. Those are genuinely
different products with different playability, not aliases to be collapsed.

---

## 8. Making a standalone .exe

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1 -NoBrowser
```

`bun build --compile` bakes the runtime and your code into one binary, so the
result runs on a machine with no Bun installed. That part is straightforward.

Playwright is what complicates it. It isn't a normal library — it ships a
separate driver process and resolves a Chromium binary from disk at runtime,
and neither survives being packed into a single executable. So:

| | Output | Trade |
|---|---|---|
| Default | `dist\` folder, ~400 MB | All 16 stores. Not a single file — ship the folder, run the .bat inside it |
| `-NoBrowser` | Single .exe, ~60 MB | The 12 HTTP stores and the dashboard. Skips Amazon, Flipkart, Croma, Play-Asia |

The `-NoBrowser` build is the one that behaves like a normal Windows program.
If the Indian importers are what you actually care about day to day, it's the
better artifact, and you can run the full version occasionally for the imports.

Neither path has been executed — see below.

## 9. Caveat

None of this has been executed. It was written in a Linux sandbox with no
network, so Bun and Playwright could not be installed, nothing was ever run,
and no part of it has been exercised on Windows specifically. The dashboard has
never been rendered, neither .exe build path has been run, and the Amazon,
Flipkart and Croma selectors have never been checked against a live page — the
four-layer extraction and the diagnostics dump exist because of that, not
instead of it. The code is
carefully written but unverified — expect to shake out a few things on first
run. The most likely candidates are the WooCommerce minor-unit handling, the
platform-inference regexes over-filtering on stores that write terse titles,
and, near-certainly, the browser selectors.
