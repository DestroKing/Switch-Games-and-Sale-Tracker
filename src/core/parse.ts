import type { Platform, Region } from "./types.ts";

/* ------------------------------------------------------------------ prices */

/**
 * Indian storefronts write prices about six different ways: "₹4,499.00",
 * "Rs. 4499", "INR 4,499", "4.499,00". Returns undefined rather than 0 on
 * failure — zero is a real value we must not invent.
 */
export function parsePrice(raw: string | number | null | undefined): number | undefined {
  if (raw === null || raw === undefined) return undefined;
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : undefined;

  // Strike-through "was" prices often sit next to the real one. Take the first
  // currency-marked number and let the caller decide if it looks wrong.
  const cleaned = raw.replace(/[^\d.,]/g, "").trim();
  if (!cleaned) return undefined;

  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");

  // A comma with no decimal point anywhere in the string is always a
  // thousands separator on these sites — "₹3,599" is three thousand five
  // hundred ninety-nine, never 3.599. Treating it as a decimal point (the
  // previous rule: "whichever separator is last wins") silently produced a
  // price ~1000x too small for any whole-rupee price written without a
  // trailing ".00", which is the normal way to write one.
  const normalised =
    lastDot === -1
      ? cleaned.replace(/,/g, "")
      : lastComma > lastDot
        ? cleaned.replace(/\./g, "").replace(",", ".")
        : cleaned.replace(/,/g, "");

  const n = Number.parseFloat(normalised);
  return Number.isFinite(n) ? n : undefined;
}

/** Pull the first rupee figure out of a blob of card text. */
export function firstRupeePrice(text: string): number | undefined {
  const m = text.match(/(?:₹|Rs\.?|INR)\s*([\d.,]+)/i);
  return m?.[1] ? parsePrice(m[1]) : undefined;
}

/* ------------------------------------------------------- classification */

export type ProductKind = "GAME" | "HARDWARE" | "ACCESSORY" | "DIGITAL" | "SERVICE" | "UNKNOWN";

export interface Classification {
  readonly platform: Platform;
  readonly kind: ProductKind;
}

/**
 * Anything matching these is not a cartridge, however loudly it says "Switch".
 * Checked before the platform patterns, because "Nintendo Switch Console" and
 * "Nintendo Switch Pro Controller" both contain the console's name and would
 * otherwise sail straight through as games.
 */
const HARDWARE = [
  /\bconsole\b/i,
  /\b(oled|lite)\s*(model|console|edition)?\b/i,
  /\bjoy[\s-]?cons?\b/i,
  /\bpro\s*controller\b/i,
  /\bdock(ing)?\s*(station|set)?\b/i,
  /\bhandheld\b.*\bsystem\b/i,
];

const ACCESSORY = [
  /\b(carry(ing)?\s*)?case\b/i,
  /\b(screen\s*)?protector\b/i,
  /\btempered\s*glass\b/i,
  /\b(grip|stand|holder|mount|strap|skin|sticker|decal)\b/i,
  /\b(charg(er|ing)|cable|adapter|power\s*bank)\b/i,
  /\b(head(set|phone)s?|earbuds?|ear\s*phones?)\b/i,
  /\b(micro\s*)?sd\s*card\b/i,
  /\bmemory\s*card\b/i,
  /\bamiibo\b/i,
  /\bsteering\s*wheel\b/i,
  /\bthumb\s*(grip|stick)/i,
  /\b(t[- ]?shirt|hoodie|mug|keychain|poster|figure|plush)\b/i,
  /\bcontrollers?\b/i,
  /\bcooling\s*pads?\b/i,
];

const DIGITAL = [
  /\b(digital|download)\s*(code|version|key)\b/i,
  /\be[- ]?shop\b/i,
  /\bgift\s*card\b/i,
  /\bswitch\s*online\b/i,
  /\bmembership\b/i,
  /\bvoucher\b/i,
  /\bdlc\b/i,
  /\bseason\s*pass\b/i,
];

/**
 * A repair/mod/installation service, not a physical product — a listing like
 * "Nintendo OLED game loading service" names the console and would otherwise
 * sail through as a game, the same way HARDWARE/ACCESSORY items would if not
 * excluded first.
 */
const SERVICE = [
  /\b(repair|installation|loading|jailbreak|unlock(ing)?|mod(ding)?|chip(ping)?|flash(ing)?)\s*service\b/i,
  /\bgame\s*loading\s*service\b/i,
  /\b(console\s*)?repair\b/i,
];

const SWITCH2 = [/switch\s*2\b/i, /\bns2\b/i, /\bswitch\s*two\b/i, /\bnintendo\s*switch\s*2/i];

/**
 * Switch markers, loosest last. `\bNS\b` and `\bNSW\b` are genuinely used by
 * Indian importers in terse titles ("Hogwarts Legacy NSW"), which is exactly
 * the case that made stores look empty before.
 */
const SWITCH = [
  /\bnintendo\s*switch\b/i,
  /\bswitch\b/i,
  /\bnsw\b/i,
  /\bns\b/i,
  /\bnintendo\b/i,
];

