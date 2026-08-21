/**
 * The one-shot entry point used by the launcher and the compiled exe.
 *
 * Collects, then serves the dashboard, then opens a browser. Failures during
 * collection are deliberately non-fatal: stale data on screen beats no screen,
 * and the collector strip at the top of the dashboard shows exactly which
 * stores fell over.
 */
import { collect } from "./cli/collect.ts";

const skipCollect = process.argv.includes("--no-collect");

if (!skipCollect) {
  try {
    await collect();
  } catch (e) {
    console.error(`Collection failed: ${e instanceof Error ? e.message : String(e)}`);
    console.error("Opening the dashboard against existing data.\n");
  }
}

// Importing here rather than at the top so the server only binds once the
// collection is finished.
await import("./web/server.ts");

const port = process.env["PORT"] ?? "4173";
const url = `http://localhost:${port}`;

// Best-effort browser open; the URL is printed regardless.
const opener =
  process.platform === "win32" ? ["cmd", "/c", "start", "", url]
  : process.platform === "darwin" ? ["open", url]
  : ["xdg-open", url];

try {
  Bun.spawn(opener, { stdout: "ignore", stderr: "ignore" });
} catch {
  // Fine — the user can click the printed link.
}
