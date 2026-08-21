import { getJson } from "../core/http.ts";
import { classify, inferRegion, parsePrice } from "../core/parse.ts";
import type { Adapter, FetchOutcome, RawListing, StoreConfig } from "../core/types.ts";

/**
 * The WooCommerce Store API is public and unauthenticated — it is what the
 * shop's own front end calls. Two path shapes are in the wild depending on the
 * Woo version, so try both.
 */
const PATHS = ["/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"];
const PER_PAGE = 100;
const MAX_PAGES = 20;

interface WooProduct {
  id: number;
  name: string;
  permalink: string;
  sku?: string;
  is_in_stock?: boolean;
  categories?: { name: string }[];
  images?: { src: string }[];
  prices?: {
    price?: string;
    currency_code?: string;
    currency_minor_unit?: number;
  };
}

export const wooAdapter: Adapter = {
  kind: "WOOCOMMERCE",

  async fetch(store: StoreConfig): Promise<FetchOutcome> {
    const base = await resolvePath(store);
    if (!base) return { status: "failed", reason: "no Store API at either known path" };

    // Without a category restriction this walks the entire catalogue, which
    // is wrong for a general retailer that also sells other consoles or
    // non-game merchandise — the classifier catches most of that, but a
    // store with a real "Nintendo Switch" category should just be scoped to
    // it. Slugs come from GET /wp-json/wc/store/v1/products/categories,
    // which "Check stores" now prints per store.
    const categoryQueries = store.collections?.length
      ? store.collections.map((slug) => `&category=${encodeURIComponent(slug)}`)
      : [""];

    const listings: RawListing[] = [];
    for (const categoryQuery of categoryQueries) {
      for (let page = 1; page <= MAX_PAGES; page++) {
        const url = `${store.baseUrl}${base}?per_page=${PER_PAGE}&page=${page}${categoryQuery}`;
        const products = await getJson<WooProduct[]>(url);
        if (!products || products.length === 0) break;

        for (const p of products) {
          const listing = toListing(store, p);
          if (listing) listings.push(listing);
        }
        if (products.length < PER_PAGE) break;
      }
    }

    return listings.length > 0
      ? { status: "ok", listings }
      : { status: "failed", reason: "Store API reachable but returned no Switch products" };
  },
};

async function resolvePath(store: StoreConfig): Promise<string | undefined> {
  for (const path of PATHS) {
    const probe = await getJson<WooProduct[]>(`${store.baseUrl}${path}?per_page=1`);
    if (Array.isArray(probe)) return path;
  }
  return undefined;
}

function toListing(store: StoreConfig, p: WooProduct): RawListing | undefined {
  const raw = p.prices?.price;
  if (raw === undefined) return undefined;

  // Woo's Store API quotes minor units, with the exponent given per response.
  const minorUnit = p.prices?.currency_minor_unit ?? 2;
  const parsed = parsePrice(raw);
  if (parsed === undefined) return undefined;
  const price = parsed / 10 ** minorUnit;

  const context = [p.name, (p.categories ?? []).map((c) => c.name).join(" ")].join(" ");
  const { platform, kind } = classify(context, store.platformHint);
  if (kind !== "GAME" || platform === "UNKNOWN") return undefined;

  return {
    storeId: store.id,
    sku: p.sku?.trim() || String(p.id),
    url: p.permalink,
    title: p.name,
    nativeCurrency: p.prices?.currency_code ?? store.currency,
    nativePrice: price,
    inStock: p.is_in_stock !== false,
    platform,
    region: inferRegion(p.name, "IN"),
    ...(p.images?.[0]?.src ? { imageUrl: p.images[0].src } : {}),
  };
}
