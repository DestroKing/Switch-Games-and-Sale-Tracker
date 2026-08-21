import { chromium } from "playwright";
import { activeStores } from "../config/overrides.ts";
const STORES = activeStores();

/**
 * Opens a hard store's search page in a visible browser and pauses on
 * Playwright Inspector, so you can point at a product card and read its real
 * selector. Use this to correct SELECTORS in src/adapters/browser.ts — those
 * values were written without network access and are guesses.
 *
 *   bun run src/cli/inspect.ts playasia
 */
const id = process.argv[2];
const store = STORES.find((s) => s.id === id);

if (!store?.searchUrls?.[0]) {
  console.log("usage: bun run src/cli/inspect.ts <storeId>");
  console.log("browser stores: " + STORES.filter((s) => s.kind === "BROWSER").map((s) => s.id).join(", "));
  process.exit(1);
}

const browser = await chromium.launch({ headless: false });
const page = await browser.newPage({ locale: "en-IN", timezoneId: "Asia/Kolkata" });
await page.goto(store.searchUrls[0].replace("{p}", "1"));

console.log("Inspector open. Pick a product card, then a title, price and link inside it.");
console.log("Copy what you find into PROFILES in src/adapters/browser.ts —");
console.log("each field takes a LIST of selectors, so add yours without deleting the others.");
await page.pause();
await browser.close();
