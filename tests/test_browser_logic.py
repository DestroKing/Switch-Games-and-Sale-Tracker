"""The browser adapter's decision-making, isolated from the browser itself.

Everything here is pure: when to stop paging, how a found selector merges with
the built-in guesses, and how a store's own "showing X of Y" text is read.
Keeping these free of Playwright means the rules that actually caused data
loss are tested in milliseconds.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from switch_tracker import paths
from switch_tracker.adapters.browser import overrides as profile_overrides
from switch_tracker.adapters.browser.pagination import ProductivityTracker, read_claimed_total
from switch_tracker.adapters.browser.profiles import PROFILES, effective_profile


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


class TestProfiles:
    def test_every_browser_store_has_a_profile(self) -> None:
        expected = {
            "amazon_in",
            "flipkart",
            "playasia",
            "gamestheshop",
            "gamenation",
            "mcubegames",
            "e2zstore",
        }
        assert expected == set(PROFILES)

    def test_every_selector_field_is_a_list_of_candidates(self) -> None:
        """Never a single string.

        A candidate that stops working must be able to sit alongside its
        replacement rather than being deleted -- sites revert.
        """
        for store_id, profile in PROFILES.items():
            for field in ("card", "title", "price", "link"):
                value = getattr(profile, field)
                assert isinstance(value, tuple), f"{store_id}.{field}"
                assert value, f"{store_id}.{field} is empty"

    @pytest.mark.parametrize("store_id", ["gamenation", "mcubegames"])
    def test_click_paginated_stores_declare_a_next_control(self, store_id: str) -> None:
        """Confirmed by diagnostics: pages 1/2/3 came back byte-identical.

        A page query parameter does nothing on these sites; page 2 exists only
        behind a client-side button click with no navigation at all.
        """
        assert PROFILES[store_id].next_page

    def test_url_paginated_stores_declare_no_next_control(self) -> None:
        assert not PROFILES["amazon_in"].next_page


class TestProfileOverrides:
    def test_a_found_selector_is_tried_before_the_built_in_guesses(self, data_dir: Path) -> None:
        profile_overrides.add_selector("amazon_in", "card", "div.found-by-clicking")
        merged = effective_profile("amazon_in")
        assert merged is not None
        assert merged.card[0] == "div.found-by-clicking"

    def test_a_found_selector_never_discards_the_built_in_guesses(self, data_dir: Path) -> None:
        """A correction must not have to carry a whole working profile with it."""
        original = PROFILES["amazon_in"].card
        profile_overrides.add_selector("amazon_in", "card", "div.found-by-clicking")
        merged = effective_profile("amazon_in")
        assert merged is not None
        assert all(candidate in merged.card for candidate in original)

    def test_the_same_selector_is_not_added_twice(self, data_dir: Path) -> None:
        profile_overrides.add_selector("amazon_in", "card", "div.x")
        profile_overrides.add_selector("amazon_in", "card", "div.x")
        merged = effective_profile("amazon_in")
        assert merged is not None
        assert merged.card.count("div.x") == 1

    def test_an_unknown_store_has_no_profile(self, data_dir: Path) -> None:
        assert effective_profile("not_a_store") is None

    def test_a_corrupt_overrides_file_falls_back_to_the_built_ins(self, data_dir: Path) -> None:
        paths.profiles_path().write_text("{broken")
        merged = effective_profile("amazon_in")
        assert merged is not None
        assert merged.card == PROFILES["amazon_in"].card


class TestProductivityTracker:
    """When to conclude a catalogue is exhausted.

    The original rule -- exactly zero new rows, twice in a row -- silently
    truncated two real stores. Sites fill trailing pages with slowly
    reshuffling "related items" filler, so the count almost never lands on
    precisely zero, and the loop paged on collecting duplicates that vanished
    at dedupe. The run then looked successful with a much smaller number.
    """

    def test_a_full_page_of_new_rows_is_productive(self) -> None:
        tracker = ProductivityTracker()
        assert tracker.record(new_rows=20, total_rows=20) is False

    def test_one_barren_page_is_not_enough_to_give_up(self) -> None:
        tracker = ProductivityTracker()
        assert tracker.record(new_rows=0, total_rows=20) is False

    def test_gives_up_after_four_consecutive_unproductive_pages(self) -> None:
        tracker = ProductivityTracker()
        results = [tracker.record(new_rows=0, total_rows=20) for _ in range(4)]
        assert results == [False, False, False, True]

    def test_a_productive_page_resets_the_streak(self) -> None:
        """Real content appearing again means the catalogue was not exhausted."""
        tracker = ProductivityTracker()
        tracker.record(new_rows=0, total_rows=20)
        tracker.record(new_rows=0, total_rows=20)
        tracker.record(new_rows=20, total_rows=20)
        assert tracker.record(new_rows=0, total_rows=20) is False

    def test_a_trickle_of_new_rows_still_counts_as_unproductive(self) -> None:
        """Below 15% new is reshuffling filler, not a catalogue still going.

        This is the case a strict zero-check missed: 2 new rows out of 20 is
        not progress, but it is not zero either.
        """
        tracker = ProductivityTracker()
        results = [tracker.record(new_rows=2, total_rows=20) for _ in range(4)]
        assert results[-1] is True

    def test_fifteen_percent_new_is_productive(self) -> None:
        tracker = ProductivityTracker()
        assert tracker.record(new_rows=3, total_rows=20) is False

    def test_an_empty_page_does_not_divide_by_zero(self) -> None:
        tracker = ProductivityTracker()
        assert tracker.record(new_rows=0, total_rows=0) is False


class TestReadClaimedTotal:
    """A store's own "showing X of Y" text. Best-effort, never authoritative."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Showing 1-20 of 1,234 results", 1234),
            ("847 products found", 847),
            ("Showing 24 of 96", 96),
            ("1-16 of 213 items", 213),
        ],
    )
    def test_reads_the_common_phrasings(self, text: str, expected: int) -> None:
        assert read_claimed_total(text) == expected

    @pytest.mark.parametrize("text", ["", "Nintendo Switch Games", "Add to cart", "of results"])
    def test_returns_nothing_when_the_page_never_says(self, text: str) -> None:
        """Plenty of stores show no count at all. That is not a failure."""
        assert read_claimed_total(text) is None
