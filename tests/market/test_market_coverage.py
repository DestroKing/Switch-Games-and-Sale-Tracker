"""Scan verdicts: COMPLETE is earned with positive evidence, never assumed.

COMPLETE is the only verdict that may later mark a product NOT_LISTED, so
every way of reaching it without proof is pinned here as a counter-example.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from switch_tracker.core.models import (
    AdapterKind,
    Condition,
    Coverage,
    Failed,
    Ok,
    Partial,
    Platform,
    RawListing,
    Region,
    StoreConfig,
)
from switch_tracker.market.coverage import scope_of, verdict
from switch_tracker.market.models import CoverageStatus, ScopeKind

ROW = RawListing(
    "s", "A", "https://s.example/a", "Zelda", "INR", 999.0, True, Platform.SWITCH, Region.IN, Condition.NEW
)

FULL = Coverage(
    pages_attempted=3,
    pages_completed=3,
    end_reached=True,
    claimed_total=250,
    raw_seen=250,
    seen_skus=frozenset({"A"}),
)


def store(kind: AdapterKind, **kw: object) -> StoreConfig:
    base = StoreConfig("s", "S", "https://s.example", kind, "INR", 2, True)
    return replace(base, **kw)  # type: ignore[arg-type]


class TestComplete:
    def test_every_page_to_the_end_matching_the_stores_count(self) -> None:
        result = verdict(Ok((ROW,), FULL), ScopeKind.CATEGORY)
        assert result.status is CoverageStatus.COMPLETE
        assert "3 of 3 pages" in result.evidence
        assert "250" in result.evidence

    def test_end_of_pagination_without_a_store_count_is_still_proof(self) -> None:
        result = verdict(Ok((ROW,), replace(FULL, claimed_total=None)), ScopeKind.CATALOGUE)
        assert result.status is CoverageStatus.COMPLETE
        assert "no product count" in result.evidence


class TestNotComplete:
    @pytest.mark.parametrize(
        ("coverage", "why"),
        [
            (replace(FULL, end_reached=False), "end"),
            (replace(FULL, pages_completed=2), "2 of 3"),
            (replace(FULL, raw_seen=249), "249 of 250"),
        ],
    )
    def test_an_ok_outcome_without_full_evidence_is_partial(self, coverage: Coverage, why: str) -> None:
        result = verdict(Ok((ROW,), coverage), ScopeKind.CATEGORY)
        assert result.status is CoverageStatus.PARTIAL
        assert why in result.evidence

    def test_the_adapters_own_partial_is_never_upgraded(self) -> None:
        result = verdict(Partial((ROW,), "time budget", FULL), ScopeKind.CATEGORY)
        assert result.status is CoverageStatus.PARTIAL
        assert "time budget" in result.evidence

    def test_failed_is_failed(self) -> None:
        result = verdict(Failed("HTTP 403"), ScopeKind.CATEGORY)
        assert result.status is CoverageStatus.FAILED
        assert "HTTP 403" in result.evidence

    def test_no_evidence_at_all_is_unknown_not_complete(self) -> None:
        """An HTTP 200 and an Ok are not proof of having read the whole catalogue."""
        result = verdict(Ok((ROW,)), ScopeKind.CATALOGUE)
        assert result.status is CoverageStatus.UNKNOWN

    @pytest.mark.parametrize(
        "kind", [ScopeKind.SEARCH, ScopeKind.BROWSE, ScopeKind.MANUAL, ScopeKind.UNKNOWN]
    )
    def test_search_and_rendered_pages_never_prove_completeness(self, kind: ScopeKind) -> None:
        result = verdict(Ok((ROW,), FULL), kind)
        assert result.status is CoverageStatus.UNKNOWN
        assert not result.status.absence_eligible

    def test_only_complete_is_absence_eligible(self) -> None:
        assert [s for s in CoverageStatus if s.absence_eligible] == [CoverageStatus.COMPLETE]


class TestScope:
    def test_configured_collections_make_a_category_scope(self) -> None:
        kind, _ = scope_of(store(AdapterKind.WOOCOMMERCE, collections=("switch-games",)))
        assert kind is ScopeKind.CATEGORY

    def test_an_unscoped_feed_is_the_whole_catalogue(self) -> None:
        assert scope_of(store(AdapterKind.SHOPIFY))[0] is ScopeKind.CATALOGUE
        assert scope_of(store(AdapterKind.HOBBYALL))[0] is ScopeKind.CATALOGUE

    def test_browser_stores_are_browsed_pages(self) -> None:
        kind, _ = scope_of(store(AdapterKind.BROWSER, search_urls=("https://s.example/search?q=x",)))
        assert kind is ScopeKind.BROWSE

    def test_the_definition_changes_when_the_configuration_does(self) -> None:
        a = scope_of(store(AdapterKind.WOOCOMMERCE, collections=("a",)))[1]
        b = scope_of(store(AdapterKind.WOOCOMMERCE, collections=("a", "b")))[1]
        assert a != b

    def test_the_definition_ignores_order_and_unrelated_fields(self) -> None:
        a = scope_of(store(AdapterKind.WOOCOMMERCE, collections=("a", "b"), note="x", tier=1))[1]
        b = scope_of(store(AdapterKind.WOOCOMMERCE, collections=("b", "a")))[1]
        assert a == b
        assert json.loads(a)["collections"] == ["a", "b"]
