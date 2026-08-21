/**
 * A deliberately polite HTTP client.
 *
 * These are small shops. One concurrent request per host and a real delay
 * between them costs us nothing — the collector runs on a schedule, not in
 * front of a user — and it keeps us off anyone's block list.
 */

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

const MIN_GAP_MS = 1200;
const TIMEOUT_MS = 20_000;
const MAX_ATTEMPTS = 3;

/** host -> promise chain, so requests to one host queue behind each other. */
const hostQueues = new Map<string, Promise<unknown>>();
const lastHit = new Map<string, number>();

export interface HttpResult {
  readonly ok: boolean;
  readonly status: number;
  readonly body: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function throttle(host: string): Promise<void> {
  const last = lastHit.get(host) ?? 0;
  const wait = MIN_GAP_MS - (Date.now() - last);
  if (wait > 0) await sleep(wait);
  lastHit.set(host, Date.now());
}

async function once(url: string, headers: Record<string, string>): Promise<HttpResult> {
  const res = await fetch(url, {
    headers: { "user-agent": UA, "accept-language": "en-IN,en;q=0.9", ...headers },
    signal: AbortSignal.timeout(TIMEOUT_MS),
    redirect: "follow",
  });
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export function get(url: string, headers: Record<string, string> = {}): Promise<HttpResult> {
  const host = new URL(url).host;
  const prior = hostQueues.get(host) ?? Promise.resolve();

  const task = prior.then(async (): Promise<HttpResult> => {
    let lastErr = "";
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      await throttle(host);
      try {
        const r = await once(url, headers);
        // 429 and 5xx are worth retrying; 403/404 are an answer, not a hiccup.
        if (r.status === 429 || r.status >= 500) {
          lastErr = `HTTP ${r.status}`;
          await sleep(1500 * attempt * attempt);
          continue;
        }
        return r;
      } catch (e) {
        lastErr = e instanceof Error ? e.message : String(e);
        await sleep(1500 * attempt * attempt);
      }
    }
    return { ok: false, status: 0, body: lastErr };
  });

  hostQueues.set(host, task.catch(() => undefined));
  return task;
}

export async function getJson<T>(url: string): Promise<T | undefined> {
  const r = await get(url, { accept: "application/json" });
  if (!r.ok) return undefined;
  try {
    return JSON.parse(r.body) as T;
  } catch {
    return undefined;
  }
}
