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
| **stuck, right now** | **Appendix C**. |

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
  - [1.9 htmx + plain JavaScript — the front end](#19-htmx--plain-javascript--the-front-end)
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
  - [3.7 Knowing when to stop turning pages](#37-knowing-when-to-stop-turning-pages)
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
- **[Part 4 — The interface, feature by feature](#part-4--the-interface-feature-by-feature)**
  - [4.1 The design system](#41-the-design-system)
  - [4.2 Status, and why colour is never alone](#42-status-and-why-colour-is-never-alone)
  - [4.3 The dashboard, top to bottom](#43-the-dashboard-top-to-bottom)
  - [4.4 The listings table](#44-the-listings-table)
  - [4.5 Filters](#45-filters)
  - [4.6 Every state a view can be in](#46-every-state-a-view-can-be-in)
  - [4.7 Accessibility, measured](#47-accessibility-measured)
  - [4.8 What was deliberately NOT done](#48-what-was-deliberately-not-done)
- **[Part 5 — The five ideas that recur](#part-5--the-five-ideas-that-recur)**
- **[Part 6 — What is deliberately not built](#part-6--what-is-deliberately-not-built)**
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

If something goes wrong, jump to **Appendix C — when it doesn't work**.

## 0.3 Where the code lives

`uv run python -m switch_tracker` runs `src/switch_tracker/__main__.py`. Start there; it
is 150 lines and it decides everything else. The rest of the tree:

```
src/switch_tracker/
├── __main__.py         THE FRONT DOOR. Reads argv, picks one of five roles (Part 2).
├── paths.py            The only code allowed to decide where a writable file goes (§3.17).
├── settings.py         Port, headful, collect-on-launch. Deliberately tiny.
├── selection.py        Encode/decode "collect only these stores" (§3.14).
├── resources.py        Reads BUNDLED read-only files, works frozen or not (§3.17).
├── spike.py            Self-check for the four things that break only after packaging.
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
├── events/             LIVE PROGRESS: writer appends rows, reader tails them (§3.13).
│
└── web/                THE DASHBOARD  (this half never scrapes)
    ├── app.py            Builds the FastAPI app, starts uvicorn.
    ├── deps.py           Hands a database connection to each route (§1.3).
    ├── queries.py        Every SELECT the page needs (§3.11).
    ├── runs.py           Starts workers; guarantees only one at a time (§3.12).
    ├── errors.py         One shape for every error response.
    ├── routers/          The URLs: pages, data, actions, events.
    ├── templates/        The HTML, with Jinja placeholders (§1.5).
    └── static/           app.js, app.css, and a vendored copy of htmx (§1.9).
```

And outside `src/switch_tracker/`:

| Path | What it is |
|---|---|
| `tests/` | 494 tests. `conftest.py` holds the shared setup ("fixtures", §1.12). |
| `scripts/scrape_check.py` | Run **one** store against the **live** site and print what came back. |
| `packaging/`, `switch_tracker.spec` | Turning it into a Windows `.exe` (§3.17). |
| `START.bat`, `setup.ps1`, `run.ps1` | What a Windows user double-clicks. |
| `docs/` | This file, plus the plan/HLD/LLD written before the code. |
| `src/adapters/`, `src/core/`, `src/web/*.ts`, `src/*.ts` | **The old TypeScript version.** Kept as a behavioural reference for the port; not shipped, not run. Ignore it. |

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
| `stores.local.json` | Corrections **Check stores** wrote (§3.1). | Yes — rebuilt by pressing **Check stores**. |
| `profiles.local.json` | Selectors the click-to-pick tool saved (§3.16). | Yes — but you'll have to re-pick them. |
| `settings.json` | Port, headful, collect-on-launch. | Yes — defaults return. |
| `run.lock` | The pid of a running worker (§3.12). | Yes, when nothing is running. |
| `diagnostics/` | Screenshots and HTML from stores that returned nothing. | Yes, always. |

For experiments, point the whole app somewhere disposable:

```bash
TRACKER_DATA_DIR=/tmp/tracker-scratch uv run python -m switch_tracker
```

*(Two `.local.json` files also sit in the repo root. Those belong to the old TypeScript
version and are not read by the Python app.)*

## 0.5 The whole system on one page

```
   YOU                                              FOURTEEN SHOPS
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
  two listings, and nothing yet connects them (Part 5).
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
| `web/templates/index.html` | ~195 | The shell the server renders once |
| `web/static/app.css` | ~725 | The design system (Part 4) |
| `web/static/app.js` | ~740 | Everything that happens after load |

**Why not React.** React, Vue and Svelte all need a **build step** — a toolchain that
compiles your source into files a browser can load. That means Node.js, a package
manager, a bundler, and a new stage in the packaging process, all to render one table
and six buttons for one user on one machine. These three files need none of it, which is
also why `switch_tracker.spec` can bundle them by copying.

**The trade-off, honestly.** State is managed by hand. `app.js` holds two small state
objects — `run` (what the current collection is doing) and `state` (what the table is
filtered to) — and functions that repaint from them. That is a pattern that stops
scaling somewhere around "several interacting views", and this app has one.

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
| Front end | htmx + vanilla JS | React | No build step for five buttons |
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

**3. Claiming the slot.** `web/runs.py:RunLauncher.start` (`runs.py:162`) does four
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

**7. The run (`services/collect.py:CollectService.run`, `collect.py:88`).**

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

**8. One store (`_process_store`, `collect.py:154`).** This is where failure is
*contained*. `adapter.fetch()` is wrapped in `asyncio.wait_for` and in a deliberately
broad `except Exception`, and every exit — timeout, crash, `Failed`, `Partial`, `Ok` —
ends the same way: a row in `run_store` and a `store_finished` event.

> A store that explodes is a *store* failure, never a *run* failure. Thirteen shops
> still get collected. That containment is why the dashboard can honestly show
> "13 ok, 1 failed: TimeoutError" instead of nothing at all.

**9. Saving (`_persist`, `collect.py:221`).** Per listing, inside one transaction:

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
`4.499,00`. Two bugs found the hard way are recorded here, and both teach the same lesson.

**Bug one — `Rs.`** The original code stripped everything that wasn't a digit, dot or
comma. The dot in `Rs.` survives that filter, so `Rs. 4499` became `.4499` → **₹0.45**.
The fix is ordering: remove currency words *before* stripping non-numerics.

**Bug two — thousands separators.** The rule "whichever separator comes last is the decimal
point" is wrong for Indian prices. `3,599` has no dot, so the comma looked like a decimal
point: **₹3.60 instead of ₹3,599**. A thousand times too small. The rule now is: a comma
with no dot anywhere is *always* a thousands separator.

> **Neither bug threw an exception. Both produced a plausible number.** That is the theme
> of this entire codebase — in a scraper, the dangerous failure is the one that type-checks.

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

## 3.7 Knowing when to stop turning pages

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

There is exactly one store-id branch in the codebase, in `extract.py`:

```python
if store_id == "flipkart":
```

Flipkart needed a genuinely different *mechanism* — walk the page's hydration state — and
you cannot express "walk the Redux store" as a config value. The useful distinction:

- *"Scroll differently, wait longer, reject these URLs"* → a **parameter**. Same algorithm,
  different values. Belongs on the profile.
- *"Don't read the DOM at all"* → a **mechanism**. Different algorithm. Needs code.

`docs/python-rewrite-hld.md` records the trigger for revisiting this: when a **second**
shop needs mechanism-level divergence, a strategy seam stops being speculative.

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

The TypeScript original returned the **native** price when no rate was available — so
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
              game_id (always NULL — see §5)
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

### How "identical results" was guaranteed

The acceptance criterion wasn't speed, it was *same rows*. So the old query was pasted into
the test file as a **frozen oracle**, and the new one compared against it across a matrix —
4 sort keys × 2 directions × every filter × in-stock × pagination — over a fixture
containing the awkward cases (a listing with one price point, one with none, a NULL price,
tied timestamps).

Frozen deliberately: an oracle imported from production changes when production changes,
and would agree with any rewrite including a wrong one.

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

Probe will only ever write a `kind` this build can actually fetch with. Anything else
(unreachable, a Shopify shop with its feed switched off) gets the shop *disabled* with a
readable reason, rather than a config value nothing can use.

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

**4. The collector** — one panel containing a dense list, one line per store:

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

**5. Progress** — hidden until a run exists, because an empty panel is noise. When a run
starts it shows the current store, page, running totals and failure count, with the raw
log **collapsed inside it**. Diagnostics matter when something breaks and should not
dominate the page the rest of the time.

**6. Moved since last run** — capped at six rows with `Show all N changes`. The backend
returns sixty. Showing all sixty measured 3,176px of a 9,409px page — a third of the
document for a secondary section, pushing the main table out of sight.

## 4.4 The listings table

**File:** `app.js`, `search()` and `headerCell()`.

This is the part people actually use, so it gets the most attention.

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

**The Change column costs no backend work.** `/api/movers` and `/api/listings` both
return `l.id`, so the two are joined in the browser:

```js
movementById = new Map(mv.map((m) => [m.id, m]));
```

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

## 4.5 Filters

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

**`/` focuses the search box** and Escape clears it — the convention every search-bearing
app shares. The handler ignores the keypress while you are typing in a field, or the
character could never be typed *into* one.

## 4.6 Every state a view can be in

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

## 4.7 Accessibility, measured

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

## 4.8 What was deliberately NOT done

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
Seven shops with different recipes, one store-id branch in the whole codebase — and the
trigger for revisiting that is written down.

**5. Record why, especially when the reason is a bug you already hit.**
Nearly every non-obvious line has a comment naming the failure that motivated it. That is
why the two price-parsing bugs are still fixed, and why nobody will "simplify" the
classifier's ordering back into breaking.

---

# Part 6 — What is deliberately not built

Two features, and they are the reason the project exists.

**The matcher.** The same cartridge at four shops is four unrelated rows. Every listing has
a `game_id` column that is always `NULL`, waiting. Matching them is what turns *"a list of
things shops sell"* into *"where is the cheapest copy of X right now"*.
`normalise_title()` in `core/parse.py` is already written and described as "the matcher's
first pass".

**The alert engine.** Detect a real price drop against a listing's own trailing median, and
**suppress it** when it's actually the whole shop repricing or the rupee moving. A currency
move is not a sale.

That second one explains the data model. Storing the native currency *and* the derived
rupee figure *and* the exchange rate's publication date looks redundant until you need to
ask: *"did four hundred prices move by the same ratio on the same day?"* The `movers`
endpoint already flags that cluster pattern; nothing acts on it yet.

It's also why thinning old data was measured and rejected: collapsing history to weekly
would delete exactly the same-day resolution that detection depends on — and the
measurements showed it wouldn't have fixed the speed problem anyway.

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
| **headful / headless** | Headless = the browser runs invisibly (normal). Headful = you can see the window (debugging, and required by the click-to-pick tool). |
| **htmx** | A small JavaScript library that lets an HTML element make a request by itself, no custom JavaScript needed (§1.9). |
| **hydration state** | The raw data a JavaScript page was built from, left embedded in the page (e.g. Flipkart's `__INITIAL_STATE__`). Often more stable than the visible HTML (§3.6). |
| **index (database)** | A structure that lets SQLite find rows without reading every one. §3.11 is a lesson in *using* one versus *seeking* with one. |
| **JSON-LD** | Structured product data shops embed for Google. Layer 1 of the extraction ladder, because it exists for search engines and survives redesigns (§3.6). |
| **lint** | Automated review for things that aren't errors: unused imports, suspicious patterns. Here: `ruff` (§1.13). |
| **listing** | One product at one shop. `UNIQUE(store_id, sku)` (§3.5). |
| **lock file** | `run.lock`, holding a running worker's process id. Guard layer 3 against two runs at once (§3.12). |
| **mypy / type checking** | Reads your type annotations and finds mismatches *before* you run the code. Configured `strict` here (§1.14). |
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
| **subprocess** | A process started by another process. The dashboard starts every job as a subprocess of itself (Part 2). |
| **template** | HTML with placeholders, filled in by Python. Here: Jinja2 (§1.5). |
| **transaction** | A group of database writes that either all land or none do. `_persist` wraps a whole store's rows in one. |
| **upsert** | Insert, or update if the row already exists. `INSERT … ON CONFLICT … DO UPDATE` (§3.11). |
| **WAL** | Write-Ahead Logging: SQLite mode where readers and writers work simultaneously. Required here, because the dashboard reads while a worker writes (§1.6). |
| **worker** | A subprocess doing one job — `collect`, `probe`, `fx`, `inspect` (Part 2). |

---

# Appendix B — Working on the code

## B.1 The gate — what must pass before anything is done

Nothing is "done" until all four are green. Run them from the project root.

```bash
uv run pytest                           # 494 tests, a couple of minutes
uv run ruff check src tests scripts     # lint
uv run ruff format src tests scripts    # formatting (rewrites files)
uv run mypy                             # types, strict mode
uv run python -m switch_tracker spike   # the packaging self-check (§3.17)
```

`pytest` never touches the network and never touches your real database — every test
gets a throwaway one from a fixture (§1.12). It is safe to run constantly.

## B.2 Testing against a real shop

Unit tests prove the logic. They cannot prove a shop still looks the way it did last
month — only the live site can:

```bash
uv run python scripts/scrape_check.py playasia --pages 3
uv run python scripts/scrape_check.py e2zstore --headful    # watch it happen
uv run python scripts/category_check.py                     # feed stores' category slugs
uv run python scripts/diagnose_extraction.py gamepookie     # why did N rows become M?
```

All three drive the **shipped** adapter and the **shipped** profile on purpose. A checker
carrying its own private copy of a store profile can pass while the collector fails on
the same page.

They answer different questions. `scrape_check` walks a browser store the way a real run
does. `category_check` asks a feed store's own API for a real product count per configured
slug — the number that otherwise vanishes into `woocommerce.py`'s per-category total, so a
wrong slug in three contributes zero to both sides of the completeness check and reports
nothing. `diagnose_extraction` explains a *gap*: which of the four layers (§3.6) actually
won, how many rows each one offers, where the survivors are lost, and whether page 2
differs from page 1 at all.

That last one exists because of a real trap. `extract()` returns the moment JSON-LD
succeeds, so a page carrying five products in a schema.org block and twenty-four in the
DOM yields **five** — and nothing anywhere says the CSS selectors were never consulted.
It also prints only to the console, never to a file, because the machine that can reach a
store is often not the machine that can share a dump.

Prefer a disposable database while experimenting:

```bash
TRACKER_DATA_DIR=/tmp/tracker-scratch uv run python scripts/scrape_check.py nistore
```

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
| `services/collect.py`, `selection.py` | `tests/test_service_collect.py` |
| `services/probe.py` | `tests/test_service_probe.py` |
| `web/queries.py` | `tests/test_queries.py` (holds the frozen oracle from §3.11) |
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
| The caller, `adapters/browser/extract.py:224` | A fallback already lives there: `parse_price(row.get("priceText")) or first_rupee_price(...)`. `first_rupee_price` deliberately takes the **first** rupee figure out of a text blob — maybe the selector path should lean on it harder. |
| `price_looks_wrong` (`parse.py:230`) | It already flags anything outside ₹299–₹12,000, so a glued number *is* noticed — but only as "worth a look", never rejected. Is flagging enough? |

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

**If you want a bigger one.** Add a fifteenth shop to `config/stores.py`: guess its
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
- **The `src/` tree contains a whole second implementation** in TypeScript. It is the
  behavioural reference for the port. Nothing in it runs.
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

| Symptom | What's actually happening | Fix |
|---|---|---|
| Dashboard opens, everything empty | The app auto-collects **once**, only to bootstrap an empty database (§3.15). After that it never starts a run by itself. | Press **Collect prices**. |
| **Moved since last run** is always empty | It needs two runs to compare. | Collect again later. |
| One store tile says 0 listings | Expected failure mode, and the reason is on the tile. Screenshots and HTML land in `<data dir>/diagnostics/`. | `scripts/scrape_check.py <store>`, then **Fix a broken store** (§3.16). |
| **CeX India** says 0 listings | Known and expected, not a regression. Its four selector lists ship as **unverified guesses**: CeX is a client-rendered Nuxt/Algolia app whose real DOM has never been captured, so the profile was written to fail loudly into a diagnostics dump rather than to be trusted. | `scripts/scrape_check.py cex_in --headful`, read `<data dir>/diagnostics/cex_in.html`, then **Fix a broken store** (§3.16). |
| `A run is already going` (409) | One run at a time, enforced in the database, not the UI (§3.12). | Wait for it, or restart the app — a dead worker's run is reaped on startup. |
| `'collect' is started by the dashboard, not run directly` | You ran a worker by hand without `--run-id`. Workers report into an existing run. | Use the dashboard, or `scripts/scrape_check.py` for one store. |
| `Address already in use` on startup | Something else has port 4173 — often an earlier copy still running. | `PORT=4174 uv run python -m switch_tracker`, or close the other copy. |
| `Executable doesn't exist … playwright install` | The browser engine was never downloaded. It is a ~400 MB download, not a Python package (§1.8). | `uv run playwright install chromium` |
| `ModuleNotFoundError` | Packages not installed, or you ran `python` instead of `uv run python`. | `uv sync`, then prefix commands with `uv run`. |
| A warning about OneDrive | Real hazard, not pedantry: the sync client locks the database mid-write and can corrupt it. | Move the folder, or set `TRACKER_DATA_DIR` to a local path. |
| You deleted `tracker.db` and it still behaves oddly | The database is **three** files (§1.6). | Delete `tracker.db-wal` and `tracker.db-shm` too. |
| Something is stuck and you want a clean slate | Nothing in the project folder holds state (§0.4). | Delete the data directory, or just use a fresh `TRACKER_DATA_DIR`. |

Still stuck? `uv run python -m switch_tracker spike` checks the four things that break
only after packaging — certificates, bundled templates, the web server, and the
Playwright driver — and prints where it stopped.
