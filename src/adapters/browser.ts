import { chromium, type Browser, type Page } from "playwright";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { classify, firstRupeePrice, inferRegion, parsePrice } from "../core/parse.ts";
import type { Adapter, FetchOutcome, Platform, RawListing, Region, StoreConfig } from "../core/types.ts";

/**
 * Extraction is layered, hardest-to-break first, because CSS class names on
 * these sites are the least durable thing about them — Flipkart in
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
  /**
   * Some storefronts (mcubegames, gamenation — both Next.js apps) never
   * change the URL for pagination at all; page 2+ only exists behind a
   * client-side button click that re-fetches and re-renders in place. When
   * set, paging clicks the first matching selector instead of navigating to
   * `searchUrls` with `{p}` substituted. Tried in order, same convention as
   * every other selector list here.
   */
  readonly nextPageSelectors?: readonly string[];
}

export function hasBrowserProfile(storeId: string): boolean {
  return storeId in PROFILES;
}

/**
 * Selectors found via `inspect.ts` land here, not in this file — same reason
 * `stores.local.json` exists instead of probe rewriting stores.ts: a tool
 * should never patch the source file it also imports. `inspect.ts` writes
 * this directly, so a corrected selector is usable on the very next
 * `collect` run with no manual editing step in between.
 */
const PROFILE_OVERRIDES_PATH = "profiles.local.json";
const SELECTOR_FIELDS = ["cardSelectors", "titleSelectors", "priceSelectors", "linkSelectors"] as const;
type SelectorField = (typeof SELECTOR_FIELDS)[number];
type ProfileOverrides = Record<string, Partial<Record<SelectorField, readonly string[]>>>;

function readProfileOverrides(): ProfileOverrides {
  if (!existsSync(PROFILE_OVERRIDES_PATH)) return {};
  try {
    return JSON.parse(readFileSync(PROFILE_OVERRIDES_PATH, "utf8")) as ProfileOverrides;
  } catch {
    return {};
  }
}

/** Exported for inspect.ts — prepends a found selector so it's tried first, without discarding the existing guesses. */
export function addProfileSelector(storeId: string, field: SelectorField, css: string): void {
  const all = readProfileOverrides();
  const forStore = all[storeId] ?? {};
  const existing = forStore[field] ?? [];
  if (existing.includes(css)) return;
  all[storeId] = { ...forStore, [field]: [css, ...existing] };
  writeFileSync(PROFILE_OVERRIDES_PATH, JSON.stringify(all, null, 2) + "\n");
}

