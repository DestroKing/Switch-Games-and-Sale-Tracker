/**
 * Domain types.
 *
 * Two decisions from the design phase are load-bearing here and should not be
 * quietly softened later:
 *
 *  1. A listing carries its NATIVE currency and price. INR is derived, never
 *     captured. Play-Asia's rupee figure is a display conversion; storing it as
 *     if it were a price makes every FX wobble look like a sale.
 *  2. `gameId` is nullable. An unmatched listing still gets collected. Matching
 *     is a separate, re-runnable pass over data we already have.
 */

export type Platform = "SWITCH" | "SWITCH2" | "UNKNOWN";

/**
 * Region is a first-class attribute, not a tag. Play-Asia splits one title
 * across Asia-English, Asia-Chinese, Japan and Western SKUs. Those are
 * different products with different playability — collapsing them into one
 * canonical game would be wrong.
 */
export type Region = "IN" | "ASIA_EN" | "ASIA_ZH" | "JP" | "US" | "EU" | "UNKNOWN";

/** Inferred per-listing from the store's own text, not asserted per store — see inferCondition(). */
export type Condition = "NEW" | "PRE_OWNED";

export type AdapterKind = "SHOPIFY" | "WOOCOMMERCE" | "JSON_API" | "BROWSER" | "MANUAL";

export type Tier = 1 | 2 | 3;

export interface StoreConfig {
  readonly id: string;
  readonly name: string;
  readonly baseUrl: string;
  readonly kind: AdapterKind;
  /** ISO 4217 of the prices this store quotes natively. */
  readonly currency: string;
  readonly tier: Tier;
  readonly enabled: boolean;
  /** Shopify/Woo: restrict the crawl to these collection or category slugs. */
  readonly collections?: readonly string[];
  /** BROWSER adapters: search or category URLs to walk, `{q}` substituted. */
  readonly searchUrls?: readonly string[];
  /**
   * Asserted platform for stores whose catalogue is known to be Switch-only.
   * Lets a terse title with no console marker still be classified, instead of
   * being dropped for saying nothing about which machine it runs on.
   */
  readonly platformHint?: Platform;
  /** Free-text note carried from the research phase. */
  readonly note?: string;
}

/** What an adapter returns. Deliberately dumb: no matching, no normalisation. */
export interface RawListing {
  readonly storeId: string;
  /** Store's own identifier where one exists, else the product URL path. */
  readonly sku: string;
  readonly url: string;
  readonly title: string;
  readonly nativeCurrency: string;
  readonly nativePrice: number;
  readonly inStock: boolean;
  readonly platform: Platform;
  readonly region: Region;
  readonly condition: Condition;
  readonly imageUrl?: string;
}

export type FetchOutcome =
  | { readonly status: "ok"; readonly listings: readonly RawListing[] }
  | { readonly status: "partial"; readonly listings: readonly RawListing[]; readonly reason: string }
  | { readonly status: "failed"; readonly reason: string };

export interface Adapter {
  readonly kind: AdapterKind;
  fetch(store: StoreConfig): Promise<FetchOutcome>;
}

export interface FxRate {
  readonly base: string;
  readonly quote: string;
  readonly rate: number;
  /** ECB publication date, not the time we fetched it. */
  readonly rateDate: string;
}
