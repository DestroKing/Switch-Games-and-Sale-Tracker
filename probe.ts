import { STORES } from "../config/stores.ts";
import { setOverride, writeOverrides } from "../config/overrides.ts";
import { get } from "../core/http.ts";
import type { AdapterKind, StoreConfig } from "../core/types.ts";

export interface ProbeResult {
  store: StoreConfig;
  detected: AdapterKind | "UNREACHABLE";
  changed: boolean;
}

/**
 * Probe asks one question per store: what does this site actually speak?
 *
 * With `apply`, the answers are written to stores.local.json rather than
 * printed for you to transcribe. Transcribing a sixteen-row table by hand is
 * exactly the kind of step that gets done wrong once and then debugged for an
 * hour.
 */
export async function probe(apply = true): Promise<ProbeResult[]> {
  const results: ProbeResult[] = [];

  console.log();
  console.log(pad("STORE", 22) + pad("EXPECTED", 14) + pad("FOUND", 15) + "");
  console.log("-".repeat(72));

  for (const store of STORES) {
    if (store.kind === "BROWSER" || store.kind === "MANUAL") {
      console.log(pad(store.id, 22) + pad(store.kind, 14) + "needs a real browser");
      continue;
    }
    const detected = await detect(store);
    const changed = detected !== store.kind;
    results.push({ store, detected, changed });

    const mark = !changed ? "ok" : detected === "UNREACHABLE" ? "will disable" : "will switch";
    console.log(pad(store.id, 22) + pad(store.kind, 14) + pad(detected, 15) + mark);
  }

  if (apply) {
    let fixed = 0;
    let disabled = 0;
    for (const r of results) {
      if (!r.changed) continue;
      if (r.detected === "UNREACHABLE") {
        setOverride(r.store.id, { enabled: false, note: "unreachable when probed" });
        disabled++;
      } else {
        setOverride(r.store.id, { kind: r.detected, note: "corrected by probe" });
        fixed++;
      }
    }
    console.log();
    if (fixed || disabled) {
      console.log(`  Applied: ${fixed} corrected, ${disabled} disabled.`);
      console.log(`  Saved to stores.local.json — delete that file to undo everything.`);
    } else {
      console.log(`  Everything already matches. Nothing to change.`);
    }
  }

  return results;
}

export function resetOverrides(): void {
  writeOverrides({});
}

async function detect(store: StoreConfig): Promise<AdapterKind | "UNREACHABLE"> {
  if (await hits(`${store.baseUrl}/products.json?limit=1`, '"products"')) return "SHOPIFY";
  if (
    (await hits(`${store.baseUrl}/wp-json/wc/store/v1/products?per_page=1`, '"prices"')) ||
    (await hits(`${store.baseUrl}/wp-json/wc/store/products?per_page=1`, '"prices"'))
  ) {
    return "WOOCOMMERCE";
  }
  if (await hits(store.baseUrl, "application/ld+json")) return "JSON_API";
  if (await hits(store.baseUrl, "<html")) return "BROWSER";
  return "UNREACHABLE";
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
