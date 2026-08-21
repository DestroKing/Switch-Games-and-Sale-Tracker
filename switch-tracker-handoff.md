# switch-tracker — handoff prompt

Paste everything below into a new conversation. It is written to be read by
Claude with no prior context.

---

I'm continuing work on an existing project. Here's the full context.

## What it is

A local price tracker for Nintendo Switch and Switch 2 **physical cartridges**
sold by Indian retailers, plus Play-Asia as an import comparison. Personal use,
runs on my own machine, all tooling free. Not a browser extension.

**Stack:** TypeScript on Bun · SQLite via built-in `bun:sqlite` (no server) ·
Playwright for stores that don't expose an API · local web dashboard on
`localhost:4173`, hand-rolled SVG charts, no framework, no CDN.

**Entry point:** double-click `switch-tracker.bat` on Windows. It runs
`setup.ps1` on first launch, then `src/menu.ts` — a numbered menu (check
stores / collect / dashboard / fix a store / update FX / schedule / reset).
No config is edited by hand.

## Architecture

```
src/
  menu.ts              menu; reads DB state to suggest the next step
  index.ts             CLI entry: menu | probe | collect | fx
  config/
    stores.ts          shipped store list (16 stores, 3 tiers)
    overrides.ts       merges stores.local.json over stores.ts
  core/
    types.ts           StoreConfig, RawListing, AdapterKind, Platform, Region
    db.ts              SQLite schema, WAL
    http.ts            polite client: 1 req/host, 1.2s gap, 20s timeout, 3 tries
    parse.ts           price parsing, product classification, region inference
  adapters/
    shopify.ts         /products.json, up to 20 pages
    woocommerce.ts     Store API, up to 20 pages
    browser.ts         Playwright, 4 extraction layers + diagnostics dump
    index.ts           registry keyed by AdapterKind
  fx/rates.ts          Frankfurter (ECB), cached, USD→INR
  web/server.ts        read-only dashboard, bound to 127.0.0.1
  cli/
    probe.ts           detect each store's real API, write corrections
    collect.ts         the collection run
    inspect.ts         headed browser for reading real selectors
```

**Browser extraction is layered, most durable first:** JSON-LD (schema.org
Product) → embedded hydration state (Flipkart's `__INITIAL_STATE__`, walked
rather than path-assumed) → CSS selectors (several candidates per field) →
₹-pattern text within a matched card. If all four return nothing, the page and
a screenshot are dumped to `diagnostics/<store>.html` — silent zero-row success
is the worst failure mode for a scraper.

## Design decisions that must not be quietly undone

1. **Native price is the truth; INR is derived.** `price_point` stores native
   currency, native price, derived INR, and the ECB rate date used. Play-Asia
   quotes USD and offers a rupee display conversion — capturing that rupee
   figure as a price makes a 2% currency slide look like a catalogue-wide 2%
   price rise, and a strengthening rupee look like a sale.
2. **`listing.game_id` is nullable.** Unmatched listings still get collected.
   Matching is a separate re-runnable pass over data already on disk, so
   improving the matcher later never means re-scraping.
3. **Region is a first-class column**, not a tag. Play-Asia splits one title
   across Asia-English, Asia-Chinese, Japan and Western SKUs — different
   products with different playability, not aliases.
4. **Corrections live in `stores.local.json`, not in TypeScript.** The probe
   must never rewrite a source file it also imports.
5. **Dashboard filtering and sorting run in SQL, not in the browser.** Sorting
   100 already-fetched rows gives you the cheapest *of those hundred* while
   looking exactly like the cheapest overall.
6. **Consoles and accessories are classified out.** Joy-Cons, docks, cases,
   amiibo, eShop codes, Online memberships. Classification reads the title plus
   the store's product type/tags/categories, and Switch-only stores carry a
   `platformHint`, so a bare "Hogwarts Legacy" is kept rather than dropped.

## Where it actually stands (this is the important part)

The project **has now been run on Windows**. Probe executed against live sites.
Collect has not yet produced verified row counts. Results so far:

