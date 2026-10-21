"""These pin the parser's OBSERVED, known-good behaviour.

Every expected value here was measured, not invented. A failure means the
parser's behaviour changed -- which for a
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
        """Pins the fix for a defect that produced 0.4499 and 4.499 here.

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

    @pytest.mark.parametrize(
        "text",
        [
            "Mario Party Superstars 3 modes",
            "Warriors 4 player co-op",
            "Nintendo Switch Sports 2 players",
            "Hyrule Warriors 2 sealed",
        ],
    )
    def test_a_word_ending_in_rs_is_not_a_rupee_marker(self, text: str) -> None:
        """The bug that made this pattern quote 3 and 4 as prices.

        The marker alternation had no word boundary, so "Rs" matched the "rs"
        INSIDE Superstars and Warriors and captured whatever number followed.
        Every result was a plausible-looking price three orders of magnitude
        too small, written into price history with nothing raising.

        Fixing it by matching only the rupee SYMBOL would work and would also
        throw away "Rs. 3,299" and "INR 2,999", which real Indian storefronts
        write -- and this function is the fallback that runs exactly when a
        store's price selector already failed.
        """
        assert first_rupee_price(text) is None

    def test_a_bare_number_with_no_marker_is_never_a_price(self) -> None:
        assert first_rupee_price("Edition 2 of 4") is None

    def test_does_not_attempt_the_european_decimal_form(self) -> None:
        """parse_price handles "4.499,00"; this pattern will not reach it.

        The digit group here is deliberately narrower than parse_price's input
        -- comma grouping with at most two decimals -- so a dot inside the
        integer part stops the match early. That is the right trade for card
        text scraped off Indian storefronts, which never write money that way,
        and loosening it would restore the sloppy class this pattern replaced.
        Pinned so the narrowing stays a decision.
        """
        assert first_rupee_price("₹4.499,00") == 4.49

    def test_takes_the_first_figure_even_when_it_is_the_struck_out_price(self) -> None:
        """A known limitation, pinned so it is a decision and not a surprise.

        Plain text cannot distinguish an MRP from the selling price beside it.
        The selector layer above handles this properly where a store exposes a
        sale-price element (GameLand's ``ins`` ordering); this fallback cannot.
        """
        assert first_rupee_price("MRP ₹5,999 ₹3,999") == 5999.0


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
            "Nintendo Switch 2 Online Game Bundled With Pokemon Pokopia",
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
            "PXN 2119 Pro Flight Simulator Joystick with Separate Throttle for Nintendo Switch",
            "Hori Fighting Stick Mini for Nintendo Switch",
            "Racing Wheel for Nintendo Switch",
            "M300 Max 2in1 Mini Projector HD 4K With 2.4G 2 Wireless Remote Video Game For TV",
            "Pokémon GO Plus | Auto-Catch Accessory | Handy for Trainers On-the-Go | Nintendo Switch",
            "Poke Ball Plus for Nintendo Switch",
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


def test_exclusions_read_the_title_when_one_is_given() -> None:
    """Tags say what a product is compatible with; the title says what it is."""
    context = "Mario Kart 8 Deluxe Nintendo Switch NINTENDO SWITCH OLED"
    assert classify(context).kind is ProductKind.HARDWARE  # context alone: the old behaviour
    assert classify(context, title="Mario Kart 8 Deluxe Nintendo Switch").kind is ProductKind.GAME
    # The platform still comes from the whole context.
    assert (
        classify("Hogwarts Legacy Nintendo Switch Games", title="Hogwarts Legacy").platform is Platform.SWITCH
    )


