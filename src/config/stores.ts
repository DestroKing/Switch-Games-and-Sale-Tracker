import type { StoreConfig } from "../core/types.ts";

/**
 * The list as verified during research. `kind` is a HYPOTHESIS for most of
 * these — run `bun run probe` and correct this file from what it reports
 * before running a collection. Four entries are unverified as cartridge
 * sellers at all; if the probe shows they are console-only, delete the line.
 */
export const STORES: readonly StoreConfig[] = [
  // ---- Tier 2: dedicated retailers. The real catalogue lives here. ----
  {
    id: "nistore",
    name: "NI Gaming Store",
    baseUrl: "https://nistore.in",
    kind: "WOOCOMMERCE",
    currency: "INR",
    tier: 2,
    enabled: true,
    platformHint: "SWITCH",
    note: "Verified: three pages of Switch/Switch 2 cartridges. Best first target.",
  },
  {
    id: "gamestheshop",
    name: "Games The Shop",
    baseUrl: "https://www.gamestheshop.com",
    kind: "JSON_API",
    currency: "INR",
    tier: 2,
    enabled: true,
    platformHint: "SWITCH",
    note: "Custom Next.js app with a query-param search API. Needs its own adapter.",
  },
  { id: "gamenation", name: "GameNation", baseUrl: "https://gamenation.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },
  { id: "gameloot", name: "GameLoot", baseUrl: "https://gameloot.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },
  { id: "mcubegames", name: "Mcube Games", baseUrl: "https://mcubegames.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },
  { id: "nekavo", name: "NEKAVO", baseUrl: "https://nekavo.com", kind: "WOOCOMMERCE", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },
  { id: "e2zstore", name: "e2zSTORE", baseUrl: "https://www.e2zstore.com", kind: "WOOCOMMERCE", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },
  { id: "gamestrade", name: "Games Trade", baseUrl: "https://gamestrade.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },

  // Unverified as cartridge sellers — cheap to keep, cheap to delete.
  { id: "emartgames", name: "Emart Games", baseUrl: "https://emartgames.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH", note: "Unverified" },
  { id: "hgworld", name: "HG World", baseUrl: "https://hgworld.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH", note: "Unverified" },
  { id: "pssales", name: "PS Sales and Service", baseUrl: "https://pssalesandservice.com", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH", note: "Shopify confirmed, cartridges unconfirmed" },
  { id: "zozila", name: "Zozila", baseUrl: "https://zozila.com", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH", note: "Unverified" },

  // ---- Tier 1: the hard three. Browser automation, run last. ----
  {
    id: "amazon_in",
    name: "Amazon.in",
    baseUrl: "https://www.amazon.in",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: [
      "https://www.amazon.in/s?k=nintendo+switch+games&i=videogames&page={p}",
      "https://www.amazon.in/s?k=nintendo+switch+2+games&i=videogames&page={p}",
    ],
    note: "Real bot detection. Cards keyed on data-component-type, which is stabler than Amazon's class names.",
  },
  {
    id: "flipkart",
    name: "Flipkart",
    baseUrl: "https://www.flipkart.com",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: [
      "https://www.flipkart.com/search?q=nintendo%20switch%20games&page={p}",
      "https://www.flipkart.com/search?q=nintendo%20switch%202%20games&page={p}",
    ],
    note: "Obfuscated, rotating class names. Adapter prefers __INITIAL_STATE__ over CSS for this reason.",
  },
  {
    id: "croma",
    name: "Croma",
    baseUrl: "https://www.croma.com",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: ["https://www.croma.com/searchB?q=nintendo%20switch%20games%3Arelevance&page={p}"],
    note: "Thin cartridge catalogue — expect a small number of rows, not a failure.",
  },

  // ---- Parked ----
  {
    id: "playasia",
    name: "Play-Asia",
    baseUrl: "https://www.play-asia.com",
    kind: "BROWSER",
    currency: "USD",
    tier: 1,
    enabled: false,
    searchUrls: ["https://www.play-asia.com/search/nintendo+switch?page={p}"],
    note: "Parked by request. Currency is USD — the INR shown on-site is a display conversion, not a price. Re-enable by flipping this flag.",
  },
];

/**
 * Search terms are baked into each browser store's searchUrls now, so pages
 * can be templated with {p}. Kept for the JSON_API adapter still to be written.
 */
export const SEARCH_TERMS: readonly string[] = [
  "nintendo switch game",
  "nintendo switch 2 game",
];
