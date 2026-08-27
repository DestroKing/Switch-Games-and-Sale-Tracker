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
        assert len(STORES) == 14

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
        assert len(overrides.active_stores()) == 14

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
        assert len(overrides.active_stores()) == 14