class TestRealFeedTitles:
    """Titles exactly as the shops wrote them, from home runs of check_stores --rejected / --list.

    Each was on the wrong side once. The feed adapters pass the title separately
    (``title=``), and these assert through that path.
    """

    @pytest.mark.parametrize(
        "title",
        [
            # nistore: a compatibility list, not a console.
            "Animal Crossing: New Horizons \u2013 Deluxe Edition for Nintendo Switch, Lite, and OLED",
            "Donkey Kong Country: Tropical Freeze for Nintendo Switch/Lite/OLED "
            "\u2013 Ultimate Adventure Edition",
            "Fire Emblem Warriors: Three Hopes \u2013 Nintendo Switch Game (Switch/Lite/OLED Compatible)",
            "Luigi\u2019s Mansion 3: Haunted Adventures on Nintendo Switch, Lite, and OLED",
            "Mario Kart 8 Deluxe \u2013 Ultimate Racing Experience (Switch/Lite/OLED) Nintendo Switch",
            "Super Mario 3D World + Bowser\u2019s Fury for Nintendo Switch Lite & OLED",
            "Super Mario Odyssey: Nintendo Switch Lite & OLED Edition",
            "Super Smash Bros Ultimate \u2013 Nintendo Switch Game for Switch Lite & OLED Consoles",
            "Pokémon Violet + The Hidden Treasure of Area Zero Bundle (Game+DLC) \u2013 Nintendo Switch",
            # HG World: Joy-Con and DLC in the marketing, or alongside "Game Card".
            "Nintendo Switch Sports | Motion-Controlled Athletics | Multiplayer Sports Fun | Best Price | "
            "Joy-Con Compatible | Nintendo Switch Game Cartridge",
            "Super Mario Party Jamboree for Nintendo Switch | Multiplayer Minigame Madness | Joy-Con Fun | "
            "Colorful Board Action | Best Price | Party Favorite",
            "Dying Light Platinum Edition Switch Game Card, Nintendo Zombie Survival Horror, Parkour Action, "
            "Co-Op, DLC Content, Best Price",
            "Overcooked All You Can Eat (Switch) | Nintendo Switch Games Co-op Edition | "
            "Overcooked Game with All DLC Remastered | Best Multiplayer Nintendo Games",
            # nekavo: the boxed game, which also includes a code.
            "Bayonetta 2 Nintendo Switch (Includes Bayonetta Digital Code)",
        ],
    )
    def test_kept_as_games(self, title: str) -> None:
        assert (
            classify(f"{title} Nintendo Switch Games", Platform.SWITCH, title=title).kind is ProductKind.GAME
        )

    @pytest.mark.parametrize(
        ("title", "kind"),
        [
            ("Nintendo Neon Red & Neon Blue Joy-Con (L-R)", ProductKind.HARDWARE),
            ("Nintendo Switch OLED Model White Joy-Con with GST Bill,", ProductKind.HARDWARE),
            ("Nintendo \u2013 Switch 32GB Lite \u2013 Blue", ProductKind.HARDWARE),
            (
                "Brand New NINTENDO Switch Lite | 15+ Best Games Bundle | 160 GB Internal(32+128) | "
                "Blue Edition | Handheld Portable Gaming Console | All Standard Accessories",
                ProductKind.HARDWARE,
            ),
            (
                "Pre Owned NINTENDO Switch V1 | 120+ Best Games Bundle | 1032GB Internal(32+1000) | "
                "Handheld Portable Gaming Console | All Standard Accessories",
                ProductKind.HARDWARE,
            ),
            ("Cricket 19 International Edition Nintendo Switch (Digital Code)", ProductKind.DIGITAL),
            ("NBA 2K27 Nintendo Switch 2 (Download Code Only)", ProductKind.DIGITAL),
            ("HG WORLD Carry Travel Hard Shell Protective Bag \u2013 Switch", ProductKind.ACCESSORY),
            (
                "Sportswear for N-S TNS-0125 | Premium Gaming & Workout Apparel | "
                "Breathable & Sweat-Wicking Fabric",
                ProductKind.ACCESSORY,
            ),
            (
                "Analog Caps Set of 4 NSW-092U | Enhanced Grip & Precision | "
                "Compatible with Nintendo Switch, Switch Lite & OLED | Premium Gaming Accessory",
                ProductKind.ACCESSORY,
            ),
            ("Game Gun TNS-2159 | Nintendo Switch Shooting Grip | FPS Game Accessory", ProductKind.ACCESSORY),
        ],
    )
    def test_dropped_as_not_games(self, title: str, kind: ProductKind) -> None:
        assert classify(f"{title} Nintendo Switch", Platform.SWITCH, title=title).kind is kind

    @pytest.mark.parametrize(
        "title",
        [
            "Super Smash Bros Ultimate for Nintendo Switch | Iconic Fighting Crossover | Massive Roster",
            "Ben 10 | Action-Packed Alien Battles | Best Price | Nintendo Switch Game Cartridge",
        ],
    )
    def test_the_title_s_console_beats_the_category_s(self, title: str) -> None:
        """HG World files these Switch 1 games under a Switch 2 category."""
        result = classify(f"{title} Nintendo Switch 2 Games", Platform.SWITCH, title=title)
        assert result.platform is Platform.SWITCH

    def test_a_title_naming_no_console_still_takes_the_category_s(self) -> None:
        assert classify("Hogwarts Legacy Nintendo Switch 2 Games", title="Hogwarts Legacy").platform is (
            Platform.SWITCH2
        )


def test_a_game_sold_as_a_bundle_of_games_is_still_a_game() -> None:
    """Flipkart, live: "Bundle with" in marketing for a real game collection."""
    title = (
        "Final Fantasy I-VI Collection Nintendo Switch | Classic JRPG Bundle with Six Final Fantasy Titles"
    )
    assert classify(title).kind is ProductKind.GAME


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

    def test_another_console_beats_the_ordinary_word_switch(self) -> None:
        """HG World, live: a PS4 game whose marketing says "Seamless Switch"."""
        title = "The Crew 2 PS4 | Open-World Motorsports | Land, Sea, Air Vehicles | Seamless Switch | Online"
        assert classify(title, Platform.SWITCH).platform is Platform.UNKNOWN

    def test_an_explicit_nintendo_switch_still_wins(self) -> None:
        assert classify("Minecraft Nintendo Switch | also on PS4").platform is Platform.SWITCH

    @pytest.mark.parametrize("title", ["Mario Kart World Switch 2", "Zelda NS2", "Metroid Nintendo Switch 2"])
    def test_switch_2_is_detected(self, title: str) -> None:
        assert classify(title).platform is Platform.SWITCH2

    @pytest.mark.parametrize("title", ["Mario Kart World Switch 2", "Zelda NS2", "Metroid Nintendo Switch 2"])
    def test_switch_2_beats_a_switch_store_hint(self, title: str) -> None:
        """The hint must not flatten Switch 2 stock into Switch.

        Every store in the shipped list carries platform_hint=SWITCH, including
        the ones scoped to a Switch 2 category. If the hint could win, an entire
        Switch 2 catalogue would file itself under the wrong platform -- and
        because platform_of checks SWITCH2 before SWITCH, the bare word "Switch"
        inside "Switch 2" must not be allowed to match first either.

        Both orderings are asserted at once here: explicit marker over hint, and
        SWITCH2 over SWITCH.
        """
        assert classify(title, Platform.SWITCH).platform is Platform.SWITCH2

    def test_a_terse_title_on_a_switch_2_store_still_falls_back_to_the_hint(self) -> None:
        """The hint is a floor, not a competitor.

        Beating it with an explicit Switch 2 marker must not stop it doing its
        actual job on a title that names no console at all.
        """
        assert classify("Hogwarts Legacy", Platform.SWITCH).platform is Platform.SWITCH

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
