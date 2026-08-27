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
from switch_tracker.adapters.browser.adapter import rejects_url
from switch_tracker.adapters.browser.pagination import ProductivityTracker, read_claimed_total
from switch_tracker.adapters.browser.profiles import PROFILES, StoreProfile, effective_profile


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


    def test_play_asia_pins_an_inr_session(self) -> None:
        """What makes StoreConfig.currency='INR' true rather than asserted.

        Play-Asia quotes whatever its session says. These cookies previously
        existed only in a standalone scraping script, so the shipped config
        claimed INR while the collector recorded the default session's
        currency under an INR label.
        """
        profile = PROFILES["playasia"]
        assert dict(profile.cookies)["currency"] == "INR"
        assert dict(profile.cookies)["country"] == "IN"
        assert profile.cookie_domain == ".play-asia.com"

    def test_no_other_store_pins_cookies(self) -> None:
        """The seam is opt-in; a shared session setting would leak everywhere."""
        assert [k for k, v in PROFILES.items() if v.cookies] == ["playasia"]


    def test_every_store_but_play_asia_keeps_the_default_page_mechanics(self) -> None:
        """The regression contract for the per-store page-mechanics fields.

        They exist so ONE store can differ. If a second profile starts setting
        them this test fails, which is the point: it forces a deliberate
        decision instead of a quiet drift where six stores each acquire a
        slightly different wait strategy nobody chose as a whole.
        """
        defaults = {
            "wait_until": "domcontentloaded",
            "scroll_passes": 1,
            "scroll_settle_ms": 0,
            "reject_url_parts": (),
            "require_digit_in_url": False,
        }
        for store_id, profile in PROFILES.items():
            if store_id == "playasia":
                continue
            for field, expected in defaults.items():
                assert getattr(profile, field) == expected, f"{store_id}.{field}"


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


class TestProductUrlFilter:
    """Rejecting hrefs that are not products.

    The classifier cannot do this job: a category link titled "Nintendo Switch"
    on a store with a SWITCH platform_hint classifies as a GAME, because the
    title genuinely does name the console.
    """

    @staticmethod
    def _profile(**kw: object) -> StoreProfile:
        return StoreProfile(card=("a",), title=("a",), price=("a",), link=("a",), **kw)  # type: ignore[arg-type]

    def test_is_a_no_op_when_the_store_configures_nothing(self) -> None:
        """The default for six of the seven browser stores."""
        profile = self._profile()
        for url in ("https://x.test/search/anything", "https://x.test/no-digits-here"):
            assert rejects_url(profile, url) is False

    def test_rejects_a_configured_path_fragment(self) -> None:
        profile = self._profile(reject_url_parts=("/search/", "/category/"))
        assert rejects_url(profile, "https://x.test/en/search/switch+games") is True
        assert rejects_url(profile, "https://x.test/en/category/consoles") is True

    def test_keeps_anything_that_matches_no_rule(self) -> None:
        """Fails OPEN, deliberately.

        A wrong rule must leave junk in the database -- recoverable -- rather
        than silently deleting a whole store's listings, which is not.
        """
        profile = self._profile(reject_url_parts=("/search/",))
        assert rejects_url(profile, "https://x.test/en/mario-kart-world/13/70abcd") is False

    def test_rejects_a_digitless_url_only_when_asked(self) -> None:
        url = "https://x.test/en/some-landing-page"
        assert rejects_url(self._profile(require_digit_in_url=True), url) is True
        assert rejects_url(self._profile(require_digit_in_url=False), url) is False

    def test_a_digit_anywhere_in_the_url_satisfies_the_rule(self) -> None:
        profile = self._profile(require_digit_in_url=True)
        assert rejects_url(profile, "https://x.test/en/mario-kart-world/13/70abcd") is False


