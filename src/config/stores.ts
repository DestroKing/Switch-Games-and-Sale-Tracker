import type { StoreConfig } from "../core/types.ts";

/**
 * `kind` for the API-based (SHOPIFY/WOOCOMMERCE) stores below is a
 * hypothesis — run `bun run probe` and correct this file, or let it write
 * stores.local.json, from what it reports. BROWSER-kind stores need a
 * `PROFILES` entry in src/adapters/browser.ts and don't go through probe at
 * all (see probe.ts's early skip for BROWSER/MANUAL kind).
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
  { id: "gameloot", name: "GameLoot", baseUrl: "https://gameloot.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },
  { id: "nekavo", name: "NEKAVO", baseUrl: "https://nekavo.com", kind: "WOOCOMMERCE", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH" },

  // Unverified as cartridge sellers — cheap to keep, cheap to delete.
  {
    id: "emartgames", name: "Emart Games", baseUrl: "https://emartgames.in", kind: "SHOPIFY",
    currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH",
    collections: ["nintendo-switch-games-cds-online-india", "nintendo-switch-2-games"],
    note: "Multi-console store (also sells PS3/PS4/PS5) — scoped to its two Switch categories, found via `bun run probe`'s category listing.",
  },
  { id: "hgworld", name: "HG World", baseUrl: "https://hgworld.in", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH", note: "Unverified" },
  { id: "pssales", name: "PS Sales and Service", baseUrl: "https://pssalesandservice.com", kind: "SHOPIFY", currency: "INR", tier: 2, enabled: true, platformHint: "SWITCH", note: "Shopify confirmed, cartridges unconfirmed" },
  {
    id: "zozila", name: "Zozila", baseUrl: "https://zozila.com", kind: "SHOPIFY",
    currency: "INR", tier: 2, enabled: false, platformHint: "SWITCH",
    note: "Disabled: `bun run probe`'s category listing shows it's a digital gift-card/voucher marketplace (Amazon, Apple iTunes, Air India, Apollo Pharmacy...), not a cartridge retailer — none of its ~100 categories matched Switch/Nintendo.",
  },

  // ---- Tier 1: browser automation, run last. ----
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
    id: "gamestheshop",
    name: "Games The Shop",
    baseUrl: "https://www.gamestheshop.com",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: [
      "https://www.gamestheshop.com/search?condition=Physical&platforms=Nintendo+Switch&categories=Game+Software&page={p}",
      "https://www.gamestheshop.com/search?condition=Physical&platforms=Nintendo+Switch+2&categories=Game+Software&page={p}",
    ],
    note: "Custom Next.js storefront, not Shopify/WooCommerce — has no public product API, so it's scraped like Amazon/Flipkart. The &page={p} suffix is a guess; confirm/adjust once inspect.ts shows page 2's real URL shape.",
  },
  {
    id: "gamenation",
    name: "GameNation",
    baseUrl: "https://gamenation.in",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: ["https://gamenation.in/PlayStation/?platform=nintendoSwitch%2CnintendoSwitch2&page={p}"],
    note: "Custom storefront (the /PlayStation/ path is misleading — it's their general catalogue, filtered by the platform query param to both Switch and Switch 2). &page={p} is a guess to confirm via inspect.ts.",
  },
  {
    id: "mcubegames",
    name: "Mcube Games",
    baseUrl: "https://www.mcubegames.in",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: ["https://www.mcubegames.in/shop?platforms=60&platforms=93&page={p}"],
    note: "Custom storefront filtered by numeric platform IDs (60/93 = Switch/Switch 2 per the URL given). &page={p} is a guess to confirm via inspect.ts.",
  },
  {
    id: "e2zstore",
    name: "e2zSTORE",
    baseUrl: "https://e2zstore.com",
    kind: "BROWSER",
    currency: "INR",
    tier: 1,
    enabled: true,
    platformHint: "SWITCH",
    searchUrls: ["https://e2zstore.com/category/nintendo-games/?paged={p}"],
    note: "Every direct HTTP request (Store API and plain homepage fetch) failed here even though the site loads fine in a real browser — almost certainly bot protection blocking non-browser traffic, so it needs Playwright rather than the WooCommerce adapter. baseUrl switched from www to non-www to match the URL that's confirmed to load.",
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
