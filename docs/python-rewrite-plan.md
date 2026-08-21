# switch-tracker — Python/FastAPI rewrite plan

Not implemented yet. Captured here so it doesn't get lost — see the
conversation that produced this for the reasoning behind each choice
(target: Indian product companies, already have Java/Spring Boot, want a
second stack that's genuinely different rather than another OOP language).

## Why this stack

- Complements an existing Java/Spring Boot background rather than
  duplicating it — different paradigm (async/await, no inheritance-heavy
  OOP), and FastAPI + Python is currently in very high demand at Indian
  product companies specifically because of LLM/AI feature integration work.
- Everything below is chosen to teach real architecture (explicit API
  contracts, layered structure) rather than to minimize dependencies the way
  the current Bun/TS version does — that constraint doesn't apply here.
- No scheduling. No Windows Task Scheduler, no APScheduler. Every action
  (Check Stores, Collect Prices, Update FX Rate) is a dashboard button that
  triggers on demand — nothing runs unattended in the background.

## The stack

**Language & tooling**
- Python 3.12+
- `uv` — package manager + venv + lockfile (`pyproject.toml`/`uv.lock`);
  can also install/manage the Python interpreter itself
- `ruff` — lint + format in one tool
- `mypy` (or `pyright`) — type checking; FastAPI is built around type hints,
  this isn't optional tooling bolted on after the fact

**Web framework & API**
- FastAPI — routes, request/response validation
- Pydantic — ships with FastAPI, defines schemas
- Uvicorn — ASGI server that runs it

**Data layer**
- SQLite via the stdlib `sqlite3` module — no ORM. Keeps the existing
  project's philosophy (filtering/sorting/aggregation happens in SQL, not
  app code) and is more directly interview-relevant than an ORM abstraction.
  (SQLModel/SQLAlchemy noted as a later swap-in if this ever needs to feel
  more "production-typical.")

**Scraping / data collection**
- `httpx` — async HTTP client for the Shopify/WooCommerce-style stores
- Playwright for Python (official first-party bindings) — for JS-heavy
  stores and the inspect/profile-building flow
- `asyncio` — concurrency for "fetch N stores politely, rate-limited per
  host," via tasks + semaphores instead of a manual host-queue

**Real-time dashboard updates**
- Server-Sent Events via FastAPI's `StreamingResponse` — every button
  streams its live output back to the page while it runs

**Frontend**
- Jinja2 — server-renders HTML
- htmx — buttons trigger a request, the response fragment swaps in; no
  build step, no virtual DOM. Keeps the project teaching FastAPI/Python
  architecture deeply instead of also teaching a new frontend framework
  at the same time.
- Plain CSS, same look as the current dashboard

**Testing**
- `pytest` + FastAPI's `TestClient` (built on httpx)

**Distribution (later, not day one)**
- PyInstaller or Nuitka if this ever needs to be a single .exe

## Known constraint carried over from the current version

"Fix a broken store" will always need to pop a separate real browser
window — Playwright needs an actual window for a human to click inside,
which can't happen inside the dashboard's own browser tab. Every other
button can genuinely live entirely on the page with live streamed output.

## Open questions for when this actually gets built

- Folder/module structure (routers, services, repository layer)
- Exact shape of the SSE progress events (per-store lines vs. structured
  JSON events the frontend renders into rows)
- Whether the element-picker approach in the current `inspect.ts` (see the
  browser-store fixing work) carries over as-is or gets rebuilt using
  Playwright's Python API idioms
