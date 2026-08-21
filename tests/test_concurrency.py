"""Bounded, order-preserving concurrency over independent stores."""

from __future__ import annotations

import asyncio

from switch_tracker.core.concurrency import bounded_gather


class TestOrdering:
    async def test_preserves_input_order_regardless_of_completion_order(self) -> None:
        """Probe prints a table. Rows arriving in completion order would shuffle it."""

        async def work(delay: float) -> float:
            await asyncio.sleep(delay)
            return delay

        # Deliberately reversed: the last item finishes first.
        results = await bounded_gather([0.03, 0.02, 0.01], 3, work)
        assert results == [0.03, 0.02, 0.01]

    async def test_returns_an_empty_list_for_no_items(self) -> None:
        async def work(item: int) -> int:
            return item

        assert await bounded_gather([], 4, work) == []


class TestBounding:
    async def test_never_exceeds_the_limit(self) -> None:
        """A flat shared limit let two large browser catalogues starve every other store."""
        in_flight = 0
        peak = 0

        async def work(_: int) -> int:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return 0

        await bounded_gather(list(range(20)), 4, work)
        assert peak <= 4

    async def test_actually_runs_concurrently(self) -> None:
        async def work(_: int) -> int:
            await asyncio.sleep(0.05)
            return 0

        started = asyncio.get_running_loop().time()
        await bounded_gather(list(range(8)), 8, work)
        assert asyncio.get_running_loop().time() - started < 0.25
