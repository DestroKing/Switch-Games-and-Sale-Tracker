# switch-tracker — a complete walkthrough

Written for someone who has never used any of these technologies. Every term is
explained the first time it appears. Read top to bottom, or jump to a feature.

**What the program does, in one sentence:** it visits fourteen Indian online shops,
finds every physical Nintendo Switch game they sell, records the price, and does that
again later so you can see what changed.

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
meanwhile. Fourteen shops fetched one after another takes fourteen seconds of mostly
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

## 1.9 htmx + plain JavaScript — the front end

**What it is.** The dashboard's interactive bits: buttons that start a job, a live console,
a filterable table. `web/static/app.js` is about 200 lines of ordinary JavaScript, plus a
vendored copy of **htmx** (a small library that lets HTML elements make requests without
you writing JavaScript for each one).

**Why not React.** React (or Vue, or Svelte) is the industry default for interactive
pages, and it was rejected for a specific reason: those frameworks require a **build
step** — a separate toolchain that compiles your source into files a browser can load.
That means Node.js, a package manager, a bundler, and a build stage in the packaging
process, all to render a table and five buttons for one user. The whole front end here is
two files served as-is.

**The trade-off, honestly.** State is managed by hand. If the dashboard grew into
something with many interacting views, this would become the wrong choice.

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
sync with Playwright); dropping Playwright (loses 7 of 14 stores).

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

# Part 3 — Feature by feature

## 3.1 The store list, and the corrections layer

**Files:** `config/stores.py`, `config/overrides.py`

`config/stores.py` is a plain Python list of fourteen shops:

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

Seven shops, each needing something different — and **zero** `if store_id == ...` branches
in the adapter. Everything is data on a `StoreProfile`:

| Field | What it controls | Set by |
|---|---|---|
| `card` / `title` / `price` / `link` | CSS recipes | all 7 |
| `ready` | wait for this before reading | all 7 |
| `next_page` | click-to-paginate controls | 3 |
| `cookies` / `cookie_domain` | session settings | Play-Asia |
| `wait_until` | how long to wait for the page | Play-Asia |
| `scroll_passes` / `scroll_settle_ms` | lazy-loading behaviour | Play-Asia |
| `reject_url_parts` / `require_digit_in_url` | drop non-product links | Play-Asia |
| `max_pages` | page cap | Play-Asia |

**Two of these are correctness, not convenience.**

*Cookies.* Play-Asia prices per session. The config says `currency="INR"` — and that was
**a lie** until recently: the cookies existed only in a hand-run test script, so the real
collector scraped whatever the default session quoted and labelled it rupees. The cookies
now ship on the profile, which is what makes the config's claim true.

*The URL filter.* Category and search links sit inside result cards, and the classifier
*cannot* reject them — a nav link titled "Nintendo Switch" plus a SWITCH hint is a textbook
game. The filter **fails open**: a row is dropped only on a positive match, so a wrong rule
leaves junk (recoverable) rather than deleting the whole shop (not).

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

## 3.14 Collecting from just some shops

**Files:** `services/collect.py`, `services/collect_worker.py`, `selection.py`,
`web/routers/actions.py`

Testing one shop shouldn't mean scraping fourteen. You tick boxes on the dashboard and
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

# Part 4 — The five ideas that recur

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

# Part 5 — What is deliberately not built

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
