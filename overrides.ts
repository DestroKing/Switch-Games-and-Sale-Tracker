import { existsSync, readFileSync, writeFileSync } from "node:fs";
import type { AdapterKind, StoreConfig } from "../core/types.ts";
import { STORES } from "./stores.ts";

/**
 * Corrections discovered by probing live in a JSON file, not in stores.ts.
 *
 * The alternative — having the probe rewrite a TypeScript source file — means
 * a tool editing code it also imports, and one bad regex silently corrupting
 * the store list. A separate overrides file keeps the shipped defaults intact
 * and makes "what did I change" a one-line diff.
 */
const PATH = "stores.local.json";

export interface StoreOverride {
  kind?: AdapterKind;
  enabled?: boolean;
  note?: string;
}

export type Overrides = Record<string, StoreOverride>;

export function readOverrides(): Overrides {
  if (!existsSync(PATH)) return {};
  try {
    return JSON.parse(readFileSync(PATH, "utf8")) as Overrides;
  } catch {
    console.warn(`  ${PATH} isn't valid JSON — ignoring it. Delete it to start over.`);
    return {};
  }
}

export function writeOverrides(next: Overrides): void {
  writeFileSync(PATH, JSON.stringify(next, null, 2) + "\n");
}

export function setOverride(storeId: string, patch: StoreOverride): void {
  const all = readOverrides();
  all[storeId] = { ...all[storeId], ...patch };
  writeOverrides(all);
}

/** The store list the rest of the app should use. */
export function activeStores(): readonly StoreConfig[] {
  const overrides = readOverrides();
  return STORES.map((s) => {
    const o = overrides[s.id];
    return o ? ({ ...s, ...o } as StoreConfig) : s;
  });
}

export function hasBeenProbed(): boolean {
  return existsSync(PATH);
}
