"""Port-critical: these encode the TypeScript implementation's OBSERVED behaviour.

Every expected value here was read out of src/core/parse.ts, not invented. A
failure means the port diverged from the system it replaces -- which for a
price tracker is silent data corruption, not a visible crash.
"""

from __future__ import annotations

import pytest

from switch_tracker.core.models import Condition, Platform, ProductKind, Region
from switch_tracker.core.parse import (
    classify,
    first_rupee_price,
    infer_condition,
    infer_region,
    normalise_title,
    parse_price,
    price_looks_wrong,
)


class TestParsePrice:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("₹4,499.00", 4499.0),
            ("Rs. 4499", 4499.0),
            ("Rs 4,499", 4499.0),
            ("INR 4,499", 4499.0),
            ("₹1,299.50", 1299.5),
            ("1,234,567", 1234567.0),
            ("3599", 3599.0),
        ],
    )
    def test_reads_the_ways_indian_storefronts_write_a_price(self, raw: str, expected: float) -> None:
        assert parse_price(raw) == expected

    def test_lone_comma_is_a_thousands_separator_never_a_decimal_point(self) -> None:
        """The regression that silently divided real prices by ~1000.

        "₹3,599" is three thousand five hundred ninety-nine. A naive
        "whichever separator comes last wins" rule reads it as 3.599, and
        every whole-rupee price written without a trailing ".00" -- which is
        the normal way to write one -- comes out 1000x too small.
        """
        assert parse_price("₹3,599") == 3599.0

    def test_european_format_uses_comma_as_the_decimal_point(self) -> None:
        assert parse_price("4.499,00") == 4499.0

    @pytest.mark.parametrize(("raw", "expected"), [("Rs. 4499", 4499.0), ("Rs. 4,499", 4499.0)])
    def test_the_period_in_rs_is_not_a_decimal_point(self, raw: str, expected: float) -> None:
        """Fixes a defect in parse.ts, which produced 0.4499 and 4.499 here.

        The period in "Rs." is inside its [^\\d.,] allow-list, so it survived
        the strip and was read as a decimal point -- silently, and reachable
        from any browser-scraped store that writes prices this way.
        """
        assert parse_price(raw) == expected

    @pytest.mark.parametrize("raw", ["", "abc", "   ", None])
    def test_returns_none_on_failure_never_zero(self, raw: str | None) -> None:
        """Zero is a real price. Inventing it to signal failure loses that."""
        assert parse_price(raw) is None

    def test_accepts_a_number_unchanged(self) -> None:
        assert parse_price(4499) == 4499.0

    def test_rejects_a_non_finite_number(self) -> None:
        assert parse_price(float("inf")) is None


class TestFirstRupeePrice:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Mario Kart World ₹4,499 Add to cart", 4499.0),
            ("Price Rs. 3,299 only", 3299.0),
            ("INR 2,999", 2999.0),
        ],
    )
    def test_pulls_the_first_rupee_figure_out_of_card_text(self, text: str, expected: float) -> None:
        assert first_rupee_price(text) == expected

    def test_returns_none_when_no_rupee_figure_present(self) -> None:
        assert first_rupee_price("Out of stock") is None


class TestClassifyExclusions:
    """Exclusions run BEFORE platform matching. This ordering is load-bearing."""

    def test_pro_controller_is_hardware_not_a_game_despite_saying_switch(self) -> None:
        """'Nintendo Switch Pro Controller' contains the console's name.

        If platform matching ran first it would sail through as a Switch game.
        """
        assert classify("Nintendo Switch Pro Controller").kind is ProductKind.HARDWARE

    @pytest.mark.parametrize(
        "title",
        [
            "Nintendo Switch OLED Console",
            "Nintendo Switch Lite Console",
            "Nintendo Switch Joy-Con Pair",
            "Nintendo Switch Docking Station",
        ],
    )
    def test_hardware_is_excluded(self, title: str) -> None:
        assert classify(title).kind is ProductKind.HARDWARE

    @pytest.mark.parametrize(
        "title",
        [
            "Nintendo Switch Carrying Case",
            "Switch Screen Protector",
            "Switch Tempered Glass",
            "amiibo Link",
            "Switch Cooling Pad",
            "Nintendo Switch Controller Grip",
            "Micro SD Card 128GB for Switch",
        ],
    )
    def test_accessories_are_excluded(self, title: str) -> None:
        assert classify(title).kind is ProductKind.ACCESSORY

    @pytest.mark.parametrize(
        "title",
        [
            "Nintendo eShop Gift Card",
            "Nintendo Switch Online Membership",
            "Zelda Digital Code",
            "Mario Kart Season Pass",
        ],
    )
    def test_digital_is_excluded(self, title: str) -> None:
        assert classify(title).kind is ProductKind.DIGITAL

    def test_a_service_is_excluded(self) -> None:
        """A real listing shape: names the console, sells labour not a cartridge."""
        assert classify("Nintendo OLED game loading service").kind is ProductKind.SERVICE


