import { writeFileSync } from "node:fs";
import { activeStores, setOverride, writeOverrides } from "../config/overrides.ts";
import { adapterFor } from "../adapters/index.ts";
import { mapWithConcurrency } from "../core/concurrency.ts";
import { get, getJson } from "../core/http.ts";
import type { StoreConfig } from "../core/types.ts";

const LOG_PATH = "check-stores.log";
// Different hosts, so this only bounds resource use, not politeness (that's
// still one request at a time per host, enforced in http.ts regardless).
const STORE_CONCURRENCY = 8;

/**
 * What detect() can conclude. Only SHOPIFY and WOOCOMMERCE have a real
 * adapter — everything else describes a page probe saw but can't act on by
 * itself, so probe must never write one of these into stores.local.json as
 * if it were an adapter kind.
 */
type Finding = "SHOPIFY" | "WOOCOMMERCE" | "UNREACHABLE" | "SHOPIFY_LOCKED" | "UNKNOWN_HTML";

export interface ProbeResult {
  store: StoreConfig;
  detected: Finding;
  changed: boolean;
}

interface StoreProbeOutcome {
  readonly lines: readonly string[];
  readonly result: ProbeResult | null;
}

/**
 * Everything for one store — detection, then (when relevant) its category
 * listing. Run concurrently across stores via mapWithConcurrency below;
 * kept as a single function per store so each store's own two network
 * round-trips still happen in the sequence that makes sense (category
 * listing depends on what detect() found), while different stores' calls
 * overlap freely since they're different hosts.
 */
async function probeStore(store: StoreConfig): Promise<StoreProbeOutcome> {
  if (store.kind === "BROWSER" || store.kind === "MANUAL") {
    return { lines: [pad(store.id, 22) + pad(store.kind, 14) + "needs a real browser"], result: null };
  }

  const detected = await detect(store);
  const changed = detected !== store.kind;

  const mark = !changed
    ? "ok"
    : detected === "SHOPIFY" || detected === "WOOCOMMERCE"
      ? "will switch"
      : !store.enabled
        ? "already disabled"
        : detected === "UNREACHABLE"
          ? "will disable"
          : detected === "SHOPIFY_LOCKED"
            ? "will disable — /products.json blocked, needs a browser adapter"
            : "will disable — no known API, needs a browser adapter";
  const lines = [pad(store.id, 22) + pad(store.kind, 14) + pad(detected, 15) + mark];

  // Print what categories/collections this store actually has, right here,
  // so scoping a mixed-catalogue store (a general retailer that also sells
  // other consoles or non-game merchandise) is a copy-paste into
  // `collections` in stores.ts instead of a manual API trip. Skipped once
  // a store already has `collections` set — this is a one-time discovery
  // aid, not something worth re-fetching (and re-paginating, now up to 50
  // pages deep) on every single run once the real answer is already known.
  const effectiveKind = detected === "SHOPIFY" || detected === "WOOCOMMERCE" ? detected : store.kind;
  if (store.enabled && !store.collections?.length && (effectiveKind === "SHOPIFY" || effectiveKind === "WOOCOMMERCE")) {
    const categories = await listCategories(store, effectiveKind);
    if (categories.length > 0) {
      // A general retailer can have 100+ categories with the one Switch
      // category buried alphabetically past the display cap — pssales
      // alone had 224, nearly all regional Xbox listings. Whatever looks
      // Switch-related always survives the cap, even if it's the 90th
      // category, since that's specifically what setting `collections`
      // in stores.ts needs. Also flagging bare "games"/"cartridge"/
      // "software" categories — a store's actual games section doesn't
      // always name the console (hgworld's console/accessory categories
      // all say "Nintendo Switch", but if it has a games category at all,
      // there's no guarantee that one does too).
      const RELEVANT = /nintendo|switch|\bgames?\b|\bcartridges?\b|\bsoftware\b/i;
      const relevant = categories.filter((c) => RELEVANT.test(c.name) || RELEVANT.test(c.slug));
      const rest = categories.filter((c) => !relevant.includes(c));
      const ordered = [...relevant, ...rest];
      const cap = Math.max(20, relevant.length);
      const shown = ordered.slice(0, cap).map((c) => `${c.name} (${c.slug})`).join(", ");
      const more = ordered.length > cap ? ` … +${ordered.length - cap} more` : "";
      const flag = relevant.length > 0 ? ` [${relevant.length} look Switch-related]` : "";
      lines.push(`      categories${flag}: ${shown}${more}`);
    }
  }

  return { lines, result: { store, detected, changed } };
}

/**
 * Probe asks one question per store: what does this site actually speak?
 *
 * It compares against `activeStores()` — the shipped defaults plus whatever
 * stores.local.json already corrected — not the raw shipped list. Comparing
 * against the shipped list meant a store that was corrected on run 1 reported
 * "will switch" on every run after that, forever, because the comparison
 * baseline never moved.
 *
 * With `apply`, the answers are written to stores.local.json rather than
 * printed for you to transcribe. Transcribing a sixteen-row table by hand is
 * exactly the kind of step that gets done wrong once and then debugged for an
 * hour.
 */
