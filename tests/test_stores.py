"""The shipped store list and the corrections layered over it."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from switch_tracker import paths
from switch_tracker.config import overrides
from switch_tracker.config.stores import STORES
from switch_tracker.core.models import AdapterKind, Platform


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


class TestShippedList:
    def test_carries_every_store(self) -> None:
        assert len(STORES) == 24

    def test_ids_are_unique(self) -> None:
        """store.id is a primary key; a duplicate would silently merge two shops."""
        ids = [s.id for s in STORES]
        assert len(ids) == len(set(ids))

    def test_designinfo_deliberately_has_no_platform_hint(self) -> None:
        """A camera/electronics retailer with 570+ categories and no games split.

        The hint that rescues terse titles on a Switch-only shop is exactly
        what leaks false positives on a general one, so this store requires an
        explicit console mention in the title instead.
        """
        store = next(s for s in STORES if s.id == "designinfo")
        assert store.platform_hint is None

    @pytest.mark.parametrize("store_id", ["zozila"])
    def test_known_non_cartridge_stores_ship_disabled(self, store_id: str) -> None:
        assert next(s for s in STORES if s.id == store_id).enabled is False

    def test_play_asia_is_configured_in_the_currency_it_actually_quotes(self) -> None:
        """INR, because the adapter pins an INR reference currency in cookies.

        This shipped as USD on the grounds that Play-Asia's rupee figure was a
        display conversion of a dollar price. It is now driven with INR session
        cookies, so rupees are what the store quotes us and INR is the captured
        fact rather than a derived one.

        The invariant being guarded is unchanged and was never Play-Asia
        specific: ``currency`` must name what a store CHARGES, because a display
        conversion recorded as a price turns every FX move into a fake sale.
        """
        assert next(s for s in STORES if s.id == "playasia").currency == "INR"

    def test_play_asia_ships_enabled(self) -> None:
        """It is a working browser store now, not a parked one."""
        assert next(s for s in STORES if s.id == "playasia").enabled is True

    def test_every_browser_store_has_urls_to_walk(self) -> None:
        for store in STORES:
            if store.kind is AdapterKind.BROWSER:
                assert store.search_urls, f"{store.id} has no search_urls"

    def test_api_stores_that_are_general_retailers_are_scoped(self) -> None:
        """An unscoped general retailer leaks its whole catalogue through."""
        for store_id in ("nistore", "nekavo", "gameloot", "emartgames", "hgworld", "designinfo"):
            store = next(s for s in STORES if s.id == store_id)
            assert store.collections, f"{store_id} is not scoped to a category"

    def test_switch_only_shops_carry_a_hint(self) -> None:
        store = next(s for s in STORES if s.id == "nistore")
        assert store.platform_hint is Platform.SWITCH


#: The ten stores added as one batch, and the adapter each was verified to
#: speak. Named here rather than inlined so the assertions below cannot drift
#: apart over which stores they are talking about.
NEW_BATCH_API = ("sheenu", "gamebuy", "hitechgamez", "gamebot", "gamekart", "consolegarage", "hadiro")
NEW_BATCH_BROWSER = ("gameland", "gamepookie", "cex_in")


class TestTheAddedBatch:
    """The ten-store expansion, 14 -> 24.

    Seven are configuration only, against feeds the app already speaks. Three
    need a browser profile. What is worth pinning is not that they exist -- the
    count test covers that -- but the properties that would silently produce
    WRONG data rather than no data if someone edited them later.
    """

    @pytest.mark.parametrize("store_id", [*NEW_BATCH_API, *NEW_BATCH_BROWSER])
    def test_every_added_store_is_present_and_enabled(self, store_id: str) -> None:
        store = next((s for s in STORES if s.id == store_id), None)
        assert store is not None, f"{store_id} is missing from the shipped list"
        assert store.enabled is True

    def test_the_added_ids_collide_with_nothing_already_shipped(self) -> None:
        """store.id is the primary key listings are filed under.

        A collision would not raise anywhere -- it would merge two shops' price
        histories into one row and read as a volatile retailer.
        """
        added = {*NEW_BATCH_API, *NEW_BATCH_BROWSER}
        assert len(added) == 10
        assert len([s for s in STORES if s.id in added]) == 10

    @pytest.mark.parametrize("store_id", NEW_BATCH_API)
    def test_every_added_api_store_is_scoped_to_categories(self, store_id: str) -> None:
        """Not one of these is a games-only shop.

        All seven also sell consoles, accessories or unrelated electronics, so
        an unscoped fetch would pull the whole catalogue and lean entirely on
        the classifier to fish the cartridges back out.
        """
        store = next(s for s in STORES if s.id == store_id)
        assert store.kind in (AdapterKind.WOOCOMMERCE, AdapterKind.SHOPIFY)
        assert store.collections, f"{store_id} is not scoped to a category"

    @pytest.mark.parametrize("store_id", [*NEW_BATCH_API, *NEW_BATCH_BROWSER])
    def test_every_added_store_quotes_rupees(self, store_id: str) -> None:
        """currency names what a store CHARGES, never what it displays.

        Every store in this batch is an Indian retailer billing in INR, so this
        is the captured fact rather than a conversion -- the invariant
        core/models.py spells out and that Play-Asia needs session cookies for.
        """
        assert next(s for s in STORES if s.id == store_id).currency == "INR"

    @pytest.mark.parametrize("store_id", ["gamebuy", "gamekart"])
    def test_parent_only_stores_list_exactly_one_category(self, store_id: str) -> None:
        """WooCommerce returns a product under its parent term AND its children.

        Listing the children alongside the parent therefore fetches the same
        products two or three times, pays for it in requests on every run, and
        discards the duplicates at dedupe.
        """
        assert len(next(s for s in STORES if s.id == store_id).collections) == 1

    def test_hitech_gamez_keeps_its_pre_owned_category(self) -> None:
        """Dropping it would lose rows AND the only signal that they are used.

        infer_condition reads the store's own category name out of the listing
        context, so this slug is where that store's second-hand stock becomes
        knowable at all.
        """
        store = next(s for s in STORES if s.id == "hitechgamez")
        assert "preowned-nintendo-switch-games" in store.collections

    @pytest.mark.parametrize("store_id", NEW_BATCH_BROWSER)
    def test_every_added_browser_store_has_a_profile(self, store_id: str) -> None:
        """A BROWSER store with no profile fails immediately and collects nothing."""
        from switch_tracker.adapters.browser.profiles import PROFILES

        store = next(s for s in STORES if s.id == store_id)
        assert store.kind is AdapterKind.BROWSER
        assert store_id in PROFILES

    def test_gameland_scrapes_its_games_category_not_its_platform_page(self) -> None:
        """The platform landing page is a superset carrying accessories too.

        Those get dropped by the classifier, but they still cost pages of a
        budgeted walk -- and pages that yield nothing are exactly what the
        productivity tracker reads as "catalogue exhausted".
        """
        store = next(s for s in STORES if s.id == "gameland")
        assert len(store.search_urls) == 2
        for url in store.search_urls:
            assert "/product-category/games/" in url
            # The WOOF filter plugin's marker. Without it pdt_type is inert and
            # the UNFILTERED category comes back, silently undoing the scoping.
            assert "swoof=1" in url

    def test_cex_scopes_to_its_two_switch_category_ids(self) -> None:
        """1038 = Switch Software, 1086 = Switch 2 Games."""
        store = next(s for s in STORES if s.id == "cex_in")
        assert [url for url in store.search_urls if "categoryIds=1038" in url]
        assert [url for url in store.search_urls if "categoryIds=1086" in url]


class TestOverrides:
    def test_the_overrides_file_lives_in_the_data_dir_not_the_working_directory(
        self, data_dir: Path
    ) -> None:
        """The bug this design removes.

        The TypeScript version used a bare relative path, so the file resolved
        against wherever the process happened to be started. For a CLI run
        from the project folder that is invisible; for a double-clicked exe it
        lands wherever Explorer was.
        """
        assert paths.overrides_path().parent == data_dir

    def test_reads_nothing_when_no_corrections_exist(self, data_dir: Path) -> None:
        assert overrides.read() == {}

    def test_applies_a_corrected_kind(self, data_dir: Path) -> None:
        overrides.set_override("designinfo", kind=AdapterKind.WOOCOMMERCE, note="corrected by probe")
        store = next(s for s in overrides.active_stores() if s.id == "designinfo")
        assert store.kind is AdapterKind.WOOCOMMERCE

    def test_applies_a_disable(self, data_dir: Path) -> None:
        overrides.set_override("nistore", enabled=False, note="unreachable when probed")
        store = next(s for s in overrides.active_stores() if s.id == "nistore")
        assert store.enabled is False

    def test_leaves_uncorrected_stores_alone(self, data_dir: Path) -> None:
        overrides.set_override("nistore", enabled=False)
        store = next(s for s in overrides.active_stores() if s.id == "nekavo")
        assert store.enabled is True

    def test_merges_successive_corrections_for_one_store(self, data_dir: Path) -> None:
        overrides.set_override("nistore", kind=AdapterKind.SHOPIFY)
        overrides.set_override("nistore", note="second pass")
        store = next(s for s in overrides.active_stores() if s.id == "nistore")
        assert store.kind is AdapterKind.SHOPIFY
        assert store.note == "second pass"

    def test_ignores_a_corrupt_file_rather_than_crashing(self, data_dir: Path) -> None:
        """A broken corrections file must not take the whole app down.

        The shipped defaults are always a usable fallback.
        """
        paths.overrides_path().write_text("{not json at all")
        assert overrides.read() == {}
        assert len(overrides.active_stores()) == 24

    def test_reset_clears_every_correction(self, data_dir: Path) -> None:
        overrides.set_override("nistore", enabled=False)
        overrides.reset()
        assert overrides.read() == {}
        assert next(s for s in overrides.active_stores() if s.id == "nistore").enabled is True

    def test_has_been_probed_reflects_whether_corrections_exist(self, data_dir: Path) -> None:
        assert overrides.has_been_probed() is False
        overrides.set_override("nistore", note="x")
        assert overrides.has_been_probed() is True

    def test_ignores_a_correction_for_an_unknown_store(self, data_dir: Path) -> None:
        """A stale entry from a renamed store must not invent a phantom store."""
        paths.overrides_path().write_text(json.dumps({"ghost_store": {"enabled": False}}))
        assert len(overrides.active_stores()) == 24
