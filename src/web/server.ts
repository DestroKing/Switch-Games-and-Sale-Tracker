import { getDb } from "../core/db.ts";

/**
 * A local, read-only dashboard. It binds to 127.0.0.1 only — this reads a
 * database of shop prices, but there is no reason for it to be reachable from
 * anywhere but this machine.
 */
const PORT = Number(process.env["PORT"] ?? 4173);

interface HealthRow {
  store_id: string;
  name: string;
  status: string;
  listings_found: number;
  duration_ms: number;
  detail: string | null;
  tier: number;
}

interface MoverRow {
  id: number;
  raw_title: string;
  url: string;
  region: string;
  store: string;
  currency: string;
  now_price: number;
  prev_price: number;
  in_stock: number;
  captured_at: string;
}

function health() {
  const db = getDb();
  const run = db
    .query<{ id: number; started_at: string; finished_at: string | null }, []>(
      `SELECT id, started_at, finished_at FROM run ORDER BY id DESC LIMIT 1`,
    )
    .get();

  if (!run) return { run: null, stores: [] };

  const stores = db
    .query<HealthRow, [number]>(
      `SELECT rs.store_id, s.name, s.tier, rs.status, rs.listings_found, rs.duration_ms, rs.detail
       FROM run_store rs JOIN store s ON s.id = rs.store_id
       WHERE rs.run_id = ?
       ORDER BY s.tier, rs.listings_found DESC`,
    )
    .all(run.id);

  return { run, stores };
}

/**
 * Price changes since the previous observation of the same listing.
 *
 * The `fxSuspect` flag is the synchronised-move check the schema was built to
 * support: if a large number of listings in the same currency all moved by the
 * same ratio, that is the rupee moving, not the shops. Flagging it here keeps
 * a currency wobble from reading as a catalogue-wide sale.
 */
function movers(limit = 60) {
  const rows = getDb()
    .query<MoverRow, []>(
      `WITH ranked AS (
         SELECT listing_id, inr_price, native_currency, in_stock, captured_at,
                ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY captured_at DESC) AS rn
         FROM price_point
       )
       SELECT l.id, l.raw_title, l.url, l.region, s.name AS store,
              cur.native_currency AS currency,
              cur.inr_price AS now_price, prev.inr_price AS prev_price,
              cur.in_stock, cur.captured_at
       FROM ranked cur
       JOIN ranked prev ON prev.listing_id = cur.listing_id AND prev.rn = 2
       JOIN listing l ON l.id = cur.listing_id
       JOIN store  s ON s.id = l.store_id
       WHERE cur.rn = 1 AND cur.inr_price <> prev.inr_price`,
    )
    .all();

  // Cluster by rounded percentage move within a currency.
  const clusters = new Map<string, number>();
  for (const r of rows) {
    const pct = ((r.now_price - r.prev_price) / r.prev_price) * 100;
    const key = `${r.currency}:${pct.toFixed(1)}`;
    clusters.set(key, (clusters.get(key) ?? 0) + 1);
  }

  const enriched = rows.map((r) => {
    const pct = ((r.now_price - r.prev_price) / r.prev_price) * 100;
    const key = `${r.currency}:${pct.toFixed(1)}`;
    return {
      ...r,
      pct,
      inStock: r.in_stock === 1,
      fxSuspect: (clusters.get(key) ?? 0) >= 8 && r.currency !== "INR",
    };
  });

  enriched.sort((a, b) => a.pct - b.pct);
  return enriched.slice(0, limit);
}

/**
 * Sorting and filtering happen in SQL, not in the page.
 *
 * The tempting shortcut is to ship 200 rows and let the browser sort them, but
 * then "cheapest first" means cheapest of whichever 200 arrived — which is a
 * wrong answer that looks like a right one. Filter and sort against the whole
 * table, then paginate.
 */
const SORT_COLUMNS = {
  price: "latest.inr_price",
  title: "l.raw_title",
  store: "s.name",
  seen: "latest.captured_at",
} as const;

type SortKey = keyof typeof SORT_COLUMNS;

interface ListingQuery {
  q: string;
  platform: string;
  region: string;
  store: string;
  inStockOnly: boolean;
  sort: SortKey;
  dir: "asc" | "desc";
  limit: number;
  offset: number;
}

function parseQuery(p: URLSearchParams): ListingQuery {
  const sort = p.get("sort");
  const dir = p.get("dir");
  return {
    q: p.get("q") ?? "",
    platform: p.get("platform") ?? "",
    region: p.get("region") ?? "",
    store: p.get("store") ?? "",
    inStockOnly: p.get("inStock") === "1",
    // Whitelisted rather than interpolated — these land in SQL text.
    sort: sort && sort in SORT_COLUMNS ? (sort as SortKey) : "price",
    dir: dir === "desc" ? "desc" : "asc",
    limit: Math.min(Number(p.get("limit")) || 100, 500),
    offset: Math.max(Number(p.get("offset")) || 0, 0),
  };
}