export async function probe(apply = true): Promise<ProbeResult[]> {
  const lines: string[] = [];
  const say = (s = ""): void => {
    console.log(s);
    lines.push(s);
  };

  say();
  say(pad("STORE", 22) + pad("EXPECTED", 14) + pad("FOUND", 15) + "");
  say("-".repeat(72));

  // Stores are independent hosts with nothing to do with each other —
  // running them concurrently means total time is roughly the slowest one
  // store, not the sum of all of them. Output still prints in the original,
  // stable store order once everything's back, just all at once at the end
  // rather than incrementally.
  const outcomes = await mapWithConcurrency(activeStores(), STORE_CONCURRENCY, probeStore);
  for (const outcome of outcomes) {
    for (const line of outcome.lines) say(line);
  }
  const results = outcomes.map((o) => o.result).filter((r): r is ProbeResult => r !== null);

  if (apply) {
    let fixed = 0;
    let disabled = 0;
    for (const r of results) {
      if (!r.changed) continue;
      const needsDisable = r.detected === "UNREACHABLE" || r.detected === "SHOPIFY_LOCKED" || r.detected === "UNKNOWN_HTML";
      if (needsDisable && !r.store.enabled) continue; // already disabled — nothing to do

      if (r.detected === "SHOPIFY" || r.detected === "WOOCOMMERCE") {
        // Never write a kind this codebase can't actually fetch with.
        if (!adapterFor(r.detected)) continue;
        setOverride(r.store.id, { kind: r.detected, note: "corrected by probe" });
        fixed++;
      } else {
        const note =
          r.detected === "UNREACHABLE" ? "unreachable when probed"
          : r.detected === "SHOPIFY_LOCKED" ? "Shopify storefront, but /products.json is blocked — needs a browser profile in src/adapters/browser.ts"
          : "no Shopify/WooCommerce API found on the homepage — needs a browser profile in src/adapters/browser.ts";
        setOverride(r.store.id, { enabled: false, note });
        disabled++;
      }
    }
    say();
    if (fixed || disabled) {
      say(`  Applied: ${fixed} corrected, ${disabled} disabled.`);
      say(`  Saved to stores.local.json — delete that file to undo everything.`);
    } else {
      say(`  Everything already matches. Nothing to change.`);
    }
  }

  // Written after every run — the printed table is long enough (categories
  // included) that scrolling the terminal buffer to copy it is worse than
  // just opening a file.
  writeFileSync(LOG_PATH, lines.join("\n") + "\n");
  console.log(`  Full output saved to ${LOG_PATH}`);

  return results;
}

export function resetOverrides(): void {
  writeOverrides({});
}

async function detect(store: StoreConfig): Promise<Finding> {
  if (await hits(`${store.baseUrl}/products.json?limit=1`, '"products"')) return "SHOPIFY";
  if (
    (await hits(`${store.baseUrl}/wp-json/wc/store/v1/products?per_page=1`, '"prices"')) ||
    (await hits(`${store.baseUrl}/wp-json/wc/store/products?per_page=1`, '"prices"'))
  ) {
    return "WOOCOMMERCE";
  }

  // Neither API answered. The homepage still tells us something: a Shopify
  // fingerprint means the storefront is real Shopify with /products.json
  // switched off by the merchant, which is a different problem than a site
  // that isn't Shopify or Woo at all — both need a browser adapter, but only
  // one is worth re-probing after a merchant setting might change.
  let home: { ok: boolean; body: string } | undefined;
  try {
    home = await get(store.baseUrl);
  } catch {
    home = undefined;
  }
  if (!home?.ok) return "UNREACHABLE";
  if (/cdn\.shopify\.com|Shopify\.shop/i.test(home.body)) return "SHOPIFY_LOCKED";
  return "UNKNOWN_HTML";
}

interface Category {
  readonly name: string;
  readonly slug: string;
}

// High on purpose — this now only ever runs for a store that has no
// `collections` set yet (see the skip above), so paying for real depth here
// costs nothing on every other run.
const MAX_CATEGORY_PAGES = 50;

async function listCategories(store: StoreConfig, kind: "SHOPIFY" | "WOOCOMMERCE"): Promise<Category[]> {
  try {
    if (kind === "WOOCOMMERCE") {
      // A single per_page=100 call silently hid hgworld's real games
      // category — it has enough categories to need a second page, and
      // nothing short of pagination would ever have surfaced it, no matter
      // how the relevance filter below was tuned.
      const out: Category[] = [];
      for (let page = 1; page <= MAX_CATEGORY_PAGES; page++) {
        const cats = await getJson<{ name: string; slug: string }[]>(
          `${store.baseUrl}/wp-json/wc/store/v1/products/categories?per_page=100&page=${page}`,
        );
        if (!cats || cats.length === 0) break;
        out.push(...cats.map((c) => ({ name: c.name, slug: c.slug })));
        if (cats.length < 100) break;
      }
      return out;
    }
    const out: Category[] = [];
    for (let page = 1; page <= MAX_CATEGORY_PAGES; page++) {
      const data = await getJson<{ collections?: { title: string; handle: string }[] }>(
        `${store.baseUrl}/collections.json?limit=250&page=${page}`,
      );
      const collections = data?.collections ?? [];
      if (collections.length === 0) break;
      out.push(...collections.map((c) => ({ name: c.title, slug: c.handle })));
      if (collections.length < 250) break;
    }
    return out;
  } catch {
    return [];
  }
}

async function hits(url: string, needle: string): Promise<boolean> {
  try {
    const r = await get(url);
    return r.ok && r.body.includes(needle);
  } catch {
    return false;
  }
}

function pad(s: string, n: number): string {
  return s.length >= n ? s.slice(0, n - 1) + " " : s + " ".repeat(n - s.length);
}
