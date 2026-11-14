# Physical Game Market Tracker — Phase 1

## Goal

Connect the Phase 0 physical-release market model to the existing retailer collection pipeline. Every normal collection run should now leave an auditable market scan and retailer-item observations, without changing the legacy price-history contract.

## Scope and identity

A market scan represents the exact configured scope for one store: adapter kind, base URL, configured collections, and configured browser search URLs. The stable scope key is a SHA-256 digest of that configuration. A configuration change therefore creates a new scope instead of allowing a narrower scan to mark items from an older, broader scope as absent.

The market retailer item is keyed by store, configured scope, and the adapter's stable SKU. Each observation stores the native price/currency and stock state. Non-HTTP(S) URLs are excluded just as they are from the legacy listing table.

A retailer SKU or a legacy matched game is **not** treated as a physical-release identity. The current adapters do not consistently expose edition and packaging format, so Phase 1 deliberately leaves discovered items unlinked (`product_id = NULL`). This prevents standard, collector, regional, Game-Key Card, and code-in-box editions from being silently merged.

## Coverage contract

The collector maps adapter results to market coverage as follows:

| Adapter result | Market coverage | May reconcile `NOT_LISTED`? |
|---|---|---|
| `Failed` | `FAILED` | No |
| `Partial` | `PARTIAL` | No |
| `Ok` with explicit completion evidence | `COMPLETE` | Yes, within the exact scope |
| `Ok` without an authoritative completion boundary | `UNKNOWN` | No |

Only an adapter that has observed the end of every configured scope can set `coverage_complete`.

### Adapter-specific verification

- **Shopify:** a short or empty page is the end signal. Reaching the 100-page safety cap without that signal is partial, not complete.
- **WooCommerce:** an empty or short API page ends each configured category; available `X-WP-Total` counts must also be satisfied. Page failures, time budgets, or safety-cap exhaustion prevent completion.
- **Browser:** every configured search URL must reach an explicit no-more-pages or empty-page signal. Productivity heuristics, page caps, time budgets, or unresolved navigation failures do not prove completeness.
- **Hobbyall:** the current endpoint returns one product array but exposes no authoritative total or pagination cursor. Successful results are recorded as `UNKNOWN` coverage until that API contract is verified.

A complete scan records positive observations for items seen, then reconciles only previously known items in the same store/scope as `NOT_LISTED`. Partial, failed, and unknown scans never create absence observations.

## Persistence and failure isolation

Market writes run in their own transaction after the legacy listing/price persistence. If market persistence fails, the existing price collection remains saved and the run receives a warning. A market scan failure must not roll back price history.

Failed, timed-out, skipped, and adapter-exception stores still receive a market scan record where the store row exists. The status and reason remain visible rather than disappearing from coverage reporting.

## Dashboard and API

Phase 1 adds:

- expanded market overview counts for total/complete/partial/failed/unknown scans, observations, and unresolved retailer items;
- `GET /api/market/scans` for recent scan coverage and completion evidence;
- `GET /api/market/discoveries` for discovered items that are not yet mapped to exact physical releases;
- dashboard panels for recent retailer coverage and unresolved discoveries.

The Phase 0 physical-release catalogue, evidence and retailer-group views remain intact.

## Out of scope

Phase 1 does not infer physical format or edition from a title, auto-link a retailer listing to a physical release, label a game out of print, calculate scarcity scores, or claim a store-wide absence from a search-results scope. Those require a verified release mapping and source-backed evidence workflow in a later phase.

## Verification

The automated suite covers:

- adapter completion signals and safety-cap behavior;
- successful, partial, failed, and unknown market scan recording;
- stock/price observations and stable retailer-item upserts;
- complete-scope-only absence reconciliation;
- preservation of unresolved physical-release identity;
- API output and existing price collection behavior.

CI runs pytest, Ruff, and mypy on this branch. A successful CI run verifies the code and fixture-backed adapter contracts; it does not replace a live collection against each configured retailer. Live store verification must be done through the app's existing **Collect specific stores** workflow and the market coverage panel.
