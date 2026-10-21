# switch-tracker

Local price tracker for Nintendo Switch / Switch 2 **physical cartridges**
across Indian retailers, plus Play-Asia for import comparison. Python +
FastAPI + SQLite, with Playwright for the stores that publish no product feed.
Runs entirely on your own machine — nothing is uploaded anywhere.

Everything is driven from one dashboard. There is no menu and nothing you have
to hand-edit (the one optional file is for fixing how games are grouped).

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

- **Watchlist** — games you starred, their best price right now, and the price
  you said you would pay. A game whose cheapest *in-stock* offer is at or below
  your target is marked **at target**, counted in the tab title, and (if you
  allow it) announced with a desktop notification while the dashboard is open.
- **Collector** — one tile per store from the last run: how many listings it
  found, and *why* if it found none. A store silently returning zero is the
  failure that otherwise hides for weeks.
- **Moved since last run** — price changes of more than 1%, once there are two
  runs to compare. When many listings in the same currency move by the same
  amount on the same day, that is flagged as the rupee moving rather than a sale.
- **Games** — one row per game across every store: its cheapest copy you can
  buy, where, and how many shops carry it. **▸** opens every offer for that game,
  and **▸** on an offer shows its price history. **☆ Watch** adds it to the
  watchlist. Switch to **Every listing** for the raw per-shop rows. Search and
  filter by console, store, region, condition and stock in either view. Sorting
  runs in the database across every row, not just the ones on screen —
  "cheapest first" over a loaded page is a different, wrong answer.

---

## Collecting every day without pressing anything

```bat
START.bat schedule --at 07:30     :: collect at 07:30 every day (Windows Task Scheduler)
START.bat schedule --off          :: stop
```

With the standalone app, use `switch-tracker.exe schedule --at 07:30`. It is a
windowless app, so it prints nothing on screen; the confirmation goes to
`windowed.log` in your data folder, and the task appears in Task Scheduler as
"switch-tracker daily collection". The
scheduled run goes through the same one-run-at-a-time guard as the button, so
it can never collide with a collection you started by hand. If the PC is off at
that time, it runs as soon as the PC is next on -- unless a collection has
already succeeded since that day's scheduled time. When a watched game hits your target during a scheduled
run, Windows shows a notification even with no dashboard open (once per new
hit). The dashboard's Collector section shows whether the daily collection is
set up and when it runs next.

## When two shops' copies of one game show as two rows

Games are grouped by a normalised title, and the grouping errs on the side of
keeping things apart: two different games merged into one would be far worse
than one game split in two. When it splits something it should not, create
`matches.local.json` in your data folder:

```json
{ "Zelda: Tears of the Kingdom": "The Legend of Zelda: Tears of the Kingdom" }
```

Paste titles exactly as the dashboard shows them, then run
`START.bat match` (or `switch-tracker.exe match`) to regroup — it takes seconds
and never re-scrapes.

---

## Fixing a store that returns nothing

Some stores have no product feed, so the app reads their pages the way a
browser does. When one changes its layout, it starts returning nothing.

Pick it from the **Fix a broken store** dropdown. A real browser window opens
on that store's page. **Alt+click** the product card, then its title, price,
and link, in that order. Each click is scored against the real page and saved
straight to your settings — there is nothing to copy or paste.

Plain clicks still work normally, so you can dismiss cookie banners first.

To find out *why* a store fails, see [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Where your data lives

Everything writable is under `%LOCALAPPDATA%\switch-tracker\`:

| File | What |
|---|---|
| `tracker.db` | The price history. This is the valuable one |
| `backups/` | A copy of `tracker.db` after every collection, newest 7 kept. To restore, close the app and copy one over `tracker.db` |
| `stores.local.json` | Corrections written by "Check stores" |
| `profiles.local.json` | Selectors saved by "Fix a broken store" |
| `watchlist.local.json` | Your watched games and targets — survives deleting the database |
| `matches.local.json` | Your title aliases for grouping games (optional, you create it) |
| `diagnostics/` | Page dumps from stores that returned nothing |

Set `TRACKER_DATA_DIR` to put them somewhere else.

The database is plain SQLite — open it with any SQLite tool.

---

## Building the standalone app

`BUILD-EXE.bat` produces `dist\switch-tracker\`, which runs on a PC with no
Python and no internet. Copy the **whole folder**; the browser engine lives
inside it. It is around 900 MB.

Then run `switch-tracker.exe` from inside that folder.

To confirm a build works, double-click `CHECK.bat` ([`docs/troubleshooting.md`](docs/troubleshooting.md) §4).

The app is unsigned, so Windows SmartScreen will warn on first run.

---

## What it does and does not cover

It tracks what the configured stores actually sell, not every game in
existence. Not built yet:

- **Detected deals.** The watchlist alerts on a target *you* set. Spotting a
  game that is unusually cheap compared with its own history, without being
  asked, is not built — the price history and the currency-move check are the
  groundwork for it.
- **Alerts with no dashboard open.** Notifications appear while a dashboard tab
  is open. Email or phone alerts would mean sending data to an outside service,
  which this app deliberately does not do.

Scope is games only. Consoles, Joy-Cons, cases, amiibo, eShop codes, Online
memberships and repair services are filtered out, as are games for other
consoles — even on stores that file them all under one category.

---

## Development

```bash
uv sync                              # dependencies
uv run pytest                        # 695 tests
uv run ruff check src tests scripts  # lint
uv run mypy                          # types (strict)
uv run python -m switch_tracker spike   # packaging self-check
```

Checking that the stores, the collected data and a build really work — every
command, and what to do when something fails — is in
**[`docs/troubleshooting.md`](docs/troubleshooting.md)**.

Design documents are in `docs/`:

- **`walkthrough.md`** — start here. Orientation (what runs, where every file lives,
  where your data goes), the tech stack and why each piece was chosen over its
  alternatives, a step-by-step trace of one collection run, then a feature-by-feature
  tour of the code. Ends with a glossary and a first-change exercise. Assumes no
  prior knowledge of any of the technologies.
- **`troubleshooting.md`** — validating the stores, the collected data and a
  build, and a table of symptoms with their fixes.
- `python-rewrite-plan.md` — the original spec
- `python-rewrite-hld.md` — architecture, and the options that lost
- `python-rewrite-lld.md` — the build plan

