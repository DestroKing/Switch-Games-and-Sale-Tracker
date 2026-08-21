/**
 * Runs `worker` over `items` with at most `limit` in flight at once,
 * preserving input order in the returned array regardless of completion
 * order. Used to process independent stores (different hosts) concurrently
 * — the politeness throttle in http.ts already serializes requests within
 * the same host, so serializing *across* stores on top of that only made
 * every run take the sum of every store's latency instead of the slowest
 * one's.
 */
export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;

  async function runNext(): Promise<void> {
    const i = next++;
    if (i >= items.length) return;
    results[i] = await worker(items[i] as T, i);
    return runNext();
  }

  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, runNext));
  return results;
}
