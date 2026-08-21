# switch-tracker

A local price tracker for Nintendo Switch / Switch 2 **physical cartridges**
across Indian retailers, plus Play-Asia as an import comparison. Runs on your
own machine — no server, no account, nothing sent anywhere except the
requests to the stores themselves.

TypeScript on Bun · SQLite (built into Bun) · Playwright for the stores that
block plain HTTP requests.

## 1. Setup (do this once)

### Windows

Double-click **`switch-tracker.bat`**. On first run it installs everything —
Bun, then Playwright's Chromium (a few minutes, mostly the Chromium
download) — then drops you into the menu.

If you'd rather run it yourself:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Before extracting a zip of this project: right-click it → Properties → tick
**Unblock**. Windows marks downloaded files, and PowerShell refuses to run
scripts carrying that mark.

Extract/clone somewhere plain like `C:\switch-tracker`. Avoid OneDrive-synced
folders — the sync client locks files mid-write, which fights with a SQLite
database being written to twice a day.

### macOS / Linux / WSL

```bash
chmod +x setup.sh && ./setup.sh
bun run menu
```

## 2. Using it

Every run after setup opens a menu:

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

The number in brackets is the suggested next step — pressing Enter takes it.
Typical first-time order:

1. **Check stores** — detects what API each shop actually speaks and writes
   corrections to `stores.local.json`. Safe to re-run any time; it never
   touches the database.
2. **Collect prices** — fetches current prices from every enabled store and
   saves them. This is append-only: each run adds a new price point, which is
   what builds up history over time.
3. **Open dashboard** — opens `http://localhost:4173` in your browser.

You never edit config by hand — "Check stores" and "Fix a broken store"
handle that for you. Delete `stores.local.json` (or pick option 7) to undo
every correction and start over.

Each menu item also maps to a plain command, if you'd rather script it:

| Menu | Command |
|---|---|
| 1 Check stores | `bun run probe` |
| 2 Collect prices | `bun run collect` |
| 3 Open dashboard | `bun run dashboard` |
| 5 Update rate | `bun run fx` |
| — | `bun run menu` |
| — | `bun run start` (collect, then open the dashboard) |

## 3. The dashboard

Serves on `http://localhost:4173`, bound to `127.0.0.1` — local only, not
reachable from your network. Three sections:

- **Collector strip** — one tile per store from the last run, with its
  listing count. A store returning zero rows without erroring is the failure
  that otherwise hides for weeks, so this is first on the page.
- **Moved since last run** — price changes against the previous observation.
  Appears after your second collection run.
- **All listings** — every listing found, searchable and filterable by
  console (Switch / Switch 2 / both), store, region, and stock status. Click
  a column header to sort; click it again to flip direction. Filters and
  sort compose, so "Switch 2, in stock, cheapest first" is three clicks, and
  they run against the whole table in SQL — not just whatever's on screen.

Two things it doesn't cover: it lists what the stores in `stores.ts` actually
sell, not every game that exists, and until each cartridge is matched across
stores, the same game at four stores shows up as four separate rows.

## 4. When a store returns nothing

If a browser-based store (Amazon, Flipkart, Croma) comes back empty, the page
and a screenshot get written to `diagnostics\<store>.html` — check there
first. To fix it:

```powershell
bun run src/cli/inspect.ts <store>
```

That opens the real page in Playwright Inspector. Click a product card, then
its title/price/link, and add what you find to the matching list in
`PROFILES` in `src\adapters\browser.ts`. Every field is a list of candidate
selectors tried in order, so add to it rather than replacing what's there.

Croma legitimately carries few cartridges — a small number there is correct,
not broken.

## 5. Running it automatically

Once a collection run is reliably green, put it on a timer — once or twice a
day is plenty.

**Windows:**

```powershell
powershell -ExecutionPolicy Bypass -File .\schedule-task.ps1
```

Registers a Task Scheduler entry for 07:30 and 21:30 daily, logging to
`collect.log`.

```powershell
Start-ScheduledTask -TaskName switch-tracker              # run now
Get-ScheduledTaskInfo -TaskName switch-tracker            # last result
Unregister-ScheduledTask -TaskName switch-tracker -Confirm:$false
```

**macOS / Linux (cron):**

```bash
crontab -e
30 7,21 * * * cd /path/to/switch-tracker && /home/you/.bun/bin/bun run collect >> collect.log 2>&1
```

Use the absolute path to `bun` — cron doesn't read your shell profile.