function listings(opt: ListingQuery) {
  const where: string[] = [];
  const params: (string | number)[] = [];

  if (opt.q) {
    where.push("l.raw_title LIKE ?");
    params.push(`%${opt.q.replace(/[%_]/g, "")}%`);
  }
  if (opt.platform) {
    where.push("l.platform = ?");
    params.push(opt.platform);
  }
  if (opt.region) {
    where.push("l.region = ?");
    params.push(opt.region);
  }
  if (opt.store) {
    where.push("l.store_id = ?");
    params.push(opt.store);
  }
  if (opt.inStockOnly) {
    where.push("latest.in_stock = 1");
  }

  const clause = where.length ? `WHERE ${where.join(" AND ")}` : "";
  const base = `
    WITH latest AS (
      SELECT listing_id, inr_price, native_price, native_currency, in_stock, captured_at,
             ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY captured_at DESC) AS rn
      FROM price_point
    )
    FROM listing l
    JOIN store s ON s.id = l.store_id
    JOIN latest ON latest.listing_id = l.id AND latest.rn = 1
    ${clause}`;

  const db = getDb();
  const total =
    db.query<{ n: number }, typeof params>(`SELECT COUNT(*) AS n ${base}`).get(...params)?.n ?? 0;

  const rows = db
    .query(
      `SELECT l.id, l.raw_title, l.url, l.region, l.platform, s.name AS store,
              latest.inr_price, latest.native_price, latest.native_currency,
              latest.in_stock, latest.captured_at
       ${base}
       ORDER BY ${SORT_COLUMNS[opt.sort]} ${opt.dir.toUpperCase()}, l.id ASC
       LIMIT ? OFFSET ?`,
    )
    .all(...params, opt.limit, opt.offset);

  return { total, rows, offset: opt.offset, limit: opt.limit };
}

/** Populates the filter dropdowns from what's actually in the database. */
function facets() {
  const db = getDb();
  return {
    stores: db
      .query(
        `SELECT s.id, s.name, COUNT(l.id) AS n
         FROM store s JOIN listing l ON l.store_id = s.id
         GROUP BY s.id ORDER BY s.name`,
      )
      .all(),
    platforms: db
      .query(`SELECT platform, COUNT(*) AS n FROM listing GROUP BY platform ORDER BY n DESC`)
      .all(),
    regions: db
      .query(`SELECT region, COUNT(*) AS n FROM listing GROUP BY region ORDER BY n DESC`)
      .all(),
  };
}

function history(listingId: number) {
  return getDb()
    .query(
      `SELECT captured_at, inr_price, native_price, native_currency, in_stock, fx_rate_date
       FROM price_point WHERE listing_id = ? ORDER BY captured_at ASC`,
    )
    .all(listingId);
}

function summary() {
  const db = getDb();
  return db
    .query<{ listings: number; stores: number; points: number; unmatched: number }, []>(
      `SELECT
         (SELECT COUNT(*) FROM listing) AS listings,
         (SELECT COUNT(DISTINCT store_id) FROM listing) AS stores,
         (SELECT COUNT(*) FROM price_point) AS points,
         (SELECT COUNT(*) FROM listing WHERE game_id IS NULL) AS unmatched`,
    )
    .get();
}

const html = await Bun.file(new URL("./index.html", import.meta.url)).text();

const server = Bun.serve({
  port: PORT,
  hostname: "127.0.0.1",
  fetch(req) {
    const url = new URL(req.url);
    const json = (data: unknown) =>
      new Response(JSON.stringify(data), { headers: { "content-type": "application/json" } });

    try {
      switch (url.pathname) {
        case "/":
          return new Response(html, { headers: { "content-type": "text/html; charset=utf-8" } });
        case "/api/summary":
          return json(summary());
        case "/api/health":
          return json(health());
        case "/api/movers":
          return json(movers());
        case "/api/listings":
          return json(listings(parseQuery(url.searchParams)));
        case "/api/facets":
          return json(facets());
        case "/api/history":
          return json(history(Number(url.searchParams.get("id"))));
        default:
          return new Response("Not found", { status: 404 });
      }
    } catch (e) {
      return json({ error: e instanceof Error ? e.message : String(e) });
    }
  },
});

console.log(`\n  Dashboard running at http://localhost:${server.port}`);
console.log(`  Press Ctrl+C to stop.\n`);
