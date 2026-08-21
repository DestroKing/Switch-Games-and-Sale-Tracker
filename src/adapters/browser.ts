import { chromium, type Browser, type Page } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { classify, firstRupeePrice, inferRegion, parsePrice } from "../core/parse.ts";
import type { Adapter, FetchOutcome, Platform, RawListing, Region, StoreConfig } from "../core/types.ts";

/**
 * Extraction is layered, hardest-to-break first, because CSS class names on
 * these three sites are the least durable thing about them — Flipkart in
 * particular ships obfuscated classes that change without notice.
 *
 *   1. JSON-LD   — schema.org Product/ItemList in a <script> tag. Survives
 *                  redesigns because it exists for search engines, not layout.
 *   2. Embedded  — the site's own hydration state (Flipkart's __INITIAL_STATE__).
 *   3. Selectors — CSS, last resort.
 *   4. Text      — within a matched card, find the ₹ figure by pattern rather
 *                  than by class.
 *
 * When all four produce nothing, the page is dumped to diagnostics/ so the
 * failure is something you can open and read, rather than a zero.
 */

interface StoreProfile {
  readonly cardSelectors: readonly string[];
  readonly titleSelectors: readonly string[];
  readonly priceSelectors: readonly string[];
  readonly linkSelectors: readonly string[];
  readonly outOfStockSelectors?: readonly string[];
  readonly defaultRegion: Region;
  readonly platformHint?: Platform;
  readonly dismiss?: readonly string[];
  /** Wait for this before scraping; usually the results container. */
  readonly ready?: string;
  readonly pages: number;
}

export function hasBrowserProfile(storeId: string): boolean {
  return storeId in PROFILES;
}