| Store | Shipped guess | Probe found |
|---|---|---|
| nistore | WOOCOMMERCE | WOOCOMMERCE ✓ |
| nekavo | WOOCOMMERCE | WOOCOMMERCE ✓ |
| pssales | SHOPIFY | SHOPIFY ✓ |
| gamestheshop | JSON_API | BROWSER |
| mcubegames | SHOPIFY | BROWSER |
| gameloot, emartgames, hgworld, zozila | SHOPIFY | WOOCOMMERCE |
| gamenation, gamestrade | SHOPIFY | (was JSON_API — see below) |
| e2zstore | WOOCOMMERCE | UNREACHABLE |
| amazon_in, flipkart, croma, playasia | BROWSER | not probeable |

**My original store-kind guesses were wrong for 9 of 12.** The real
distribution is heavily WooCommerce, not Shopify. Detection via
`/products.json` returning `"products"` and the Woo Store API returning
`"prices"` are both strong signals; trust those.

### Three bugs found and fixed — keep these fixed

1. **`probe.ts` looped over `STORES` (shipped defaults) instead of
   `activeStores()`.** It compared detection against a list that never changes,
   so a corrected store reported "will switch" on every subsequent run for
   ever. Fix: iterate the effective list, and report a third state for
   "already corrected".
2. **`detect()` concluded `JSON_API` from the mere presence of
   `application/ld+json` on the homepage** — which nearly every shop publishes,
   so it was a coin flip. Worse, there is **no `JSON_API` adapter** in the
   registry, so `adapterFor()` returned undefined and `collect` silently
   skipped those stores. The probe was converting working stores into skipped
   ones. Fix: probe only ever writes a kind that has an adapter. When no usable
   API exists it disables the store with a readable reason, and distinguishes
   `SHOPIFY_LOCKED` (Shopify fingerprint in the HTML — `cdn.shopify.com`,
   `Shopify.shop` — but `/products.json` switched off by the merchant) from
   `UNKNOWN_HTML`.
3. **No per-store deadline in `collect`.** With 20s timeouts × 3 retries ×
   quadratic backoff × up to 20 pages, one unresponsive store costs ~20 minutes
   of total silence, and the store name was only printed *after* it finished so
   you couldn't tell which one stalled. Fix: 180s deadline per store via
   `Promise.race`, and print the store name *before* the fetch.

Also: `stores.local.json` was a bare relative path, resolving against the
working directory. Anchor it to the project root with `import.meta.dir`.

### Not built yet

- **Matcher** (canonical catalogue + fuzzy title matching) — next up. Until it
  exists, the same cartridge at four stores is four rows.
- **Alert engine** — drop detection against each listing's own trailing median
  (not a store-advertised "was" price), with a synchronised-move suppression
  rule: if ≥80% of a store's catalogue moves by the same ratio on the same day,
  that's a reprice or FX reset, not a sale. Telegram is the intended delivery.
- **Games The Shop adapter** — custom Next.js endpoint, needs its request shape
  read from a live page first.
- Play-Asia is parked at `enabled: false`.

### Known-suspect areas, in order of likelihood

1. **Browser selectors for Amazon / Flipkart / Croma have never been checked
   against a live page.** Use `bun run src/cli/inspect.ts <store>` to open the
   page in Playwright Inspector, then *add* working selectors to the arrays in
   `PROFILES` in `src/adapters/browser.ts` — every field is an array, so never
   delete a candidate that might work again.
2. **WooCommerce minor-unit handling** — Store API returns integer minor units
   with a divisor; getting this wrong yields prices off by 100×.
3. **Platform-inference regexes over-filtering** on stores with terse titles.
4. Croma will legitimately return few rows — its cartridge range is thin. A
   small number there is accurate, not broken.

## What I need

[Replace this section with whatever you're working on. Likely candidates:]

- Interpret my `collect` output and fix whichever adapters return zero rows.
- Write the matcher.
- Write the alert engine.
- Fix a specific store's selectors from a `diagnostics/` dump.

## Constraints

- Windows 10, no WSL, no Docker. Bun runs natively; `bun:sqlite` is in the
  runtime so nothing compiles.
- I'm on a free plan, so please front-load: give me complete files rather than
  fragments, and prefer one thorough answer over several rounds.
- Don't assume any code has been verified unless this document says it has.
