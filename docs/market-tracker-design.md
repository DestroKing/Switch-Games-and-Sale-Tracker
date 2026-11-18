# Physical Game Market Rarity Tracker — Phase 0 design

Status: **AGREED 2026-11-16.** Decisions taken:

- Identity: exact-key matches count automatically; their releases are flagged "unverified
  identity", which lowers confidence. Everything fuzzier goes to review.
- Coverage evidence: extend the legacy adapters with a generic, optional `Coverage` report
  (owner asked for "whichever keeps it de-coupled"). An own market scanner would still need
  the collection observer for browser-store stock, so it adds surface *and* duplicates fetch
  logic. `Coverage` is market-agnostic, so legacy never depends on market.
- Backfill: yes, read-only, coverage UNKNOWN.

## 1. What was inspected (2026-11-15)

| Area | Finding |
|---|---|
| Baseline | `main` @ `dd3a327`: 818 passed, Ruff clean, mypy clean (local). CI on `dd3a327`: success ([run 43633948524](https://github.com/DestroKing/Switch-Games-and-Sale-Tracker/actions/runs/43633948524)). |
| Process model | `serve` (dashboard) spawns subprocess workers (`collect`, `probe`, `fx`, `inspect`). `tests/test_import_boundary.py` pins that the UI process never imports Playwright or an adapter. |
| Adapters | Narrow `Adapter.fetch(store, sink) -> Ok \| Partial \| Failed`. Classification to GAME happens **inside** the adapter, so only game rows leave it. |
| Collection | `CollectService` persists `listing` (upsert) + `price_point` (append, one per listing per run, with `in_stock`) + `run_store` status `ok/partial/failed`. |
| Storage | One `tracker.db`; legacy tables kept byte-identical on purpose; additive DDL in `core/db.py`; `VACUUM INTO` backups per run. |
| Packaging | PyInstaller onedir; templates/static added as `datas`; workers imported lazily inside `__main__` branches. |

### Previous market work (reference only, will not be restored)

Commits `6172384`, `6fa303e`, `54efc73`, `0c3f3bb`, `a47512a` exist as objects but are
**not on any branch** (unrelated history to `main`). They put market tables in
`core/db.py`, hooks in `services/collect.py`, endpoints in `web/routers/data.py`
and markup in `index.html`. That is exactly the coupling §2 of the brief forbids.
Its CI runs on `0c3f3bb`/`54efc73` failed; `a47512a` (Ruff fix) was never run in CI.
Kept as reference: the enum vocabulary and the rule "ordinary price scans are never complete".

## 2. Corrections to the brief (verified against code)

1. **`Ok` is not proof of completeness, and in one case it is wrong.** Shopify and Woo
   return `Ok` when the `MAX_PAGES` backstop is hit without a short page. Browser `Ok`
   only means "no problems and ≥90% of a scraped count". The legacy "still listed" rule
   (`web/queries.py::_IN_STOCK`) trusts `ok`, so this is a latent legacy defect too.
2. **Absence after classification is unsafe.** Adapters drop non-game rows *before*
   returning. A classifier change that reclassifies a game would make it look delisted.
   Absence must be computed against **every raw product the walk saw**, not the kept rows.
3. **"Unknown stock" cannot currently be expressed.** `RawListing.in_stock` is `bool`, and
   API adapters default a missing flag to `True`. Shopify `available` and Woo `is_in_stock`
   are always present, so API stock is *reported*; browser stock is *inferred* (no sold-out
   marker). The market model records which, per storefront.
4. **Marketplace sellers and barcodes are not extracted by any adapter.** The model allows
   them; data will only exist where a SKU is itself an EAN/UPC or a title carries a product
   code. Seller-level counting is a later browser-profile change, not part of this build.
5. **Hobbyall's single-response API has no total or paging metadata.** Until verified it is
   treated as coverage UNKNOWN (never absence-eligible).
6. **"Hard to Find" and "Very Limited" are indistinguishable** with ~15 independent shops. Merged.
7. **Existing price history can seed market history.** ~months of `price_point` rows exist;
   a read-only backfill gives history on day one (with coverage UNKNOWN, so no absences).
8. **Removability testing should come first, not last.** Proven from Phase 1 and kept green.
9. **CI cannot be triggered from this machine.** Org policy forbids pushing to github.com from
   here; commits are made locally and pushed by the owner, then CI is read back.

## 3. Architecture

### 3.1 Package

```
src/switch_tracker/market/
  __init__.py        enabled(settings) + the 3 entry points the app calls
  db.py              market.db connect, user_version migrations, backup
  models.py          enums + frozen dataclasses (pure)
  coverage.py        scan verdict: COMPLETE / PARTIAL / FAILED / UNKNOWN (pure)
  ingest.py          observer: scan rows, listing upsert, state spans, absence reconciliation
  identity.py        attribute extraction (format, edition, codes) + matching tiers
  retailers.py       shipped retailer/storefront defaults + grouping edits
  availability.py    per-release availability metrics (pure over query rows)
  assess.py          trends, rarity classification + explanation, OOP assessment (pure)
  backfill.py        read-only import of legacy tracker.db history
  web/router.py      /market page + /api/market/* (mounted only when enabled)
  web/templates/market.html, web/static/market.{js,css}
tests/market/        everything market, runnable alone: uv run pytest tests/market
```

### 3.2 Storage: separate `market.db`

Chosen over tables in `tracker.db` because: removal = delete one file; no risk to the
price history migrations; own backup rotation; observation growth and write locks stay out of
the price DB. Cost: no cross-DB transaction — acceptable because market ingestion is
idempotent per `(legacy_run_id, storefront)` and a missed ingest yields *UNKNOWN*, the safe
direction. No foreign keys into legacy; storefronts are keyed by the legacy `store_id` string.
Migrations: ordered list applied under `PRAGMA user_version`, additive only.

### 3.3 Entities

```
game ─< release ─< release_code (EAN/UPC/product code, UNIQUE)
            │
            └──< listing_match >── listing ─< state_span >── scan >── scope
                                     │                          │
retailer ─< storefront ──────────────┴──────────────────────────┘
release ─< evidence                  audit_log (every manual change, before/after)
```

- **game**: title-level work. **release**: platform × edition × region × format (+ publisher),
  `verified` flag. Edition/format are columns, not tables — they have no attributes of their own.
- **retailer** = business / ownership group (`kind` INDEPENDENT | MARKETPLACE,
  `verification` VERIFIED | UNVERIFIED, note, verified_at). **storefront** = one scanned site
  (legacy store id), `retailer_id`, `stock_signal` REPORTED | INFERRED, `ships_from_abroad`.
- **scope**: storefront + kind (CATEGORY | COLLECTION | CATALOGUE | SEARCH | BROWSE) +
  fingerprint of the configured collections/URLs. Editing store config makes a *new* scope, so
  reconciliation never spans two definitions. Only CATEGORY/COLLECTION/CATALOGUE are absence-eligible.
- **scan**: one per storefront per legacy run: pages attempted/completed, claimed total, raw seen,
  end reached, verdict, evidence text, failure detail.
- **listing**: market's own copy (original title, URL, SKU, codes, platform, region, condition,
  format/edition hints, scope, first/last seen). **listing_match**: current match + tier + reasons JSON.
- **state_span** (history): `(listing, state, price, first_scan, last_scan, started_at,
  last_confirmed_at, confirmations)`. Unchanged state extends the open span; a change opens a new
  one. States: IN_STOCK, OUT_OF_STOCK, LISTED_STOCK_UNKNOWN, NOT_LISTED. "Unknown because coverage
  insufficient" is *derived* (stale or uncovered), never stored. Reappearance opens a new span, so
  past unavailability is never overwritten.

Scans are append-only events and per-listing history is run-length spans: lossless for state changes,
and roughly 50x smaller than a row per listing per run.

### 3.4 Integration boundary (the only legacy touch points)

| # | Legacy file | Change | Why |
|---|---|---|---|
| 1 | `core/models.py` | `Coverage` dataclass; optional `coverage=None` on `Ok`/`Partial` | generic fetch telemetry, no market concept |
| 2 | 4 adapters | fill `Coverage` (pages, end_reached, claimed_total, raw skus seen); backstop hit → `Partial` | completion evidence + fixes defect §2.1 |
| 3 | `services/collect.py` | optional `observer` (Protocol: `store_done`, `run_done`), each call in try/except | one push point; a market fault can never fail a price run |
| 4 | `services/collect_worker.py` | build `market.observer()` when enabled (lazy import) | wiring |
| 5 | `web/app.py` + `pages.py` + `index.html` | include market router when enabled; one nav link | dashboard entry |
| 6 | `settings.py` | `market_tracker: bool = True` | the off switch |
| 7 | `__main__.py`, `switch_tracker.spec` | `market` subcommand (rebuild/backfill); market templates in `datas` | CLI + packaging |

**Disable:** `"market_tracker": false` in `settings.json` → no router, no observer, no DB opened.
**Remove:** delete `market/`, `tests/market/`, `market.db`; revert rows 3–7 (≈25 lines). Rows 1–2 are
generic and may stay. A subprocess test runs the app and a collection with `switch_tracker.market`
made unimportable to prove it.

### 3.5 Data flow

```
collect worker ── adapter.fetch ──> Ok/Partial(+Coverage) ──> CollectService._persist (legacy, unchanged)
                                                     └──> observer.store_done ──> market.db:
                                                             scope, scan(verdict), listing upsert,
                                                             span extend/open, absence (COMPLETE only)
                       run end ──> observer.run_done ──> rematch identities, backup market.db
dashboard /market ──> market.db (read) ──> availability → assessment (computed on read)
```

No second scrape, no second scheduler: market data rides the existing daily collection.

## 4. Rules and methodology

**Coverage verdict** (`coverage.py`): COMPLETE only if scope kind is absence-eligible, every configured
sub-scope ended on a short or empty page (never the backstop), no page failed, and the walk saw at
least the store's `x-wp-total` when one exists. BROWSER: PARTIAL at best, never absence-eligible. Hobbyall: UNKNOWN.

**Absence**: on a COMPLETE scan of scope S, a listing previously seen in S and whose SKU is not in the
walk's *raw* seen set gets NOT_LISTED. It reads "not in its Switch-games category", never "delisted by retailer".

**Matching tiers**: CONFIRMED (manual) > EXACT_CODE (shared EAN/product code, one release) >
EXACT_KEY (normalised title + platform + edition + region + format, one candidate, no conflicting
signal) > PROBABLE (single fuzzy candidate) > AMBIGUOUS (several) > UNMATCHED. REJECTED pairs are
remembered. Only CONFIRMED/EXACT_* are counted. Reasons are stored per match. Review actions: confirm, reject,
re-point, split release, merge releases — each written to `audit_log`.

**Availability (per release, fresh = confirmed in the last 7 days)**: independent retailers listing /
in stock / out of stock (verified and unverified separately), marketplace listings, import
(ships-from-abroad) listings, stock-unknown, stale, last listed, last in stock. Same-retailer storefronts collapse to one.

**Rarity classification** (decision list, no composite score):
INSUFFICIENT_DATA → WIDELY_AVAILABLE (≥4 independent in stock) → LIMITED (2–3) → VERY_LIMITED (1, or
marketplace/import only) → TEMPORARILY_UNAVAILABLE (0 now, in stock within 60 days) →
NO_CONFIRMED_CURRENT_AVAILABILITY. Thresholds are named constants, pinned by realistic scenario tests.
Separate **confidence** HIGH/MEDIUM/LOW from fresh-coverage share, identity verification, retailer verification.
Every result returns its factor list: counted retailers, ages, coverage, and what is missing.

**Out-of-print** (separate from scarcity): evidence rows (kind, claim DISCONTINUED / OUT_OF_PRINT /
IN_PRODUCTION / REPRINTED, reliability OFFICIAL / TRADE / RETAILER / COMMUNITY, URL, dates, notes). Status:
CONFIRMED (official claim, no newer official contrary claim) / REPORTED / CONFLICTING / NO_EVIDENCE.
Market data appears only as context, never as evidence.

## 5. Phases (redesigned) and TODO

Each phase is test-first, ends green (targeted tests, then the full suite, Ruff and mypy), and is committed locally.

- [ ] **P0 Design.** This document; agreement on open decisions.
- [ ] **P1 Foundation + off switch.** Package skeleton, `market.db` + migrations, models, settings flag,
      import-boundary and removal-simulation tests, `tests/market/`.
- [ ] **P2 Coverage evidence.** `Coverage` on outcomes, 4 adapters fill it, backstop → Partial, `coverage.py` verdicts.
- [ ] **P3 Ingestion + history.** Observer protocol in `CollectService`, scopes, scans, listings, spans,
      absence reconciliation; end-to-end test with fake adapters.
- [ ] **P4 Identity.** Attribute extraction, game/release/codes, matching tiers, review ops, audit log.
- [ ] **P5 Retailers + availability.** Shipped retailer defaults, grouping edits, availability metrics.
- [ ] **P6 Assessment.** Trends, rarity + confidence + explanation, evidence + OOP status.
- [ ] **P7 Backfill + CLI.** Read-only legacy history import; `switch-tracker market rebuild|backfill`.
- [ ] **P8 API + dashboard.** `/api/market/*`, `/market` page (catalogue, detail, overview, review, evidence).
- [ ] **P9 Hardening.** Synthetic large-history perf + indexes, market.db backup rotation, docs, packaging
      `datas` check, full regression, local commit; CI is read back after the owner pushes.

Not built (YAGNI, add when needed): per-scope scan frequencies (no separate scan exists), marketplace
seller extraction, materialised rarity tables (compute-on-read is fine at this size), stored UNKNOWN observations.

## 6. Risks

| Risk | Mitigation |
|---|---|
| False delisting | COMPLETE only via positive evidence; raw-SKU absence; scope fingerprints; scenario tests per adapter |
| Wrong identity merges | exact-key only on full dimension agreement; ambiguity is a state; rejections remembered |
| Market fault breaks price collection | separate DB + connection; observer calls wrapped; collect test with a raising observer |
| Legacy adapter change regresses prices | change is additive; existing 818 tests + new coverage tests; backstop→Partial called out |
| Stale data shown as current | freshness window on every metric; stale counted separately |
| Browser stock inferred | `stock_signal` per storefront; shown in explanations; lowers confidence |
