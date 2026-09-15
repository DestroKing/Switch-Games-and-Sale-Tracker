# switch-tracker

Local price tracker for Nintendo Switch / Switch 2 **physical cartridges**
across Indian retailers, plus Play-Asia for import comparison. Python +
FastAPI + SQLite, with Playwright for the stores that publish no product feed.
Runs entirely on your own machine — nothing is uploaded anywhere.

Everything is driven from one dashboard. There is no menu and nothing to
hand-edit.

---

## Getting started (Windows)

1. Put this folder somewhere sensible — **not inside OneDrive**. The sync
   client locks the database mid-write and can corrupt it. `C:\switch-tracker\`
   is fine. (The app warns you if it detects this.)
2. Right-click `START.bat` → **Properties** → tick **Unblock** → OK.
   Windows blocks scripts that came from another machine.
3. Double-click **`START.bat`**.

The first run installs everything — Python, the packages, and a browser engine
— which takes 10–20 minutes and about 1 GB of downloads. Every run after that
goes straight to the dashboard.

Nothing needs administrator rights. It all installs into your own user folder.

**macOS / Linux:** `uv sync && uv run playwright install chromium && uv run python -m switch_tracker`

---

## The dashboard

Opens at `http://127.0.0.1:4173`, reachable only from this machine.

| Button | What it does |
|---|---|
| **Collect prices** | Fetches current prices from every enabled store and appends them to the history |
| **Check stores** | Detects what each store's website actually runs on and corrects the config itself |
| **Update exchange rate** | Refreshes the USD→INR rate from the ECB |
| **Fix a broken store** | Opens a store in a real browser window so you can click on the parts it failed to read |
| **Reset corrections** | Undoes everything "Check stores" wrote |
| **Collect specific stores…** | Tick any number of stores and collect only those — useful for testing one shop without waiting for all twenty-four. Disabled stores can be picked too; naming a store overrides its disabled state |

Each button starts a separate background process and returns immediately. Live
progress streams into the console panel underneath.

**Collecting is something you ask for.** The app collects by itself exactly
once — the first time you open it with an empty database and the stores already
checked — so there is something to look at. After that, opening the dashboard
never starts a run; press **Collect prices** when you want fresh prices.

**You can close the tab.** The work is happening in another process, so
closing, refreshing, or even restarting the app does not stop a collection —
reopening picks the progress back up where it left off.

Below the buttons:

- **Collector** — one tile per store from the last run: how many listings it
  found, and *why* if it found none. A store silently returning zero is the
  failure that otherwise hides for weeks.
- **Moved since last run** — price changes, once there are two runs to compare.
  When many listings in the same currency move by the same amount on the same
  day, that is flagged as the rupee moving rather than a sale.
- **All listings** — search and filter by console, store, region, condition and
  stock. Sorting runs in the database across every row, not just the ones on
  screen — "cheapest first" over a loaded page is a different, wrong answer.

---

## Fixing a store that returns nothing

Some stores have no product feed, so the app reads their pages the way a
browser does. When one changes its layout, it starts returning nothing.

Pick it from the **Fix a broken store** dropdown. A real browser window opens
on that store's page. **Alt+click** the product card, then its title, price,
and link, in that order. Each click is scored against the real page and saved
straight to your settings — there is nothing to copy or paste.

Plain clicks still work normally, so you can dismiss cookie banners first.

---

## Where your data lives

Everything writable is under `%LOCALAPPDATA%\switch-tracker\`:

| File | What |
|---|---|
| `tracker.db` | The price history. This is the valuable one — back it up |
| `stores.local.json` | Corrections written by "Check stores" |
| `profiles.local.json` | Selectors saved by "Fix a broken store" |
| `diagnostics/` | Page dumps from stores that returned nothing |

Set `TRACKER_DATA_DIR` to put them somewhere else.

The database is plain SQLite — open it with any SQLite tool.

---

## Building the standalone app

`BUILD-EXE.bat` produces `dist\switch-tracker\`, which runs on a PC with no
Python and no internet. Copy the **whole folder**; the browser engine lives
inside it. It is around 900 MB.

Then run `switch-tracker.exe` from inside that folder.

`CHECK.bat` runs the built app's self-check and keeps the window open, which is
the quickest way to confirm a build works. (Double-clicking the exe directly
will flash and vanish if it exits — that is Windows closing the console, not a
crash.)

The app is unsigned, so Windows SmartScreen will warn on first run.

---

## What it does and does not cover

It tracks what the configured stores actually sell, not every game in
existence. Two things are deliberately not built yet:

- **Matching across stores.** The same cartridge at four shops is four separate
  rows. Every listing carries a `game_id` that is always empty, waiting for the
  matcher.
- **Alerts.** The price history and the currency-move detection are the
  groundwork; nothing notifies you yet.

Scope is games only. Consoles, Joy-Cons, cases, amiibo, eShop codes, Online
memberships and repair services are filtered out, as are games for other
consoles — even on stores that file them all under one category.

---

## Development

```bash
uv sync                              # dependencies
uv run pytest                        # 494 tests
uv run ruff check src tests scripts  # lint
uv run mypy                          # types (strict)
uv run python -m switch_tracker spike   # packaging self-check
```

`scripts/scrape_check.py <store_id>` runs one store's **real** collection path
against the live site and prints what came back — which engine launched, which
pager was used, how many listings survived. It drives the shipped adapter and
the shipped profile on purpose: a check that carries its own private copy of a
store profile can pass while the collector fails on the same page.

```bash
uv run python scripts/scrape_check.py playasia --pages 3
uv run python scripts/scrape_check.py e2zstore --headful
```

Design documents are in `docs/`:

- **`walkthrough.md`** — start here. Orientation (what runs, where every file lives,
  where your data goes), the tech stack and why each piece was chosen over its
  alternatives, a step-by-step trace of one collection run, then a feature-by-feature
  tour of the code. Ends with a glossary, a first-change exercise and a
  troubleshooting table. Assumes no prior knowledge of any of the technologies.
- `python-rewrite-plan.md` — the original spec
- `python-rewrite-hld.md` — architecture, and the options that lost
- `python-rewrite-lld.md` — the build plan

The `src/` tree still contains the original TypeScript implementation. It is
the behavioural reference for the port and will be removed once the Python
version has been run against live stores.