class TestPagingPathSelection:
    def test_no_profile_uses_an_unscoped_has_text_pager(self) -> None:
        """The shape that caused the 350-rows-36-listings bug.

        A bare ":has-text(...)" matches every element containing the text,
        html and body included, so `.last` resolved to a footer <small> reading
        "Terms > Privacy". _click_next clicked it and reported success.

        This replaces an earlier assertion that Play-Asia must carry NO pager
        selectors at all. That was the right guard while its only verified
        mechanism was the numeric-text clicker; the live page has since been
        confirmed to expose `button.pa-pagination-next`, which is strictly
        better -- it cannot be confused with the Slick carousel's "1 2 3 4"
        buttons that a text-matching clicker would press. The invariant worth
        keeping is not "no selectors", it is "no selector that can match the
        whole document".
        """
        for store_id, profile in PROFILES.items():
            for selector in profile.next_page:
                assert not selector.startswith(":"), f"{store_id}: unscoped {selector!r}"

    def test_play_asia_pages_by_its_own_pagination_button(self) -> None:
        """Confirmed on the live page, alongside "1" and "139" position labels."""
        assert PROFILES["playasia"].next_page == ("button.pa-pagination-next",)

    def test_play_asia_cards_are_the_confirmed_container_first(self) -> None:
        """Every previously-shipped selector matched zero elements.

        Extraction only worked by falling through to "[class*='product']",
        which matches 488 elements of nav, carousels and page furniture -- and
        that is what broke paging, because _click_next fingerprints the first
        few cards to confirm a page turned. Furniture does not change between
        pages, so a successful click read as a failure.
        """
        assert PROFILES["playasia"].card[0] == "div.pa-modern-product-item"

    def test_the_paging_rule_changes_path_selection_for_play_asia_only(self) -> None:
        """Asserted against the SHIPPED stores and profiles, not a fixture.

        The rule gained a second trigger ("no {p} to substitute"). This pins
        which real store each trigger applies to, so a future edit to a search
        URL cannot silently move a store onto the other mechanism.
        """
        from switch_tracker.adapters.browser.adapter import uses_click_paging
        from switch_tracker.adapters.browser.profiles import PROFILES
        from switch_tracker.config.stores import STORES
        from switch_tracker.core.models import AdapterKind

        chosen = {
            store.id: "click"
            if uses_click_paging(PROFILES[store.id], store.search_urls[0])
            else "url"
            for store in STORES
            if store.kind is AdapterKind.BROWSER
        }
        assert chosen == {
            "amazon_in": "url",
            "flipkart": "url",
            "gamestheshop": "url",
            "gamenation": "click",
            "mcubegames": "click",
            "e2zstore": "click",
            "playasia": "click",
        }


class TestBudgetInvariant:
    def test_no_profile_budget_reaches_the_services_hard_deadline(self) -> None:
        """Extends the default-only check below to PER-STORE budgets.

        A profile may raise its own budget for a large catalogue. If one ever
        exceeds the service deadline, the service's wait_for fires first,
        cancels the coroutine, and every page already scraped is discarded --
        the precise loss the self-limit exists to prevent, reintroduced by a
        single number in a config file.
        """
        from switch_tracker.services.collect import CollectService

        for store_id, profile in PROFILES.items():
            if profile.time_budget_s is not None:
                assert profile.time_budget_s < CollectService.DEFAULT_BROWSER_DEADLINE_S, store_id

    def test_a_profile_budget_covers_the_pages_it_allows(self) -> None:
        """A cap it cannot reach in the time given is a misleading setting.

        Play-Asia: 150 pages at the measured ~8.5s each needs ~1275s, and it is
        allowed 1320s. Loose enough that the budget, not the cap, should be what
        stops a genuinely huge run -- but not so loose that max_pages is fiction.
        """
        profile = PROFILES["playasia"]
        assert profile.time_budget_s is not None and profile.max_pages is not None
        assert profile.time_budget_s / profile.max_pages >= 8.0

    def test_the_adapter_stops_before_the_service_gives_up(self) -> None:
        """The whole partial-results mechanism depends on this ordering.

        If the adapter's self-limit were the larger of the two, the service's
        wait_for would always fire first, cancel the coroutine, and discard
        every page scraped -- exactly the loss the self-limit exists to avoid.
        A comment cannot fail a build; this can.
        """
        from switch_tracker.adapters.browser.adapter import DEFAULT_TIME_BUDGET_S
        from switch_tracker.services.collect import CollectService

        assert DEFAULT_TIME_BUDGET_S < CollectService.DEFAULT_BROWSER_DEADLINE_S


class TestStoreOrdering:
    def test_play_asia_is_the_first_browser_store(self) -> None:
        """Browser stores run 4 at a time in list order.

        Play-Asia is the slowest (networkidle plus a deep click-paged walk), so
        it claims a slot immediately rather than queueing behind six others and
        starting with most of the run's wall-clock already spent.
        """
        from switch_tracker.config.stores import STORES
        from switch_tracker.core.models import AdapterKind

        browser = [s.id for s in STORES if s.kind is AdapterKind.BROWSER]
        assert browser[0] == "playasia", browser

