"""The browser adapter's decision-making, isolated from the browser itself.

Everything here is pure: when to stop paging, how a found selector merges with
the built-in guesses, and how a store's own "showing X of Y" text is read.
Keeping these free of Playwright means the rules that actually caused data
loss are tested in milliseconds.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from switch_tracker import paths
from switch_tracker.adapters.browser import overrides as profile_overrides
from switch_tracker.adapters.browser.adapter import _condition_for, rejects_url
from switch_tracker.adapters.browser.extract import Extracted
from switch_tracker.adapters.browser.pagination import ProductivityTracker, read_claimed_total
from switch_tracker.adapters.browser.profiles import PROFILES, StoreProfile, effective_profile
from switch_tracker.core.models import Condition, Region


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
            "gameland",
            "gamepookie",
            "cex_in",
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

    def test_gamepookie_pages_by_a_load_more_button(self) -> None:
        """It has no pagination at all -- confirmed on the live site.

        The ?page= parameter it originally shipped with was INERT: it built a
        valid-looking URL that returned page 1's products every time, so a
        --pages 3 run reported three pages and 5 unique products. That reads as
        a working walk right up until the count is compared against the
        category's own ~88.

        Load-more paging appends rather than replaces, so page N holds pages
        1..N. _advanced() fingerprints card COUNT alongside the first few
        hrefs, so a grid growing 24 -> 48 registers as a real advance even
        though the leading cards never move, and _dedupe drops the repeats.
        """
        assert PROFILES["gamepookie"].next_page[0] == "[data-hook='load-more-button']"

    def test_gamepookie_scrolls_far_enough_to_reach_that_button(self) -> None:
        """The scroll is required BY the button, not a general nicety.

        It sits below the grid, so there is nothing to click until the page has
        been scrolled to the bottom -- and the grid gets longer every time it
        is pressed.
        """
        assert PROFILES["gamepookie"].scroll_passes > 1

    def test_a_store_paged_by_clicking_declares_no_inert_page_parameter(self) -> None:
        """A {p} that does nothing is worse than no {p}.

        uses_click_paging() already routes past it, so the parameter changes no
        behaviour -- it just asserts in the config that a mechanism exists when
        it does not, which is what sent this store's diagnosis down the
        pagination path instead of the load-more one.
        """
        from switch_tracker.config.stores import STORES

        store = next(s for s in STORES if s.id == "gamepookie")
        assert all("{p}" not in url for url in store.search_urls)

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


    #: field -> the stores allowed to depart from its default, and nothing else.
    #:
    #: This replaces a blanket "every store except playasia" exemption. The
    #: guard's purpose is unchanged and is NOT "only one store may differ" --
    #: it is that a departure must be a decision somebody made and can point at
    #: evidence for. Listing them per field keeps that true while allowing a
    #: second store to opt into ONE mechanic without silently unlocking four
    #: others for itself.
    PAGE_MECHANIC_OPT_INS: ClassVar[dict[str, set[str]]] = {
        "wait_until": {"playasia"},
        "scroll_passes": {"playasia", "gamepookie"},
        "scroll_settle_ms": {"playasia", "gamepookie"},
        "reject_url_parts": {"playasia"},
        "require_digit_in_url": {"playasia"},
    }

    def test_only_the_listed_stores_depart_from_the_default_page_mechanics(self) -> None:
        """The regression contract for the per-store page-mechanics fields.

        If a profile starts setting one of these without being named above,
        this fails -- which is the point. It forces a deliberate decision
        instead of a quiet drift where six stores each acquire a slightly
        different wait strategy nobody chose as a whole.

        GamePookie's entry is evidence-backed, not a preference: a live
        --pages 3 run extracted exactly FIVE products from every page of a
        category reporting ~88. Wix extends the grid as you scroll, and the
        default single proportional jump lands at 60% of a document only five
        cards tall, so it never reaches far enough to pull the next batch.
        """
        defaults = {
            "wait_until": "domcontentloaded",
            "scroll_passes": 1,
            "scroll_settle_ms": 0,
            "reject_url_parts": (),
            "require_digit_in_url": False,
        }
        for store_id, profile in PROFILES.items():
            for field, expected in defaults.items():
                if store_id in self.PAGE_MECHANIC_OPT_INS[field]:
                    continue
                assert getattr(profile, field) == expected, f"{store_id}.{field}"

    def test_a_listed_store_actually_uses_the_opt_in_it_claims(self) -> None:
        """The other half, or the list above rots into a permission slip.

        An entry that no longer corresponds to a real departure should be
        deleted, not left granting a store the right to drift later.
        """
        defaults = {
            "wait_until": "domcontentloaded",
            "scroll_passes": 1,
            "scroll_settle_ms": 0,
            "reject_url_parts": (),
            "require_digit_in_url": False,
        }
        for field, store_ids in self.PAGE_MECHANIC_OPT_INS.items():
            for store_id in store_ids:
                assert getattr(PROFILES[store_id], field) != defaults[field], (
                    f"{store_id} is listed as opting out of {field} but still uses the default"
                )

    def test_cex_derives_its_sku_from_the_query_parameter(self) -> None:
        """The bug a live run found: 69 products scraped, ONE kept.

        Every CeX URL is /product-detail?id=NNNN. The path tail is therefore
        the same string for the entire catalogue, and UNIQUE(store_id, sku)
        folded the whole shop into a single listing -- while the run still
        reported Ok, because nothing in the pipeline treats "everything
        deduped into one row" as an error.
        """
        assert PROFILES["cex_in"].sku_url_params == ("id",)

    def test_no_other_store_keeps_query_parameters(self) -> None:
        """Opt-in, because this function's job is a STABLE answer across runs.

        A store whose URLs carry an unrelated ?id= tracking parameter would
        have every SKU change the moment a global rule started reading it --
        every price series restarting at one point, with no error anywhere.
        """
        assert [k for k, v in PROFILES.items() if v.sku_url_params] == ["cex_in"]

    def test_cex_leads_with_the_selector_confirmed_against_the_live_page(self) -> None:
        """A --diagnose-pager run scored the profile's own candidates.

        "[data-testid='search-product-card']" -> 0, "article.product-card" -> 0,
        "div.search-product-card" -> 17. The dead guesses are kept as trailing
        fallbacks, because a site can revert, but a selector that matches
        nothing must never sit ahead of one that works: from_selectors takes
        the FIRST candidate that yields rows, and Play-Asia is this file's
        standing record of what a wrong winner costs.
        """
        assert PROFILES["cex_in"].card[0] == "div.search-product-card"

    #: store -> the results CONTAINER it waits on instead of one of its cards.
    #:
    #: A legitimate and sometimes better choice: Amazon's div.s-main-slot is
    #: the results region, so it appears before any individual card does and
    #: the wait ends sooner. Listed explicitly rather than allowed generally,
    #: because "not a card selector" is also exactly what a ready that matches
    #: NOTHING looks like from here -- and that costs the full timeout on
    #: every page, silently.
    READY_CONTAINERS: ClassVar[dict[str, str]] = {"amazon_in": "div.s-main-slot"}

    def test_every_profiles_ready_selector_is_a_card_or_a_declared_container(self) -> None:
        """A `ready` that matches nothing is a silent per-page tax.

        wait_for_selector is wrapped in contextlib.suppress, so a container
        that never appears does not fail -- it burns the full 15s timeout and
        carries on. CeX shipped with a `ready` naming its two zero-matching
        selector guesses and paid 15s of every 18.1s page for it, which is the
        kind of cost that hides behind "browser stores are just slow".

        Offline this cannot check what a selector MATCHES, only that it is one
        the profile has some reason to believe in. Tying it to the card list
        is what makes that meaningful: the cards are the part of a profile
        that gets corrected when a store breaks, so a repair fixes both.
        """
        for store_id, profile in PROFILES.items():
            if profile.ready is None:
                continue
            parts = {part.strip() for part in profile.ready.split(",")}
            if profile.ready == self.READY_CONTAINERS.get(store_id):
                continue
            assert parts & set(profile.card), (
                f"{store_id}.ready={profile.ready!r} is neither a declared card selector "
                "nor its listed results container"
            )

    def test_a_declared_container_is_not_just_a_card_selector_in_disguise(self) -> None:
        """Keeps the exemption list honest.

        If a store's container becomes one of its card selectors, the entry
        should be deleted rather than left standing as a blanket exemption
        from the check above.
        """
        for store_id, container in self.READY_CONTAINERS.items():
            profile = PROFILES[store_id]
            assert profile.ready == container, f"{store_id}: stale container entry"
            assert container not in profile.card, (
                f"{store_id}: {container!r} is a card selector now -- drop the exemption"
            )


class TestConditionResolution:
    """New or pre-owned, and where that answer is allowed to come from.

    Wrong here is worse than missing: a mislabelled listing still shows up, in
    the wrong bucket, forever, and nothing anywhere raises.
    """

    @staticmethod
    def _row(title: str, context: str = "") -> Extracted:
        return Extracted(title=title, price=1.0, href="/p/1", in_stock=True, context=context)

    def test_the_title_is_still_the_default_source(self) -> None:
        """The behaviour every existing store had before context existed."""
        profile = PROFILES["e2zstore"]
        assert _condition_for(profile, self._row("Zelda TotK (Pre-Owned)")) is Condition.PRE_OWNED
        assert _condition_for(profile, self._row("Zelda TotK")) is Condition.NEW

    def test_a_store_that_has_not_opted_in_ignores_card_context(self) -> None:
        """The guard that keeps this change from corrupting Amazon.

        An Amazon search card routinely carries "6 used & new offers" under the
        price, and PRE_OWNED matches "used" on a bare word boundary. Reading card
        text for
        every store at once would therefore relabel a large slice of Amazon's
        catalogue as second-hand -- silently, and permanently.
        """
        row = self._row("Mario Kart World", context="Mario Kart World ₹4,499 6 used & new offers")
        assert PROFILES["amazon_in"].condition_from_context is False
        assert _condition_for(PROFILES["amazon_in"], row) is Condition.NEW

    def test_an_opted_in_store_reads_the_whole_card(self) -> None:
        """GameLand's reason for the seam: the badge is not in the title."""
        row = self._row("Zelda TotK", context="Pre-Owned Zelda TotK ₹3,499 Add to cart")
        assert _condition_for(PROFILES["gameland"], row) is Condition.PRE_OWNED

    def test_an_opted_in_store_falls_back_to_the_title_when_there_is_no_card(self) -> None:
        """JSON-LD and hydration-state rows carry no context at all.

        Empty must read as "nothing available", not as "the card said nothing",
        or opting in would DISABLE the title read for every non-selector layer.
        """
        row = self._row("Zelda TotK (Pre-Owned)", context="")
        assert _condition_for(PROFILES["gameland"], row) is Condition.PRE_OWNED

    def test_an_asserted_condition_wins_over_everything_the_page_says(self) -> None:
        """CeX deals only in used stock and, for that reason, never labels it.

        Its titles read "Mario Kart World", so both the title and the card read
        NEW for a catalogue where nothing is.
        """
        row = self._row("Mario Kart World", context="Mario Kart World ₹4,499 Buy now")
        assert _condition_for(PROFILES["cex_in"], row) is Condition.PRE_OWNED

    def test_exactly_one_store_asserts_a_condition(self) -> None:
        """Per-store assertion is the exception the model warns about.

        core/models.Condition records that at least one real retailer sells new
        and pre-owned from one catalogue, so a per-store flag is wrong for the
        normal shop. This fails if a second store quietly acquires one.
        """
        assert [k for k, v in PROFILES.items() if v.default_condition is not None] == ["cex_in"]

    def test_exactly_one_store_reads_condition_from_card_text(self) -> None:
        assert [k for k, v in PROFILES.items() if v.condition_from_context] == ["gameland"]