class TestClassifyPlatform:
    def test_a_terse_title_is_kept_when_the_store_hints_switch_only(self) -> None:
        result = classify("Hogwarts Legacy", Platform.SWITCH)
        assert result.platform is Platform.SWITCH
        assert result.kind is ProductKind.GAME

    def test_a_terse_title_is_unknown_without_a_hint(self) -> None:
        """A general retailer must not have every bare title assumed Switch."""
        result = classify("Hogwarts Legacy")
        assert result.platform is Platform.UNKNOWN
        assert result.kind is ProductKind.UNKNOWN

    def test_an_explicit_other_console_beats_the_store_hint(self) -> None:
        """A hint means 'assume Switch when nothing is said'.

        It must never mean 'assume Switch even when the text names a
        different console' -- that leaks every PS/Xbox title through as a
        false Switch match on a multi-platform retailer.
        """
        assert classify("Hogwarts Legacy PS5", Platform.SWITCH).platform is Platform.UNKNOWN

    @pytest.mark.parametrize(
        "title",
        ["FIFA 23 Xbox", "God of War PlayStation 5", "Mario Kart Wii U", "Pokemon 3DS", "Zelda GameCube"],
    )
    def test_other_consoles_are_not_switch(self, title: str) -> None:
        assert classify(title, Platform.SWITCH).platform is Platform.UNKNOWN

    @pytest.mark.parametrize(
        "title", ["Mario Kart World Switch 2", "Zelda NS2", "Metroid Nintendo Switch 2"]
    )
    def test_switch_2_is_detected(self, title: str) -> None:
        assert classify(title).platform is Platform.SWITCH2

    @pytest.mark.parametrize("title", ["Hogwarts Legacy NSW", "Hogwarts Legacy NS", "Zelda Nintendo Switch"])
    def test_terse_importer_markers_count_as_switch(self, title: str) -> None:
        """'NSW'/'NS' are genuinely used by Indian importers in terse titles."""
        assert classify(title).platform is Platform.SWITCH


class TestInferRegion:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Zelda (Asia Chinese)", Region.ASIA_ZH),
            ("Zelda (Asia English)", Region.ASIA_EN),
            ("Zelda JP Version", Region.JP),
            ("Zelda NTSC-U", Region.US),
            ("Zelda PAL", Region.EU),
            ("Zelda Asia", Region.ASIA_EN),
        ],
    )
    def test_reads_the_region_out_of_the_title(self, title: str, expected: Region) -> None:
        assert infer_region(title, Region.IN) is expected

    def test_falls_back_to_the_store_default(self) -> None:
        assert infer_region("Mario Kart World", Region.IN) is Region.IN


class TestInferCondition:
    @pytest.mark.parametrize(
        "context",
        ["Pre-Owned Games", "Zelda (Used)", "Refurbished Switch game", "Open Box", "Second-hand", "Renewed"],
    )
    def test_detects_pre_owned_from_the_stores_own_text(self, context: str) -> None:
        assert infer_condition(context) is Condition.PRE_OWNED

    def test_defaults_to_new_not_unknown(self) -> None:
        """Most stores never say 'new' outright because nothing else it could be.

        UNKNOWN as the default would make the condition filter useless.
        """
        assert infer_condition("Mario Kart World") is Condition.NEW


class TestNormaliseTitle:
    def test_strips_console_and_format_noise(self) -> None:
        got = normalise_title("The Legend of Zelda: Tears of the Kingdom (Nintendo Switch)")
        assert got == "the legend of zelda tears of the kingdom"

    def test_strips_importer_markers_and_bracketed_regions(self) -> None:
        assert normalise_title("Hogwarts Legacy NSW [Asia]") == "hogwarts legacy"

    def test_strips_condition_words(self) -> None:
        assert normalise_title("Mario Kart 8 Deluxe - Brand New Sealed") == "mario kart 8 deluxe"

    def test_collapses_whitespace_and_punctuation(self) -> None:
        assert normalise_title("  Metroid   Dread!!  ") == "metroid dread"


class TestPriceLooksWrong:
    @pytest.mark.parametrize("inr", [0.0, 99.0, 298.0, 12_001.0, 99_999.0])
    def test_flags_prices_that_make_no_sense_for_a_cartridge(self, inr: float) -> None:
        assert price_looks_wrong(inr, ProductKind.GAME) is True

    @pytest.mark.parametrize("inr", [299.0, 4499.0, 12_000.0])
    def test_accepts_a_plausible_cartridge_price(self, inr: float) -> None:
        assert price_looks_wrong(inr, ProductKind.GAME) is False

    def test_only_judges_games(self) -> None:
        """A console legitimately costs far more than any cartridge."""
        assert price_looks_wrong(35_000.0, ProductKind.HARDWARE) is False
