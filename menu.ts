import { existsSync } from "node:fs";
import { activeStores, hasBeenProbed } from "./config/overrides.ts";
import { collect } from "./cli/collect.ts";
import { probe, resetOverrides } from "./cli/probe.ts";
import { refreshRates } from "./fx/rates.ts";
import { getDb } from "./core/db.ts";

/**
 * One screen instead of six commands.
 *
 * The menu reads the database before drawing itself, so the recommended action
 * reflects what has actually happened rather than a fixed tutorial order. The
 * common mistake this prevents is collecting before probing, which produces a
 * screen of failures that look like broken code and are really just a store
 * list that was never corrected.
 */

const DB = process.env["TRACKER_DB"] ?? "data/tracker.db";

interface State {
  probed: boolean;
  hasDb: boolean;
  lastRun?: string;
  ok: number;
  failed: number;
  listings: number;
  runs: number;
}

function readState(): State {
  const base: State = { probed: hasBeenProbed(), hasDb: existsSync(DB), ok: 0, failed: 0, listings: 0, runs: 0 };
  if (!base.hasDb) return base;

  try {
    const db = getDb();
    const run = db.query<{ id: number; started_at: string }, []>(
      `SELECT id, started_at FROM run ORDER BY id DESC LIMIT 1`,
    ).get();
    if (!run) return base;

    const counts = db.query<{ ok: number; failed: number }, [number]>(
      `SELECT SUM(status IN ('ok','partial')) AS ok, SUM(status NOT IN ('ok','partial')) AS failed
       FROM run_store WHERE run_id = ?`,
    ).get(run.id);

    const listings = db.query<{ n: number }, []>(`SELECT COUNT(*) AS n FROM listing`).get()?.n ?? 0;
    const runs = db.query<{ n: number }, []>(`SELECT COUNT(*) AS n FROM run`).get()?.n ?? 0;

    return {
      ...base,
      lastRun: run.started_at,
      ok: counts?.ok ?? 0,
      failed: counts?.failed ?? 0,
      listings,
      runs,
    };
  } catch {
    return base;
  }
}

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} days ago`;
}

function draw(s: State): string {
  console.clear();
  console.log("\n  SWITCH CARTRIDGE TRACKER");
  console.log("  " + "─".repeat(46));

  if (!s.hasDb || !s.lastRun) {
    console.log("  No prices collected yet.");
  } else {
    console.log(`  Last run ${ago(s.lastRun)} · ${s.ok} stores working, ${s.failed} not`);
    console.log(`  ${s.listings.toLocaleString("en-IN")} listings · ${s.runs} run${s.runs === 1 ? "" : "s"}`);
  }
  if (!s.probed) console.log("  Stores have not been checked yet.");

  // Recommend the next useful thing rather than always the same thing.
  const suggest = !s.probed ? "1" : !s.lastRun ? "2" : s.runs < 2 ? "2" : "3";

  console.log();
  console.log(`  1  Check stores        ${!s.probed ? "← start here" : "re-detect and fix the store list"}`);
  console.log(`  2  Collect prices      ${s.probed && !s.lastRun ? "← do this next" : s.runs === 1 ? "← run again to get price changes" : "fetch the latest prices"}`);
  console.log(`  3  Open dashboard      ${s.lastRun && s.runs >= 2 ? "← see what moved" : "browse what's collected"}`);
  console.log(`  4  Fix a broken store`);
  console.log(`  5  Update exchange rate`);
  console.log(`  6  Run twice daily automatically`);
  console.log(`  7  Reset store corrections`);
  console.log(`  0  Quit`);
  console.log();
  return suggest;
}

async function fixStore(): Promise<void> {
  const stores = activeStores().filter((s) => s.kind === "BROWSER");
  console.log("\n  Which store returned nothing?\n");
  stores.forEach((s, i) => {
    const dumped = existsSync(`diagnostics/${s.id}.html`);
    console.log(`  ${i + 1}  ${s.name}${dumped ? "   (diagnostics saved — this one failed)" : ""}`);
  });
  console.log("  0  Back\n");

  const pick = Number(prompt("  Number: ") ?? "0");
  const store = stores[pick - 1];
  if (!store) return;

  console.log(`\n  Opening ${store.name} in a real browser.`);
  console.log("  Click a product card, then its title, price and link.");
  console.log("  Add what you find to PROFILES in src/adapters/browser.ts —");
  console.log("  each field is a list, so add yours without removing the others.\n");

  const proc = Bun.spawn(["bun", "run", "src/cli/inspect.ts", store.id], {
    stdout: "inherit",
    stderr: "inherit",
  });
  await proc.exited;
}

async function schedule(): Promise<void> {
  if (process.platform !== "win32") {
    console.log("\n  On macOS or Linux, add this to `crontab -e`:\n");
    console.log(`  30 7,21 * * * cd ${process.cwd()} && bun run collect >> collect.log 2>&1\n`);
    return;
  }
  const proc = Bun.spawn(
    ["powershell", "-ExecutionPolicy", "Bypass", "-File", "schedule-task.ps1"],
    { stdout: "inherit", stderr: "inherit" },
  );
  await proc.exited;
}

async function dashboard(): Promise<void> {
  console.log("\n  Starting the dashboard. Close this window to stop it.\n");
  const proc = Bun.spawn(["bun", "run", "src/web/server.ts"], {
    stdout: "inherit",
    stderr: "inherit",
  });
  await Bun.sleep(1500);
  const url = "http://localhost:4173";
  const open =
    process.platform === "win32" ? ["cmd", "/c", "start", "", url]
    : process.platform === "darwin" ? ["open", url]
    : ["xdg-open", url];
  try {
    Bun.spawn(open, { stdout: "ignore", stderr: "ignore" });
  } catch { /* the URL is printed anyway */ }
  await proc.exited;
}

async function pause(): Promise<void> {
  prompt("\n  Press Enter to go back ");
}

async function main(): Promise<void> {
  for (;;) {
    const state = readState();
    const suggested = draw(state);

    const choice = (prompt(`  Choose [${suggested}]: `) ?? "").trim() || suggested;

    switch (choice) {
      case "1":
        await probe(true);
        await pause();
        break;
      case "2":
        await collect();
        await pause();
        break;
      case "3":
        await dashboard();
        break;
      case "4":
        await fixStore();
        await pause();
        break;
      case "5": {
        const rates = await refreshRates(["USD"]);
        for (const r of rates) console.log(`  ${r.base} to INR: ${r.rate} (ECB ${r.rateDate})`);
        if (rates.length === 0) console.log("  No non-rupee stores enabled — nothing to convert.");
        await pause();
        break;
      }
      case "6":
        await schedule();
        await pause();
        break;
      case "7":
        resetOverrides();
        console.log("\n  Store corrections cleared. Run 'Check stores' again.");
        await pause();
        break;
      case "0":
        console.log();
        return;
      default:
        break;
    }
  }
}

await main();