/**
 * An explicit marker for a DIFFERENT console must beat `storeHint` — a store
 * hint means "assume Switch when the text says nothing about console," not
 * "assume Switch even when the text names a different one." Without this,
 * any store with `platformHint: "SWITCH"` that also happens to sell other
 * consoles (a general retailer, not a Switch-only shop) leaks every PS4/PS5/
 * Xbox title through as a false "Switch" match.
 */
const OTHER_CONSOLE = [
  /\bplay\s*station\s*[1-5]?\b/i,
  /\bps[1-5]\b/i,
  /\bps\s*vita\b/i,
  /\bxbox\b/i,
  /\bwii\s*u\b/i,
  /\bwii\b/i,
  /\b3ds\b/i,
  /\bnintendo\s*ds\b/i,
  /\bgame\s*boy\b/i,
  /\bgamecube\b/i,
  /\bsteam\s*key\b/i,
  /\b(pc|windows)\s*(game|version)\b/i,
];

/**
 * `context` should be everything the store gives: title, product type, tags,
 * categories, breadcrumbs. Passing only the title is what made terse-titled
 * stores report near-zero.
 *
 * `storeHint` lets a store or collection known to contain only Switch games
 * assert that, so "Hogwarts Legacy" in a "Switch Games" collection is kept
 * instead of dropped for not naming its console.
 */
export function classify(context: string, storeHint?: Platform): Classification {
  const text = context.replace(/\s+/g, " ");

  // Order matters. Exclusions first, or hardware wins on platform match.
  if (SERVICE.some((r) => r.test(text))) return { platform: platformOf(text, storeHint), kind: "SERVICE" };
  if (DIGITAL.some((r) => r.test(text))) return { platform: platformOf(text, storeHint), kind: "DIGITAL" };
  if (HARDWARE.some((r) => r.test(text))) return { platform: platformOf(text, storeHint), kind: "HARDWARE" };
  if (ACCESSORY.some((r) => r.test(text))) return { platform: platformOf(text, storeHint), kind: "ACCESSORY" };

  const platform = platformOf(text, storeHint);
  if (platform === "UNKNOWN") return { platform, kind: "UNKNOWN" };

  // Platform is known and nothing excluded it. Treat as a game — on a page of
  // Switch search results that is overwhelmingly what a leftover row is.
  return { platform, kind: "GAME" };
}

function platformOf(text: string, hint?: Platform): Platform {
  if (SWITCH2.some((r) => r.test(text))) return "SWITCH2";
  if (SWITCH.some((r) => r.test(text))) return "SWITCH";
  // Text names a different console outright. This must win over the store's
  // hint, or a multi-platform retailer with platformHint: "SWITCH" leaks
  // every PS4/Xbox/etc. title through as a false Switch match.
  if (OTHER_CONSOLE.some((r) => r.test(text))) return "UNKNOWN";
  // No console named at all. Trust the store's context if it has one — a
  // title pulled from a Switch-games collection is a Switch game.
  return hint ?? "UNKNOWN";
}

/** Convenience for callers that only want the platform. */
export function inferPlatform(context: string, hint?: Platform): Platform {
  return classify(context, hint).platform;
}

/**
 * Prices that make no sense for a cartridge. Not a hard reject — it flags rows
 * worth a look rather than silently dropping something real.
 */
export function priceLooksWrong(inr: number, kind: ProductKind): boolean {
  if (kind !== "GAME") return false;
  return inr < 299 || inr > 12_000;
}

/* ---------------------------------------------------------------- regions */

const REGION_RULES: ReadonlyArray<readonly [RegExp, Region]> = [
  [/\b(asia|asian)\b.*\b(chinese|chs|cht|zh)\b|\bchinese\s*sub/i, "ASIA_ZH"],
  [/\b(asia|asian)\b.*\b(english|eng|en)\b|\basia\s*english\b/i, "ASIA_EN"],
  [/\b(jpn?|japan|japanese|nts-j)\b/i, "JP"],
  [/\b(usa?|ntsc-u|north\s*america)\b/i, "US"],
  [/\b(eu|pal|europe|uk)\b/i, "EU"],
  [/\b(asia|asian)\b/i, "ASIA_EN"],
];

export function inferRegion(title: string, storeDefault: Region): Region {
  for (const [pattern, region] of REGION_RULES) {
    if (pattern.test(title)) return region;
  }
  return storeDefault;
}

/* ------------------------------------------------------------ title clean */

const NOISE = [
  /\bnintendo\s*switch\s*2\b/gi,
  /\bnintendo\s*switch\b/gi,
  /\bswitch\s*2\b/gi,
  /\bswitch\b/gi,
  /\b(nsw|ns2|ns)\b/gi,
  /\b(video\s*)?game(s)?\b/gi,
  /\b(cartridge|cart|physical|standard|edition)\b/gi,
  /\((asia|japan|us|eu|english|chinese)[^)]*\)/gi,
  /\[[^\]]*\]/g,
  /\b(pre[- ]?owned|used|new|sealed|import|brand\s*new)\b/gi,
  /\bfor\s+nintendo\b/gi,
];

/** Crude normalisation; the matcher's first pass. */
export function normaliseTitle(title: string): string {
  let s = title.toLowerCase();
  for (const r of NOISE) s = s.replace(r, " ");
  return s.replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}
