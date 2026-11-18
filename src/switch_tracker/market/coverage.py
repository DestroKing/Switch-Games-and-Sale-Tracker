"""What a scan proves about its scope.

COMPLETE is the only verdict that may mark a product NOT_LISTED, so it is
earned with positive evidence: an enumerable scope, every page read, every
path ended on its own short or empty page, and at least the store's own count
seen where it gives one. Anything less is PARTIAL or UNKNOWN -- never COMPLETE
by default, and never upgraded from an adapter's own Partial.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from switch_tracker.core.models import AdapterKind, Failed, FetchOutcome, Partial, StoreConfig
from switch_tracker.market.models import CoverageStatus, ScopeKind


@dataclass(frozen=True, slots=True)
class Verdict:
    status: CoverageStatus
    #: Why, in words: shown beside every absence this scan is used for.
    evidence: str


def scope_of(store: StoreConfig) -> tuple[ScopeKind, str]:
    """The scope a store's configuration walks, and a canonical definition of it.

    The definition is what makes a scope a scope: editing the configured
    collections yields a different one, so an absence is never reconciled
    against a scan of something else. Order and unrelated fields (note, tier)
    are deliberately not part of it.
    """
    if store.kind is AdapterKind.BROWSER:
        # Rendered pages behind bot detection and page budgets; even a
        # category page here is not enumerable in any way we can verify.
        kind = ScopeKind.BROWSE
    elif store.kind in (AdapterKind.SHOPIFY, AdapterKind.WOOCOMMERCE):
        kind = ScopeKind.CATEGORY if store.collections else ScopeKind.CATALOGUE
    elif store.kind is AdapterKind.HOBBYALL:
        kind = ScopeKind.CATALOGUE
    else:
        kind = ScopeKind.UNKNOWN
    definition = json.dumps(
        {
            "adapter": str(store.kind),
            "collections": sorted(store.collections),
            "search_urls": sorted(store.search_urls),
        },
        sort_keys=True,
    )
    return kind, definition


def verdict(outcome: FetchOutcome, scope: ScopeKind) -> Verdict:
    if isinstance(outcome, Failed):
        return Verdict(CoverageStatus.FAILED, f"fetch failed: {outcome.reason}")
    if not scope.enumerable:
        return Verdict(CoverageStatus.UNKNOWN, f"{scope.lower()} results never prove a product is absent")
    if isinstance(outcome, Partial):
        return Verdict(CoverageStatus.PARTIAL, f"adapter reported partial: {outcome.reason}")

    coverage = outcome.coverage
    if coverage is None:
        return Verdict(CoverageStatus.UNKNOWN, "the adapter reports no completion evidence")

    pages = f"{coverage.pages_completed} of {coverage.pages_attempted} pages"
    gaps = []
    if coverage.pages_completed < coverage.pages_attempted:
        gaps.append(f"read {pages}")
    if not coverage.end_reached:
        gaps.append("did not reach the end of pagination")
    if coverage.claimed_total is not None and coverage.raw_seen < coverage.claimed_total:
        gaps.append(f"saw {coverage.raw_seen} of {coverage.claimed_total} products the store counts")
    if gaps:
        return Verdict(CoverageStatus.PARTIAL, "; ".join(gaps))

    count = (
        f"saw {coverage.raw_seen} of the {coverage.claimed_total} products the store counts"
        if coverage.claimed_total is not None
        else f"saw {coverage.raw_seen} products; the store states no product count"
    )
    return Verdict(CoverageStatus.COMPLETE, f"read {pages} to the end of pagination; {count}")
