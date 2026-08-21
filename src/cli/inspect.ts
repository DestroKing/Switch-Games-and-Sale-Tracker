import { chromium } from "playwright";
import { activeStores } from "../config/overrides.ts";
import { addProfileSelector } from "../adapters/browser.ts";
const STORES = activeStores();

/**
 * Opens a hard store's search page and guides you through building its
 * PROFILES entry by clicking, with zero manual editing afterward.
 *
 *   bun run src/cli/inspect.ts playasia
 *
 * Alt+click the card, then its title, price and link, in that order — each
 * click is scored automatically (a card selector must repeat across the
 * page; title/price/link are scored by how many sampled cards actually
 * contain them) and the winner is written straight to profiles.local.json,
 * which browser.ts merges over its built-in guesses at fetch time. Nothing
 * needs pasting into browser.ts by hand.
 *
 * Playwright Inspector's own "pick locator" isn't used here on purpose — it
 * produces `getByRole(...)`-style locator code for test scripts, not plain
 * CSS, and there's no way to read what you picked there back into this
 * script. Plain clicks (no Alt) still behave normally, so cookie banners and
 * "continue" buttons can still be dismissed.
 *
 * Clicks are resolved via `elementsFromPoint`, not `event.target` — a lot of
 * product cards wrap the whole tile in one invisible/absolute-positioned
 * overlay link for click-to-navigate, so a plain click always hits that
 * overlay, never the title/price text visually underneath it. Reading the
 * whole element stack at the click point recovers the real element even
 * when a click alone couldn't reach it.
 */
const id = process.argv[2];
const store = STORES.find((s) => s.id === id);

if (!store?.searchUrls?.[0]) {
  console.log("usage: bun run src/cli/inspect.ts <storeId>");
  console.log("browser stores: " + STORES.filter((s) => s.kind === "BROWSER").map((s) => s.id).join(", "));
  process.exit(1);
}

type Field = "cardSelectors" | "titleSelectors" | "priceSelectors" | "linkSelectors";

const STEPS: { field: Field; prompt: string }[] = [
  { field: "cardSelectors", prompt: "Alt+click the WHOLE PRODUCT CARD — the box around one listing." },
  { field: "titleSelectors", prompt: "Alt+click that card's TITLE text." },
  { field: "priceSelectors", prompt: "Alt+click that card's PRICE text." },
  { field: "linkSelectors", prompt: "Alt+click that card's LINK (often the title itself, or the image)." },
];

interface Candidate {
  css: string;
  matches: number;
}

interface Pick {
  tag: string;
  text: string;
  candidates: Candidate[];
}

let stepIndex = 0;
let cardSelector: string | undefined;

function announce(): void {
  const step = STEPS[stepIndex];
  if (step) {
    console.log(`\n${stepIndex + 1}/4 — ${step.prompt}`);
  } else {
    console.log(
      `\nAll four saved to profiles.local.json for "${store.id}". Run "bun run collect" to try it, ` +
        `or keep Alt+clicking — another round starts over from the card, useful for a second example ` +
        `if some listings look different (e.g. one on sale).`,
    );
    stepIndex = 0; // let another round of examples add fallback candidates
  }
}

const browser = await chromium.launch({ headless: false });
const page = await browser.newPage({ locale: "en-IN", timezoneId: "Asia/Kolkata" });

async function coverageWithinCards(css: string): Promise<number> {
  if (!cardSelector) return 0;
  return page.evaluate(
    ({ cardSel, css }) => {
      const cards = Array.from(document.querySelectorAll(cardSel)).slice(0, 8);
      if (cards.length === 0) return 0;
      let hits = 0;
      for (const card of cards) {
        try {
          if (card.querySelector(css)) hits++;
        } catch {
          // invalid selector in this DOM context — treat as a miss
        }
      }
      return hits / cards.length;
    },
    { cardSel: cardSelector, css },
  );
}

