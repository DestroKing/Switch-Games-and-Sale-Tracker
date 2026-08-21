# switch-tracker

Local price tracker for Nintendo Switch / Switch 2 **physical cartridges**
across Indian retailers, plus Play-Asia for import comparison. Bun +
TypeScript + SQLite, Playwright for stores that block plain HTTP requests.
Runs entirely on your machine.

## Setup

**Windows:** double-click `switch-tracker.bat`. First run installs Bun +
Chromium, then opens the menu.

Manual: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`

Before extracting a zip: right-click → Properties → **Unblock** (Windows
blocks scripts from downloaded files otherwise). Avoid OneDrive-synced
folders — the sync client locks the SQLite file mid-write.

**macOS / Linux / WSL:** `chmod +x setup.sh && ./setup.sh && bun run menu`

## The menu

```
1  Check stores        2  Collect prices      3  Open dashboard
4  Fix a broken store  5  Update FX rate       6  Schedule twice daily
7  Reset corrections   0  Quit
```

The bracketed number is the suggested next step; Enter takes it.

| # | Command | Does |
|---|---|---|
| 1 | `bun run probe` | Detects each store's real API, writes `stores.local.json` |
| 2 | `bun run collect` | Fetches and saves prices — append-only, builds history |
| 3 | `bun run dashboard` | Opens `localhost:4173` |
| 4 | — | Guided browser walkthrough to fix a store returning nothing |
| 5 | `bun run fx` | Refreshes the USD→INR rate |
| 7 | — | Wipes `stores.local.json` |

No hand-editing config — options 1 and 4 write their own corrections. Delete
`stores.local.json` (or run option 7) to reset everything.

## Dashboard

`localhost:4173`, local only. Three sections:

- **Collector strip** — rows found per store, last run. A silent zero is the
  failure that otherwise hides for weeks.
- **Moved since last run** — price changes, once there's a second run to
  compare against.
- **All listings** — search/filter by console, store, region, stock. Sorts
  against the full table in SQL, not just whatever's loaded on screen.

Covers what the configured stores actually sell, not every game in
existence. Cartridges aren't matched across stores yet, so the same game at
four stores is four separate rows.

## Fixing a broken store

```powershell
bun run src/cli/inspect.ts <store>
```

Opens the real page. **Alt+click** the product card, then its title, price,
and link, in that order — each click is scored and saved straight to
`profiles.local.json`, nothing to paste into code by hand. Plain clicks
still behave normally, so cookie banners etc. can be dismissed. A store that
returns nothing also dumps `diagnostics/<store>.html` for a look.

## Scheduling

**Windows:**

```powershell
powershell -ExecutionPolicy Bypass -File .\schedule-task.ps1
```

Registers 07:30/21:30 daily via Task Scheduler, logs to `collect.log`.

```powershell
Start-ScheduledTask -TaskName switch-tracker
Get-ScheduledTaskInfo -TaskName switch-tracker
Unregister-ScheduledTask -TaskName switch-tracker -Confirm:$false
```

**macOS / Linux (cron)** — use bun's absolute path, cron doesn't read your
shell profile:

```bash
30 7,21 * * * cd /path/to/switch-tracker && /home/you/.bun/bin/bun run collect >> collect.log 2>&1
```
