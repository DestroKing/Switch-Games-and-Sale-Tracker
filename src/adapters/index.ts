import type { Adapter, AdapterKind } from "../core/types.ts";
import { browserAdapter } from "./browser.ts";
import { shopifyAdapter } from "./shopify.ts";
import { wooAdapter } from "./woocommerce.ts";

const REGISTRY: Partial<Record<AdapterKind, Adapter>> = {
  SHOPIFY: shopifyAdapter,
  WOOCOMMERCE: wooAdapter,
  BROWSER: browserAdapter,
  // JSON_API: Games The Shop's Next.js endpoint — write once the probe shows
  // the request shape. MANUAL: intentionally has no adapter.
};

export function adapterFor(kind: AdapterKind): Adapter | undefined {
  return REGISTRY[kind];
}

export { closeBrowser } from "./browser.ts";
