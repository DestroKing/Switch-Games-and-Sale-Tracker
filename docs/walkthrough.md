# switch-tracker — a complete walkthrough

**Who this is for:** someone who has never used Python, FastAPI, SQLite, Playwright or
any of the rest of it. Every term is explained the first time it appears, and
**Appendix A is a glossary** you can jump to from anywhere.

**What the program does, in one sentence:** it visits twenty-four online shops — twenty-three
Indian retailers plus Play-Asia for import comparison — finds every physical Nintendo
Switch game they sell, records the price, and does that again later so you can see what
changed.

## How to read this

| If you are… | Read |
|---|---|
| **new to all of this** | Part 0, then Part 1, then straight through. Roughly two hours. |
| **a programmer, new to this codebase** | §0.3 and §0.5, then Part 2 *including the trace at its end*, then dip into Part 3. Half an hour. |
| **here to change one thing** | §0.2, then **Appendix B**, then the one §3.x section about the thing you're changing. |
| **stuck, right now** | [`troubleshooting.md`](troubleshooting.md). |

Part 1 does not depend on Part 3, every section names the files it is about, and every
cross-reference looks like §3.4 — so skipping around is safe.

## Contents

- **[Part 0 — Orientation: what you're looking at](#part-0--orientation-what-youre-looking-at)**
  - [0.1 What it is, physically](#01-what-it-is-physically)
  - [0.2 Run it once](#02-run-it-once)
  - [0.3 Where the code lives](#03-where-the-code-lives)
  - [0.4 Where your data lives](#04-where-your-data-lives)
  - [0.5 The whole system on one page](#05-the-whole-system-on-one-page)
  - [0.6 Seven words you need before Part 1](#06-seven-words-you-need-before-part-1)
- **[Part 1 — The tech stack](#part-1--the-tech-stack)**
  - [1.1 Python 3.12 — the language](#11-python-312--the-language)
  - [1.2 uv — the package manager](#12-uv--the-package-manager)
  - [1.3 FastAPI — the web framework](#13-fastapi--the-web-framework)
  - [1.4 uvicorn — the web server](#14-uvicorn--the-web-server)
  - [1.5 Jinja2 — the templating engine](#15-jinja2--the-templating-engine)
  - [1.6 SQLite — the database](#16-sqlite--the-database)
  - [1.7 httpx — the HTTP client](#17-httpx--the-http-client)
  - [1.8 Playwright — browser automation](#18-playwright--browser-automation)
  - [1.9 Plain CSS + plain JavaScript — the front end](#19-plain-css--plain-javascript--the-front-end)
  - [1.10 Server-Sent Events — live progress](#110-server-sent-events--live-progress)
  - [1.11 PyInstaller — packaging](#111-pyinstaller--packaging)
  - [1.12 pytest — the test framework](#112-pytest--the-test-framework)
  - [1.13 ruff — linting and formatting](#113-ruff--linting-and-formatting)
  - [1.14 mypy (strict) — static type checking](#114-mypy-strict--static-type-checking)
  - [1.15 Frankfurter / ECB — exchange rates](#115-frankfurter--ecb--exchange-rates)
  - [Stack summary](#stack-summary)
- **[Part 2 — The one architectural idea](#part-2--the-one-architectural-idea)**
  - [The problem](#the-problem)
  - [The answer: the program launches itself](#the-answer-the-program-launches-itself)
  - [Why this shape won](#why-this-shape-won)
  - [Three things this buys you, free](#three-things-this-buys-you-free)
  - [And it's enforced by a test](#and-its-enforced-by-a-test)
  - [The trace — one press of *Collect prices*, end to end](#the-trace--one-press-of-collect-prices-end-to-end)
- **[Part 3 — Feature by feature](#part-3--feature-by-feature)**
  - [3.1 The store list, and the corrections layer](#31-the-store-list-and-the-corrections-layer)
  - [3.2 Three ways to read a shop](#32-three-ways-to-read-a-shop)
  - [3.3 Deciding what's a game — the sieve](#33-deciding-whats-a-game--the-sieve)
  - [3.4 Reading a price — where the real bugs live](#34-reading-a-price--where-the-real-bugs-live)
  - [3.5 SKUs — forty lines that decide whether the project works](#35-skus--forty-lines-that-decide-whether-the-project-works)
  - [3.6 Scraping a page — the four-layer ladder](#36-scraping-a-page--the-four-layer-ladder)
  - [3.7 Knowing when to stop turning pages — and when not to](#37-knowing-when-to-stop-turning-pages--and-when-not-to)
  - [3.8 Turning the page when there's no URL to go to](#38-turning-the-page-when-theres-no-url-to-go-to)
  - [3.9 Per-shop quirks, without per-shop code](#39-per-shop-quirks-without-per-shop-code)
  - [3.10 Exchange rates — and the null that matters](#310-exchange-rates--and-the-null-that-matters)
  - [3.11 Saving the data — and the query that had to be rewritten](#311-saving-the-data--and-the-query-that-had-to-be-rewritten)
  - [3.12 Making sure two runs can't collide](#312-making-sure-two-runs-cant-collide)
  - [3.13 Watching progress live](#313-watching-progress-live)
  - [3.14 Collecting from just some shops](#314-collecting-from-just-some-shops)
  - [3.15 Collecting once, not every launch](#315-collecting-once-not-every-launch)
  - [3.16 The self-repair tools](#316-the-self-repair-tools)
  - [3.17 Shipping it as an .exe](#317-shipping-it-as-an-exe)
  - [3.18 Matching one game across shops](#318-matching-one-game-across-shops)
  - [3.19 Collecting on a schedule](#319-collecting-on-a-schedule)
- **[Part 4 — The interface, feature by feature](#part-4--the-interface-feature-by-feature)**
  - [4.1 The design system](#41-the-design-system)
  - [4.2 Status, and why colour is never alone](#42-status-and-why-colour-is-never-alone)
  - [4.3 The dashboard, top to bottom](#43-the-dashboard-top-to-bottom)
  - [4.4 The listings table](#44-the-listings-table)
  - [4.5 Games, offers and price history](#45-games-offers-and-price-history)
  - [4.6 The watchlist](#46-the-watchlist)
  - [4.7 Filters](#47-filters)
  - [4.8 Every state a view can be in](#48-every-state-a-view-can-be-in)
  - [4.9 Accessibility, measured](#49-accessibility-measured)
  - [4.10 What was deliberately NOT done](#410-what-was-deliberately-not-done)
- **[Part 5 — The five ideas that recur](#part-5--the-five-ideas-that-recur)**
- **[Part 6 — What is still not built](#part-6--what-is-still-not-built)**
  - [Where to start reading](#where-to-start-reading)
- **[Appendix A — Glossary](#appendix-a--glossary)**
- **[Appendix B — Working on the code](#appendix-b--working-on-the-code)**
  - [B.1 The gate — what must pass before anything is done](#b1-the-gate--what-must-pass-before-anything-is-done)
  - [B.2 Testing against a real shop](#b2-testing-against-a-real-shop)
  - [B.3 Where the tests for X live](#b3-where-the-tests-for-x-live)
  - [B.4 Your first change — a guided exercise](#b4-your-first-change--a-guided-exercise)
  - [B.5 Things that will surprise you](#b5-things-that-will-surprise-you)
- **[Appendix C — When it doesn't work](#appendix-c--when-it-doesnt-work)**


---

# Part 0 — Orientation: what you're looking at

Nothing in Part 1 will land until you have seen the thing run once. This part takes
about fifteen minutes, and after it you will know what the program is, where every
file lives, and where your data goes.

## 0.1 What it is, physically

It is **one Python program** of roughly 60 source files that you start with one
command. It has no server to deploy, no account to create, no cloud anything. When it
runs you get:

- a **web page** at `http://127.0.0.1:4173` (the *dashboard*), reachable only from your
  own machine, and
- a **single database file** on your disk that grows a little every time you press
  **Collect prices**.

That's the whole product. Everything else in this document is about how those two
things are built.

## 0.2 Run it once

**Windows.** Double-click `START.bat`. The first run downloads Python, the packages and
a browser engine — 10–20 minutes, about 1 GB — and every run after that goes straight to
the dashboard. (Read the README's *Getting started* first: there are two Windows
gotchas, OneDrive and the "Unblock" checkbox.)

**macOS / Linux**, three commands:

```bash
uv sync                              # install Python packages into .venv/
uv run playwright install chromium   # download the browser engine (~400 MB, once)
uv run python -m switch_tracker      # start the dashboard
```

Then open `http://127.0.0.1:4173` and press **Collect prices**. Progress appears live in
the console panel; the first run takes a while because it visits two dozen real
websites politely, one request at a time per site.

Three things worth noticing while it runs, because each one is a design decision
explained later:

| What you see | Where it's explained |
|---|---|
| The page stays responsive, and closing the tab does not stop the run | Part 2 |
| A store tile can say "0 listings" **with a reason**, instead of just failing | §3.2 |
| **Moved since last run** stays empty until you have collected twice | §3.11 |

If something goes wrong, jump to [`troubleshooting.md`](troubleshooting.md).

## 0.3 Where the code lives

`uv run python -m switch_tracker` runs `src/switch_tracker/__main__.py`. Start there; it
is 180 lines and it decides everything else. The rest of the tree:

```
src/switch_tracker/
├── __main__.py         THE FRONT DOOR. Reads argv, picks one of five roles (Part 2).
├── paths.py            The only code allowed to decide where a writable file goes (§3.17).
├── settings.py         Port, headful, collect-on-launch. Deliberately tiny.
├── selection.py        Encode/decode "collect only these stores" (§3.14).
├── resources.py        Reads BUNDLED read-only files, works frozen or not (§3.17).
├── spike.py            Self-check for the four things that break only after packaging.
├── schedule.py         collect-now, and the daily scheduled task (§3.19).
│
├── config/             WHICH SHOPS EXIST
│   ├── stores.py         The twenty-four shops, hand-written (§3.1).
│   └── overrides.py      Merges in the corrections probe wrote (§3.1).
│
├── core/               THINGS EVERYTHING ELSE USES
│   ├── models.py         The vocabulary: StoreConfig, RawListing, Ok/Partial/Failed (§3.2).
│   ├── db.py             SQLite connection, schema, WAL settings (§1.6, §3.11).
│   ├── http.py           The polite HTTP client: one request at a time per host (§1.7).
│   ├── parse.py          Is it a game? What platform? What price? (§3.3, §3.4).
│   ├── skus.py           The stable product id — 40 load-bearing lines (§3.5).
│   └── concurrency.py    bounded_gather: run N things at once, no more.
│
├── adapters/           HOW TO READ A SHOP  (never imported by the dashboard — Part 2)
│   ├── base.py           The shape every adapter must have.
│   ├── registry.py       kind -> adapter.
│   ├── shopify.py        Shops with a /products.json feed.
│   ├── woocommerce.py    Shops with the WooCommerce Store API.
│   └── browser/          Shops with no feed at all: drive real Chrome (§3.6–3.9).
│       ├── adapter.py      The page loop, and the click that must prove it worked (§3.8).
│       ├── extract.py      The four-layer ladder for reading a page (§3.6).
│       ├── pagination.py   When to stop turning pages (§3.7).
│       ├── profiles.py     Per-shop recipes, as DATA not code (§3.9).
│       ├── provider.py     Owns the Chromium instance.
│       ├── overrides.py    Recipes the click-to-pick tool saved (§3.16).
│       └── diagnostics.py  Screenshots/HTML when a shop goes quiet.
│
├── services/           THE FIVE JOBS  (each runs in its own process)
│   ├── collect.py        A collection run: pools, deadlines, saving (§3.11).
│   ├── collect_worker.py Process entry point for `collect`.
│   ├── probe.py          "What does this shop actually run on?" (§3.16).
│   ├── probe_worker.py   Process entry point for `probe`.
│   ├── fx_refresh.py     Process entry point for `fx`.
│   └── inspect.py        The click-to-pick repair tool, in a visible window (§3.16).
│
├── fx/rates.py         USD->INR, and the null it refuses to fake (§3.10).
├── core/matcher.py     Groups listings into games, across shops (§3.18).
├── events/             LIVE PROGRESS: writer appends rows, reader tails them (§3.13).
│
└── web/                THE DASHBOARD  (this half never scrapes)
    ├── app.py            Builds the FastAPI app, starts uvicorn.
    ├── deps.py           Hands a database connection to each route (§1.3).
    ├── queries.py        Every SELECT the page needs (§3.11).
    ├── runs.py           Starts workers; guarantees only one at a time (§3.12).
    ├── errors.py         One shape for every error response.
    ├── watchlist.py      Reads/writes watchlist.local.json (§4.6).
    ├── routers/          The URLs: pages, data, actions, events, watch.
    ├── templates/        The HTML, with Jinja placeholders (§1.5).
    └── static/           app.js and app.css, served as they sit on disk (§1.9).
```

And outside `src/switch_tracker/`:

| Path | What it is |
|---|---|
| `tests/` | 695 tests. `conftest.py` holds the shared setup ("fixtures", §1.12). |
| `scripts/check_stores.py` | **The pre-release sweep.** Run any store, of any kind, against the **live** site and get a verdict, not just a count ([troubleshooting.md](troubleshooting.md) §2). |
| `scripts/scrape_check.py`, `category_check.py`, `diagnose_extraction.py` | Narrower live-site tools: one browser store's walk, feed stores' category slugs, and "why did N rows become M" ([troubleshooting.md](troubleshooting.md) §2). |
| `scripts/check_data.py` | Read-only check of what a collection **saved**: cut titles, bad prices, missing rupee figures, ungrouped listings, games compared across stores ([troubleshooting.md](troubleshooting.md) §3). |
| `packaging/`, `switch_tracker.spec` | Turning it into a Windows `.exe` (§3.17). |
| `START.bat`, `setup.ps1`, `run.ps1` | What a Windows user double-clicks. |
| `docs/` | This file, plus the plan/HLD/LLD written before the code. |

> **If you read only three files:** `__main__.py` (what the program *is*),
> `core/models.py` (the vocabulary), `services/collect.py` (the actual job).

## 0.4 Where your data lives

**Not in the project folder.** Every writable path comes from one function,
`paths.data_dir()`, and §3.17 explains why that matters:

| Platform | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\switch-tracker\` |
| macOS / Linux | `~/.local/share/switch-tracker/` (or `$XDG_DATA_HOME/switch-tracker/`) |
| Anywhere, forced | set `TRACKER_DATA_DIR=/some/path` |

What you'll find in there:

| File | What it holds | Safe to delete? |
|---|---|---|
| `tracker.db` | **All your price history.** | Only if you mean it — this is the data. |
| `tracker.db-wal`, `tracker.db-shm` | SQLite's side files (§1.6). Part of the database. | Delete *with* `tracker.db`, never alone. |
| `backups/` | A copy of the database after **every** collection, newest 7 kept (`core/db.py:backup`). Made with SQLite's `VACUUM INTO`, which copies one consistent snapshot. Copying the file by hand mid-run could tear it, and would miss what's still in the WAL. | Yes, but it's your undo. To restore one, close the app and copy it over `tracker.db`. |
| `stores.local.json` | Corrections **Check stores** wrote (§3.1). | Yes — rebuilt by pressing **Check stores**. |
| `profiles.local.json` | Selectors the click-to-pick tool saved (§3.16). | Yes — but you'll have to re-pick them. |
| `settings.json` | Port, headful, collect-on-launch. | Yes — defaults return. |
| `watchlist.local.json` | Your watched games and target prices (§4.6). | Only if you mean it — targets are typed by hand. |
| `matches.local.json` | Your title aliases for the matcher (§3.18). Optional; you create it. | Yes — games regroup without your aliases. |
| `run.lock` | The pid of a running worker (§3.12). | Yes, when nothing is running. |
| `diagnostics/` | Screenshots and HTML from stores that returned nothing, plus `flipkart-p<N>-navigation.json` redirect traces (§3.7). | Yes, always. |

For experiments, point the whole app somewhere disposable:

```bash
TRACKER_DATA_DIR=/tmp/tracker-scratch uv run python -m switch_tracker
```

## 0.5 The whole system on one page

```
   YOU                                           TWENTY-FOUR SHOPS
    │                                            (nistore, amazon_in,
    │ browser at 127.0.0.1:4173                    flipkart, playasia, …)
    ▼                                                      ▲
┌────────────────────────┐                                 │ HTTP, or a real
│  DASHBOARD process     │   starts a second copy          │ Chrome window
│  `switch-tracker`      │   of ITSELF, then forgets it    │
│                        │ ──────────────────────────▶ ┌───┴────────────────┐
│  • serves the page     │                             │  WORKER process    │
│  • runs SELECTs        │                             │  `… collect`       │
│  • NEVER scrapes       │                             │  • adapters        │
└───────────┬────────────┘                             │  • Playwright      │
            │ reads                                    └───────┬────────────┘
            │                                                  │ writes
            ▼                                                  ▼
        ┌──────────────────────────────────────────────────────────┐
        │  tracker.db   (SQLite, WAL mode: read + write at once)    │
        │                                                           │
        │  store ──< listing ──< price_point      ← the history     │
        │  run ──< run_store                      ← what happened   │
        │      ──< run_event                      ← live progress   │
        └──────────────────────────────────────────────────────────┘
```

Read that diagram twice. **The two processes never speak to each other** — they share a
database file, and that single choice is what Part 2 is about.

## 0.6 Seven words you need before Part 1

Full list in **Appendix A — glossary**. These seven appear immediately:

- **scrape** — read data out of a web page that was built for human eyes, because the
  shop offers no proper data feed.
- **adapter** — the code that knows *one way* of reading a shop. Three exist: Shopify
  feed, WooCommerce API, real browser (§3.2).
- **listing** — one product at one shop. "Zelda at nistore" and "Zelda at gameloot" are
  two listings. The matcher groups them into one **game** (§3.18).
- **price point** — one price for one listing at one moment. Listings get *updated*;
  price points only ever get *appended*. That append-only table is the whole point of
  the program.
- **run** — one press of a button. Every run gets a row in `run`, and everything that
  happens during it is tagged with that run's id.
- **process** — a running program, with its own memory, that the operating system can
  kill without touching anything else. This app deliberately uses two at a time.
- **async** — code that says "wake me when the website answers" instead of sitting idle
  waiting. Written `async def` and `await` (§1.7).

---

# Part 1 — The tech stack

For each choice: *what it is*, *why it was picked*, and *what was rejected*.

## 1.1 Python 3.12 — the language

**What it is.** A programming language known for being readable. The `3.12` is the
version; the project uses features that only exist from 3.12 onward.

**Why.** The project was originally written in TypeScript and deliberately rewritten.
The stated reason was *learning a second stack* — and the design documents are unusually
honest about this. `docs/python-rewrite-hld.md` scored "don't rewrite at all" as a real
option and concluded it was **the better engineering choice**, then rejected it anyway
because it defeated the point of the exercise. That reasoning is written down rather than
hidden, which is the honest way to record a decision made for non-technical reasons.

**Rejected.** Staying on TypeScript/Bun (cheaper, and its compiler already existed); Java
(the author already knows it professionally, so it teaches nothing new).

**What "3.12 only" buys.** Two things you'll see in the code:
- `type` parameters on functions — `async def bounded_gather[T, R](...)` in
  `core/concurrency.py`. The `[T, R]` says "this function works with any type, and the
  type that goes in is the type that comes out". Older Python needed three lines of
  boilerplate for that.
- `StrEnum` — a list of allowed values that is also a string. `Platform.SWITCH` behaves
  like the text `"SWITCH"` when written to the database, but a typo like
  `Platform.SWICH` fails immediately instead of silently storing nonsense.

## 1.2 uv — the package manager

**What it is.** Software depends on other software ("packages" or "dependencies"). A
package manager downloads them and records exactly which versions you used, so the same
code behaves the same on another machine. `uv` is a modern, very fast one.

**Why.** Two files do the work: `pyproject.toml` lists what the project needs
(`fastapi>=0.115`), and `uv.lock` records the *exact* versions actually installed. Anyone
running `uv sync` gets a byte-identical environment.

**One local wrinkle, so you don't go hunting.** In *this* repository `uv.lock` is
deliberately **not** committed — the reason is spelled out in `.gitignore`. It was
generated behind a private package mirror, so it pins hundreds of index URLs that
resolve nowhere else, and `uv sync` then fails with connection errors that look like a
broken project. `pyproject.toml` bounds every version instead, and each machine resolves
its own. The guarantee above is what a *committed* lockfile buys you; here the trade was
made consciously.

**Rejected.** `pip` — the traditional tool. It installs packages but does **not** by
itself record exact versions, so two machines can end up with different code. Poetry does
lock versions but is much slower.

**Why it mattered here.** Earlier in this project `playwright-stealth` was imported by the
code but never *declared* in `pyproject.toml`. It worked on the machine where someone had
installed it by hand, and the whole test suite failed to even start anywhere else. The
fix was `uv add playwright-stealth`, which updates the declaration and the lockfile
together. A plain `pip install` would have fixed that one machine and left the next
`uv sync` to silently uninstall it again.

## 1.3 FastAPI — the web framework

**What it is.** The dashboard is a web page. Something must listen for requests from the
browser ("give me the listings") and answer them. A *web framework* is the library that
turns "a request arrived at `/api/listings`" into "call this Python function".

You'll see this pattern all over `web/routers/`:

```python
@router.get("/summary")
def summary(conn: Conn) -> dict[str, int]:
    return queries.summary(conn)
```

The `@router.get("/summary")` line is a **decorator** — it attaches a label to the
function below it, saying "run this when a browser asks for `/summary`".

**Why FastAPI.** Three reasons that matter here:
1. It reads the **type annotations** you already wrote and enforces them. In
   `routers/data.py`, `limit: int = Query(default=100, ge=1, le=500)` means a request
   asking for a million rows is rejected by the framework before your code runs.
2. It is **async-native** (see §1.7) — important because this app waits on slow websites.
3. It supports **streaming responses**, which is how live progress reaches the page (§1.10).

**Rejected.** Flask — simpler and very popular, but synchronous by default and does not
validate types. Django — a much bigger framework built around its own database layer and
admin site; almost all of it would be unused here.

**Dependency injection.** You'll see `conn: Conn` as a parameter. `Conn` is defined as
`Annotated[sqlite3.Connection, Depends(get_conn)]`, which tells FastAPI: *"before calling
this function, run `get_conn()` and pass the result in."* The function never has to know
where the database connection comes from — which is what lets the tests swap in a
throwaway database with one line.

## 1.4 uvicorn — the web server

**What it is.** FastAPI describes *what* to do with a request. Something still has to open
a network port and speak HTTP. That's uvicorn.

**Why it's worth mentioning.** One line in `web/app.py` carries a hard-won lesson:

```python
uvicorn.run(app, host="127.0.0.1", port=config.port, log_level="warning")
```

- `host="127.0.0.1"` means **this machine only**. Not reachable from your network. This
  is a personal tool with no login; binding it to `0.0.0.0` would expose it to anyone on
  your Wi-Fi.
- Passing `app` (the actual object) rather than the string `"module:app"` — the string
  form asks uvicorn to *find* the code by name, which does not work once the app is
  packaged into a single `.exe`. The comment in the file says exactly this.

**Binding to 127.0.0.1 keeps out other machines, but not other websites.** That
distinction took a security review to surface, and it's worth understanding because it
catches most local tools. Two attacks pass a loopback bind:

- **Cross-site requests.** Any web page you visit can make *your* browser send a
  form-style POST to `http://127.0.0.1:4173/actions/collect`, or to `/reset-corrections`.
  A "simple" cross-site POST needs no permission check from the browser, so it lands
  and runs, even though the attacking page can never read the reply.
- **DNS rebinding.** A hostile hostname that later resolves to `127.0.0.1` makes the
  attacker's page *same-origin* with the dashboard, so it can read every `/api/*`
  response.

`web/guard.py` closes both with plain middleware that runs before routing:

| Check | Applies to | Stops |
|---|---|---|
| `Host` must be exactly `127.0.0.1:<port>` or `localhost:<port>` | every request | DNS rebinding (the rebound page sends *its* hostname) |
| `Origin` must equal `http://<that Host>`; a **missing** Origin is refused | every POST/PUT/DELETE | cross-site requests (browsers always send Origin on these) |
| `Sec-Fetch-Site`, when present, must be `same-origin` | every POST/PUT/DELETE | the same, from the browser's own account of where a request came from |

GETs are checked by Host only, because a plain page load sends no Origin. That puts one
rule on every route instead: **a GET must never change anything.** The app never sends
CORS headers, and a test asserts it. Another test walks the app's whole route list and
fires a forged request at every state-changing route, so a route added later is covered
without anyone remembering to.

The tests act as the real page does, with its own Host and Origin. **There is no switch
that turns the guard off for tests**, because a switch like that is exactly what ends up
left on.

## 1.5 Jinja2 — the templating engine

**What it is.** A way to build HTML with placeholders. `templates/index.html` contains:

```html
{% for store in collectable %}
<label class="check"><input type="checkbox" value="{{ store.id }}"> {{ store.name }}</label>
{% endfor %}
```

`{% for %}` loops; `{{ }}` inserts a value. Python passes in a list of stores and Jinja
produces one checkbox per store.

**Why.** It ships with FastAPI's ecosystem and **escapes HTML by default** — if a store
were named `<script>`, Jinja writes it as harmless text rather than letting it run.

**Rejected.** Building HTML by joining strings in Python (easy to get wrong, and unsafe).
A JavaScript framework (see §1.9).

## 1.6 SQLite — the database

**What it is.** A database stores data in a structured way you can query. Most databases
(PostgreSQL, MySQL) are *servers*: separate programs you install, configure and keep
running. **SQLite is a single file.** Your whole database is `tracker.db`, and the
"database software" is a library inside your program.

**Why.** This is a personal tool for one person on one machine. A database server would
mean installation, a service to keep running, and a password to manage — for one user.
SQLite means the app is a folder you can copy, and your data is a file you can back up by
dragging it.

**Rejected.** PostgreSQL/MySQL (a server to run, for one user); JSON files (no querying,
no transactions, and rewriting the whole file on every change corrupts easily); an ORM
like SQLAlchemy — a library that hides SQL behind Python objects. Rejected because the
interesting logic here *is* the SQL, and hiding it made the performance problem in §3.11
invisible.

**Two SQLite settings in `core/db.py` worth understanding:**

```python
conn.execute("PRAGMA journal_mode = WAL")
```
**WAL** = Write-Ahead Logging. Normally, writing to SQLite locks the file so nobody can
read. WAL writes changes to a side file first, so **readers and writers work at the same
time**. This project needs that: the dashboard reads the database *while* a scraping
process writes to it. It also means the database is really three files — `tracker.db`,
`tracker.db-wal` and `tracker.db-shm` — which matters if you ever delete it by hand.

```python
conn.execute("PRAGMA busy_timeout = 5000")
```
If a write is in progress, wait up to 5 seconds rather than failing instantly.

## 1.7 httpx — the HTTP client

**What it is.** Code that fetches a web address, like a browser does but without display.

**Why httpx, and why "async".** Fetching a web page takes maybe a second, almost all of it
spent *waiting* for the far end. Normal ("synchronous") code sits idle during that wait.
**Asynchronous** code says "wake me when the reply arrives" and does something else
meanwhile. Two dozen shops fetched one after another takes two dozen seconds of mostly
waiting; fetched concurrently it takes about as long as the slowest one.

You'll see this as `async def` and `await`:

```python
async def get(self, url: str) -> HttpResult:
    response = await client.get(url, headers=request_headers)
```

`await` means "pause here, let other work run, resume when this finishes".

**Rejected.** `requests` — the most popular Python HTTP library, but synchronous only.

**The politeness layer.** `core/http.py` wraps httpx in a `PoliteClient` that allows only
**one request at a time per website**, with a **1.2 second gap** between them. These are
small independent shops. The comment is blunt about why: *"it keeps us off anyone's block
list."* Note the design detail — a lock alone would serialise requests but not space them
out, so the class also remembers when it last called each host.

## 1.8 Playwright — browser automation

**What it is.** Some shops publish their catalogue as raw data you can fetch directly.
Others build the page **in the browser** using JavaScript — fetch their address with httpx
and you get an empty shell. For those, you need a real browser. Playwright starts an
actual Chrome, loads the page, waits for the JavaScript to run, and lets you read the
result.

**Why Playwright.** Modern, maintained by Microsoft, and — critically — it can run code
*inside* the page and pass values back to Python. That capability is what makes the
click-to-pick tool (§3.13) possible at all.

**Rejected.** Selenium — the old standard; clunkier and needs a separately-managed driver.
BeautifulSoup — parses HTML but cannot *run* JavaScript, so the pages that need a browser
would still be empty.

**The cost, stated plainly.** Playwright is not a normal library: it ships a Node.js
program and downloads a ~400 MB browser. That single fact dominates the packaging story
(§1.11) and is why the browser scraping runs in a **separate process** (§2).

## 1.9 Plain CSS + plain JavaScript — the front end

**What it is.** Three files, served exactly as they sit on disk:

| File | Lines | Job |
|---|---|---|
| `web/templates/index.html` | ~220 | The shell the server renders once |
| `web/static/app.css` | ~760 | The design system (Part 4) |
| `web/static/app.js` | ~1,130 | Everything that happens after load |

**Why not React.** React, Vue and Svelte all need a **build step** — a toolchain that
compiles your source into files a browser can load. That means Node.js, a package
manager, a bundler, and a new stage in the packaging process, all to render one table
and six buttons for one user on one machine. These three files need none of it, which is
also why `switch_tracker.spec` can bundle them by copying.

**The trade-off, honestly.** State is managed by hand. `app.js` holds two small state
objects — `run` (what the current collection is doing) and `state` (what the table is
filtered to), plus the watchlist — and functions that repaint from them. That is a
pattern that stops scaling somewhere around "several interacting views". This app now
has two table views, expandable detail rows and a watchlist whose ☆ buttons appear in
the table, and `app.js` has grown from ~740 to ~1,130 lines. That's still manageable,
because every one of those reads from one state object and binds one delegated listener
per container (§4.5). But it is the honest place to reconsider if a third view arrives.

**The rule that keeps it honest.** Every repaint reads from those objects, never from
the DOM. The temptation in framework-free code is to ask the page what it currently
shows — `document.querySelectorAll('.js-store:checked')` and so on. Do that for
*display* state and the screen slowly drifts out of sync with the thing it is
describing, because you are now parsing text you printed yourself.

## 1.10 Server-Sent Events — live progress

**What it is.** A collection run takes minutes. The page needs to show progress as it
happens. Three ways to do that:
- **Polling** — the page asks "done yet?" every second. Simple, wasteful, laggy.
- **WebSockets** — a permanent two-way channel. Powerful, and more machinery than needed.
- **Server-Sent Events (SSE)** — the server holds one connection open and pushes text
  down it. One-way, built into every browser, no library.

**Why SSE.** Progress only flows one way. And browsers **reconnect SSE automatically**,
remembering the last message id they received — which the design leans on heavily (§3.10).

**What it looks like on the wire** (`web/routers/events.py`):

```
id: 42
event: store_progress
data: {"store_id": "playasia", "page": 3, "count": 105}
```

## 1.11 PyInstaller — packaging

**What it is.** Turns a Python project into a folder containing a `.exe` that runs on a
machine with no Python installed.

**Why this is hard here.** PyInstaller bundles Python code. Playwright is not just Python
— it's a Node.js program plus a browser binary, both found *on disk at runtime*. Neither
survives naive bundling. `docs/python-rewrite-hld.md` scored five different ways of
handling this and notes the same wall was hit in the TypeScript version, so it isn't a
Python problem.

**The chosen approach.** Bundle Chromium inside the folder and point Playwright at it with
an environment variable set *before* Playwright is first imported. That "before" is why
`packaging/runtime_hook_playwright.py` exists — a **runtime hook** is code PyInstaller runs
at startup ahead of everything else.

**Rejected.** Downloading the browser on first run (fails behind a corporate firewall);
using whatever browser the machine has (three code paths, and Chrome auto-updates out of
sync with Playwright); dropping Playwright (loses 10 of 24 stores).

## 1.12 pytest — the test framework

**What it is.** Tests are code that checks other code. `pytest` finds and runs them.

**Why.** The standard, and its **fixtures** are the reason. A fixture is a named piece of
setup a test can request just by naming it as a parameter:

```python
def test_filters_by_platform(self, conn):        # asks for `conn`
    result = queries.listings(conn, ...)
```

pytest sees `conn`, finds the fixture called `conn`, builds a fresh throwaway database,
and passes it in. Each test gets its own — no test can pollute another.

**Rejected.** `unittest` (in the standard library, but requires class boilerplate for what
fixtures do in one line).

**Two notable things in this suite:**
- `pytest-asyncio` — lets tests `await` things, needed because most of this code is async.
- The HTTP tests run against a **real local web server** started by a fixture, not a fake.
  `tests/conftest.py` explains why: redirect-following and the politeness delay are
  properties of the real client on a real socket. A fake would let both silently break.

## 1.13 ruff — linting and formatting

**What it is.** A *linter* reads your code and flags problems that aren't errors — an
unused import, a line too long, a suspicious pattern.

**Why.** ruff replaces four separate tools (flake8, isort, pyupgrade, and more) with one,
and is fast enough to run constantly. `pyproject.toml` enables specific rule families,
including `BLE` — "blind except" — which flags any code that catches *every possible
error*. That is usually a bug, and this codebase does it deliberately in about a dozen
places, each with a comment saying why.

## 1.14 mypy (strict) — static type checking

**What it is.** Python does not normally check types. You can pass a string where a number
was expected and only find out when it crashes. mypy reads the annotations and checks them
before you run anything.

**`strict` means it refuses to let anything go unchecked** — every function must be
annotated, no silently-untyped values.

**Why it earns its place.** A concrete example from this project. This looked fine:

```python
wait_until: str = "domcontentloaded"
```

mypy rejected it: Playwright accepts only four specific values there. The fix makes a typo
impossible:

```python
WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]
```

A misspelling is now caught by the type checker instead of crashing mid-scrape.

## 1.15 Frankfurter / ECB — exchange rates

**What it is.** A free API serving European Central Bank reference rates. No signup, no key.

**Why.** The ECB publishes **on working days only**, so a Saturday fetch returns Friday's
rate. That is correct, not stale — and the code stores the rate's *publication date*
alongside it rather than the time it was fetched. That date is the thing the unbuilt alert
engine will need to tell "this game went on sale" from "the rupee moved" (§5).

## Stack summary

| Layer | Choice | Main alternative rejected | One-line reason |
|---|---|---|---|
| Language | Python 3.12 | TypeScript (incumbent) | Learning a second stack — recorded as a non-technical decision |
| Packages | uv | pip | Locks exact versions; pip alone does not |
| Web framework | FastAPI | Flask, Django | Async-native, validates from type hints, streams |
| Server | uvicorn | gunicorn | ASGI (async) support |
| Templates | Jinja2 | string building | Escapes HTML by default |
| Database | SQLite | PostgreSQL | One file, no server, one user |
| DB access | raw SQL | SQLAlchemy ORM | The SQL *is* the logic here |
| HTTP | httpx | requests | Async; `requests` is sync-only |
| Browser | Playwright | Selenium, BeautifulSoup | Runs page JS; can call back into Python |
| Front end | Vanilla JS | React | No build step for one page |
| Live updates | SSE | WebSockets, polling | One-way, auto-reconnect, no library |
| Packaging | PyInstaller onedir | Docker, onefile | Ships a browser; must be a real folder |
| Tests | pytest | unittest | Fixtures |
| Lint | ruff | flake8 + isort + black | One fast tool |
| Types | mypy strict | none | Catches whole classes of bug before running |
| FX | Frankfurter/ECB | paid APIs | Free, no key, dated rates |

---

# Part 2 — The one architectural idea

Everything else follows from this, so it's worth getting straight before the features.

## The problem

Scraping is slow (minutes) and fragile (a browser can hang). A dashboard must stay
responsive. If both live in the same program, one bad website freezes the whole app.

## The answer: the program launches itself

`switch-tracker` is one executable with **five personalities**, chosen by a command-line
argument (`__main__.py`):

| Command | Role |
|---|---|
| `serve` | the dashboard (default) |
| `collect` | worker: gather prices |
| `probe` | worker: detect what each shop runs on |
| `fx` | worker: refresh exchange rates |
| `inspect` | worker: open a visible browser for the click-to-pick tool |

Four more commands are for you rather than for the dashboard, and they aren't workers.
None of them needs a `--run-id`: `spike` (packaging self-check, §3.17), `match`
(regroup games, §3.18), and `collect-now` / `schedule` (§3.19). `collect-now` is the
interesting one, because it doesn't collect anything itself. It asks the same launcher
the button uses to start a `collect` worker, then waits for it to finish.

When you press a button, the dashboard **starts a second copy of itself** with a different
argument, then goes straight back to serving pages.

```
  Browser tab
      │  POST /actions/collect
      ▼
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  DASHBOARD process   │ spawn   │   WORKER process         │
  │  (serve)             │────────▶│   (collect)              │
  │  • FastAPI + Jinja   │         │  • adapters              │
  │  • reads SQLite      │         │  • Playwright/Chromium   │
  │  • NEVER scrapes     │         │  • writes SQLite         │
  └──────────┬───────────┘         └───────────┬──────────────┘
             │  reads run_event                │ writes run_event
             ▼                                 ▼
          SSE to browser  ◀────────  tracker.db (WAL mode)
```

The two processes never talk directly. They share **a table in the database**. The worker
appends progress rows; the dashboard reads them and forwards them to your browser.

## Why this shape won

Four options were scored in `docs/python-rewrite-hld.md`. The reasoning is worth
understanding because it's the kind of argument that generalises:

- **Run the work inside the streaming response.** Simplest. Fatal flaw: the work is tied to
  the browser connection, so **closing the tab kills a 10-minute scrape**, and refreshing
  starts a second one.
- **Run the work as background tasks inside the dashboard.** Fixes the tab problem. But
  Chromium now lives in the dashboard's process, so a hung browser takes the UI with it.
- **Separate processes** *(chosen)*.
- **Don't rewrite; finish the TypeScript version.** Scored *joint-highest*, and rejected
  only because it defeats the project's stated purpose.

The deciding argument was not elegance. It was this: options 1 and 2 both had to admit
that the click-to-pick tool **cannot** run in-process — it needs a visible browser window.
So a subprocess mechanism was mandatory either way. Making it *uniform* **removes a
special case** instead of adding machinery.

> **The generalisable lesson:** when a design forces one permanent exception, ask whether
> the exception should become the rule.

## Three things this buys you, free

1. **Close the tab.** Nothing is lost — nothing in the browser owns the work.
2. **Refresh.** You rejoin the running job rather than starting a second one.
3. **Restart the whole app.** Progress replays, because it was on disk all along.

## And it's enforced by a test

Architecture written in a document decays. This one is checked mechanically —
`tests/test_import_boundary.py`:

```python
import switch_tracker.web.app          # the dashboard's whole import graph
forbidden = sorted(m for m in sys.modules
    if m.startswith("playwright") or m.startswith("switch_tracker.adapters"))
```

If the dashboard ever *imports* scraping code, the build fails. Note it runs in a
**separate process** — once pytest has loaded the adapters for other tests, checking
in-process would prove nothing.

This test is load-bearing in a way that shows up later: when the subset-collection feature
needed a helper shared by the dashboard *and* the worker, this rule is what forced it into
its own dependency-free module (§3.14).

---

## The trace — one press of *Collect prices*, end to end

Everything above is shape. This is the actual sequence, with the file that does each
step. Follow it with the files open; it is the fastest way to get the codebase into
your head.

```
 browser         DASHBOARD process              db            WORKER process
    │                                                              (does not exist yet)
    │ POST /actions/collect
    ├──────────────▶ actions.collect
    │                     │ validate ids
    │                     ├──▶ runs.RunLauncher.start
    │                     │        ├── reap_stale()
    │                     │        ├── INSERT INTO run ──────▶ (run 7)
    │                     │        ├── spawn ──────────────────────────▶ new process
    │                     │        └── write run.lock (pid)             │
    │ ◀── {"run_id": 7} ──┘                                            │
    │                                                                  │
    │ GET /api/runs/7/events  (stays open)                             │
    ├──────────────▶ events.events                                     │
    │                     │  every 250 ms: SELECT … run_event          │
    │ ◀── id: 1 …         │ ◀──────────────── run_event ◀── INSERT ────┤ progress
    │ ◀── id: 2 …         │                                            │
    │                                                       price_point ◀┘ results
```

**1. The click.** `web/static/app.js` posts to `/actions/collect`. If you used
**Collect specific stores…**, the ticked ids go on as `?only=nistore,playasia`.

**2. The route.** `web/routers/actions.py:collect` (`actions.py:38`). It parses the ids
with `selection.parse_ids`, and if any id isn't a real store it answers **404 before a
run row exists** — a typo must not occupy the one active-run slot.

**3. Claiming the slot.** `web/runs.py:RunLauncher.start` (`runs.py:165`) does four
things in order:

```python
self.reap_stale()                       # a dead worker must not wedge the app
if self.active() is not None: raise RunAlreadyActive(kind)   # 409 to the browser
cursor = self._conn.execute("INSERT INTO run (started_at) VALUES (?)", ...)
pid = self._spawn(worker_command(kind, run_id, *extra))
```

`worker_command` (`runs.py:109`) is where "the program launches itself" becomes literal:

```python
[sys.executable, "-m", "switch_tracker", "collect", "--run-id", "7"]   # development
[sys.executable,                         "collect", "--run-id", "7"]   # frozen .exe
```

Frozen, `sys.executable` **is the .exe** — so it is the same binary, run again, with a
different argument.

**4. The dashboard is already done.** It writes the worker's pid to `run.lock`, returns
`{"run_id": 7}`, and goes back to serving pages. Total time: milliseconds. Nothing about
the next ten minutes belongs to it.

**5. The worker wakes up** in `__main__.py`: `main` → `_parse` → `_dispatch` →
`_run_worker` → `services/collect_worker.py:run(7, only)`. Note *where* the imports are:

```python
if command == "collect":
    from switch_tracker.services import collect_worker      # INSIDE the branch
```

Import-inside-a-function looks like a style violation and is load-bearing. At module
level, merely *starting the dashboard* would load Playwright — the thing Part 2 exists
to prevent, and `tests/test_import_boundary.py` fails the build if it ever happens.

**6. Setting up (`collect_worker.py:38`).** Open the database, ensure the schema, load
settings, and build the store list — `overrides.active_stores()`, which is
`config/stores.py` merged with the corrections in `stores.local.json` (§3.1). Then the
one conditional cost in the program:

```python
if needs_browser(stores, only):
    from switch_tracker.adapters.browser.provider import BrowserProvider
    provider = BrowserProvider(headless=not config.headful)
```

An HTTP-only selection never pays to launch Chromium — and `needs_browser` asks the
**selection**, not the enabled flags, for the reason §3.14 spells out.

**7. The run (`services/collect.py:CollectService.run`, `collect.py:98`).**

```python
active = select_stores(stores, only)     # scope
self._sync_store_table(stores)           # ...but sync the FULL list (§3.14)
events.run_started(len(active))
await self._fx.refresh(currencies)       # one rate for the whole run (§3.10)
await asyncio.gather(
    bounded_gather(http_stores,    self.http_concurrency,    process),   # 8 at once
    bounded_gather(browser_stores, self.browser_concurrency, process),   # 4 at once
)
```

Two pools, because eight simultaneous Chrome contexts and eight simultaneous HTTP
requests cost wildly different amounts of memory. Two deadlines for the same reason:
**180 s** per HTTP store, **600 s** per browser store.

**8. One store (`_process_store`, `collect.py:171`).** This is where failure is
*contained*. `adapter.fetch()` is wrapped in `asyncio.wait_for` and in a deliberately
broad `except Exception`, and every exit — timeout, crash, `Failed`, `Partial`, `Ok` —
ends the same way: a row in `run_store` and a `store_finished` event.

> A store that explodes is a *store* failure, never a *run* failure. The other twenty-two
> still get collected. That containment is why the dashboard can honestly show
> "22 ok, 1 failed: TimeoutError" instead of nothing at all.

**9. Saving (`_persist`, `collect.py:233`).** Per listing, inside one transaction:

```sql
INSERT INTO listing (...) ON CONFLICT(store_id, sku) DO UPDATE SET ... RETURNING id
INSERT INTO price_point (listing_id, run_id, captured_at, native_price, inr_price, ...)
```

**Upsert the listing, always append the price point.** The listing is *what exists now*;
the price point is *what was true at 14:32 today*, and history is never edited. The
rupee figure comes from `fx.to_inr()`, which returns `None` rather than guessing (§3.10).

**10. Finishing.** `UPDATE run SET finished_at = ?` and a `run_finished` event. The
worker then simply exits. It never releases `run.lock` — the dashboard's `reap_stale()`
does that on its next launch or startup, because a worker that *crashed* couldn't have
cleaned up either and both cases must behave identically (§3.12).

**11. Meanwhile, all through steps 7–10:** every `events.*` call above inserted a row
into `run_event` with an increasing `seq`. Your browser has been holding
`GET /api/runs/7/events` open since step 4; `web/routers/events.py` polls that table and
pushes each row down as an SSE message whose `id` is the `seq`. Close the tab and
reopen: the browser sends the last id it saw, and the stream resumes there (§3.13).

**Now re-read the diagram in §0.5.** Every arrow in it should be a specific file.

---

# Part 3 — Feature by feature

## 3.1 The store list, and the corrections layer

**Files:** `config/stores.py`, `config/overrides.py`

`config/stores.py` is a plain Python list of twenty-four shops:

```python
StoreConfig(
    id="nistore",
    base_url="https://nistore.in",
    kind=AdapterKind.WOOCOMMERCE,     # a HYPOTHESIS, not a fact
    currency="INR",
    collections=("nintendo-switch-games", "nintendo-switch-pre-owned-games"),
    platform_hint=Platform.SWITCH,
)
```

Two ideas here matter.

**`kind` is a guess.** Nobody can tell what software a shop runs by looking. The `probe`
worker (§3.12) finds out and writes a correction.

**Corrections never edit this file.** They go to `stores.local.json` in your data folder.
The docstring gives the rule: *"a tool must never rewrite the source it also imports."* If
probe edited `stores.py`, one bad write would corrupt the store list permanently.
`active_stores()` merges the two at read time.

One detail worth copying: the merge iterates the **shipped list** and looks corrections up
by id, not the other way round. A stale correction naming a deleted store is ignored
rather than inventing a phantom shop.

**`tier` is a mechanism, not an opinion.** `tier=2` means "has a public product feed";
`tier=1` means "needs a real browser". It decides which adapter group a shop belongs to
and roughly when it runs — nothing else. It is deliberately **not** a trust or reputation
score, however tempting that reading is on a list that mixes Amazon with two-person
import shops. One integer answering both questions would make the collection order depend
on somebody's opinion of a retailer, and the two answers would drift apart the first time
they disagreed. If shop reputation ever needs recording, it gets its own field.

**Almost every shop is scoped to categories.** `collections` (feeds) and `search_urls`
(browser) both exist to point at a shop's *games* categories rather than its whole
catalogue. That is not just politeness about request counts: the classifier (§3.3) is the
only other thing standing between a camera retailer's 570 categories and your price
history, and narrowing the input first leaves it a far easier job. Two of the newer
WooCommerce shops list only a **parent** category on purpose — WooCommerce returns a
product under its parent *and* each of its child terms, so listing the children beside it
fetches the same products two or three times and throws the duplicates away at dedupe.

**And one shop that cannot be scoped at all.** HG World is the exception that shows why
the rule exists. Its Cloudflare front end returns 403 for the Store API's `category=`
parameter by *every* route: term id or slug, v1 or legacy path, 100 or 10 per page. It is
the parameter and not rate limiting, because a bare request repeated *after* the refusals
still answers 200. The two routes that look like escapes are both dead ends.
`category_id=` answers 200 only because WordPress ignores unknown parameters, so it returns
the unfiltered catalogue. `wp/v2/product?product_cat=` filters correctly but carries no
price. So HG World is fetched **unscoped**, about 16 pages and 1,596 products, and the
classifier sieves the lot.

Fetching it unscoped meant two settings had to change together. `collections=()` is the
obvious one. The other is dropping `platform_hint`. Once the classifier is the *only*
sieve, a hint saying "assume Switch when the text names no console" quietly relabels a
general electronics shop's terse-titled accessories as games. It is the same reasoning as
`designinfo` in §3.3. The cost is that a Switch game whose title never says "switch" is
missed. That is acceptable here because HG World's own titles are verbose, and a missed row
is recoverable where a poisoned price series is not. Both properties are pinned by tests
(`test_stores.py` for the missing hint, `test_adapter_woocommerce.py` for the unscoped
fetch), so restoring either one fails loudly. The full investigation is in the
store's comment in `stores.py`, and `scripts/check_stores.py --probe` reproduces it ([troubleshooting.md](troubleshooting.md) §2).

## 3.2 Three ways to read a shop

**Files:** `adapters/shopify.py`, `adapters/woocommerce.py`, `adapters/browser/`

| Kind | How | Can it prove it got everything? |
|---|---|---|
| `SHOPIFY` | Every Shopify shop exposes `/products.json` | Inferred — a short page means the last page |
| `WOOCOMMERCE` | The shop's own public Store API | **Yes** — an `x-wp-total` header states the count |
| `BROWSER` | Drive a real Chrome | Best-effort — scraped "showing X of Y" prose |

All three answer with the same three-way result (`core/models.py`):

```python
FetchOutcome = Ok | Partial | Failed
```

**The middle one is the interesting one.** Most scrapers have two states: worked, or threw
an exception. `Partial` means *"I got rows, but I have reason to think some are missing."*

Notice how honestly each adapter earns its verdict. WooCommerce has a real header, so it
can say "fetched 213 of 213". The browser adapter only has scraped prose, and says so in
the message it shows you: *"best-effort, not a structured total"*. **Confidence differs by
source, and that difference is surfaced rather than flattened.**

`Failed` carries a human-readable `reason`, because that text is the only thing you'll see
when a shop goes quiet.

**Which makes the reason text worth getting right.** The WooCommerce adapter used to treat
a refused request exactly like an empty category: it hit `break`, collected nothing, and
reported *"Store API reachable but returned no Switch products"*. That sentence is false
for a store answering 403, and it sends you hunting for a classifier problem that isn't
there. Now every early exit records why. A refusal records `HTTP 403`, a garbled body
records `invalid JSON`, and a body that isn't a product list says so. The verdict follows
the evidence:

| What happened | Outcome |
|---|---|
| Nothing collected, and requests failed | `Failed("category …, page 1: HTTP 403")`, the real cause |
| Nothing collected, and requests succeeded | `Failed("…returned no Switch products")`, true now |
| Rows collected, but some pages failed | `Partial`, naming the pages it lost |

**Names arrive HTML-encoded.** The Store API returns "Batman: Arkham Trilogy &#8211;
Nintendo Switch", not an actual dash. A live run caught it: stored raw, the entity showed
on the dashboard as literal text, and the matcher read "8211" as a word, which split the
game from every other shop's copy (§3.18). The adapter now decodes product *and*
category names, and category names matter too because they feed classification.

## 3.3 Deciding what's a game — the sieve

**File:** `core/parse.py`

A shop's "Nintendo" category contains games, consoles, controllers, cases, gift cards and
repair services. Only cartridges belong in a cartridge price history.

The classifier is a **sieve, and the order of the mesh is the algorithm**:

```python
for patterns, kind in ((SERVICE, ...), (DIGITAL, ...), (HARDWARE, ...), (ACCESSORY, ...)):
    if _any(patterns, text):
        return Classification(platform_of(text, store_hint), kind)
# only now: if a platform is named and nothing excluded it, it's a game
```

**Why exclusions run first:** "Nintendo Switch Pro Controller" contains the word "Switch".
Check the platform first and it sails through as a game.

**Exclusions read the title; the platform reads everything.** The feed stores pass tags and
categories too, so that a terse "Hogwarts Legacy" in a "Nintendo Switch Games" category
still counts as a Switch game. But tags say what a product is *compatible with*, not what
it *is*. Consolegarage tags every Switch game "NINTENDO SWITCH OLED" and "SWITCH LITE", so
checking the console rule against tags threw out 58 of its 92 products, Mario Kart 8 Deluxe
among them. `classify(context, hint, title=...)` now checks the exclusions against the
title alone. That took consolegarage from 30 listings to 75, with only its consoles and
cases still dropped. `check_stores.py <store> --rejected` lists what a feed store dropped
and why; that's how this was found.

Even in titles, a few words are context rather than the product, and `--rejected` showed each
one dropping real games:

| Word | Is the product when… | Is only context when… |
|---|---|---|
| Lite / OLED | one model is named: "Nintendo Switch Lite – Turquoise" | both are listed: "Mario Kart 8 Deluxe (Switch/Lite/OLED)" (nistore) |
| Joy-Con | it's in the name: "Nintendo Neon Red & Neon Blue Joy-Con" | it's after the first `\|`: "Nintendo Switch Sports \| … \| Joy-Con Compatible" (HG World) |
| DLC | it's in the name of a non-physical product | it follows "+" ("Game+DLC"), sits after the `\|`, or comes with "Game Card"/"Cartridge" (HG World) |
| Digital code | "Cricket 19 … (Digital Code)" | it's inside "(Includes …)": "Bayonetta 2 (Includes Bayonetta Digital Code)" (nekavo) |

**The title's console beats the category's.** HG World files "Super Smash Bros Ultimate for
Nintendo Switch" under a Switch 2 category, so seven Switch 1 games came out as Switch 2.
When the title names a console, that console wins. Only a title naming no console falls
back to the tags and categories.

**Another console beats a bare "switch".** "The Crew 2 PS4 | … | Seamless Switch" came out
as a Switch game. Explicit markers ("Nintendo Switch", "NSW") still win outright, but the
loose ones (a bare "switch", "NS", "Nintendo") now count only after the other-console check.

**Each exclusion word is checked against real titles before it's added.** A "PXN Flight
Simulator Joystick … Nintendo Switch" came through HG World as a game, so joysticks, fight
or arcade sticks, flight sticks, HOTAS and racing wheels are now excluded. "Gamepad" was
tried and taken out again: Flipkart's advertising writes "Gamepad Accessory" into the title
of a real game (*Sonic x Shadow Generations*). "Throttle" and "mouse" stay out too, because
of Full Throttle and Mickey Mouse. The same HG World list held a "Mini Projector … Video
Game For TV" and a "Pokémon GO Plus | Auto-Catch Accessory", so projectors and the
Pokémon GO Plus / Poké Ball Plus are excluded by name. Excluding "accessory" itself would
drop that Sonic game too. A console sold with a game ("Nintendo Switch 2 … Bundled With
Pokemon Pokopia", ₹59,999 at designinfo) is hardware. The rule is "bundl**ed** with",
because Flipkart writes "Classic JRPG Bundle with Six … Titles" into a real game.

### The store hint, and the rule that saves it

Some shops sell only Switch games, so a bare title like "Hogwarts Legacy" is a Switch game
even though it never says so. That's `platform_hint`. But a hint is dangerous, so
`platform_of` applies it last:

```
"switch 2" in text?     → SWITCH2
"switch" in text?       → SWITCH
another console named?  → UNKNOWN     ← beats the hint
otherwise               → the hint, or UNKNOWN
```

The third line is the whole trick. A hint means *"assume Switch when the text says nothing
about a console"* — **not** *"assume Switch even when the text names a different one"*.
Without it, one multi-console shop with a hint leaks every PS5 and Xbox title into your
Switch price history.

You can see the same care in the config: `designinfo` — a 570-category camera shop —
deliberately has **no** hint, with a comment explaining that the hint which rescues terse
titles on a specialist shop is exactly what poisons a general one.

## 3.4 Reading a price — where the real bugs live

**File:** `core/parse.py`

Indian shops write prices at least six ways: `4,499.00`, `Rs. 4499`, `INR 4,499`,
`4.499,00`. Three bugs found the hard way are recorded here, and all three teach the same
lesson.

**Bug one — `Rs.`** The original code stripped everything that wasn't a digit, dot or
comma. The dot in `Rs.` survives that filter, so `Rs. 4499` became `.4499` → **₹0.45**.
The fix is ordering: remove currency words *before* stripping non-numerics.

**Bug two — thousands separators.** The rule "whichever separator comes last is the decimal
point" is wrong for Indian prices. `3,599` has no dot, so the comma looked like a decimal
point: **₹3.60 instead of ₹3,599**. A thousand times too small. The rule now is: a comma
with no dot anywhere is *always* a thousands separator.

**Bug three: `rs` inside a word.** When a card's price selector matches nothing,
`first_rupee_price` searches the whole card's text for a rupee marker (layer 4 of the
ladder in §3.6). Its pattern looked for `Rs` with no word boundary, so it matched the "rs"
*inside* ordinary words and took whatever number came next. "Mario Party Supe**rs**tars
3 modes" was priced at **₹3**, and "Warrio**rs** 4 player co-op" at **₹4**. The fix puts a
`\b` boundary in front of `Rs` and `INR`. `₹` needs none, because it isn't a word
character. The digit group was also tightened to how money is actually written (comma
groups, at most two decimals), and the match goes back through `parse_price` instead of a
second, local parser. Two parsers for one job drift apart.

One limitation is kept on purpose and written into the docstring. "First" really means
first: `MRP ₹5,999 ₹3,999` yields 5,999, the struck-through price. Plain text can't tell
the two apart, and that is why store profiles prefer a sale-price selector wherever a shop
offers one (§3.9).

> **None of the three threw an exception. All three produced a plausible number.** That
> is the theme of this entire codebase: in a scraper, the dangerous failure is the one
> that type-checks.

Which is why `parse_price` returns `None` on failure and never `0`:

```python
"""Returns None rather than 0 on failure -- zero is a real value
and must not be invented."""
```

## 3.5 SKUs — forty lines that decide whether the project works

**File:** `core/skus.py`

Every listing needs a **stable identifier** so the second run knows it's looking at the
same product as the first. The `listing` table enforces `UNIQUE(store_id, sku)`.

```python
def sku_from_url(url):
    asin = _ASIN.search(parsed.path)          # Amazon: /dp/B0XXXXXXXX
    if asin: return asin.group(1)
    pid = parse_qs(parsed.query).get("pid")   # Flipkart: ?pid=...
    if pid: return pid[0]
    return [s for s in parsed.path.split("/") if s][-1]   # else: last path segment
```

The query string is deliberately dropped — tracking parameters change between visits, and
letting them into the id would mint a brand-new product every run.

**Why this tiny file is load-bearing**, in the docstring's own words: if the id is
unstable, *every price series has exactly one point, "moved since last run" is permanently
empty, and nothing anywhere reports an error.*

**The opposite failure: an id that isn't unique.** The feed stores (Shopify,
WooCommerce) use the shop's own SKU field, which shopkeepers type by hand. Consolegarage
gives seven different games the SKU `CGGM`. `UNIQUE(store_id, sku)` folded all seven into
one listing whose title and price flipped every run: seven price histories mixed into one,
reported as OK. `one_product_per_sku` now replaces a SKU shared by several products with
each product's own id. A SKU that names exactly one product is kept, so every existing
price series carries on. The same product listed in two collections is kept once.

## 3.6 Scraping a page — the four-layer ladder

**File:** `adapters/browser/extract.py`

For shops with no data feed, the code tries four ways to read a page, **hardest to break
first**:

| # | Layer | Why it's durable |
|---|---|---|
| 1 | **JSON-LD** — structured data shops embed for Google | Exists for search engines, survives redesigns |
| 2 | **The site's own state** — e.g. Flipkart's `__INITIAL_STATE__` | The data the page itself was built from |
| 3 | **CSS selectors** — per-shop recipes | The least durable thing on a page |
| 4 | **Text pattern** — find a ₹ figure inside the card | Pattern, not structure |

Layer 2 deserves a note. Flipkart's class names are scrambled and rotate, so the code
reads the raw data the page hydrated from — and walks it **structurally**, hunting any
object that has a title, a numeric price and a URL, rather than following a fixed path.
A fixed path would break on Flipkart's next deploy.

The function returns *which layer worked*, so a failure tells you where in the ladder it
fell over.

**A trap preserved in a comment here:** `:has-text('Sold Out')` is Playwright syntax, not
real CSS. Handing it to the browser's own `querySelector` throws — and that caught
exception silently disabled out-of-stock detection **for every shop at once**. It's now
emulated as a plain text search.

## 3.7 Knowing when to stop turning pages — and when not to

**File:** `adapters/browser/pagination.py`

The obvious rule — *stop when a page yields nothing new* — silently truncated two real
shops. Trailing pages get padded with "related items" that reshuffle slightly, so the
count of new rows almost never lands on exactly zero.

```python
UNPRODUCTIVE_RATIO = 0.15    # below this share of new rows, it's filler
GIVE_UP_AFTER = 4            # four pages, not one — one odd page isn't an ending
```

A **proportion** sustained over several pages is what distinguishes "genuinely finished"
from "recycling filler".

### The opposite mistake: stopping because one page failed

**File:** `adapters/browser/adapter.py`, the page loop and the second pass after it.

Running dry is one reason to stop. A page that *won't load* is a different question, and
Flipkart is where it got answered.

Partway through a walk, Flipkart answers a perfectly valid page URL with a `301` to **the
byte-identical URL**, 19 hops in a row, until Chromium gives up with
`ERR_TOO_MANY_REDIRECTS`. It looks like a bad URL and isn't one. It is a **verdict on the
session**, and the page it hits *moves between runs*:

| Run | What happened |
|---|---|
| `--pages 3` | p1–p3 all clean |
| full, older build | p3 clean, **p4 struck**, p5–p8 collected normally |
| full, a later build | p1–p2 clean, **p3 struck**, and the walk *stopped* |

That third row was the real bug. The loop used to `break` on a failed page, assuming a
page that failed twice would keep failing. So one struck page threw away the rest of the
catalogue, and a run returned 79 listings where the older continue-anyway build had
collected 228. The fix is four rules, each answering one shape of failure:

1. **Wait, then retry.** On a failed navigation the adapter closes the tab, sleeps
   `_REDIRECT_LOOP_BACKOFF_S` (8 s), and tries once more in a fresh tab. The wait is the
   part that matters. An instant re-issue, fresh tab or not, gets the same verdict.
2. **Skip, don't stop.** If the retry fails too, the page goes into a `struck` dict and
   the walk carries on to the next page.
3. **But stop on a streak.** `_MAX_NAV_FAILURES = 3` *consecutive* failures end the walk.
   Only a streak separates "one struck page" from "this session is blocked outright", and
   the second case must stop rather than spend the whole time budget proving it. One good
   page resets the count.
4. **Go back for what was lost.** After the walk, a **second pass** retries every struck
   page once. The elapsed walk *was* the backoff, since minutes have passed, and the
   redirect traces show Flipkart's edge answering 200 to the identical request once the
   verdict expires. The pass checks the same deadline before every page.

The bookkeeping detail is what makes the verdict honest. A failed page is *held back* in
`struck` rather than written straight into `problems`. Only pages the second pass
couldn't recover get reported. So a walk that lost p5 and got it back reports **Ok**,
which is what actually happened, instead of a `Partial` that would send you
investigating a complete fetch. Both passes fold rows in through one shared `_absorb()`,
so a recovered page dedupes and classifies exactly like its neighbours. Measured on a
live walk: **79 → 184 listings**, p5 struck and skipped.

**Why not just fix the URL?** Because there's no fixed version. The traces from one run show
the edge normalising the *same* request two different ways. The hop that leaves
`sid=4rr%2Cfa6%2C32v` encoded answers 200. The hop that decodes it to `sid=4rr,fa6,32v`
is the one that loops. Which form comes back isn't decided by what was sent. There's
nothing to choose, only a page to retry later. That's the warning in the comment above
`_REDIRECT_LOOP_BACKOFF_S`, and it is there so nobody spends an afternoon re-encoding.

Two supporting pieces:

- **The shop's own pager link is preferred.** `_flipkart_page_url()` uses the page's own
  `page=N` link when that link keeps *both* platform filters, and falls back to the
  template otherwise. A pager link that drops the Switch 2 facet would quietly halve the
  catalogue.
- **Every failed navigation leaves a trace.** `_goto_flipkart()` records each
  main-frame redirect hop and writes `diagnostics/flipkart-p<N>-navigation.json` on
  failure. That file is how the "self-redirect, moving page" diagnosis above was made, so
  the next one won't need a reproduction.

All of this runs without a browser in `tests/test_flipkart_recovery.py`, against a mocked
page.

## 3.8 Turning the page when there's no URL to go to

**File:** `adapters/browser/adapter.py`

Some shops render page 2 entirely in the browser — no new address. You must click.

This is where the project's most instructive bug lived. Play-Asia returned **350 raw rows
but only 39 products**, and it took a reproduction to explain why:

The pager selector list ended with `:has-text('>')`. Unscoped, that Playwright selector
matches **every element containing a `>` character** — including `<html>` and `<body>`.
The code took the last match, which was a footer `<small>` reading *"Terms > Privacy"*,
clicked it, and **returned success**. The page never turned. Page 1 was re-scraped until
the productivity tracker gave up four pages later.

Measured on a reproduction: **10 extractions, 350 raw rows, 35 unique products.**

The fix is not a better selector — it's that **a click now has to prove it worked**:

```python
before = await _results_fingerprint(page, profile.card)   # card count + first 5 hrefs
...click...
if await _advanced(page, profile.card, before):           # did the results change?
    return True
```

Deliberately *not* a URL check: a click that navigates to a terms page changes the URL
while destroying the results, and would pass one.

After: **2 extractions, 70 raw rows.** And the failure mode is now impossible for *any*
shop, not just this one.

**The proof is only as good as what it fingerprints.** A home run later stopped Play-Asia
at page 102 of 139, missing about 1,600 products. `diagnose-pager` showed why: the one
card class matched three things on page 1. There were 36 search results in
`#pa-modern-products-container`, 30 grey loading placeholders, and 8 "recommended" cards
repeated on every page. Clicking Next swapped the results for placeholders at once, so the
fingerprint changed instantly and the page counted as turned *before its results arrived*.
Deep pages load slowest, so from about page 97 only the recommended row was read, and four
pages of repeats later the productivity tracker (§3.7) ended the walk.

So the card selector is now scoped to the results grid, with no fallbacks. A fallback would
bring the bug back: while the grid is empty mid-load, the fingerprint would fall through to
it and read "turned" again. Deep pages also get `advance_timeout_ms` (20 s instead of 4 s)
to replace the results; the real end of the catalogue is a disabled Next, which returns at
once. A browser test reproduces the swap, and it fails with the old selector.

Play-Asia's address does change, to `#fc=p:2`. Jumping straight to a page by that fragment
was left alone: click paging works once it waits for the right thing.

## 3.9 Per-shop quirks, without per-shop code

**File:** `adapters/browser/profiles.py`

Ten shops, each needing something different — and **zero** `if store_id == ...` branches
in the adapter. Everything is data on a `StoreProfile`:

| Field | What it controls | Set by |
|---|---|---|
| `card` / `title` / `price` / `link` | CSS recipes | all 10 |
| `ready` | wait for this before reading | all 10 |
| `next_page` | click-to-paginate controls | 4 |
| `platform_hint` | assume Switch on a terse title | all 10 |
| `default_region` | which regional edition, absent a marker | Play-Asia, GamePookie |
| `default_condition` | assert new/pre-owned for the whole shop | CeX India |
| `condition_from_context` | read condition from the whole card, not the title | GameLand |
| `cookies` / `cookie_domain` | session settings | Play-Asia |
| `wait_until` | how long to wait for the page | Play-Asia |
| `scroll_passes` / `scroll_settle_ms` | lazy-loading behaviour | Play-Asia |
| `reject_url_parts` / `require_digit_in_url` | drop non-product links | Play-Asia |
| `max_pages` / `time_budget_s` | page cap, and the shop's own deadline | Play-Asia |
| `sku_includes_region` | keep regional editions as separate listings | Play-Asia |

**Several of these are correctness, not convenience.**

*Cookies.* Play-Asia prices per session. The config says `currency="INR"` — and that was
**a lie** until recently: the cookies existed only in a hand-run test script, so the real
collector scraped whatever the default session quoted and labelled it rupees. The cookies
now ship on the profile, which is what makes the config's claim true.

*The URL filter.* Category and search links sit inside result cards, and the classifier
*cannot* reject them — a nav link titled "Nintendo Switch" plus a SWITCH hint is a textbook
game. The filter **fails open**: a row is dropped only on a positive match, so a wrong rule
leaves junk (recoverable) rather than deleting the whole shop (not).

*The region default.* Most shops sell Indian stock, so `Region.IN` is the sensible
assumption — but GamePookie is an importer, and US, Asian and Japanese pressings sit in
the same category as domestic ones with nothing in the title to say which. Region is
modelled here as a genuinely **different product** (§3.2, `core/models.py`), not a tag on
one, so asserting IN would not be a mislabel — it would merge editions that are not
interchangeable. `Region.UNKNOWN` is the honest answer, and a title that *does* say still
upgrades the row.

*Condition, and its two escape hatches.* By default a listing is new or pre-owned
according to what its **title** says, because a shop's own wording is the only source of
truth that works everywhere (§3.3). Two shops break that:

- **CeX India** deals exclusively in second-hand stock and, precisely because that is its
  entire business, never labels anything — its titles read "Mario Kart World". So the
  fact lives with the retailer: `default_condition=Condition.PRE_OWNED` overrides whatever
  the page says. It is the only shop that asserts one, and a test fails if a second
  quietly acquires it.
- **GameLand** puts "Pre-owned" in a **badge** next to the product name rather than in it,
  so a title-only read files its whole used shelf as new. `condition_from_context=True`
  widens the read to the entire card's text.

The second one is opt-in, and that is the load-bearing part. `PRE_OWNED` matches "used" on
a bare word boundary, and an Amazon search card routinely carries *"6 used & new offers"*
under the price — so switching every shop to card text at once would relabel a large slice
of Amazon's catalogue as second-hand. Silently, permanently, and in exactly the
fail-*closed* direction the URL filter above argues against. The wider signal is available
to any shop somebody has actually looked at; no shop acquires it by accident.

### Where declarative stops working

Store-id branches exist, and every one of them names the same shop:

```python
if store_id == "flipkart":      # extract.py, once: read the hydration state
if store.id == "flipkart":      # adapter.py, four times: navigation recovery (§3.7)
```

Flipkart needed a genuinely different *mechanism* twice. First it had to walk the page's
hydration state, and you can't express "walk the Redux store" as a config value. Then it
needed the redirect-loop recovery, which is a different way of *navigating*, not
different values for the same navigation. The useful distinction:

- *"Scroll differently, wait longer, reject these URLs"* → a **parameter**. Same algorithm,
  different values. Belongs on the profile.
- *"Don't read the DOM at all"*, *"retry a refused page later"* → a **mechanism**.
  Different algorithm. Needs code.

`docs/python-rewrite-hld.md` records the trigger for revisiting this: when a **second
shop** needs mechanism-level divergence, a strategy seam stops being speculative. Note
what has and hasn't happened. The branches went from one to five, but the shop count is
still one, so the trigger as written hasn't fired. What *has* changed is the cost of
waiting. Four checks scattered through one loop are harder to read than one. The middle
ground is a profile flag such as `navigation_retry=True`. It would be a parameter that
switches the recovery on, and it would remove the id checks from the walk without
building a strategy interface for one implementation.

## 3.10 Exchange rates — and the null that matters

**File:** `fx/rates.py`

Rates refresh at the **start** of a run, so every price in that run converts at one rate
rather than drifting mid-run.

The important function is the one that declines to answer:

```python
def to_inr(self, native_price, currency):
    fx = self.latest_rate(currency)
    if fx is None:
        return None, None          # write NULL
    return round(native_price * fx.rate, 2), fx.rate_date
```

An earlier version returned the **native** price when no rate was available — so
`$59.99` landed in the rupee column as if it were ₹59.99. Silently, in the one table the
project exists to accumulate. The docstring states the principle the whole codebase runs on:

> *"A missing number is recoverable; a wrong one is indistinguishable from a real price
> forever after."*

This is why `price_point.inr_price` is nullable — the single deliberate schema difference
from the original.

## 3.11 Saving the data — and the query that had to be rewritten

**Files:** `core/db.py`, `services/collect.py`, `web/queries.py`

### The shape of the data

Seven tables. The three that carry the value:

```
store   ──< listing ──< price_point
                │
              game_id ──> game     (filled by the matcher, §3.18)
```

- **`listing`** — one row per product per shop. `UNIQUE(store_id, sku)`.
- **`price_point`** — one row per listing **per run**. This is the history, and the only
  table that grows forever.

Saving is *upsert the listing, always append a price point*:

```sql
INSERT INTO listing (...) VALUES (...)
ON CONFLICT(store_id, sku) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen
```

`first_seen` is deliberately **excluded** from the update — it's a fact about when the
product appeared, and overwriting it each run would erase it.

**Only web links are saved.** A listing's URL comes from the shop's own data. A
WooCommerce `permalink` is stored as received, and `urljoin()` keeps a `javascript:`
scheme intact. Rendered as a link on the dashboard, that's script running on the
dashboard's own origin, which gets past every other protection it has, including the
cross-site guard (§1.4). So `_persist` drops any listing whose URL isn't `http`/`https`.
`app.js` checks again with `safeHref()` before drawing a link, because rows saved
before this rule existed are still in older databases. `esc()` alone isn't enough:
`javascript:alert(1)` contains nothing to escape.

### The performance problem, and why it was invisible

To show a price list, you need the *newest* price point per listing. The original code
asked for it like this:

```sql
WITH latest AS (
  SELECT ..., ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY captured_at DESC) AS rn
  FROM price_point
)
JOIN latest ON latest.listing_id = l.id AND latest.rn = 1
```

Read plainly: *number every row of price history, then keep the ones numbered 1.* The cost
is tied to **all history**, not to the listings on screen. Measured at 5,000 listings/run:

| Elapsed | price_points | `listings()` |
|---|---|---|
| 3 months | 450,000 | 1.1 s |
| 1 year | 1,825,000 | 5.3 s |
| 2 years | 3,650,000 | 23.8 s |
| 3 years | 5,475,000 | **39.6 s** |

Worse than linear — doubling the rows quadrupled the time, once the sort stopped fitting
in memory.

### The fix

```sql
JOIN price_point latest ON latest.id = (
  SELECT pp.id FROM price_point pp
  WHERE pp.listing_id = l.id
  ORDER BY pp.captured_at DESC, pp.id DESC
  LIMIT 1 OFFSET 0
)
```

For each listing on screen, jump straight to its newest row using the index that already
existed. Measured after:

| Elapsed | before | after |
|---|---|---|
| 1 year | 5.3 s | **48 ms** |
| 3 years | 39.6 s | **59 ms** |

Flat, because the cost now tracks the listing count — which plateaus — instead of history,
which doesn't.

> **The insight worth keeping:** the right index already existed. The query plan even said
> `SCAN price_point USING INDEX`. But *using* an index and *seeking* with one are different
> things — the window function read the index in order and still visited every row. Only
> `EXPLAIN QUERY PLAN` tells you which you got, and with one run in the database both forms
> are instant. **The bug was invisible until history accumulated — the exact thing this
> project exists to accumulate.**

### Why it had to be a JOIN

The obvious version — select the price as a value in the output list — is wrong here, and
subtly so. `in_stock_only` **filters** on the latest row, and two of the four sort options
**order by** it. A projected value can't be filtered or sorted on. That version passes a
casual test and breaks three features.

### The second-newest row, and what "moved" means

The same subquery, written once as `_NTH_LATEST_ID`, takes an `OFFSET`. Offset 0 is
`latest` and offset 1 is `previous`, so `listings()` LEFT JOINs both and computes the
movement in SQL:

```sql
CASE WHEN previous.inr_price IS NOT NULL AND previous.inr_price != 0
          AND latest.inr_price IS NOT NULL
          AND ABS(<pct>) > 1.0              -- MIN_CHANGE_PCT
     THEN <pct> ELSE NULL END AS change_pct
```

It is a LEFT join on purpose. A listing seen only once has no previous row, and it must
still appear in the list with a `NULL` change rather than disappear from it.

Three decisions are built into it:

- **Movement has a floor.** `MIN_CHANGE_PCT = 1.0`. A ₹4,499 game re-quoted at ₹4,489 is
  rounding noise, not news, and a "movers" view full of 0.2% wiggles hides the 30% drop
  you came for. The same floor applies to `movers()` (§4.3), so the panel and the column
  can't disagree about whether something moved. At or under the floor, `change_pct` is
  `NULL`, which means "nothing to report", the same as no previous observation.
- **Sorting by change narrows the list to real movers.** With `sort=change`, the floor
  and "has a previous price" become `WHERE` conditions, applied **before** `COUNT` and
  `LIMIT`. If they were applied after, page 2 would start in the wrong place and the
  total would count rows you can't reach. So `total` drops when you pick that sort. That
  is intended, and noted in [troubleshooting.md](troubleshooting.md) because it reads like a bug the first time.
- **NULLs sort last in both directions.** SQLite puts NULL first in ascending order,
  which would open "biggest drops first" with a screen of listings that never moved.
  `ORDER BY change_pct IS NULL, change_pct …` keeps them at the bottom either way.

### How "identical results" was guaranteed

The acceptance criterion wasn't speed, it was *same rows*. So the old query was pasted into
the test file as a **frozen oracle**, and the new one compared against it across a matrix —
4 sort keys × 2 directions × every filter × in-stock × pagination — over a fixture
containing the awkward cases (a listing with one price point, one with none, a NULL price,
tied timestamps).

Frozen deliberately: an oracle imported from production changes when production changes,
and would agree with any rewrite including a wrong one.

The cost of freezing is that a **deliberate** behaviour change has to be copied into the
oracle by hand. That really happened. The 1% floor landed in `queries.py` and not in the
oracle, so fifteen matrix cases failed on the one row whose price hadn't moved: `0.0` in
the oracle, `NULL` in production. The fix is to write the new rule into the oracle as a
literal, `> 1.0`, and *not* to import `MIN_CHANGE_PCT`, for the same reason as above. The
failure was the oracle doing its job. It stops anything changing the rows without
someone deciding to. `sort=change` is outside the matrix and has its own test
(`test_change_sort_shows_only_actual_movers`), because the narrowing is specified
behaviour, not something to compare against old SQL.

## 3.12 Making sure two runs can't collide

**File:** `web/runs.py`

Two scrapes at once would fight over the database. Three independent guards:

| Layer | Mechanism | Catches |
|---|---|---|
| 1 | `SELECT id FROM run WHERE finished_at IS NULL` | the normal case |
| 2 | `CREATE UNIQUE INDEX idx_run_active ON run((1)) WHERE finished_at IS NULL` | the race layer 1 missed |
| 3 | A lock file holding the worker's process id | a **second copy of the app** |

Layer 2 is the elegant one. Indexing the constant `1` means every unfinished run maps to
the **same index key**, so uniqueness permits exactly one. It's a mutex expressed in the
database schema — it survives crashes and multiple browser tabs in a way a Python variable
cannot. The code comment notes that the greyed-out button in the UI is *cosmetic* and must
never be relied on.

Layer 3 exists because layers 1 and 2 live inside one database file — a second launched
copy of the app would open the same file and, if the first had crashed, see no active run.
A process id is checkable. A timestamp would only ever be a guess, and a legitimate
10-minute browser run would trip any timeout short enough to be useful.

## 3.13 Watching progress live

**Files:** `events/writer.py`, `events/reader.py`, `web/routers/events.py`

The worker writes rows to `run_event`; the dashboard tails that table and forwards them.

```python
events = await asyncio.to_thread(reader.since, run_id, cursor)
```

`asyncio.to_thread` matters: SQLite reads *block*, and this loop shares its thread with
every other request the dashboard is serving. Pushing the read to a side thread stops one
slow query from freezing the whole dashboard.

Each event carries a `seq` number sent as the SSE `id`. Browsers remember the last id and
send it back on reconnect, so a dropped connection resumes exactly where it left off — no
duplicates, no gaps. That single detail is what makes "close the tab, nothing is lost"
true rather than aspirational.

The writer swallows its own errors on purpose:

> *"Progress reporting is worth having; it is not worth losing a multi-minute collection
> over."*

**What the page does with those events.** `follow()` in `app.js` subscribes once and
folds every event into one small object:

```js
const run = { total: 0, done: 0, failed: 0, listings: 0, store: "", page: 0 };
```

`run_started` sets `total`; `store_progress` updates `store`/`page`; `store_finished`
increments `done` and adds to `listings`. Then `paintProgress()` renders that object.

Two details worth copying. First, the progress bar stays **indeterminate** until at
least one store finishes — before that there is no honest percentage, because a store's
page count is not known in advance, and a fake one is worse than none. Second, the panel
**stays on screen after the run ends**, showing the outcome. A run that vanishes the
moment it completes leaves the user with no answer to "did that work?".

## 3.14 Collecting from just some shops

**Files:** `services/collect.py`, `services/collect_worker.py`, `selection.py`,
`web/routers/actions.py`

Testing one shop shouldn't mean scraping two dozen. You tick boxes on the dashboard and
press **Collect selected**.

**The design decision:** pass a *set* of shop ids, not one id.

```python
async def run(self, stores, run_id=None, *, only: tuple[str, ...] = ()) -> int:
```

`only=()` means "all enabled" — today's behaviour. A non-empty set means exactly those,
and **ignores whether a shop is enabled**, because naming a shop *is* the intent.

A tuple costs the same code as a single string, and it makes a second use case —
*"re-run the three shops that failed"* — a later change in the dashboard with **no worker
changes at all**. That's why the set won: the generality was free.

**One shared definition, deliberately:**

```python
def select_stores(stores, only) -> list[StoreConfig]:
```

It's a module-level function, not a method, because the *worker* needs the answer before a
service exists — to decide whether to launch Chromium at all. That gate previously read:

```python
any(s.enabled and s.kind is BROWSER for s in stores)     # WRONG once runs can be narrowed
```

Pick a *disabled* browser shop and the browser was never launched, so the shop recorded
*"no adapter / skipped"* and collected nothing — silently, for the exact case the feature
existed to serve.

**And a layering lesson.** The dashboard and the worker both need to encode the id list
into a command-line argument. The obvious shared home was `services/collect.py` — but that
file imports adapter code, and the dashboard is **forbidden** from importing adapters
(§2). So the encoding lives in its own dependency-free module, `selection.py`:

> *"One module because BOTH sides of that boundary need the same answer, and they cannot
> share a richer one."*

## 3.15 Collecting once, not every launch

**Files:** `web/app.py`, `web/queries.py`

The app used to scrape every time you opened it. Now it collects automatically **only to
bootstrap an empty database**:

```python
def has_ever_collected(conn) -> bool:
    return conn.execute("SELECT 1 FROM run_store LIMIT 1").fetchone() is not None
```

Two choices in that one line:

**Why `run_store` and not `run`.** Probe, FX and inspect *all* create a `run` row — only a
collection writes `run_store`. Asking the `run` table would tell someone who had merely
pressed "Check stores" that they'd already collected, and skip the bootstrap they needed.

**Why derived state, not a settings flag.** A flag drifts: delete `tracker.db` and the app
stays permanently convinced it has collected, leaving you an empty dashboard with no
obvious cause. Reading the database means a wiped database correctly bootstraps itself.

The decision itself is a pure function — four booleans in, a verdict out — so all seven
paths are testable without starting a server.

## 3.16 The self-repair tools

Two capabilities exist because shops change without warning.

**Probe** (`services/probe.py`) — asks each shop *"what do you actually run on?"* and
writes corrections. Note it compares against the **effective** store list (defaults +
existing corrections), not the shipped one. Comparing against shipped meant a shop
corrected on run 1 reported "will switch" forever, because the baseline never moved.

Probe will only ever write a `kind` this build can actually fetch with. When the server
*answers* with something unusable, such as a Shopify shop with its feed switched off,
the shop is *disabled* with a readable reason, rather than given a config value nothing
can use.

**A shop that can't be reached is left alone.** A failed connection is a fact about the
network, not the shop: a filtered office network, a Wi-Fi drop or a five-minute outage
all look identical. Probe used to disable on it, and one "Check stores" on a filtered
network disabled 10 of 23 working shops, which then silently stopped being collected
until someone pressed **Reset corrections**. Now it reports *"could not be reached just
now"* and writes nothing. A shop an older probe disabled that way is re-enabled the next
time it answers.

**Detection checks the shape of the reply, not a substring.** Probe used to decide "this
is Shopify" if the body of `/products.json` *contained the text* `"products"`. A WordPress
404 page answers with status 200, and its inline JavaScript routinely contains that exact
literal. So HG World, a hand-verified WooCommerce shop, was detected as Shopify, and probe
wrote `kind=SHOPIFY` into `stores.local.json`. Because corrections layer *over* the
shipped config (§3.1), that one wrong write overrode the correct `stores.py` entry for a
month. Every run then failed with the Shopify adapter's *"no parseable JSON"*.

The check now parses the reply and tests its structure. Shopify means a JSON object whose
`products` is a list. WooCommerce means a non-empty JSON list whose first item has a
`prices` key. `get_json` already returns `None` for a refusal or non-JSON, so an HTML page
can't pass either test, whatever text it contains.

The general lesson: a correction mechanism is only as trustworthy as its detector, and
**a correction overrides a hand-verified fact**. So a detector that writes corrections has
to fail *closed*, by writing nothing, when it isn't sure.

**Inspect** (`services/inspect.py`) — the click-to-pick tool. It opens a **visible** Chrome
on the shop's page; you Alt+click the product card, then its title, price and link.

Two details make it work:

*Clicks are resolved by `elementsFromPoint`, not the click target.* Product cards usually
have an invisible link covering the whole tile, so a normal click always hits the overlay
and never the price text underneath. Reading the entire stack of elements at the click
point recovers the real one.

*Every pick is scored before it's saved.* A card selector must **repeat** (2–500 matches);
a title selector is checked against 8 sampled cards and reported as a percentage. You get
told *"in 88% of sampled cards — saved"* rather than a silent success.

## 3.17 Shipping it as an .exe

**Files:** `switch_tracker.spec`, `packaging/runtime_hook_playwright.py`, `paths.py`,
`resources.py`, `spike.py`

Two rules keep frozen and development builds behaving identically.

**Every writable path resolves in one place** — `paths.py`. The original used a bare
relative filename for its corrections file, so it resolved against whatever folder the
process started in: invisible for a command-line tool, wrong for a double-clicked `.exe`.
The docstring states the goal precisely: *"makes that class of bug unrepresentable rather
than merely fixed."*

**`sys._MEIPASS` is banned** everywhere except one file. That variable exists *only* in a
frozen build, so any code using it behaves differently in development than in the shipped
app — the exact class of bug that only appears after packaging. Bundled read-only files go
through `importlib.resources`, which works identically either way. The one legitimate use
is the PyInstaller startup hook, which by definition only ever runs frozen.

**`spike.py`** is a self-check that proves the four things which work in development and
fail only after freezing: TLS certificates, template bundling, the web server, and the
Playwright driver. `switch-tracker spike` prints the same output either way — that
sameness is the whole point.

## 3.18 Matching one game across shops

**Files:** `core/matcher.py`, `services/collect.py`, `web/queries.py:games`

Until this existed, "Metroid Prime 4" at four shops was four unrelated rows, and
`listing.game_id` (in the schema from the very first version) was always
`NULL`. Matching is what turns *"a list of things shops sell"* into *"where is the
cheapest copy of X right now"*, which is the question the project exists to answer.

### The key

```python
match_key("Pokémon Legends: Z-A (Nintendo Switch 2)")   # "pokemon legends z a"
match_key("Pokemon Legends Z-A - Switch 2")              # "pokemon legends z a"
```

`match_key` is `normalise_title()` from `core/parse.py` (strip console names, "game",
"edition", condition words and bracketed regions), plus three fixes found by feeding it
real titles:

| Fix | Without it |
|---|---|
| **Fold accents** (`unicodedata` NFKD) before normalising | `normalise_title` drops non-ASCII, so "Pokémon" became "pok mon" and never met "Pokemon" |
| **Delete apostrophes** (straight, curly and backtick) | "Luigi's" became "luigi s", split from "Luigis" |
| A short **stop list**: the, of, and, for, nintendo, and region words such as asia, english, version | Play-Asia writes regions *into* the title ("Asia English"), and "Mario Kart World for Nintendo Switch 2" kept a stray "for" |
| **Publisher prefixes** Amazon prepends (Warner Bros Interactive Entertainment, Square Enix, Bandai Namco, Ubisoft, Electronic Arts, …), stripped from the *start* only, longest first | "Warner Bros Interactive Entertainment Hogwarts Legacy" never met "Hogwarts Legacy". Found in the first live run on real data |

The prefix list is hand-curated, and its exclusions are the point. Sega, Capcom, Konami,
Namco and EA are left out because real titles begin with them (Capcom Fighting
Collection, Namco Museum, EA Sports FC). A prefix is also kept unless at least two words
are left after it. With one word left, "Square Enix Collection" would become
"collection", and two different publishers' collections would silently share one price
series.

### Cut titles, and marketing after a bar

The first live run showed Flipkart splitting almost every game. Two causes, fixed at two
different layers:

- **The title was cut before it was ever saved.** Flipkart's cards show 55 characters
  and "...": "The Legend of Zelda: Breath of the Wild - Nintendo Swit...". The full name is
  in the card's `title` attribute, and the scraper read the visible text first. Now a
  visible title ending in an ellipsis is replaced by a `title` attribute that *starts
  with* it, never by one that says something else (`adapters/browser/extract.py`). This is
  a fix to the stored data, not the matcher: the cut name was simply lost. The next
  collection overwrites each listing's title in place, keeping its price history.
- **The full title is mostly advertising.** "Mario Kart World Nintendo Switch 2 | Premium
  Racing Adventure | Best Physical Switch 2 Games | …" changes per listing, so keying the
  whole thing splits every game. The name is the part before the first `|`, but only
  under two conditions, and both must hold:
  1. The part before the `|` names the console, the way Flipkart ends its names
     ("Neon White Nintendo Switch Games CD | …"). Without that, the tail is a subtitle:
     "Fire Emblem | Engage" must not merge with "Fire Emblem | Three Houses", and
     "Splatoon 3 | Side Order" must not merge with Splatoon 3.
  2. Nothing after the `|` names an edition, a number, or a variant word (deluxe, twin
     pack, remastered, …). Amazon writes "Shinobi: Art of Vengeance | **Deluxe** Edition |
     Switch 2", and cutting there would merge the Deluxe with the Standard.

  Otherwise the whole title is keyed as before. When it's unsure, it splits.

Measured on the live data: 24 new merges, all of them correct; nothing that used to group
came apart; and games found at 2+ stores rose from 247 to 262. Every price was identical
before and after, and every game's best price agreed with a recalculation from the raw
price points.

**A re-keyed game leaves a forwarding address.** Watches are stored by key, so any
improvement to the key would silently orphan them. When a key disappears and *all* its
listings moved to one new key, `rematch` writes that to `game_redirect` (an additive table).
A key whose listings split across several new keys records nothing, because that would be
a guess. A key that comes back into use loses its redirect: it is its own game again.
`watch_status` tries the stored key, then the stored key run through today's `match_key`,
then the redirect chain (guarded against cycles), and takes the first that **is** a game.
A "New only" watch whose game is all pre-owned today reports nothing, rather than falling
through to another game's price. On the live data, all 109 keys this change retired still
found their game. The ☆ in the table checks against the key
the server resolved the watch to.

What is **not** on the stop list matters more than what is. "a" and "an" were on it at
first, and the first real title tried showed the problem: "Pokemon Legends Z-A"
tokenises to "… z a", so dropping the "a" would merge it with any "Legends Z". Single
letters carry meaning in titles. The test file pins these *must-not-merge* pairs as
carefully as the must-merge ones: Z-A vs Z, Mario Kart 8 vs 8 Deluxe, Xenoblade 2 vs 3.

> **The asymmetry that decides every rule here.** A missed merge costs one line in an
> alias file and is visible: two rows that should be one. A **wrong** merge puts two
> games' prices in one series, and nothing anywhere reports it. So the key errs towards
> splitting. It's the same asymmetry as `parse_price` returning `None` (§3.4).

### The pass

`rematch(conn, aliases)` recomputes **every** listing's game from `raw_title`,
`platform` and `region`, all of which are already stored, in one transaction. Games
nothing points at any more are deleted, so an improved key doesn't leave its old
spelling behind as an empty game. Three places run it:

| Where | Why |
|---|---|
| The end of every collection (`CollectService.run`) | New listings get grouped with no extra step |
| `serve`, once, if there are listings but no games | A database collected before matching existed works straight away, not after the next 20-minute run |
| `switch-tracker match` | After editing the alias file, regroup in about a second |

Because it reads only stored columns, **improving the matcher never requires a
re-scrape**. That was a design rule from the original handoff, and it's why matching is
a separate pass and not something done while collecting. A failure inside the pass is
caught and logged as a run warning: the prices are already saved, and grouping is
derived data.

`UNKNOWN`-platform listings are never matched, because matching them would group a PS5
title with its Switch namesake.

### Regions: separate in the data, together in the view

The `game` table keys `(canonical_title, platform, region)`. That is the original schema,
kept on purpose, because Play-Asia's regional editions are genuinely different products
(§3.9). But the **Games view groups by title and platform only**. "Where is this
cheapest?" is a question *across* regions, since an import is exactly the alternative
being compared. Each row still names its best offer's region, so nothing is hidden.

### When it gets one wrong

`matches.local.json`, in the data directory, maps one title onto another:

```json
{ "Zelda: Tears of the Kingdom": "The Legend of Zelda: Tears of the Kingdom" }
```

Both sides go through `match_key`, so you can paste titles straight from the dashboard
without knowing the key format. Then run `switch-tracker match`. A corrupt file is
ignored with no aliases, the same as `stores.local.json`: degraded, not broken.

There's no "split" override. Merges are the common failure and splits the rare one,
and because the key errs towards splitting, a wrong merge needs two titles to normalise
to the *same* string. Add a split mechanism when one is actually seen.

### The query, and the one-MIN() rule

`games()` returns one row per game with its **best offer**, meaning the cheapest you can
*buy*. In-stock offers rank ahead of every out-of-stock one:

```sql
MIN((1 - latest.in_stock) * 1e9 + latest.inr_price) AS best_rank,
latest.inr_price AS best_price, s.name AS best_store, l.url AS best_url, ...
```

The store and URL come from SQLite's documented **bare-column rule**: in an aggregate
query with *exactly one* `min()` or `max()`, the other selected columns come from the row
that produced it. That gives "the cheapest offer, *and where it is*" in one pass, without
a self-join. The word *exactly* is load-bearing, and it was learned the hard way. The
first version also selected `MAX(price)` for a price range, which quietly voided the
rule. `best_store` started naming an arbitrary row, and only the test asserting the
store *alongside* the price caught it. The range was dropped. It is the clearest example
in this codebase of a feature that wasn't worth the correctness it cost.

The same WHERE builder, `_filters()`, serves both `listings()` and `games()`. That's how
the two views can never disagree about what "In stock only" or a store filter means.

## 3.19 Collecting on a schedule

**Files:** `schedule.py`, `__main__.py`

History is the product, and history collected only when someone remembers to press a
button is sparse. Movers stay mostly empty, and a watchlist target has nothing to fire
against. Two commands fix that:

```bash
switch-tracker schedule --at 07:30    # daily Windows scheduled task (prints a cron line elsewhere)
switch-tracker schedule --off         # remove it
switch-tracker collect-now            # what the task runs; also fine by hand
```

From source, prefix them with `uv run python -m`. On Windows, `START.bat` forwards its
arguments, so `START.bat schedule --at 07:30` from a command prompt in the project folder
does the same thing. With the packaged build, run `switch-tracker.exe schedule --at 07:30`.

**`collect-now` goes through the same `RunLauncher` as the button.** It doesn't call the
collector directly, so a scheduled run gets every guard from §3.12: stale-run reaping,
the one-active-run unique index, and the PID lock that catches a second copy of the app.
A scheduled task that skipped those would be the one remaining way to start two
collections at once. If a run is already going, `collect-now` leaves it alone and exits
0, because the prices are being collected either way.

**It waits for the worker instead of exiting the moment it has spawned one.** Task
Scheduler considers a task finished when its process exits. A task that "finishes" in
50 ms while a 20-minute collection runs on unseen has a history that says nothing true,
and leaves a child process that "End task" can't reach. When the worker is gone,
`reap_stale()` closes any run it left unfinished with a readable reason, so a crashed
night doesn't block the next morning.

It refuses with exit code 2 if the stores have never been checked. That's the same rule
as the launch bootstrap (§3.15), and for the same reason.

`schedule --at` also refuses while `TRACKER_DATA_DIR` or `TRACKER_DB` is set in your
shell. The task runs in a fresh environment and wouldn't see either, so it would
quietly collect into the *default* database rather than the one you were pointed at.

The startup regroup in `serve` (§3.18) can meet a scheduled collection mid-write. If the
database is locked, it prints a note and starts the dashboard anyway, because the
running collection regroups everything when it finishes. A dashboard that refused to
start there would be all cost and no gain.

**No console window every morning.** The frozen exe is already built windowless
(`switch_tracker.spec`). From source, the task runs `pythonw.exe` instead of
`python.exe` when the venv has one.

**A day the PC was off isn't lost.** A plain `schtasks /SC DAILY` trigger simply skips
a day the PC was off at that time. So the task is registered from an XML definition
(`task_xml()`) with `StartWhenAvailable`, the one setting the `schtasks` flags can't
express: a missed run starts at the next chance. The task runs
`collect-now --slot 07:30` (its own time), which does nothing if a collection that
**succeeded** has finished since the most recent 07:30. So a catch-up never re-collects
a day you already collected by hand.

It's anchored to the slot, not a rolling window, and that matters. The first version
skipped if anything was collected "in the last 20 hours". A missed 07:30 caught up at
15:00 then made the *next* morning's run see a collection 16.5 hours old and skip,
leaving about 40 hours between collections. And only a collection where at least one
store succeeded counts: a catch-up that ran with no network writes all-failed rows,
and must not convince tomorrow that today is done. The XML also
runs as you with least privilege (no administrator rights needed), ignores battery
restrictions, and refuses a second overlapping instance.

**Alerts reach you with no tab open.** When the scheduled run ends, `notify_new_hits()`
compares the watchlist's hits *before* and *after* the run and shows a Windows
notification for each **new** one. That diff needs no stored state, and a game that
sits under target all week doesn't pop up every morning. The notification goes through
PowerShell's built-in WinRT API under PowerShell's own app id, so nothing is installed.
The script is a **constant**: game titles come from shop data, so they arrive XML-escaped
in an environment variable and are never spliced into PowerShell code.

**The dashboard shows the schedule, read-only.** A line under the Collector heading
reads `schtasks /Query`: *"Collects daily on its own · next …"*, or how to set it up.
`/api/schedule` only ever reads. Creating an OS task from a web endpoint is exactly the
capability a cross-site request must never reach (§1.4), so registering stays a command.

---

# Part 4 — The interface, feature by feature

Parts 1–3 are about getting prices into a database. This part is about getting them
back out of it in a form a person can read quickly.

The whole interface is one page, and its job is narrow: **let someone see, in a few
seconds, whether the collector is healthy and whether anything got cheaper.** Every
decision below traces back to that sentence.

## 4.1 The design system

**File:** `web/static/app.css`, the `:root` block.

Everything the interface draws comes from named values at the top of one file. There are
no loose pixel numbers further down — a hardcoded `13px` next to a `--t-base: 13.5px`
token is a bug, because the next person will copy whichever they see first.

| Scale | Values | Why these |
|---|---|---|
| Spacing | `--s1` 4px → `--s7` 48px | A 4px base. Every margin, padding and gap uses one. |
| Type | `--t-micro` 10.5 → `--t-xl` 21px | A tight 1.15 ratio, so six steps fit on screen without any one shouting. |
| Radius | `--r-sm` 4, `--r-md` 6, `--r-lg` 10 | Tied to element size. Not applied uniformly. |
| Motion | `--dur` 120ms, one easing curve | Short. This is a tool; transitions acknowledge input, they don't perform. |

**The surface ramp is the part worth understanding.** There are five background values,
and they are not arbitrary shades:

```
--bg-sunken   #0a0c10   inputs, the log — things you type into or read from
--bg          #0f1115   the page itself
--surface     #161920   panels resting on the page
--surface-raised #1c2029  table headers, popovers, buttons
--surface-hover  #212632  the row under your pointer
```

Darker means *recessed*, lighter means *raised*. That is how a physical stack reads under
one light source, and following it means depth never needs a shadow to be legible. The
whole app uses exactly two shadows, both on popovers.

**Colour is split into two systems that never mix.** `--accent` (a single red) marks the
one primary action. `--ok / --warn / --bad / --info` mean status and nothing else. Mixing
them is how you end up with a green "success" message sitting next to a green button that
is not a success — the reader cannot tell which green means what.

There is one more pair worth calling out:

```css
--drop: var(--ok);    /* a price went DOWN — good news here */
--rise: var(--bad);
```

Named for **meaning**, not hue. On a price tracker "down" is good, which is the opposite
of a stock ticker. Aliasing it means the table never has to know which colour that is.

## 4.2 Status, and why colour is never alone

**File:** `app.css`, the `.status` component.

A store can be `ok`, `partial`, `failed`, `skipped`, `running` or `idle`. Each renders
through one class, and each carries **three independent signals**:

```css
.status.ok      { color: var(--ok); }   .status.ok::before      { content: "✓"; }
.status.failed  { color: var(--bad); }  .status.failed::before  { content: "✕"; }
.status.partial { color: var(--warn); } .status.partial::before { content: "▲"; }
```

colour · glyph · and (where it matters) the word itself. Roughly one man in twelve has
some form of colour vision deficiency, so a red border alone is not a status — it is a
decoration that happens to be meaningful to most people. The glyph is what makes the
state survive a monochrome screen, and WCAG 1.4.1 requires exactly this.

The same principle drives the price columns: a drop renders `▼23.1%`, not just green
text.

## 4.3 The dashboard, top to bottom

The order of the page is the order of the questions:

**1. The topbar** — sticky, because the run status and the primary action must stay
reachable while you scroll a few thousand rows. It holds three things: what this is,
whether anything is running, and the single action you most likely came to press.

**2. The action bar** — everyday actions on the left, then a spacer, then the diagnostic
and destructive ones pushed to the far end. That distance is the safety mechanism.
Fitts's Law says a close, large target is easy to hit; the corollary is that the thing
you must *not* hit by accident gets distance. `Reset corrections` also keeps a confirm
dialog, but the layout does the first half of the work.

Note it is a **toolbar, not a card**. Boxing a row of buttons in its own rounded panel
adds a container whose only job is to announce "these are buttons", which the buttons
already do.

**3. The stats strip** — one bordered strip holding four figures, not four cards holding
one figure each. Same information, a third of the height. Cards would be right only if
each figure had its own actions or its own detail view. None of them does.

**4. The watchlist** — the games you starred, their best price right now, and your
target. It sits above the collector on purpose. "Has anything I want got cheap?" is
the question most visits are for, and a hit outranks a health tile (§4.6).

**5. The collector** — one panel containing a dense list, one line per store:

```
✕ Flipkart                    0
  failed · page loaded but nothing extracted...
✓ NI Gaming Store           338
```

This started as a grid of bordered status cards. At 24 stores that is 24 rounded boxes
wrapping about fifteen characters each — the brightly-coloured dashboard that scans
*badly*, precisely because every item shouts equally. A list answers the real question
("which broke?") faster: the glyphs line up into a column your eye can run down, and
`boot()` sorts failures to the top, so you find them without reading a single name.

Healthy stores get one line. Only a store worth investigating spends a second line on its
reason — a column of two dozen identical "ok"s is noise.

**6. Progress** — hidden until a run exists, because an empty panel is noise. When a run
starts it shows the current store, page, running totals and failure count, with the raw
log **collapsed inside it**. Diagnostics matter when something breaks and should not
dominate the page the rest of the time.

**7. Moved since last run.** This shows six rows, then `Show all N changes`, with a
**Store** dropdown above it.

The preview limit is a layout decision. When the backend returned sixty rows, showing
all sixty measured 3,176px of a 9,409px page. That is a third of the document for a
secondary section, and it pushed the main table out of sight. The preview stays at six
whatever the backend returns.

The backend used to **cap** movers at sixty. It no longer does, and the reason is about
honesty, not convenience. A cap made every count derived from it a *floor*. The UI had to
print "60+ changed", and the "price drops" figure in the stats strip could only ever say
"at least". Removing the cap makes both numbers true totals. The 1% movement floor
(§3.11) is what keeps an uncapped list from filling with rounding noise.

The store dropdown is built from the stores that **actually have movements** in the
current data, not from the full store list, so no option ever leads to an empty panel.
If a refresh removes the selected store's movements, the filter falls back to *All
stores* instead of showing an unexplained blank. Filtering happens in the browser over
data already fetched. That's an exception to the "filter in SQL" rule in §3.11, and it
is safe only because the list is now complete: filtering a capped list would answer
"which of the first sixty moved at this shop", which is a different question. (It costs
a full fetch on every page load, and that's on the improvement list for when movers
reach the thousands.)

**8. The table** — Games by default, Every listing one click away. §4.4 covers what both
views share, and §4.5 covers the Games view and the ▸ detail rows.

## 4.4 The listings table

**File:** `app.js`, `search()` and `headerCell()`.

This is the part people actually use, so it gets the most attention. Everything in this
section applies to both views (§4.5). The examples use Every listing because it has
more columns.

**Sorting is keyboard-operable**, which it previously was not:

```js
return `<th class="${cls}" scope="col"${active ? ` aria-sort="${dir}"` : ""}>
  <button class="sort" type="button" data-sort="${col.key}">…</button></th>`;
```

The old version put a click handler on the `<th>` itself. That works with a mouse and is
invisible to a keyboard — a `<th>` is not focusable, so the sort could never be reached
by Tab. A real `<button>` fixes it and gets Enter/Space handling for free. `aria-sort`
lives on the `<th>`, which is where assistive technology looks.

**Sorting re-queries the server.** Re-sorting the hundred rows already on screen would
sort a *subset* and present it as the whole answer — the cheapest price on this page is
not the cheapest price.

**The Change column is sortable, so it comes from the server.** It started as a
browser-side join: `/api/movers` and `/api/listings` both return `l.id`, so the page
matched them up with

```js
movementById = new Map(mv.map((m) => [m.id, m]));
```

That was free, and it was fine until someone wanted to *sort* by change. A browser-side
join can only sort the rows already on screen, which is the subset problem from the
paragraph above. So `listings()` now returns `change_pct` on every row (§3.11), and
sorting by change re-queries the server like any other column. The map is still there
for two things only the movers payload has: the previous absolute price for the
`was ₹4,499` tooltip, and the `fx_suspect` flag that decides whether a drop counts as a
deal.

Unchanged and sub-1% prices render as `—`, not `+0.0%`. A plus sign in front of zero
makes "nothing happened" look like a rise. (`deltaCell` also has a `<0.1%` branch for
moves too small to show at one decimal. It predates the 1% floor and can no longer be
reached.)

A row whose price dropped gets `▼23.1%` and a green rule in the gutter. The rule is
`inset 3px 0 0` on the first cell — not a coloured row background, which would destroy
the scannability the table exists for and collide with the hover state.

**Row height was a real measurement.** Tags originally sat on their own line under the
title; median row height was 55px. Putting the title and tags on one shared, clamped line
brought it to 40px — a 1000px viewport went from eighteen visible products to twenty-eight.

**The table has its own scroll viewport, and that is load-bearing:**

```css
.tablewrap { overflow: auto; max-height: calc(100vh - var(--table-chrome)); }
```

The horizontal half stops the page body scrolling sideways. The vertical half is subtler:
`overflow-x: auto` alone already makes an element a scroll container (CSS computes the
other axis to `auto` when one is not `visible`), so `position: sticky` on the header
sticks to *that box*, not the viewport. Unbounded, the box never scrolls internally and
the header simply leaves with the page. The height limit is what gives sticky something
to stick inside. This is a trap worth remembering — it looks like a `top` offset bug and
is not one.

**"Load 100 more" appends; it doesn't repaint.** It used to rebuild the whole table by
reassigning `innerHTML`. That destroyed the rows you were reading, left the browser
nothing to anchor the scroll position to, and snapped you back to the top, so every
"load more" cost you the scroll back down. Now `search(append=true)` paints only the new
rows and inserts them into the `<tbody>` already on screen. Two details matter:

- **Focus survives.** If you reached the button by keyboard, focus moves to the new
  button with `preventScroll: true`, so you aren't dropped onto `<body>` and the view
  doesn't jump past the rows that just arrived.
- **Sort handlers bind only on a full paint.** On append, the header buttons keep their
  existing DOM nodes, so binding again would make one click sort twice.

## 4.5 Games, offers and price history

**Files:** `app.js` (`gameRowHtml`, `offersHtml`, `historyHtml`), `web/queries.py:games`.

The table has two views, chosen by a segmented control at the start of the toolbar:
**Games** (the default) and **Every listing**. They share every filter, the chips, the
sort buttons and the "Load more" path. Only the endpoint, the columns and the valid sort
keys change.

**Games is the default because it answers the question people come with.** "Where is
Metroid Prime 4 cheapest?" used to mean typing "metroid" and scanning six rows from four
shops. Now it is one row that already shows the answer:

```
▸  Metroid Prime 4: Beyond         ₹4,499   Amazon India          3 stores   ☆ Watch
```

**A row is named after the game, not its cheapest copy.** The name is the shortest
title among the game's *new* listings, falling back to a pre-owned title only when
nothing new exists. The first version used the cheapest listing's title, and the
cheapest copy is often used, so rows read "Super Mario Bros. Wonder - Pre-Owned". The
condition belongs in the badge beside the best offer, not in the game's name.

**Is it a good price?** Under the best price sits its history: a dim *"lowest ₹3,499"*
when it has been cheaper before, or a green **lowest ever** tag when today's best *is*
the all-time low. That's the lowest price recorded for the game across every store and
every collection. It's a plain `MIN` over price history, so it can't produce a false
"deal" the way trend detection could. The tag needs at least two collections of history:
seen only once, every price is trivially its own lowest.

*Best price* is the cheapest offer **you can buy**, so in-stock offers rank ahead of
out-of-stock ones (§3.18). The store name links straight to that offer. In both price
directions, games you can buy come first, out-of-stock-only games next, and games with
no rupee price yet (no exchange rate) come last. An offer with no rupee price still
counts in *Offers*, because it will appear when you expand the row, but it is never
chosen as "best".
**"In stock" also means "still listed".** A product the shop has removed keeps its last
price point forever, so it used to stay "in stock" at its old price, and could win "best
price", indefinitely. Now a listing counts as buyable only if no *fully successful* run of
its store has happened since its latest price (`_IN_STOCK` in `web/queries.py`). A partial
or failed run proves nothing, because it may simply not have reached that listing.
When sorted by price, a separator row, *"Out of stock everywhere — sorted by price again
below"*, marks where the buyable games end. Without it, a ₹2,999 game listed under a
₹6,499 one under "Best price ▲" looked like a broken sort. It is drawn once per list,
including across "Load more".
*Offers* reads "3 stores" when every offer is at a different shop. It says "4 offers · 3
stores" only when one shop lists the game twice, usually new and pre-owned. The first
version printed "1 · 1 store" on every single-shop game, which read like a typo.

Switching views resets the sort only if the new view has no such column. Otherwise a
"Change" sort would fall back silently on the server and leave a stale ▲ on screen.

**Late replies are dropped.** Every `search()` takes a sequence number, and a reply
that is no longer the latest is thrown away. Without it, pressing "Load more" in Games
and switching to Every listing before it answered *appended game rows into the listings
table*. Any two quick filter changes could also paint the older answer last. The view
toggle made a long-standing race easy to hit, which is why it was fixed alongside it.

### Expanding a row

The ▸ at the start of every row opens a **detail row** underneath it, in place, without
leaving the page:

- On a **game**, it lists every offer for that game. The request reuses the current
  filters (`filterParams()`), so the offers you see are exactly the ones the *Offers*
  count was computed from. Tick "In stock only" and the expanded list shrinks with it.
- On a **listing**, including one inside an expanded game, it shows that listing's price
  history.

```
▾  Metroid Prime 4 Beyond   NI Gaming Store   ₹4,799
   ╱╲___╱‾‾╲__•   Now ₹4,799 · lowest ₹4,499 (12 Sep) · highest ₹5,499 · 9 prices since 1 Aug
```

The history line is one SVG `<polyline>`, with no chart library (§4.10). It is
**time-scaled**: a three-week gap between collections looks like a gap, instead of being
squeezed between two neighbouring points. It is also `aria-hidden`. **The sentence next to
it is the content**, and it is what a screen reader reads: now, lowest-ever with its
date, highest, and how many observations. The lowest-ever price is the number a buyer
actually wants, which is why it gets the bold. With only one price recorded, the panel
says so ("a line appears after the next collection") rather than drawing a dot.

`/api/history` existed from the start with no caller, and its docstring said charting
would be "built on purpose or not at all". This is that.

**The ▸ is a real `<button>` with `aria-expanded`**, and the CSS draws ▸ or ▾ *from that
attribute*. What you see and what a screen reader hears can't disagree about whether a row
is open. Every ▸ on the page, nested ones included, is handled by **one** delegated
listener on `#list`, bound once at load. A listener per button would be lost on each
repaint and doubled on each append, which is the same trap as the facet bug in §4.7.

## 4.6 The watchlist

**Files:** `app.js` (`paintWatch`, `notifyNewHits`), `web/watchlist.py`,
`web/routers/watch.py`, `web/queries.py:watch_status`.

Press **☆ Watch** on a game and it joins the Watchlist panel, which sits near the top of
the page, above the collector. "Has anything I want got cheap?" is the question most
visits are for, and a hit is worth more than a health tile. Type the price you would pay
into *Your target*. It saves when the field loses focus, and you can leave it blank to
just keep an eye on a game.

```
Watchlist   3 watched · 1 at or below target
Metroid Prime 4: Beyond  ✓ at target    ₹4,499   Amazon India   [ 4500 ]   Remove
Mario Kart World                        ₹6,299   NI Gaming      [ 5500 ]   Remove
```

**Every change answers back, and the destructive one can be undone.** The target box
saves when it loses focus, with no button, so a note beside the heading confirms
"Target ₹4,000 saved". Unwatching used to throw a typed-in target away with no way
back. Now the note offers **Undo** for twelve seconds, which restores the entry *with*
its target. The repaint after a save also puts keyboard focus back where Tab sent it;
without that, tabbing out of a target box landed you at the top of the page.

**Any copy, or new only, per game.** Each watched game has an **Any / New only** toggle.
With *Any*, a pre-owned copy under target is a hit; with *New only*, used copies are
ignored entirely, for the best price, the stock check and the lowest-ever figure alike.
It's the same `games()` query with the condition filter set, so all three agree.
Entries written before the toggle existed read as *Any*, which is how they already
behaved.

**The two controls never overwrite each other.** A save that leaves a field out keeps
the stored value: the target box sends no condition, and the toggle sends no target.
The toggle used to send the target it had on hand. Type a new price, click *New only*
before leaving the box, and if the toggle's request landed second it put the **old**
price back. An explicit `null` target still means "no target"; the server tells
*omitted* from *null* apart. **Undo** re-sends the old target and condition
explicitly, because the deleted entry had nothing left to keep.

**A hit needs the best offer to be in stock.** "₹2,999, sold out" is not a price anyone
can act on, and an alert that fires on it teaches you to ignore alerts. A test pins
exactly that case.

How a hit reaches you, from always to most intrusive:

1. **The panel.** Hits sort first, with a green gutter rule plus "✓ at target", so it
   never relies on colour alone (§4.2).
2. **The tab title.** It becomes `(1) Switch cartridge prices`, visible from any other tab.
3. **A desktop notification**, if you allowed one. The browser asks the first time you
   press ☆, because permission can only be requested from a click. Each hit is announced
   **once**: the keys of current hits are kept in `localStorage`, so reloading doesn't
   re-announce, and a game that later drops back under target *is* announced again.

The limitation, stated plainly: notifications fire only while a dashboard tab is open.
A scheduled collection (§3.19) at 7:30 with no tab open shows its hits the next time you
open the page. Anything more would need a service outside the machine, which this
project deliberately doesn't have (Part 6).

**Stored as a file, not a table.** `watchlist.local.json` lives in the data directory
next to `stores.local.json`. That keeps the dashboard's database writes limited to run
bookkeeping, and it means the watchlist survives deleting `tracker.db`, which is exactly
when you would least want to re-enter every target. Entries are keyed by *game key +
platform*, **not by game id**. An id isn't stable across matcher changes: a key that
changes means one game deleted and a new one created (§3.18), so a list of ids would
silently empty itself the first time the matcher improved. Keys can change too, because
adding an alias renames one. So `watch_status` resolves every watched key **through the
aliases** before looking it up, and adding the alias that fixes a split never orphans a
watch on the old spelling.

Three protections around the file, all found by an adversarial review of the first
version:

- **One lock around every read and write.** FastAPI runs these endpoints on a thread
  pool, so two quick ☆ clicks are two concurrent read-modify-writes. Measured without
  the lock: 40 parallel adds kept **2**, and 32 failed outright, because on Windows
  `os.replace` raises `PermissionError` while another thread has the file open.
- **Write to a temp file, then rename.** A reader never sees a truncated file, which a
  plain `write_text` (empty the file first, then fill it) would show for a moment.
- **A file `read()` can't use is renamed to `.json.bad-<n>`** (a unique number per
  rename, so two bad edits never overwrite each other) before anything is written
  over it. That covers broken JSON *and* valid JSON that isn't a list, so a hand-edit
  with a typo is set aside rather than destroyed. A non-numeric target such as `"4000"`
  is read as "no target" instead of crashing the panel.

## 4.7 Filters

Search, two segmented controls, two checkbox popovers, a stock toggle, and a reset.

**Active filters appear as removable chips**, each removing exactly one condition:

```
[search zelda ×] [console Switch 2 ×] [store CeX India ×]  Clear all
```

Recognition rather than recall: you can see what is narrowing the list without reopening
four menus, and narrowing is never a one-way door you have to hunt to undo.

**The popovers are `<details>` elements.** Native disclosure semantics give keyboard
operation and screen-reader state for free. The only thing JavaScript adds is
click-outside and Escape to close, because that is the one behaviour `<details>` does not
have and every other menu on the platform does (Jakob's Law).

**The store and region boxes are rebuilt after every collection**, because a run can add
stores and regions. Two things follow, and the first was a real bug:

- **Their listeners are bound once, at load, on the containers.** The binding used to
  live inside `loadFacets()`, which `boot()` reruns when a collection finishes. Each run
  stacked one more listener, so after five runs a single tick fired five searches. That
  is invisible until the network panel is open, and it gets worse the more you use the
  app.
- **Rebuilt boxes are re-ticked from `state`.** Otherwise the summary would still say
  "Store (2)" over a popover with nothing ticked, with the filter still applied and no
  visible way to see which stores it was.

**Counts follow the other filters.** "Amazon India (1)" means one matching item *under
everything else you've set*, so choosing Switch 2 updates the store counts. A facet ignores
its *own* filter, though: ticking a store must not zero every other store's count, or you
could never widen the selection. `queries.facets` takes the same `ListingQuery` as the list,
and a sequence number drops late replies, the same way `search()` does.

**The filters live in the URL.** `?view=listings&q=mario&platform=SWITCH2&store=amz` works
on refresh, as a bookmark, or as a link. The URL is rewritten with `history.replaceState`
on each full repaint, so it doesn't add history entries. It is read once, before `boot()`,
and only known values are accepted: an unknown view, sort or direction is ignored, and the
search text only ever reaches the page through `esc()`. Paging (`offset`, `limit`) is never
put in the URL. Back/forward navigation between filter states was skipped: add
`pushState` and `popstate` if people ask for it.

**`/` focuses the search box** and Escape clears it — the convention every search-bearing
app shares. The handler ignores the keypress while you are typing in a field, or the
character could never be typed *into* one.

## 4.8 Every state a view can be in

A view that can load has a **loading** state, a view that can be empty has an **empty**
state, and anything that can fail has an **error** state. Each is built, not left to
chance:

| State | What renders |
|---|---|
| Loading | A skeleton the same shape as the content, so nothing jumps when data lands |
| Empty (no data) | "Nothing collected yet — press Collect prices to fill this in" |
| Empty (no matches) | "Nothing matches those filters" + a pointer at the chips above |
| Error | A red notice naming what failed and what to do |
| Running | Status pill, progress bar, current store and page, live counts |
| Finished | The panel **stays**, showing the outcome |

The skeleton matters more than it looks. A spinner occupies no space, so when real
content arrives the page lurches downward — the metric for that is Cumulative Layout
Shift, and a skeleton of roughly the right height keeps it near zero.

## 4.9 Accessibility, measured

Not asserted — measured, with a script driving the real rendered page.

**Contrast.** Every text node in the rendered DOM was walked, its computed colour compared
against the nearest ancestor that actually paints a background. All 669 pass their
threshold (4.5:1 normal, 3:1 large). One token moved because of it: `--ink-3` cleared
4.63:1 on `--surface` but only **4.29:1** on `--surface-raised`, which is exactly where
column headers and popovers put it. The fix is to check against the *lightest* surface a
colour lands on, not the page.

**Control boundaries** get their own token for a reason:

```css
--line-control: #606a88;   /* 3.52:1 on --bg */
```

WCAG 1.4.11 wants 3:1 for the visual information required to identify a control, and
nothing at all for a decorative divider. On this palette a button's fill reaches only
1.16:1 against the page and an input's 1.04:1 — so the border *is* the boundary and has
to carry that contrast alone.

**Keyboard.** A real Tab pass: 24 stops, every one with a visible focus ring, no positive
`tabindex`, order matching the visual layout. A skip link jumps past the lot to the table.

**Reflow.** No horizontal scrolling on the page body at any width from 1920px down to
320px (WCAG 1.4.10).

## 4.10 What was deliberately NOT done

Worth recording, because these are the things a redesign reaches for by default:

- **No gradients, no glassmorphism, no glow.** A measurement of the rendered page finds
  zero gradient backgrounds and two shadows, both on popovers.
- **Two radii, three font weights, six type sizes** on screen. Checked by reading computed
  styles off the live page, not by intent.
- **One animation** — the pulsing dot while a run is active, and it is the only thing on
  screen that moves. All motion sits behind `prefers-reduced-motion`.
- **No icon set.** The status glyphs are text characters. A dependency that ships a
  thousand icons to use six is a packaging problem, not a design win.
- **Dark only.** A deliberate choice for a data-dense utility rather than an unfinished
  one — a light theme is a second set of contrast decisions, not an inverted hue.

---

# Part 5 — The five ideas that recur

If you remember nothing else:

**1. The dangerous failure is the one that produces a plausible number.**
`Rs. 4499` → ₹0.45. `3,599` → ₹3.60. `$59.99` stored as ₹59.99. None threw an exception.
Hence: `parse_price` returns `None`, never `0`. `inr_price` is nullable. Adapters return
`Failed(reason)` rather than an empty list.

**2. When you can't compute something correctly, write nothing.**
> *"A missing number is recoverable; a wrong one is indistinguishable from a real price
> forever after."*

**3. Enforce architecture with tests, not documents.**
`test_import_boundary.py` fails the build if the dashboard imports scraping code.
A test asserts the adapter's time budget is lower than the service's deadline. A test
pins which shops use which pagination mechanism. Comments can't fail a build.

**4. Per-shop differences are data; per-shop mechanisms are code.**
Ten browser shops with different recipes, and every store-id branch in the codebase
belongs to one of them (Flipkart). The trigger for revisiting that is written down, and so
is the point at which it starts to bite (§3.9).

**5. Record why, especially when the reason is a bug you already hit.**
Nearly every non-obvious line has a comment naming the failure that motivated it. That is
why the three price-parsing bugs are still fixed, and why nobody will "simplify" the
classifier's ordering back into breaking.

---

# Part 6 — What is still not built

This part used to list two features as "the reason the project exists": the matcher and
the alert engine. The matcher is now built (§3.18). The alert engine is half built: the
half you configure yourself exists, and the half that works things out for you does not.

**Built: targeted alerts.** The watchlist (§4.6) answers *"tell me when X is under ₹Y"*,
which is a rule you write yourself, against a price you chose.

**Not built: detected alerts.** This would spot a real price drop against a listing's
own trailing median, and **suppress it** when it's actually the whole shop repricing or
the rupee moving. A currency move is not a sale. It is the difference between "you told
me to watch Metroid" and "Zelda is 30% under its usual price and you never asked".

That second half explains the data model. Storing the native currency *and* the derived
rupee figure *and* the exchange rate's publication date looks redundant until you need to
ask: *"did four hundred prices move by the same ratio on the same day?"* The `movers`
endpoint already flags that cluster pattern; nothing acts on it yet.

It's also why thinning old data was measured and rejected: collapsing history to weekly
would delete exactly the same-day resolution that detection depends on — and the
measurements showed it wouldn't have fixed the speed problem anyway.

**Not built: alerts that reach you with no tab open.** Desktop notifications fire only
while the dashboard is open in a browser (§4.6). Anything more, such as email, Telegram
or a phone push, means sending data to a service outside this machine, which this
project has so far deliberately avoided. It's a real decision to make, not an oversight.

---

## Where to start reading

| If you want to understand… | Read |
|---|---|
| The architecture | `docs/python-rewrite-hld.md` §2–3, then `__main__.py` |
| What a "good" comment looks like here | `core/parse.py` |
| The trickiest code | `adapters/browser/extract.py` |
| How failures reach you | `core/models.py`, then `adapters/base.py` |
| The tests that hold it together | `test_import_boundary.py`, `test_queries.py` |
| What actually happens when you press a button | Part 2's trace, with the files open |
| A word you don't recognise | Appendix A |
| How to run, test and change it | Appendix B |

---

# Appendix A — Glossary

Every term this document uses that isn't ordinary English. Alphabetical, so you can
land here from anywhere.

| Term | What it means here |
|---|---|
| **adapter** | Code that knows one way to read a shop. Three exist: Shopify feed, WooCommerce API, real browser (§3.2). |
| **argv** | The words after the program's name on the command line. `collect --run-id 7` is argv, and it is how this app tells a new copy of itself what to be (Part 2). |
| **async / await** | Code that hands control back while waiting on the network instead of sitting idle. `await` = "pause here, resume when the answer arrives" (§1.7). |
| **bounded_gather** | This project's helper for "run these N jobs, but never more than K at once" (`core/concurrency.py`). |
| **CSS selector** | A string that picks elements out of a page, e.g. `div.product-card h3`. The least durable way to read a shop (§3.6). |
| **decorator** | The `@something` line above a function. It attaches behaviour without changing the function — `@router.get("/summary")` means "call this for that URL" (§1.3). |
| **dependency injection** | Declaring what a function needs (`conn: Conn`) and letting the framework supply it. What lets tests swap in a throwaway database (§1.3). |
| **fixture** | Named test setup that a test asks for by naming a parameter. `def test_x(self, conn)` gets a fresh database (§1.12). |
| **frozen** | Running as the packaged `.exe` rather than from source. `sys.frozen` is how the code tells (§3.17). |
| **FX** | Foreign exchange — here, the USD→INR rate used to compare Play-Asia with Indian shops (§3.10). |
| **game** | One title on one platform, grouped across shops by the matcher. The Games view shows one row per game (§3.18, §4.5). |
| **headful / headless** | Headless = the browser runs invisibly (normal). Headful = you can see the window (debugging, and required by the click-to-pick tool). |
| **hydration state** | The raw data a JavaScript page was built from, left embedded in the page (e.g. Flipkart's `__INITIAL_STATE__`). Often more stable than the visible HTML (§3.6). |
| **index (database)** | A structure that lets SQLite find rows without reading every one. §3.11 is a lesson in *using* one versus *seeking* with one. |
| **JSON-LD** | Structured product data shops embed for Google. Layer 1 of the extraction ladder, because it exists for search engines and survives redesigns (§3.6). |
| **lint** | Automated review for things that aren't errors: unused imports, suspicious patterns. Here: `ruff` (§1.13). |
| **listing** | One product at one shop. `UNIQUE(store_id, sku)` (§3.5). |
| **lock file** | `run.lock`, holding a running worker's process id. Guard layer 3 against two runs at once (§3.12). |
| **mypy / type checking** | Reads your type annotations and finds mismatches *before* you run the code. Configured `strict` here (§1.14). |
| **match key** | The normalised form of a title that the matcher groups on: `"Pokémon Legends: Z-A (Switch 2)"` → `"pokemon legends z a"`. Two listings with the same key, platform and region are the same game (§3.18). |
| **oracle (test)** | A frozen, known-good copy of old behaviour that a rewrite is compared against. Deliberately *not* imported from production, so it can't silently agree with a wrong change (§3.11). |
| **ORM** | A library that hides SQL behind objects (e.g. SQLAlchemy). Deliberately not used — the SQL *is* the logic here (§1.6). |
| **overrides / corrections** | Machine-written config that layers on top of the hand-written config, in a *separate file*, because a tool must never rewrite the source it also imports (§3.1). |
| **pagination** | Walking a shop's catalogue page by page. Knowing when to stop is a real problem (§3.7, §3.8). |
| **Partial** | An outcome meaning "I got rows, but I believe some are missing". The whole point of §3.2. |
| **pid** | Process id — the number the operating system gives a running program. Checkable, which is why the lock file stores one (§3.12). |
| **Playwright** | Microsoft's browser-automation library. Starts a real Chrome, runs the page's JavaScript, and can pass values back to Python (§1.8). |
| **PRAGMA** | A SQLite setting. Two matter here: `journal_mode = WAL` and `busy_timeout` (§1.6). |
| **price point** | One price for one listing at one moment. Append-only; this is the history. |
| **probe** | The job that asks each shop "what software do you actually run on?" and writes corrections (§3.16). |
| **process** | A running program with its own memory, killable on its own. This app deliberately uses one for the dashboard and one per job (Part 2). |
| **query plan** | SQLite's explanation of *how* it will answer a query. `EXPLAIN QUERY PLAN` is what exposed the §3.11 problem. |
| **route / router** | A URL and the function that answers it. Grouped in `web/routers/` (§1.3). |
| **run** | One press of a button, one row in the `run` table, one id stamped on everything that happens. |
| **scraping** | Reading data out of a page built for human eyes, because there's no data feed. |
| **selector scoring** | Checking a human's click against the real page before saving it — "matched 88% of sampled cards" (§3.16). |
| **SKU** | The stable per-shop product id. If it isn't stable, every price series has exactly one point and nothing reports an error (§3.5). |
| **SSE (Server-Sent Events)** | One long-lived HTTP response the server keeps pushing text into. One-way, auto-reconnecting, no library (§1.10, §3.13). |
| **struck page** | A page that failed to *load*, as opposed to one that loaded and came back empty. It is held back, retried in a second pass after the walk, and reported only if it is still missing (§3.7). |
| **subprocess** | A process started by another process. The dashboard starts every job as a subprocess of itself (Part 2). |
| **template** | HTML with placeholders, filled in by Python. Here: Jinja2 (§1.5). |
| **transaction** | A group of database writes that either all land or none do. `_persist` wraps a whole store's rows in one. |
| **upsert** | Insert, or update if the row already exists. `INSERT … ON CONFLICT … DO UPDATE` (§3.11). |
| **watchlist** | Games you starred, each with an optional target price. A **hit** means the best *in-stock* offer is at or below target (§4.6). |
| **WAL** | Write-Ahead Logging: SQLite mode where readers and writers work simultaneously. Required here, because the dashboard reads while a worker writes (§1.6). |
| **worker** | A subprocess doing one job — `collect`, `probe`, `fx`, `inspect` (Part 2). |

---

# Appendix B — Working on the code

## B.1 The gate — what must pass before anything is done

Nothing is "done" until all four are green. Run them from the project root.

```bash
uv run pytest                           # 704 tests, about 1.5 minutes in parallel
uv run ruff check src tests scripts     # lint
uv run ruff format src tests scripts    # formatting (rewrites files)
uv run mypy                             # types, strict mode
uv run python -m switch_tracker spike   # the packaging self-check (§3.17)
```

`pytest` runs the tests **in parallel**, one worker per CPU core (pytest-xdist, set in
`pyproject.toml`): about 1.5 minutes on 8 cores, against 4.5 one at a time. To debug a
test with `print` output or `--pdb`, run it with `-n 0`, which runs one at a time.

`pytest` never touches the network and never touches your real database — every test
gets a throwaway one from a fixture (§1.12). It is safe to run constantly.

## B.2 Testing against a real shop

Unit tests prove the logic; only the live site proves a shop still looks the way it did
last month. The live-site tools (`check_stores.py` and the narrower `scrape_check.py`,
`diagnose_extraction.py`, `category_check.py`), and `check_data.py` for what a collection
saved, are documented with every option in
[`troubleshooting.md` §2–3](troubleshooting.md#2-validating-the-stores).

## B.3 Where the tests for X live

| You changed… | Run… |
|---|---|
| `core/parse.py` | `tests/test_parse.py` |
| `core/skus.py` | `tests/test_skus.py` |
| `core/db.py`, the schema | `tests/test_db.py` |
| `core/http.py` | `tests/test_http.py` (starts a real local web server) |
| `core/concurrency.py` | `tests/test_concurrency.py` |
| `config/stores.py` | `tests/test_stores.py` |
| `adapters/shopify.py` | `tests/test_adapter_shopify.py` |
| `adapters/woocommerce.py` | `tests/test_adapter_woocommerce.py` |
| anything under `adapters/browser/` | `test_adapter_browser.py`, `test_browser_extract.py`, `test_browser_logic.py` |
| the page loop's retry / skip / second pass (§3.7) | `tests/test_flipkart_recovery.py` (mocked page, no browser) |
| `services/collect.py`, `selection.py` | `tests/test_service_collect.py` |
| `core/matcher.py` | `tests/test_matcher.py` (must-merge *and* must-not-merge pairs) |
| `schedule.py` | `tests/test_schedule.py` (never touches the real Task Scheduler) |
| `web/watchlist.py`, `routers/watch.py` | `tests/test_web_app.py` (`TestWatchlist`) |
| `services/probe.py` | `tests/test_service_probe.py` |
| `web/queries.py` | `tests/test_queries.py` (holds the frozen oracle from §3.11, plus `TestGames`, `TestWatchStatus`) |
| `web/runs.py` | `tests/test_runs.py` |
| `web/app.py`, `web/routers/` | `tests/test_web_app.py` |
| `events/` | `tests/test_events.py` |
| `fx/rates.py` | `tests/test_fx.py` |
| `__main__.py` | `tests/test_entrypoint.py` |
| **any import in `web/`** | `tests/test_import_boundary.py` — the architecture test (Part 2) |

Run one file, or one test, while working:

```bash
uv run pytest tests/test_parse.py
uv run pytest tests/test_parse.py -k price -vv
```

## B.4 Your first change — a guided exercise

The house style here is **test first**: write the failing test, watch it fail for the
right reason, then decide where the fix belongs (§1.12). Try it on the 40 lines with the
worst track record in the project — the price parser (§3.4).

**Warm-up (read only).** Pick a browser store and watch which extraction layer wins:

```bash
uv run python scripts/scrape_check.py gamenation --pages 1
```

Compare its output against the ladder in §3.6. You should be able to say *which* of the
four layers produced those rows, and why the ones above it didn't.

**Step 1 — find the failure yourself.** `parse_price` handles the six formats in §3.4.
Poke at it directly:

```bash
uv run python -c "
from switch_tracker.core.parse import parse_price
for s in ['Rs. 4499', '3,599', '4.499,00', 'MRP \u20b94,499 \u20b93,999', '\u20b94,499 \u2013 \u20b95,299']:
    print(repr(s), '->', parse_price(s))
"
```

The first three are the formats §3.4 was hardened for, and they are right. The last two
are a **discount label** ("was ₹4,499, now ₹3,999") and a **price range** — both
extremely common on Indian storefronts — and today they come back as `44993999.0` and
`44995299.0`. Two numbers glued together.

Sit with that for a second, because it is §3.4's lesson happening live: nothing raised,
nothing returned `None`, and the answer is off by four orders of magnitude.

**Step 2 — write the test before touching anything.** `tests/test_parse.py` groups cases
in classes (`class TestParsePrice`) and uses `pytest.mark.parametrize` for tables of
inputs. Add your two cases in that style, assert what you think is *correct*, and run:

```bash
uv run pytest tests/test_parse.py -k price -vv
```

**Step 3 — decide where the fix belongs.** This is the actual exercise, and there is no
single right answer. Three real candidates:

| Where | What it would mean |
|---|---|
| `parse_price` itself | "Two figures in one string → take the *lower*" (the sale price). Fixes every caller at once, and bakes a retail assumption into a pure parser. |
| The caller, `adapters/browser/extract.py:264` | A fallback already lives there: `parse_price(row.get("priceText")) or first_rupee_price(...)`. `first_rupee_price` deliberately takes the **first** rupee figure out of a text blob — maybe the selector path should lean on it harder. |
| `price_looks_wrong` (`parse.py:260`) | It already flags anything outside ₹299–₹12,000, so a glued number *is* noticed — but only as "worth a look", never rejected. Is flagging enough? |

Before you choose, answer the question that decides it: **can any shipped store profile
actually produce such a string?** `adapters/browser/profiles.py` holds the `price`
selectors (§3.9), and one pointing at a card container rather than the sale-price element
would deliver exactly this. Check, then write what you found in the test's docstring —
whether the answer is "reachable today" or "not with current profiles, but one selector
change away", that sentence is worth more than the fix.

**Why this exercise and not "add a feature":** every rule in `parse_price` exists because
it was wrong once, in a way that produced a believable number and no error. Once you have
felt that, the comment density everywhere else in this codebase stops looking like
over-explaining.

**If you want a bigger one.** Add a twenty-fifth shop to `config/stores.py`: guess its
`kind`, leave `platform_hint` alone unless the shop sells *only* Switch games (§3.3),
then press **Check stores** and let `probe` correct your guess (§3.16). Watch what it
writes to `stores.local.json` — and note that your guess in `stores.py` was never edited.

## B.5 Things that will surprise you

- **Imports inside functions are deliberate.** `__main__.py` and `collect_worker.py` do
  this to keep Playwright out of the dashboard's import graph (Part 2). A test enforces
  it. Don't tidy them to the top of the file.
- **`except Exception` with a `# noqa: BLE001` comment is deliberate too.** The lint rule
  is switched *on* precisely so each of the dozen exceptions has to be justified in a
  comment next to it (§1.13).
- **`uv.lock` is not committed** in this repository, on purpose — see the reason in
  `.gitignore`. `pyproject.toml` bounds every version; each machine resolves its own.
- **Browser-store profiles are allowed to ship unverified.** `cex_in`'s selectors are
  explicit guesses, marked as such in `profiles.py`. That is a deliberate choice, not an
  oversight: when nothing extracts, the adapter already dumps the rendered HTML and tells
  you which tool to run, so a guess fails no worse than an empty profile while producing a
  better dump to fix it from. Replace them from that dump before trusting a run.
- **A store's `platform_hint` never beats an explicit marker.** Every shop in the list
  hints `SWITCH`, including the ones scoped to a Switch 2 category. `platform_of` checks
  the Switch 2 patterns *first* for exactly that reason — otherwise a whole Switch 2
  catalogue would file itself under the wrong console (§3.3).

---

# Appendix C — When it doesn't work

Moved to [`troubleshooting.md`](troubleshooting.md): every symptom with its cause and fix, plus every command that validates the stores, the collected data and a build.
