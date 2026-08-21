import { getJson } from "../core/http.ts";
import { classify, inferRegion, parsePrice } from "../core/parse.ts";
import type { Adapter, FetchOutcome, RawListing, StoreConfig } from "../core/types.ts";

interface ShopifyVariant {
  id: number;
  title: string;
  price: string;
  available: boolean;
  sku?: string;
}

interface ShopifyProduct {
  id: number;
  title: string;
  handle: string;
  product_type?: string;
  tags?: string[];
  variants: ShopifyVariant[];
  images?: { src: string }[];
}

const PAGE_SIZE = 250;
// A backstop, not a target — the loop below already stops for real once a
// page comes back with fewer than PAGE_SIZE items. This just bounds a
// genuinely broken feed that never does, so it's generous rather than tuned
// to whatever any one store's real page count happens to be today.
const MAX_PAGES = 100;

/**
 * Shopify exposes the entire catalogue as JSON at /products.json with no auth
 * and no key. Where collections are configured we page through those instead —
 * faster, and politer than pulling a whole catalogue of unrelated stock.
 */
export const shopifyAdapter: Adapter = {
  kind: "SHOPIFY",

  async fetch(store: StoreConfig): Promise<FetchOutcome> {
    const paths = store.collections?.length
      ? store.collections.map((c) => `/collections/${c}/products.json`)
      : ["/products.json"];

    const listings: RawListing[] = [];
    const problems: string[] = [];

    for (const path of paths) {
      let page = 1;
      for (; page <= MAX_PAGES; page++) {
        const url = `${store.baseUrl}${path}?limit=${PAGE_SIZE}&page=${page}`;
        const data = await getJson<{ products?: ShopifyProduct[] }>(url);

        if (!data) {
          problems.push(`${path} page ${page}: no parseable JSON`);
          break;
        }
        const products = data.products ?? [];
        if (products.length === 0) break;

        for (const p of products) {
          const listing = toListing(store, p);
          if (listing) listings.push(listing);
        }
        if (products.length < PAGE_SIZE) break;
      }
    }

    if (listings.length === 0) {
      return { status: "failed", reason: problems.join("; ") || "zero products returned" };
    }
    if (problems.length > 0) {
      return { status: "partial", listings, reason: problems.join("; ") };
    }
    return { status: "ok", listings };
  },
};

function toListing(store: StoreConfig, p: ShopifyProduct): RawListing | undefined {
  const variant = p.variants?.[0];
  if (!variant) return undefined;

  const price = parsePrice(variant.price);
  if (price === undefined) return undefined;

  // Everything the store tells us, not just the title. A terse "Hogwarts
  // Legacy" in a product_type of "Nintendo Switch Games" is a Switch game;
  // passing the title alone is what made these stores look empty.
  const context = [p.title, p.product_type ?? "", (p.tags ?? []).join(" ")].join(" ");
  const { platform, kind } = classify(context, store.platformHint);

  // These shops also sell consoles, Joy-Cons, cases and eShop credit. Only
  // cartridges belong in a cartridge price history.
  if (kind !== "GAME" || platform === "UNKNOWN") return undefined;

  return {
    storeId: store.id,
    sku: variant.sku?.trim() || String(p.id),
    url: `${store.baseUrl}/products/${p.handle}`,
    title: p.title,
    nativeCurrency: store.currency,
    nativePrice: price,
    inStock: variant.available !== false,
    platform,
    region: inferRegion(p.title, "IN"),
    ...(p.images?.[0]?.src ? { imageUrl: p.images[0].src } : {}),
  };
}
