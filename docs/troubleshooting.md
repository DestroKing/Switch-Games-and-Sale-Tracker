# Troubleshooting and validation

Every check that the app works, in one place: the shops, the data a collection saved, and
a packaged build. After those comes a table of symptoms and their fixes.

Run the commands from the project folder, in a prompt where `uv` works (`START.bat` sets
that up the first time). They work the same in Command Prompt, PowerShell and bash. **None
of them writes to your price history** unless the step says so.

For *how* any of this works, see [`walkthrough.md`](walkthrough.md). References like
"walkthrough §3.18" point there.

**Contents**

1. [Before you start](#1-before-you-start)
2. [Validating the stores](#2-validating-the-stores)
3. [After a collection: checking the data](#3-after-a-collection-checking-the-data)
4. [Checking a build](#4-checking-a-build), and the code's own tests
5. [When it doesn't work](#5-when-it-doesnt-work)

---

## 1. Before you start

- **Use your own network.** Shops change their sites without warning, and some networks,
  offices especially, block shopping sites outright. On a filtered network, browser stores
  fail with `ERR_CONNECTION_RESET` and feed stores time out. That's the network, not the
  app. If a check fails on one network, try the other before changing anything.
- **Experiment in a throwaway data folder** when you want to collect without touching
  your real database. Everything the app writes goes to `TRACKER_DATA_DIR`:

  | Shell | Command |
  |---|---|
  | Command Prompt | `set TRACKER_DATA_DIR=%TEMP%\tracker-scratch` |
  | PowerShell | `$env:TRACKER_DATA_DIR = "$env:TEMP\tracker-scratch"` |
  | bash | `export TRACKER_DATA_DIR=/tmp/tracker-scratch` |

  It lasts until you close that window. The scheduled task refuses to register while it
  is set, because the task would never see it.

---

## 2. Validating the stores

Unit tests prove the logic. Only the live site can prove a shop still looks the way it
did last month.

### The main check: `check_stores.py`

```
uv run python scripts/check_stores.py
```

This runs every enabled store, one at a time, through the same registry, store list
(with your local corrections applied) and profiles the collector uses. It **judges** the
result rather than just counting it, flagging:
- pages that repeat;
- prices at zero or 100×;
- a currency that disagrees with the store's config;
- catalogues where nothing is in stock.

Each of those checks exists because that failure has shipped here at least once.

**It checks several stores at once**: 6 by default, at most 3 of them browser stores,
because each opens its own browser. Each store's report prints as one block when that store
finishes, so the order differs from run to run. A full sweep takes about as long as the
slowest store. Each shop still gets one request at a time with the usual pause between
requests; the speed-up only comes from checking *different* shops at the same time.

| Variation | Command |
|---|---|
| Just some stores | `uv run python scripts/check_stores.py hgworld flipkart` |
| Include stores that are switched off, to spot one disabled by mistake | `uv run python scripts/check_stores.py --include-disabled` |
| One kind of store at a time | `uv run python scripts/check_stores.py --kind BROWSER` (or `WOOCOMMERCE`, `SHOPIFY`, …) |
| Fewer pages, in a visible browser | `uv run python scripts/check_stores.py flipkart --pages 3 --headful` |
| Where a store's settings come from, and its recorded run outcomes | `uv run python scripts/check_stores.py flipkart --history` |
| Every listing a store returned: spot a non-game (a joystick, a console) that got through | `uv run python scripts/check_stores.py hgworld --list` |
| Every product a feed store DROPPED, and what the filter took it for: spot a real game thrown out | `uv run python scripts/check_stores.py designinfo --rejected` |
| More or fewer stores at once (`--jobs 1` = one at a time, easiest to follow live) | `uv run python scripts/check_stores.py --jobs 10` |

Afterwards, press **Check stores** once in the dashboard. An older version of it switched
a store off just because it could not reach it at that moment. The current one turns such
stores back on as soon as they answer.

### When one store fails: narrowing it down

| Question | Command |
|---|---|
| Why does a feed store answer 403 or 401? | `uv run python scripts/check_stores.py hgworld --probe` |
| What does one browser store's real walk return? | `uv run python scripts/scrape_check.py playasia --pages 3` |
| …and can I watch it? | `uv run python scripts/scrape_check.py e2zstore --headful` |
| Why does paging stop early? | `uv run python scripts/scrape_check.py playasia --diagnose-pager` |
| Why did it extract N rows when the page shows M? | `uv run python scripts/diagnose_extraction.py gamepookie` |
| Are the feed stores' category settings right? | `uv run python scripts/category_check.py` |

What each one tells you:

- **`--probe`** re-asks the host one variable at a time: with and without the category
  filter, at `per_page` 100 and 10, by term id and by slug. Then it **repeats the first
  request that worked**, and that last step tells the two possible causes apart. If the
  known-good request now fails too, the trigger is request volume, and no parameter change
  will help. If it still passes, a specific parameter is being blocked (walkthrough §3.1).
- **`scrape_check`** walks one browser store the way a real run does. It prints which
  browser engine launched, which pager was used, and how many listings survived.
- **`diagnose_extraction`** explains a *gap*. It shows:
  - which of the four extraction layers won (walkthrough §3.6);
  - how many rows each layer offers;
  - where the survivors are lost;
  - whether page 2 differs from page 1 at all.

  This matters because `extract()` stops at the first layer that returns anything. So a
  page with five products in a JSON-LD block and twenty-four in the page itself yields
  **five**, and nothing says the other layers were never tried. It prints to the console
  only, so you can paste the output somewhere.
- **`category_check`** asks each feed store's own API how many products are really in each
  configured category. All the stores are checked at once, and the results print in
  the order you named them. A wrong category name then shows up as a visible number, rather
  than a silent zero folded into a total.

Every one of these drives the **shipped** adapter and the **shipped** profile on purpose.
A checker carrying its own private copy of a store's profile could pass while the
collector fails on the same page.

If a browser store keeps returning nothing, its page layout has probably changed. Fix it
from the dashboard: **Fix a broken store**, then Alt+click the card, its title, price and
link (walkthrough §3.16).

---

## 3. After a collection: checking the data

`check_stores.py` asks "does each shop still scrape?". This asks "is what was saved
right?":

```
uv run python scripts/check_data.py
```

```
store            listings   cut  bad price  no INR  ungrouped
amazon_in             761     0          0       0          1
flipkart              196     0          0       0          0
...
1342 games, 262 of them compared across 2+ stores.
Watched games with no offer today: 0

OK
```

It exits with code 1 if anything in the **cut** or **bad price** column is not zero. Pass
`--db path\to\tracker.db` to check a copy instead of the app's own database.

| Column | What a non-zero number means | What to do |
|---|---|---|
| **cut** | Titles the shop cut short ("…Nintendo Swit...") among listings it showed in its latest run. The scraper reads the full name from the card when the page has it (walkthrough §3.18), so this means a shop cuts titles a different way. | Tell a developer the store id. Note: a listing cut in an older run is repaired the next time the shop shows it, so only current listings count. |
| **bad price** | A latest price of zero or less. Never right. Note: a listing the shop has since removed is NOT counted as buyable. If a store's latest *fully successful* run didn't include it, it no longer wins "best price" and no longer counts as in stock. A partial or failed run never does this, because it may simply not have reached the listing. | `uv run python scripts/check_stores.py <store>` to see what the page offers now. |
| **no INR** | A price with no rupee figure: an import store and no exchange rate stored yet. Recording no number is deliberate (walkthrough §3.10). | Press **Update exchange rate**. |
| **ungrouped** | Listings the matcher couldn't key, usually because the title is all console words ("Nintendo Switch Game"). | Usually nothing. Such listings still appear in **Every listing**. |
| **compared across 2+ stores** | Not a problem, just the number to watch. If it drops sharply after a change, grouping got worse. | |
| **Watched games with no offer today** | Informational. Usually the game is sold out or gone everywhere. A watch whose game was regrouped under a new name follows it automatically (walkthrough §3.18). | Nothing, unless you expected offers: then find the game in **Games** and watch it from there. |

**Two copies of one game in two rows?** That's a missed merge, which is deliberate: the
matcher errs towards splitting. Create `matches.local.json` in your data folder, pasting
titles exactly as the dashboard shows them:

```json
{ "Zelda: Tears of the Kingdom": "The Legend of Zelda: Tears of the Kingdom" }
```

Then regroup. It takes seconds and never re-scrapes. This one does write, but only the
grouping, never prices:

```
uv run python -m switch_tracker match
```

With the standalone app, use `switch-tracker.exe match`.

---

## 4. Checking a build

```
uv run python -m switch_tracker spike
```

This checks the four things that work in development but break only after packaging:
certificates, the bundled templates, the web server, and the Playwright driver. It prints
where it stopped. Run it from source first: a failure there is about this machine, not
the build. For example, on a network that intercepts HTTPS with its own certificate, the
certificate check fails the same way from source and from the exe.

For a built app, double-click **`CHECK.bat`**. It runs the packaged app's self-check and
keeps the window open. (Double-clicking the exe itself makes the window flash and vanish
when it exits. That's Windows closing the console, not a crash.)

**The code's own tests** need no network and never touch your data:

```
uv run pytest
```

They run in parallel, one worker per CPU core: about 1.5 minutes on 8 cores, against 4.5
one at a time. If a single test misbehaves only in parallel, or you want to see its
`print` output, run it on its own with `-n 0`:

```
uv run pytest tests/test_parse.py -n 0 -s
```

If the exe shows a bug that's fixed in the source, the build is older than the source.
Run `scripts/check_stores.py <store>` from source; if that passes, rebuild with
`BUILD-EXE.bat`.

---

## 5. When it doesn't work

| Symptom | What's actually happening | Fix |
|---|---|---|
| Dashboard opens, everything empty | The app auto-collects **once**, only to bootstrap an empty database (walkthrough §3.15). After that it never starts a run by itself. | Press **Collect prices**. |
| **Moved since last run** is always empty | It needs two runs to compare. | Collect again later. |
| One store tile says 0 listings | Expected failure mode, and the reason is on the tile. Screenshots and HTML land in `<data dir>/diagnostics/`. | `scripts/scrape_check.py <store>`, then **Fix a broken store** (walkthrough §3.16). |
| **CeX India** says 0 listings | Known and expected, not a regression. Its four selector lists ship as **unverified guesses**: CeX is a client-rendered Nuxt/Algolia app whose real DOM has never been captured, so the profile was written to fail loudly into a diagnostics dump rather than to be trusted. | `scripts/scrape_check.py cex_in --headful`, read `<data dir>/diagnostics/cex_in.html`, then **Fix a broken store** (walkthrough §3.16). |
| The `.exe` shows a bug the walkthrough says is fixed | The packaged build is older than the source. Several reports (HG World's *"no parseable JSON"*, Flipkart continuing past a failed page without the retry line, `+0.0` in the Change column) turned out to be fixed in the repo and reproducible only in a stale build. | Run `scripts/check_stores.py <store>` from source first. If that passes, rebuild with `BUILD-EXE.bat`. |
| A feed store fails with `no parseable JSON` or `no Store API at either known path` | The shop changed platform or domain. Real cases: gameloot and designinfo moved from Shopify to WooCommerce; emartgames moved from emartgames.in (which no longer resolves) to emartgames.com. | `uv run python scripts/check_stores.py <store> --probe`. Look for `x-wp-total` (WooCommerce answers) and a 404 on `/products.json` (not Shopify any more). `getaddrinfo failed` means the domain itself is gone: find the shop's new address in a browser. Pressing **Check stores** corrects the kind on your PC; a new domain or category needs a change in `config/stores.py`. |
| A WooCommerce store ends **Partial** with `ReadTimeout` on one page | A page of 100 products is a heavy request for a slow shop, and HG World is read unscoped (about 1,700 products). A page that times out on every retry is asked for again as four pages of 25. If even that fails, just that page is skipped and the walk carries on, as long as the shop's own count says more products exist. The walk also stops itself after 300 s and keeps what it has: the collector's 360 s deadline would cancel the store and keep nothing. | Usually nothing. If the same store is Partial on every run, `check_stores.py <store>` shows which page. |
| **HG World** fails with `HTTP 403` | Cloudflare blocks the Store API's `category=` filter on that host (walkthrough §3.1). If it says *"no parseable JSON"* instead, a stale correction is making it use the Shopify adapter (walkthrough §3.16). | Make sure `stores.py` has no `collections` for it. Press **Reset corrections**, then **Check stores**. `check_stores.py hgworld --probe` shows exactly which requests are refused. |
| **Flipkart** logs `ERR_TOO_MANY_REDIRECTS` on a page | A session-level self-redirect, not a bad URL (walkthrough §3.7). The page is retried after a pause, skipped if that fails too, and retried once more after the walk. | Usually nothing to do. If the store ends **Partial**, read `diagnostics/flipkart-p<N>-navigation.json` for the hop-by-hop trace. |
| Sorting by **Change** shows far fewer listings | Intended. That sort only lists real movers: listings with a previous price that moved by more than 1% (walkthrough §3.11). | Sort by anything else to see everything again. |
| A price changed a little and the Change column says `—` | Moves of 1% or less are treated as noise and not reported, in the column or the movers panel (walkthrough §3.11). | Nothing. `MIN_CHANGE_PCT` in `web/queries.py` is the knob. |
| One game shows as two rows in **Games** | A missed merge: the two shops spell it differently enough that the keys differ ("The Legend of Zelda: …" vs "Zelda: …"). Deliberate — the matcher errs towards splitting (walkthrough §3.18). | Add `{"one title": "the other title"}` to `matches.local.json` in the data dir, then run `switch-tracker match`. |
| **Games** is empty but **Every listing** is not | The listings were never grouped: nothing has run the matcher since they were collected. | Restart the dashboard (it groups once on startup), or run `switch-tracker match`. |
| A watched game is under target but not marked **at target** | Its cheapest offer is out of stock. A hit needs an offer you can actually buy (walkthrough §4.6). | Nothing. Expand the game's row to see the out-of-stock offer. |
| The daily collection didn't run | It catches up the next time the PC is on, but skips if a collection already succeeded since that day's scheduled time (walkthrough §3.19). Or the stores were never checked, so `collect-now` exits with code 2. A task registered *before* the catch-up change has no catch-up; run `schedule --at` again to replace it. | In *Task Scheduler*, find "switch-tracker daily collection" and read its *Last Run Result* (`0x2` means not checked yet). Press **Check stores** once if needed. |
| `This dashboard only answers to its own address` or `Changes can only be made from the dashboard page itself` (403) | The cross-site guard (walkthrough §1.4) refused the request. You opened the dashboard under an address it doesn't recognise, or something other than the dashboard page sent the change. | Open it as `http://127.0.0.1:<port>` or `http://localhost:<port>`, with the port the console printed. |
| `A run is already going` (409) | One run at a time, enforced in the database, not the UI (walkthrough §3.12). | Wait for it, or restart the app — a dead worker's run is reaped on startup. |
| `'collect' is started by the dashboard, not run directly` | You ran a worker by hand without `--run-id`. Workers report into an existing run. | Use the dashboard, or `scripts/scrape_check.py` for one store. |
| `Address already in use` on startup | Something else has port 4173 — often an earlier copy still running. | Close the other copy, or set `PORT` to another number, the same way as `TRACKER_DATA_DIR` in [§1](#1-before-you-start). |
| `Executable doesn't exist … playwright install` | The browser engine was never downloaded. It is a ~400 MB download, not a Python package (walkthrough §1.8). | `uv run playwright install chromium` |
| `ModuleNotFoundError` | Packages not installed, or you ran `python` instead of `uv run python`. | `uv sync`, then prefix commands with `uv run`. |
| A warning about OneDrive | Real hazard, not pedantry: the sync client locks the database mid-write and can corrupt it. | Move the folder, or set `TRACKER_DATA_DIR` to a local path. |
| You deleted `tracker.db` and it still behaves oddly | The database is **three** files (walkthrough §1.6). | Delete `tracker.db-wal` and `tracker.db-shm` too. |
| Wrong prices, or non-games (joysticks, bags, a ₹0 listing), left over from an older version | Filter and matching fixes apply to new collections only. A non-game the old rules let in just stops being collected and lingers out of stock, and before the shared-SKU fix one listing could record prices from several products. Neither can be separated out afterwards: the database doesn't store whether a listing is a game, and a mixed history has no marker. So start a fresh database instead of purging rows. | Close the dashboard. In the data dir, move `tracker.db`, `tracker.db-wal` and `tracker.db-shm` into a folder named `old` (moving keeps them recoverable). Start the dashboard: it builds a new database and collects once. Kept: `watchlist.local.json`, `matches.local.json`, `stores.local.json`, `profiles.local.json` and `settings.json`. Lost: price history and lowest-ever prices. Afterwards, open **Watchlist**: re-add any watch that no longer finds its game, because one saved under an old shortened title loses its redirect along with the old database. |
| Something is stuck and you want a clean slate | Nothing in the project folder holds state (walkthrough §0.4). | Delete the data directory, or just use a fresh `TRACKER_DATA_DIR`. |
