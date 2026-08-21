"""Bounded, order-preserving concurrency."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence


async def bounded_gather[T, R](
    items: Sequence[T],
    limit: int,
    worker: Callable[[T], Awaitable[R]],
) -> list[R]:
    """Run ``worker`` over ``items``, at most ``limit`` in flight.

    Input order is preserved in the result regardless of completion order --
    probe prints a table, and rows arriving in completion order would shuffle
    it between runs for no reason.

    Stores are independent hosts, so running them concurrently makes a run
    cost roughly the slowest store rather than the sum of all of them. The
    per-host throttle in http.py already serialises requests WITHIN a host,
    so this bound is about machine resources, not politeness.
    """
    if not items:
        return []

    semaphore = asyncio.Semaphore(limit)

    async def guarded(item: T) -> R:
        async with semaphore:
            return await worker(item)

    return list(await asyncio.gather(*(guarded(item) for item in items)))