class TestAddedBrowserProfiles:
    def test_gameland_prefers_the_sale_price_over_the_struck_through_one(self) -> None:
        """``ins`` wraps the discounted figure; ``del`` keeps the original.

        Ordering is the whole assertion. If the plain ``.amount`` came first it
        would match the ``del`` too, and every discounted row would record its
        PRE-sale price -- so the one event this tracker exists to notice is the
        one it would miss.
        """
        price = PROFILES["gameland"].price
        assert price[0] == "li.price-wrap .price ins .amount"
        assert price.index("li.price-wrap .price ins .amount") < price.index(".price")

    def test_gamepookie_does_not_assume_an_indian_region(self) -> None:
        """It imports US, Asian and Japanese pressings into the same category.

        Region is modelled here as a genuinely different, non-interchangeable
        product, so defaulting to IN would not be a mislabel -- it would merge
        editions that are not the same thing.
        """
        assert PROFILES["gamepookie"].default_region is Region.UNKNOWN

    def test_every_other_browser_store_still_defaults_to_the_indian_region(self) -> None:
        for store_id, profile in PROFILES.items():
            if store_id in ("gamepookie", "playasia"):
                continue
            assert profile.default_region is Region.IN, store_id

    def test_gamepookie_anchors_on_wix_data_hooks_not_generated_classes(self) -> None:
        """Wix class names are hashed and rotate per deploy; data-hook does not."""
        profile = PROFILES["gamepookie"]
        for field in ("card", "title", "price"):
            assert any("data-hook" in selector for selector in getattr(profile, field)), field


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
            # All three of the newly added browser stores page by URL: each
            # carries a real {p} and none declares a next-page control, which
            # is the combination that keeps them off the click path.
            "gameland": "url",
            "gamepookie": "click",
            "cex_in": "url",
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

