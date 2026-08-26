import { chromium, type Browser, type Page } from "playwright";
import type { StoreConfig, ScrapedProduct } from "../core/types.ts";
import { classify, platformOf } from "../core/parse.ts";

interface StoreProfile {
  pageParam: string;
  selectors: {
    card: string;
    title: string;
    price: string;
    link: string;
    image?: string;
  };
}

export const PROFILES: Record<string, StoreProfile> = {
  amazon_in: {
    pageParam: "page",
    selectors: {
      card: "[data-component-type='s-search-result']",
      title: "h2 a span",
      price: ".a-price-whole",
      link: "h2 a.a-link-normal",
    },
  },
  flipkart: {
    pageParam: "page",
    selectors: {
      card: "div._7eIMF7",
      title: "a.WKTcLC",
      price: "div.Nx9bqj",
      link: "a.WKTcLC",
    },
  },
  gamestheshop: {
    pageParam: "page",
    selectors: {
      card: ".product-item-info, .product-layout",
      title: ".product-name a, .title a",
      price: ".price, .special-price",
      link: ".product-name a, .title a",
    },
  },
  gamenation: {
    pageParam: "page",
    selectors: {
      card: ".product-card, .col-item",
      title: ".product-title a, h4 a",
      price: ".price, .sale-price",
      link: ".product-title a, h4 a",
    },
  },
  mcubegames: {
    pageParam: "page",
    selectors: {
      card: ".product-card-wrapper, .grid-view-item",
      title: ".grid-view-item__title a, .product-title a",
      price: ".price-item--sale, .price",
      link: ".grid-view-item__title a, .product-title a",
    },
  },
  e2zstore: {
    pageParam: "page",
    selectors: {
      card: ".product-item,.product_item",
      title: ".woocommerce-loop-product__title,h2.woocommerce-loop-product__title",
      price: ".price .amount",
      link: ".woocommerce-LoopProduct-link",
    },
  },
  playasia: {
    pageParam: "page",
    selectors: {
      card: ".product-item, .search-item, .item",
      title: ".item-name a, .product-name a, a.title, h3 a",
      price: ".price-value, .item-price .amount, .product-price, .price",
      link: ".item-name a, .product-name a, a.title, h3 a",
    },
  },
};

export async function scrapeBrowserStore(
  store: StoreConfig,
  onProgress?: (msg: string) => void
): Promise<ScrapedProduct[]> {
  const profile = PROFILES[store.id];
  if (!profile) {
    throw new Error(`No browser profile defined for store: ${store.id}`);
  }

  const browser: Browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  });
  const page: Page = await context.newPage();

  const products: ScrapedProduct[] = [];
  const searchUrls = store.searchUrls ?? [`${store.baseUrl}?{pageParam}={p}`];

  try {
    for (const baseUrlTemplate of searchUrls) {
      let pageNum = 1;
      let hasMore = true;

      while (hasMore && pageNum <= 50) {
        const targetUrl = baseUrlTemplate
          .replace("{pageParam}", profile.pageParam)
          .replace("{p}", pageNum.toString());

        onProgress?.(`[${store.id}] Scraping page ${pageNum}: ${targetUrl}`);

        await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
        
        const cards = await page.locator(profile.selectors.card).all();
        if (cards.length === 0) {
          hasMore = false;
          break;
        }

        let pageProductsFound = 0;

        for (const card of cards) {
          try {
            const titleEl = card.locator(profile.selectors.title).first();
            const priceEl = card.locator(profile.selectors.price).first();
            const linkEl = card.locator(profile.selectors.link).first();

            const title = (await titleEl.textContent())?.trim() ?? "";
            const rawPrice = (await priceEl.textContent())?.trim() ?? "";
            const href = (await linkEl.getAttribute("href")) ?? "";

            if (!title) continue;

            const link = href.startsWith("http") ? href : new URL(href, store.baseUrl).toString();
            
            // Clean currency strings and parse values safely
            const priceClean = parseFloat(rawPrice.replace(/[^0-9.]/g, "")) || 0;

            const platform = platformOf(title);
            const kind = classify(title, store.platformHint);

            products.push({
              storeId: store.id,
              title,
              price: priceClean,
              currency: store.currency,
              link,
              platform,
              kind,
            });

            pageProductsFound++;
          } catch {
            // Skip individual malformed item cards cleanly
          }
        }

        if (pageProductsFound === 0) {
          hasMore = false;
        } else {
          pageNum++;
        }
      }
    }
  } finally {
    await browser.close();
  }

  return products;
}