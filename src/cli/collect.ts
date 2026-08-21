import { adapterFor, closeBrowser } from "../adapters/index.ts";
import { activeStores } from "../config/overrides.ts";
import { mapWithConcurrency } from "../core/concurrency.ts";
import { getDb, nowIso } from "../core/db.ts";
import type { RawListing, StoreConfig } from "../core/types.ts";
import { refreshRates, toInr } from "../fx/rates.ts";

/**
 * Stores are on different hosts and have nothing to do with each other, so
 * there's no reason one store's 180s deadline should delay every store
 * after it in line. But HTTP stores and BROWSER stores cost wildly
 * different amounts of CPU/memory per store — a flat concurrency limit
 * shared between them let several real Chromium contexts compete for the
 * same machine at once, which is a plausible way a store that used to
 * finish comfortably inside 180s now doesn't. Two separate pools, each
 * sized for what it actually costs.
 */
const HTTP_CONCURRENCY = 8;
// Was 2 — with only 2 slots, two large catalogues (Amazon, Flipkart) landing
// in both at once left every other browser store waiting for the entire
// run, not just running a bit later. Raised enough that a couple of large
// stores can't fully block the rest, still capped well below the browser
// store count so it's not opening a real Chromium context per store at once.
const BROWSER_CONCURRENCY = 4;

/**
 * No single store may hold the run hostage. Sized per KIND, not per store —
 * an HTTP store is bounded tightly regardless of catalogue size, since
 * http.ts's own per-request timeout/retry budget caps each page it fetches
 * either way. A BROWSER store has no such luck: it now pages for as long as
 * the site's own "next" control keeps working, so its budget has to cover a
 * genuinely large catalogue, not a guess about any one store's page count.
 * That's still a shared, universal number — never a per-store override that
 * would need updating the next time some catalogue grows.
 */
const HTTP_DEADLINE_MS = 180_000;
const BROWSER_DEADLINE_MS = 600_000;

function withDeadline<T>(work: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const bell = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`gave up after ${Math.round(ms / 1000)}s (${label})`)), ms);
  });
  return Promise.race([work, bell]).finally(() => clearTimeout(timer)) as Promise<T>;
}

export async function collect(): Promise<void> {
  const db = getDb();
  const STORES = activeStores();
  syncStoreTable(STORES);

  // Refresh FX before anything else, so every price in this run converts at
  // one rate rather than drifting mid-run.
  const currencies = [...new Set(STORES.filter((s) => s.enabled).map((s) => s.currency))];
  await refreshRates(currencies);

  const runId = Number(
    db.query<{ id: number }, [string]>(
      `INSERT INTO run (started_at) VALUES (?) RETURNING id`,
    ).get(nowIso())?.id,
  );

  const active = STORES.filter((s) => s.enabled);
  console.log(`run ${runId}: ${active.length} stores\n`);

  async function processStore(store: StoreConfig): Promise<void> {
    const started = Date.now();
    const adapter = adapterFor(store.kind);

    // A complete line, not a prefix written now and a suffix later — with
    // several stores in flight at once, two stores each writing half a line
    // would interleave into garbage. Still names the store before the fetch
    // starts, so a stall is identifiable by which store never printed a
    // second line.
    console.log(`  ${store.id} (${store.kind}) starting...`);

    if (!adapter) {
      record(runId, store.id, "skipped", 0, Date.now() - started, `no adapter for ${store.kind}`);
      console.log(`  ${store.id}: skipped - no ${store.kind} adapter`);
      return;
    }

    try {
      const deadline = store.kind === "BROWSER" ? BROWSER_DEADLINE_MS : HTTP_DEADLINE_MS;
      const outcome = await withDeadline(adapter.fetch(store), deadline, store.id);
      if (outcome.status === "failed") {
        record(runId, store.id, "failed", 0, Date.now() - started, outcome.reason);
        console.log(`  ${store.id}: FAILED - ${outcome.reason}`);
        return;
      }
      const saved = persist(runId, store, outcome.listings);
      record(
        runId,
        store.id,
        outcome.status,
        saved,
        Date.now() - started,
        outcome.status === "partial" ? outcome.reason : null,
      );
      console.log(`  ${store.id}: ${outcome.status} - ${saved} listings`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      record(runId, store.id, "failed", 0, Date.now() - started, msg);
      console.log(`  ${store.id}: THREW - ${msg}`);
    }
  }

  const httpStores = active.filter((s) => rank(s) === 0);
  const browserStores = active.filter((s) => rank(s) === 1);

  // Both pools run at once — HTTP stores were never waiting on browser
  // stores to begin with, no reason to start them staggered.
  await Promise.all([
    mapWithConcurrency(httpStores, HTTP_CONCURRENCY, processStore),
    mapWithConcurrency(browserStores, BROWSER_CONCURRENCY, processStore),
  ]);

  db.run(`UPDATE run SET finished_at = ? WHERE id = ?`, [nowIso(), runId]);
  await closeBrowser();
  console.log(`\nrun ${runId} complete`);
}

function rank(s: StoreConfig): number {
  return s.kind === "BROWSER" ? 1 : 0;
}

function syncStoreTable(STORES: readonly StoreConfig[]): void {
  const db = getDb();
  const stmt = db.prepare(
    `INSERT INTO store (id, name, base_url, kind, currency, tier, enabled)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       name = excluded.name, base_url = excluded.base_url,
       kind = excluded.kind, currency = excluded.currency,
       tier = excluded.tier, enabled = excluded.enabled`,
  );
  for (const s of STORES) {
    stmt.run(s.id, s.name, s.baseUrl, s.kind, s.currency, s.tier, s.enabled ? 1 : 0);
  }
}

function persist(runId: number, store: StoreConfig, listings: readonly RawListing[]): number {
  const db = getDb();
  const now = nowIso();

  const upsertListing = db.prepare<{ id: number }, [string, string, string, string, string, string, string | null, string, string]>(
    `INSERT INTO listing (store_id, sku, url, raw_title, platform, region, image_url, first_seen, last_seen)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(store_id, sku) DO UPDATE SET
       url = excluded.url, raw_title = excluded.raw_title,
       platform = excluded.platform, region = excluded.region,
       last_seen = excluded.last_seen
     RETURNING id`,
  );

  const insertPrice = db.prepare(
    `INSERT INTO price_point
       (listing_id, run_id, captured_at, native_currency, native_price, inr_price, fx_rate_date, in_stock)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
  );

  const tx = db.transaction((rows: readonly RawListing[]) => {
    let count = 0;
    for (const l of rows) {
      const row = upsertListing.get(
        store.id, l.sku, l.url, l.title, l.platform, l.region,
        l.imageUrl ?? null, now, now,
      );
      if (!row) continue;
      const { inr, rateDate } = toInr(l.nativePrice, l.nativeCurrency);
      insertPrice.run(
        row.id, runId, now, l.nativeCurrency, l.nativePrice, inr,
        rateDate ?? null, l.inStock ? 1 : 0,
      );
      count++;
    }
    return count;
  });

  return tx(listings);
}

function record(
  runId: number,
  storeId: string,
  status: string,
  found: number,
  ms: number,
  detail: string | null,
): void {
  getDb().run(
    `INSERT OR REPLACE INTO run_store (run_id, store_id, status, listings_found, duration_ms, detail)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [runId, storeId, status, found, ms, detail],
  );
}
