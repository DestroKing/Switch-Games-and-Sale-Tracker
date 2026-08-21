import { Database } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

const DB_PATH = process.env["TRACKER_DB"] ?? "data/tracker.db";

/**
 * Schema notes, since a few columns exist for reasons that are not obvious:
 *
 * - price_point stores native_price AND inr_price, plus the fx_rate_date used
 *   to derive the latter. Keeping the rate alongside the price is what makes a
 *   synchronised-move check possible after the fact.
 * - listing.game_id is nullable on purpose. Collect first, match later.
 * - run_store is the health table. A store that silently returns zero rows is
 *   the failure mode that quietly rots a tracker, so absence gets recorded as
 *   loudly as an exception does.
 */
const SCHEMA = `
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS store (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  base_url    TEXT NOT NULL,
  kind        TEXT NOT NULL,
  currency    TEXT NOT NULL,
  tier        INTEGER NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS game (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_title TEXT NOT NULL,
  platform        TEXT NOT NULL,
  region          TEXT NOT NULL,
  UNIQUE (canonical_title, platform, region)
);

CREATE TABLE IF NOT EXISTS listing (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id    TEXT NOT NULL REFERENCES store(id),
  sku         TEXT NOT NULL,
  game_id     INTEGER REFERENCES game(id),
  url         TEXT NOT NULL,
  raw_title   TEXT NOT NULL,
  platform    TEXT NOT NULL,
  region      TEXT NOT NULL,
  condition   TEXT NOT NULL DEFAULT 'NEW',
  image_url   TEXT,
  first_seen  TEXT NOT NULL,
  last_seen   TEXT NOT NULL,
  UNIQUE (store_id, sku)
);

CREATE INDEX IF NOT EXISTS idx_listing_game ON listing(game_id);
CREATE INDEX IF NOT EXISTS idx_listing_unmatched ON listing(game_id) WHERE game_id IS NULL;

CREATE TABLE IF NOT EXISTS fx_rate (
  base        TEXT NOT NULL,
  quote       TEXT NOT NULL,
  rate        REAL NOT NULL,
  rate_date   TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY (base, quote, rate_date)
);

CREATE TABLE IF NOT EXISTS price_point (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id      INTEGER NOT NULL REFERENCES listing(id),
  run_id          INTEGER NOT NULL REFERENCES run(id),
  captured_at     TEXT NOT NULL,
  native_currency TEXT NOT NULL,
  native_price    REAL NOT NULL,
  inr_price       REAL NOT NULL,
  fx_rate_date    TEXT,
  in_stock        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pp_listing_time ON price_point(listing_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_pp_run ON price_point(run_id);

CREATE TABLE IF NOT EXISTS run (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS run_store (
  run_id         INTEGER NOT NULL REFERENCES run(id),
  store_id       TEXT NOT NULL REFERENCES store(id),
  status         TEXT NOT NULL,
  listings_found INTEGER NOT NULL DEFAULT 0,
  duration_ms    INTEGER NOT NULL DEFAULT 0,
  detail         TEXT,
  PRIMARY KEY (run_id, store_id)
);
`;

let db: Database | undefined;

/**
 * `CREATE TABLE IF NOT EXISTS` only ever applies to a table that doesn't
 * exist yet — a database file from before the `condition` column existed
 * keeps missing it forever otherwise. Guarded by PRAGMA table_info rather
 * than a bare ALTER TABLE, since re-running it on a database that already
 * has the column would throw "duplicate column name".
 */
function migrate(handle: Database): void {
  const cols = handle.query<{ name: string }, []>(`PRAGMA table_info(listing)`).all();
  if (!cols.some((c) => c.name === "condition")) {
    handle.exec(`ALTER TABLE listing ADD COLUMN condition TEXT NOT NULL DEFAULT 'NEW'`);
  }
}

export function getDb(): Database {
  if (db) return db;
  mkdirSync(dirname(DB_PATH), { recursive: true });
  db = new Database(DB_PATH, { create: true });
  db.exec(SCHEMA);
  migrate(db);
  return db;
}

export function nowIso(): string {
  return new Date().toISOString();
}
