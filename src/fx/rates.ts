import { getDb, nowIso } from "../core/db.ts";
import { getJson } from "../core/http.ts";
import type { FxRate } from "../core/types.ts";

/**
 * Frankfurter serves ECB reference rates, needs no key, and publishes on
 * working days only. Two consequences we handle rather than paper over:
 *
 *  - A weekend fetch returns Friday's rate. That is correct, not stale, so we
 *    store it under its own publication date and reuse it.
 *  - The stored rate_date on each price_point is what later lets the alert
 *    engine ask "did four hundred prices move by the same ratio on the same
 *    day?" — the question that separates an FX reset from a sale.
 */
const ENDPOINT = "https://api.frankfurter.app";

interface FrankfurterResponse {
  base: string;
  date: string;
  rates: Record<string, number>;
}

export async function refreshRates(bases: readonly string[] = ["USD"]): Promise<FxRate[]> {
  const db = getDb();
  const insert = db.prepare(
    `INSERT OR REPLACE INTO fx_rate (base, quote, rate, rate_date, fetched_at)
     VALUES (?, ?, ?, ?, ?)`,
  );

  const out: FxRate[] = [];
  for (const base of bases) {
    if (base === "INR") continue;
    const data = await getJson<FrankfurterResponse>(`${ENDPOINT}/latest?from=${base}&to=INR`);
    const rate = data?.rates?.["INR"];
    if (data === undefined || rate === undefined) {
      console.warn(`  fx: could not fetch ${base}->INR`);
      continue;
    }
    insert.run(base, "INR", rate, data.date, nowIso());
    out.push({ base, quote: "INR", rate, rateDate: data.date });
  }
  return out;
}

/** Most recent stored rate for a currency, or 1 for INR itself. */
export function latestRate(base: string): FxRate | undefined {
  if (base === "INR") {
    return { base: "INR", quote: "INR", rate: 1, rateDate: nowIso().slice(0, 10) };
  }
  const row = getDb()
    .query<{ rate: number; rate_date: string }, [string]>(
      `SELECT rate, rate_date FROM fx_rate
       WHERE base = ? AND quote = 'INR'
       ORDER BY rate_date DESC LIMIT 1`,
    )
    .get(base);

  return row ? { base, quote: "INR", rate: row.rate, rateDate: row.rate_date } : undefined;
}

export function toInr(nativePrice: number, currency: string): { inr: number; rateDate?: string } {
  const fx = latestRate(currency);
  if (!fx) return { inr: nativePrice };
  return { inr: Math.round(nativePrice * fx.rate * 100) / 100, rateDate: fx.rateDate };
}
