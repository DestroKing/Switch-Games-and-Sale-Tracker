"""What every adapter agrees to.

Two protocols, kept narrow on purpose.  An adapter's whole job is "given a
store, produce listings"; it has no business reaching a database, a run
record, or the dashboard.
"""

from __future__ import annotations

from typing import Protocol

from switch_tracker.core.models import AdapterKind, FetchOutcome, StoreConfig


class ProgressSink(Protocol):
    """The only thing an adapter may say while it works.

    Replaces the TypeScript version's ``console.log``. Structured rather than
    textual, because this has to survive to a durable table that a dashboard
    tails -- a closed browser tab must not lose a running collection's
    progress, and stdout cannot deliver that.

    Deliberately one method: an adapter must not be able to declare a run
    finished, mark a store failed, or write a health row. Those belong to the
    orchestrator that called it.
    """

    def page(self, store_id: str, page: int, count: int) -> None:
        """Report "page N done, M listings so far" for a still-running fetch."""
        ...


class NullSink:
    """Discards progress. The default, and what most tests want."""

    def page(self, store_id: str, page: int, count: int) -> None:
        return None


class Adapter(Protocol):
    kind: AdapterKind

    async def fetch(self, store: StoreConfig, sink: ProgressSink) -> FetchOutcome:
        """Collect a store's listings.

        Must never raise. Every failure has to come back as ``Failed`` with a
        readable reason, because that reason is what reaches run_store.detail
        and is the only thing a human sees when a store goes quiet.
        """
        ...