await page.exposeFunction("__reportPick", async (pick: Pick) => {
  const step = STEPS[stepIndex];
  if (!step) return;

  if (step.field === "cardSelectors") {
    // A card selector has to repeat — candidates arrive ordered stable-first
    // (id, then value-specific attribute, then bare attribute, then class,
    // then tag), so the first one that repeats a sane number of times wins.
    const winner = pick.candidates.find((c) => c.matches >= 2 && c.matches <= 500);
    if (!winner) {
      const best = pick.candidates[0]?.matches ?? 0;
      console.log(`   ✗ nothing there repeats across the page (best match count: ${best}) — try the tile's outer box instead.`);
      return;
    }
    cardSelector = winner.css;
    addProfileSelector(store.id, "cardSelectors", winner.css);
    console.log(`   ✓ card: ${winner.css}  (${winner.matches} listings on this page) — saved.`);
  } else {
    let best: { css: string; coverage: number } | undefined;
    for (const c of pick.candidates) {
      const coverage = await coverageWithinCards(c.css);
      if (!best || coverage > best.coverage) best = { css: c.css, coverage };
    }
    if (!best || best.coverage === 0) {
      console.log(`   ✗ that doesn't appear inside the saved card selector — click something inside one of the highlighted tiles.`);
      return;
    }
    addProfileSelector(store.id, step.field, best.css);
    console.log(`   ✓ ${step.field}: ${best.css}  (found in ${Math.round(best.coverage * 100)}% of sampled cards) — saved.`);
  }

  stepIndex++;
  announce();
});

// Runs in the browser, not Node — re-injected on every navigation.
await page.addInitScript(() => {
  let hovered: HTMLElement | null = null;

  function candidatesFor(el: Element): { css: string; matches: number }[] {
    const tag = el.tagName.toLowerCase();
    const tried = new Map<string, { css: string; matches: number }>();

    const add = (css: string) => {
      if (tried.has(css)) return;
      try {
        tried.set(css, { css, matches: document.querySelectorAll(css).length });
      } catch {
        // not valid CSS in this context — skip
      }
    };

    if (el.id) add(`#${CSS.escape(el.id)}`);
    for (const attr of ["data-testid", "data-cy", "data-component-type", "data-id", "data-product-id", "data-asin", "data-sku", "data-pid"]) {
      const v = el.getAttribute(attr);
      if (v !== null) {
        add(`${tag}[${attr}='${CSS.escape(v)}']`);
        add(`[${attr}]`);
      }
    }
    const classes = [...el.classList].map((c) => CSS.escape(c));
    if (classes.length) add(`${tag}.${classes.join(".")}`);
    add(tag);
    return [...tried.values()];
  }

  document.addEventListener(
    "mouseover",
    (e) => {
      if (hovered) hovered.style.outline = "";
      hovered = e.target as HTMLElement;
      hovered.style.outline = "2px solid #ff2d78";
    },
    true,
  );

  document.addEventListener(
    "click",
    (e) => {
      if (!e.altKey) return; // plain clicks still dismiss banners, navigate, etc.
      e.preventDefault();
      e.stopPropagation();

      // A card's title/price often sit UNDER a full-tile overlay <a> used for
      // click-to-navigate — e.target on a click there is always that overlay,
      // never the text visually underneath it. elementsFromPoint returns the
      // whole stack at that point, front-to-back, so the real title/price
      // element is still in there even when it isn't what a plain click would
      // have hit.
      const stack = document
        .elementsFromPoint(e.clientX, e.clientY)
        .filter((el) => el.tagName !== "HTML" && el.tagName !== "BODY")
        .slice(0, 8);
      const top = stack[0] ?? (e.target as Element);

      const seen = new Set<string>();
      const candidates: { css: string; matches: number }[] = [];
      for (const el of stack) {
        for (const c of candidatesFor(el)) {
          if (seen.has(c.css)) continue;
          seen.add(c.css);
          candidates.push(c);
        }
      }

      (window as unknown as { __reportPick: (p: unknown) => void }).__reportPick({
        tag: top.tagName.toLowerCase(),
        text: (top.textContent ?? "").trim().replace(/\s+/g, " "),
        candidates,
      });
    },
    true,
  );
});

await page.goto(store.searchUrls[0].replace("{p}", "1"));

console.log(`\nOpened ${store.name}.`);
announce();
console.log("\nPlain clicks still behave normally (dismiss popups, scroll, etc). Close the browser when done.\n");

await page.waitForEvent("close", { timeout: 0 }).catch(() => undefined);
await browser.close();