const PROFILES: Record<string, StoreProfile> = {
  amazon_in: {
    // data-component-type is Amazon's own hook and is markedly more stable
    // than their generated class names.
    cardSelectors: [
      "div[data-component-type='s-search-result']",
      "div.s-result-item[data-asin]:not([data-asin=''])",
    ],
    titleSelectors: ["h2 a span", "h2 span", "[data-cy='title-recipe'] span"],
    priceSelectors: ["span.a-price span.a-offscreen", "span.a-price-whole", ".a-color-price"],
    linkSelectors: ["h2 a", "a.a-link-normal.s-no-outline", "a[href*='/dp/']"],
    outOfStockSelectors: ["span:has-text('Currently unavailable')", ".a-color-price:has-text('unavailable')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "div.s-main-slot",
    dismiss: ["input[data-action-type='DISMISS']", "button:has-text('Continue shopping')"],
    pages: 3,
  },

  flipkart: {
    // Flipkart's classes are generated and rotate. Anchor on structure and
    // href shape instead; the /p/ path segment has been stable for years.
    cardSelectors: [
      "div[data-id]",
      "div._1sdMkc",
      "a[href*='/p/']:has(img)",
    ],
    titleSelectors: ["a[title]", "div.KzDlHZ", "a.wjcEIp", "div._4rR01T"],
    priceSelectors: ["div.Nx9bqj", "div._30jeq3", "div._4b5DiR"],
    linkSelectors: ["a[href*='/p/']"],
    outOfStockSelectors: ["div:has-text('Sold Out')", "div:has-text('Coming Soon')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "div[data-id], a[href*='/p/']",
    dismiss: ["button._2KpZ6l._2doB4z", "span._30XB9F", "button:has-text('✕')"],
    pages: 3,
  },

  croma: {
    cardSelectors: ["li.product-item", "div.product-item", "[data-testid='product-card']"],
    titleSelectors: ["h3.product-title", ".product-title a", "h3 a"],
    priceSelectors: ["span.amount", ".new-price", "[data-testid='price']"],
    linkSelectors: ["a[href*='/p/']", "h3 a", "a"],
    outOfStockSelectors: [".out-of-stock", "div:has-text('Out of stock')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "li.product-item, div.product-item, [data-testid='product-card']",
    pages: 2,
  },

  playasia: {
    cardSelectors: ["div.product-item", "li.product", "[class*='product-tile']"],
    titleSelectors: [".product-title", ".title", "h3"],
    priceSelectors: [".price", ".product-price"],
    linkSelectors: ["a"],
    outOfStockSelectors: [".out-of-stock", ".sold-out"],
    defaultRegion: "UNKNOWN",
    pages: 2,
  },
};

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

let shared: Browser | undefined;

async function getBrowser(): Promise<Browser> {
  shared ??= await chromium.launch({
    headless: process.env["HEADFUL"] !== "1",
    args: [
      "--disable-blink-features=AutomationControlled",
      "--disable-features=IsolateOrigins,site-per-process",
    ],
  });
  return shared;
}

export async function closeBrowser(): Promise<void> {
  await shared?.close();
  shared = undefined;
}

interface Extracted {
  title: string;
  price: number;
  href: string;
  inStock: boolean;
}

export const browserAdapter: Adapter = {
  kind: "BROWSER",

  async fetch(store: StoreConfig): Promise<FetchOutcome> {
    const profile = PROFILES[store.id];
    if (!profile) return { status: "failed", reason: `no profile for ${store.id}` };
    if (!store.searchUrls?.length) return { status: "failed", reason: "no searchUrls configured" };

    const browser = await getBrowser();
    const context = await browser.newContext({
      userAgent: UA,
      locale: "en-IN",
      timezoneId: "Asia/Kolkata",
      viewport: { width: 1440, height: 960 },
      extraHTTPHeaders: { "accept-language": "en-IN,en;q=0.9" },
    });

    // Trim the automation tell that these sites check for.
    await context.addInitScript(() => {
      Object.defineProperty(navigator, "webdriver", { get: () => undefined });
    });

    const listings: RawListing[] = [];
    const problems: string[] = [];
    const methods = new Set<string>();

    try {
      const page = await context.newPage();
      // Images are most of the bytes and none of the data.
      await page.route("**/*.{png,jpg,jpeg,webp,gif,svg,woff,woff2}", (r) => r.abort());

      for (const template of store.searchUrls) {
        for (let p = 1; p <= profile.pages; p++) {
          const url = template.replace("{p}", String(p));
          try {
            const { rows, method } = await scrapePage(page, store, profile, url);
            methods.add(method);
            for (const row of rows) {
              const l = toListing(store, profile, row);
              if (l) listings.push(l);
            }
            if (rows.length === 0) break; // no more pages
          } catch (e) {
            problems.push(`p${p}: ${e instanceof Error ? e.message : String(e)}`);
          }
          await page.waitForTimeout(2500 + Math.random() * 2500);
        }
      }
    } finally {
      await context.close();
    }

    const unique = dedupe(listings);

    if (unique.length === 0) {
      return {
        status: "failed",
        reason:
          (problems.join("; ") || "page loaded but nothing extracted") +
          ` — HTML dumped to diagnostics/${store.id}.html; run: bun run src/cli/inspect.ts ${store.id}`,
      };
    }
    const via = `via ${[...methods].join("+")}`;
    return problems.length
      ? { status: "partial", listings: unique, reason: `${problems.join("; ")} (${via})` }
      : { status: "ok", listings: unique };
  },
};

async function scrapePage(
  page: Page,
  store: StoreConfig,
  profile: StoreProfile,
  url: string,
): Promise<{ rows: Extracted[]; method: string }> {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45_000 });

  for (const d of profile.dismiss ?? []) {
    await page.locator(d).first().click({ timeout: 1500 }).catch(() => undefined);
  }

  if (profile.ready) {
    await page.waitForSelector(profile.ready, { timeout: 15_000 }).catch(() => undefined);
  }

  // Lazy-loaded grids need a nudge.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.6));
  await page.waitForTimeout(1200);

  // ---- layer 1: JSON-LD
  const jsonLd = await fromJsonLd(page);
  if (jsonLd.length > 0) return { rows: jsonLd, method: "json-ld" };

  // ---- layer 2: embedded hydration state (Flipkart)
  if (store.id === "flipkart") {
    const embedded = await fromFlipkartState(page);
    if (embedded.length > 0) return { rows: embedded, method: "embedded-state" };
  }

  // ---- layer 3 + 4: selectors, with in-card text fallback for price
  const rows = await fromSelectors(page, profile);
  if (rows.length > 0) return { rows, method: "selectors" };

  await dump(page, store.id);
  return { rows: [], method: "none" };
}

async function fromJsonLd(page: Page): Promise<Extracted[]> {
  const blobs = await page
    .locator('script[type="application/ld+json"]')
    .allTextContents()
    .catch(() => [] as string[]);

  const out: Extracted[] = [];
  for (const blob of blobs) {
    let data: unknown;
    try {
      data = JSON.parse(blob);
    } catch {
      continue;
    }
    for (const node of flatten(data)) {
      const type = String((node as Record<string, unknown>)["@type"] ?? "");
      if (!/product/i.test(type)) continue;
      const rec = node as Record<string, any>;
      const offer = Array.isArray(rec["offers"]) ? rec["offers"][0] : rec["offers"];
      const price = parsePrice(offer?.price ?? offer?.lowPrice);
      const name = String(rec["name"] ?? "");
      const href = String(rec["url"] ?? offer?.url ?? "");
      if (!name || price === undefined || !href) continue;
      out.push({
        title: name,
        price,
        href,
        inStock: !/OutOfStock|SoldOut/i.test(String(offer?.availability ?? "")),
      });
    }
  }
  return out;
}

/** Walks arrays, @graph nodes and ItemList elements into a flat node list. */
function* flatten(node: unknown): Generator<unknown> {
  if (Array.isArray(node)) {
    for (const n of node) yield* flatten(n);
    return;
  }
  if (node && typeof node === "object") {
    yield node;
    const rec = node as Record<string, unknown>;
    for (const key of ["@graph", "itemListElement", "item", "mainEntity"]) {
      if (rec[key]) yield* flatten(rec[key]);
    }
  }
}

async function fromFlipkartState(page: Page): Promise<Extracted[]> {
  return page
    .evaluate(() => {
      const state = (window as any).__INITIAL_STATE__;
      if (!state) return [];
      const found: Extracted[] = [];
      const seen = new Set<unknown>();

      // The shape of this object changes; walk it looking for anything with a
      // title and a price rather than assuming a path.
      const walk = (n: any, depth: number): void => {
        if (!n || typeof n !== "object" || depth > 12 || seen.has(n)) return;
        seen.add(n);
        const title = n.title ?? n.productTitle ?? n.name;
        const price = n.finalPrice?.value ?? n.price?.value ?? n.sellingPrice?.value;
        const url = n.baseUrl ?? n.url ?? n.pageUri;
        if (typeof title === "string" && typeof price === "number" && typeof url === "string") {
          found.push({
            title,
            price,
            href: url,
            inStock: n.availability?.intent !== "OUT_OF_STOCK",
          });
        }
        for (const v of Object.values(n)) walk(v, depth + 1);
      };
      walk(state, 0);
      return found;
    })
    .catch(() => [] as Extracted[]);
}

async function fromSelectors(page: Page, profile: StoreProfile): Promise<Extracted[]> {
  for (const cardSel of profile.cardSelectors) {
    const count = await page.locator(cardSel).count().catch(() => 0);
    if (count === 0) continue;

    const rows = await page.locator(cardSel).evaluateAll(
      (nodes, cfg) => {
        const pick = (n: Element, sels: string[]): string => {
          for (const s of sels) {
            const t = n.querySelector(s)?.textContent?.trim();
            if (t) return t;
          }
          return "";
        };
        return nodes.map((n) => ({
          title:
            pick(n, cfg.titleSelectors) ||
            n.querySelector("a[title]")?.getAttribute("title") ||
            n.querySelector("img")?.getAttribute("alt") ||
            "",
          priceText: pick(n, cfg.priceSelectors),
          // If no price selector matched, hand the whole card's text to the
          // rupee-pattern fallback rather than giving up on the row.
          cardText: n.textContent ?? "",
          href: (() => {
            for (const s of cfg.linkSelectors) {
              const h = n.querySelector(s)?.getAttribute("href");
              if (h) return h;
            }
            return n.getAttribute("href") ?? "";
          })(),
          oos: (cfg.outOfStockSelectors ?? []).some((s) => {
            try {
              return Boolean(n.querySelector(s));
            } catch {
              return false;
            }
          }),
        }));
      },
      {
        titleSelectors: [...profile.titleSelectors],
        priceSelectors: [...profile.priceSelectors],
        linkSelectors: [...profile.linkSelectors],
        outOfStockSelectors: [...(profile.outOfStockSelectors ?? [])],
      },
    );

    const parsed: Extracted[] = [];
    for (const r of rows) {
      if (!r.title || !r.href) continue;
      const price = parsePrice(r.priceText) ?? firstRupeePrice(r.cardText);
      if (price === undefined) continue;
      parsed.push({ title: r.title, price, href: r.href, inStock: !r.oos });
    }
    if (parsed.length > 0) return parsed;
  }
  return [];
}

/** A failure you can open in a browser beats a failure that is just a zero. */
async function dump(page: Page, storeId: string): Promise<void> {
  try {
    mkdirSync("diagnostics", { recursive: true });
    writeFileSync(`diagnostics/${storeId}.html`, await page.content());
    await page.screenshot({ path: `diagnostics/${storeId}.png`, fullPage: false });
  } catch {
    // Diagnostics failing must never mask the original problem.
  }
}

function toListing(store: StoreConfig, profile: StoreProfile, r: Extracted): RawListing | undefined {
  const { platform, kind } = classify(r.title, profile.platformHint);
  // Only cartridges. Consoles, Joy-Cons, cases and eShop codes are dropped
  // here rather than polluting the price history.
  if (kind !== "GAME" || platform === "UNKNOWN") return undefined;

  const absolute = r.href.startsWith("http") ? r.href : new URL(r.href, store.baseUrl).toString();

  return {
    storeId: store.id,
    sku: skuFromUrl(absolute),
    url: absolute.split("?")[0] ?? absolute,
    title: r.title,
    nativeCurrency: store.currency,
    nativePrice: r.price,
    inStock: r.inStock,
    platform,
    region: inferRegion(r.title, profile.defaultRegion),
  };
}

function skuFromUrl(url: string): string {
  const u = new URL(url);
  // Amazon: the ASIN is the stable id. Flipkart: the pid query param.
  const asin = u.pathname.match(/\/dp\/([A-Z0-9]{10})/i)?.[1];
  if (asin) return asin;
  const pid = u.searchParams.get("pid");
  if (pid) return pid;
  return (u.pathname.split("/").filter(Boolean).pop() ?? u.pathname).slice(0, 120);
}

function dedupe(listings: readonly RawListing[]): RawListing[] {
  const seen = new Map<string, RawListing>();
  for (const l of listings) seen.set(l.sku, l);
  return [...seen.values()];
}