function effectiveProfile(storeId: string): StoreProfile | undefined {
  const base = PROFILES[storeId];
  if (!base) return undefined;
  const override = readProfileOverrides()[storeId];
  if (!override) return base;
  const merged: { -readonly [K in keyof StoreProfile]: StoreProfile[K] } = { ...base };
  for (const field of SELECTOR_FIELDS) {
    const found = override[field];
    if (found?.length) merged[field] = [...found, ...base[field]];
  }
  return merged;
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
  },

  playasia: {
    cardSelectors: ["div.product-item", "li.product", "[class*='product-tile']"],
    titleSelectors: [".product-title", ".title", "h3"],
    priceSelectors: [".price", ".product-price"],
    linkSelectors: ["a"],
    outOfStockSelectors: [".out-of-stock", ".sold-out"],
    defaultRegion: "UNKNOWN",
  },

  // ---- gamestheshop, gamenation and mcubegames below were confirmed
  // against real diagnostics/<id>.html dumps, not guessed — no clicking
  // needed once the actual page markup is available. e2zstore is still an
  // unverified guess: its diagnostics dump so far only ever shows a
  // Cloudflare bot-check page, so there's no real markup to read yet.

  gamestheshop: {
    // Pulled from a real diagnostics/gamestheshop.html dump, not guessed —
    // this site has its own stable "ak-" prefixed class names.
    cardSelectors: ["div.ak-card"],
    titleSelectors: ["a.ak-card-title", ".ak-card-title"],
    priceSelectors: ["span.ak-card-priceVal", ".ak-card-price"],
    linkSelectors: ["a.ak-card-title", "a[href^='/product/']"],
    outOfStockSelectors: [":has-text('Out of Stock')", ":has-text('Sold Out')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "div.ak-card",
  },

  gamenation: {
    // Pulled from a real diagnostics/gamenation.html dump. Next.js storefront
    // with CSS-module class names (a per-build hash suffix, e.g. "-O644MW-",
    // so matched by substring rather than the exact class). The original
    // guess used lowercase "/products/" — the real links are "/Products/"
    // (capital P), and CSS attribute matching is case-sensitive by default,
    // which is why this silently matched nothing despite the page rendering
    // real listings the whole time.
    cardSelectors: ["a[class*='productCard' i]", "a[href*='/Products/' i]"],
    titleSelectors: ["h3[class*='productTitle' i]", "h3"],
    // The "current" price and the struck-through "old" price are separate,
    // similarly-named spans — same pitfall as Croma, pick the current one.
    priceSelectors: ["span[class*='currentPrice' i]", "span[class*='price' i]"],
    linkSelectors: ["a[class*='productCard' i]", "a[href*='/Products/' i]"],
    outOfStockSelectors: [":has-text('Out of Stock')", ":has-text('Sold Out')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "a[class*='productCard' i]",
    // Confirmed via diagnostics: the &page={p} URL param does nothing at
    // all — pages 1/2/3 came back byte-for-byte the same 20 products.
    // Pagination is a client-side button with no URL change; the real
    // "Next page" control is aria-labelled, unlike mcubegames below.
    nextPageSelectors: ["button[aria-label='Next page']"],
  },

  mcubegames: {
    // Pulled from a real diagnostics/mcubegames.html dump. Tailwind utility
    // classes only, no semantic per-component names, and the product link
    // wraps the image and the title in two separate <a> tags rather than one
    // card — "/product/" (singular) is also the real path, the original
    // guess used the plural "/products/".
    cardSelectors: ["div.bg-card", "a[href^='/product/']"],
    titleSelectors: ["p.line-clamp-2", "p"],
    priceSelectors: ["span.font-semibold", "span"],
    linkSelectors: ["a[href^='/product/']"],
    outOfStockSelectors: [":has-text('Out of Stock')", ":has-text('Sold Out')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "div.bg-card, a[href^='/product/']",
    // Confirmed via diagnostics: pages 1/2/3 were identical — the same
    // under-count (14 vs. a real catalogue of 42 pages) would happen to any
    // store built this way. The "Next" control has no text or aria-label,
    // just a chevron icon, so it's targeted by that icon's class instead —
    // .last() because the same icon could plausibly appear elsewhere (a
    // carousel, a dropdown) and pagination sits at the bottom of the page.
    // No page count here — it stops when clickNextPage can't find/click a
    // next control anymore, which tracks the real catalogue size (however
    // many pages that turns out to be) instead of a number that goes stale
    // the moment the catalogue grows.
    nextPageSelectors: ["button:has(svg.lucide-chevron-right)"],
  },

  e2zstore: {
    // Was guessed WooCommerce before probing found it blocks non-browser
    // requests outright (403) — the storefront theme is presumably still
    // WooCommerce's default markup, so start from the same "current price
    // wins over struck-through old price" pattern fixed for Croma/hgworld-
    // style themes: `ins` wraps the sale price, `del` the crossed-out one.
    cardSelectors: ["li.product", "div.product", "[data-product-id]"],
    titleSelectors: ["h2.woocommerce-loop-product__title", ".product-title", "h2 a", "h3 a"],
    priceSelectors: ["span.price ins .amount", "span.price .amount", ".price"],
    linkSelectors: ["a.woocommerce-LoopProduct-link", "a"],
    outOfStockSelectors: [".out-of-stock", ":has-text('Out of stock')"],
    defaultRegion: "IN",
    platformHint: "SWITCH",
    ready: "li.product, div.product",
  },
};

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

/**
 * A backstop, not a target — every store stops paging on its own real
 * signal (an empty page, or no next control left to click), whatever page
 * count that turns out to be. This exists only to bound a genuinely broken
 * loop, so it's set generously high and shared by every store rather than
 * tuned per store to whatever page count happened to be true on the day it
 * was checked.
 */
const MAX_PAGES_SAFETY = 300;

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
    const profile = effectiveProfile(store.id);
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
        // Fresh per search term (not shared across templates) — two search
        // terms legitimately overlapping in their early results shouldn't
        // look like "this term ran dry" the moment the second one starts.
        const seenSkus = new Set<string>();
        let staleStreak = 0;

        // No per-store page count — the loop below stops itself the real
        // way. MAX_PAGES_SAFETY is purely a last-resort guard against a
        // genuinely broken loop that never produces either stopping signal;
        // it should never be the thing that actually ends a real run.
        for (let p = 1; p <= MAX_PAGES_SAFETY; p++) {
          try {
            let rows: Extracted[];
            let method: string;

            if (p > 1 && profile.nextPageSelectors?.length) {
              // No URL to go to — this store's pagination only exists
              // behind a client-side button click with no navigation at
              // all, confirmed by page 1/2/3 coming back byte-identical
              // when driven by a URL parameter instead.
              const clicked = await clickNextPage(page, profile.nextPageSelectors);
              if (!clicked) break; // reached the last page
              await page.waitForTimeout(800);
              ({ rows, method } = await extract(page, store, profile));
              if (rows.length === 0) await dump(page, `${store.id}-p${p}`);
            } else {
              const url = template.replace("{p}", String(p));
              ({ rows, method } = await scrapePage(page, store, profile, url, p));
            }

            methods.add(method);
            let newOnPage = 0;
            for (const row of rows) {
              const l = toListing(store, profile, row);
              if (!l) continue;
              listings.push(l);
              if (!seenSkus.has(l.sku)) {
                seenSkus.add(l.sku);
                newOnPage++;
              }
            }

            // Visible progress instead of silence for however many minutes
            // a large catalogue takes — this is what "stuck" actually looks
            // like from outside otherwise, working or not.
            console.log(`  ${store.id}: page ${p} — ${listings.length} listings so far`);

            if (rows.length === 0) break; // a genuinely empty page — unambiguous

            // Some sites never return a clean empty page past the real last
            // one — they keep showing "related"/suggested items instead, so
            // rows.length alone never reaches 0 (this is why Amazon/Flipkart
            // ran for the full deadline instead of stopping). Tracking new
            // *listings* — after classification and dedup, not raw rows —
            // catches that: once a page contributes nothing not already
            // seen, twice in a row, there's nothing left worth paying more
            // requests to find. Twice, not once, so a single page that
            // happens to be all duplicates doesn't end a run that still had
            // real pages ahead of it.
            staleStreak = newOnPage === 0 ? staleStreak + 1 : 0;
            if (staleStreak >= 2) break;
          } catch (e) {
            problems.push(`p${p}: ${e instanceof Error ? e.message : String(e)}`);
          }
          // Was 2.5-5s, tuned for tiny independent shops where that gap is
          // free. A real 40+ page category listing pays that cost on every
          // page — for a headless browser session on a major site (not a
          // raw HTTP hammering loop), a shorter, still-real gap is enough
          // courtesy without being the reason a large, correctly-scoped
          // catalogue can't finish inside its own time budget.
          await page.waitForTimeout(800 + Math.random() * 800);
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

/** Tries each candidate, biased toward the last match — pagination controls
 * sit at the end of a results grid, and the same icon-only button could
 * plausibly exist elsewhere on the page (a carousel, a dropdown). Returns
 * false on a disabled button (the real "no more pages" signal for this
 * kind of control) or when nothing matches at all. */
async function clickNextPage(page: Page, selectors: readonly string[]): Promise<boolean> {
  for (const sel of selectors) {
    const locator = page.locator(sel).last();
    if ((await locator.count().catch(() => 0)) === 0) continue;
    if (await locator.isDisabled().catch(() => false)) return false;
    try {
      await locator.click({ timeout: 5000 });
      return true;
    } catch {
      continue;
    }
  }
  return false;
}

async function scrapePage(
  page: Page,
  store: StoreConfig,
  profile: StoreProfile,
  url: string,
  pageNum: number,
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

  const result = await extract(page, store, profile);

  // Only on a genuine zero-row failure — dumping every page on every run
  // regardless of outcome (a brief experiment) meant a full-page screenshot
  // on every successful page too, which is real overhead for no benefit
  // once a store is actually working. A wrong price/title on an otherwise
  // successful page still won't leave a diagnostic file; that needs a
  // targeted look (inspect.ts, or ask for a fresh dump) rather than an
  // always-on cost paid by every store on every run.
  if (result.rows.length === 0) {
    const suffix = pageNum > 1 ? `-p${pageNum}` : "";
    await dump(page, `${store.id}${suffix}`);
  }

  return result;
}

async function extract(page: Page, store: StoreConfig, profile: StoreProfile): Promise<{ rows: Extracted[]; method: string }> {
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
  return { rows, method: rows.length > 0 ? "selectors" : "none" };
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
          // `:has-text('...')` is Playwright locator syntax, not real CSS —
          // native querySelector() throws on it (caught below, silently
          // returning false), which is why "in stock only" never actually
          // removed anything: every out-of-stock check quietly failed.
          // Emulated here as a plain substring match against the card's own
          // text instead, so it isn't required to be real CSS.
          oos: (cfg.outOfStockSelectors ?? []).some((s) => {
            const textMatch = /^:has-text\((['"])(.+)\1\)$/.exec(s);
            if (textMatch) return (n.textContent ?? "").includes(textMatch[2] ?? "");
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
    await page.screenshot({ path: `diagnostics/${storeId}.png`, fullPage: true });
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
