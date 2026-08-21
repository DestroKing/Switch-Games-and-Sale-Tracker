import { writeFileSync } from "node:fs";
import { activeStores, setOverride, writeOverrides } from "../config/overrides.ts";
import { adapterFor } from "../adapters/index.ts";
import { get, getJson } from "../core/http.ts";
import type { StoreConfig } from "../core/types.ts";

const LOG_PATH = "check-stores.log";

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
  const results: ProbeResult[] = [];
  const lines: string[] = [];
  const say = (s = ""): void => {
    console.log(s);
    lines.push(s);
  };

  say();
  say(pad("STORE", 22) + pad("EXPECTED", 14) + pad("FOUND", 15) + "");
  say("-".repeat(72));

  for (const store of activeStores()) {
    if (store.kind === "BROWSER" || store.kind === "MANUAL") {
      say(pad(store.id, 22) + pad(store.kind, 14) + "needs a real browser");
      continue;
    }
    const detected = await detect(store);
    const changed = detected !== store.kind;
    results.push({ store, detected, changed });

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
    say(pad(store.id, 22) + pad(store.kind, 14) + pad(detected, 15) + mark);

    // Print what categories/collections this store actually has, right here,
    // so scoping a mixed-catalogue store (a general retailer that also sells
    // other consoles or non-game merchandise) to just its Switch section is a
    // copy-paste into `collections` in stores.ts instead of a manual API trip.
    const effectiveKind = detected === "SHOPIFY" || detected === "WOOCOMMERCE" ? detected : store.kind;
    if (store.enabled && (effectiveKind === "SHOPIFY" || effectiveKind === "WOOCOMMERCE")) {
      const categories = await listCategories(store, effectiveKind);
      if (categories.length > 0) {
        const shown = categories.slice(0, 20).map((c) => `${c.name} (${c.slug})`).join(", ");
        const more = categories.length > 20 ? ` … +${categories.length - 20} more` : "";
        say(`      categories: ${shown}${more}`);
      }
    }
  }

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

async function listCategories(store: StoreConfig, kind: "SHOPIFY" | "WOOCOMMERCE"): Promise<Category[]> {
  try {
    if (kind === "WOOCOMMERCE") {
      const cats = await getJson<{ name: string; slug: string }[]>(
        `${store.baseUrl}/wp-json/wc/store/v1/products/categories?per_page=100`,
      );
      return (cats ?? []).map((c) => ({ name: c.name, slug: c.slug }));
    }
    const data = await getJson<{ collections?: { title: string; handle: string }[] }>(
      `${store.baseUrl}/collections.json?limit=250`,
    );
    return (data?.collections ?? []).map((c) => ({ name: c.title, slug: c.handle }));
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
