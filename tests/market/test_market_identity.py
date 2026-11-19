"""Identity extraction regression tests, including Nintendo product codes."""

from __future__ import annotations

import pytest

from switch_tracker.core.matcher import match_key
from switch_tracker.market.identity import extract
from switch_tracker.market.models import Format


@pytest.mark.parametrize(
    ("title", "platform", "edition", "key", "fmt"),
    [
        ("Cyberpunk 2077 Ultimate Edition – Nintendo Switch 2", "SWITCH2", "ULTIMATE", "cyberpunk 2077", Format.UNKNOWN),
        ("Grand Theft Auto: The Trilogy – The Definitive Edition – Nintendo Switch", "SWITCH", "DEFINITIVE", "grand theft auto trilogy", Format.UNKNOWN),
        ("Red Dead Redemption Standard Edition – Nintendo Switch", "SWITCH", "STANDARD", "red dead redemption", Format.UNKNOWN),
        ("The Witcher 3 Wild Hunt Complete Edition Nintendo Switch", "SWITCH", "COMPLETE", "witcher 3 wild hunt", Format.UNKNOWN),
        ("Minecraft Legends Deluxe Edition Nintendo Switch", "SWITCH", "DELUXE", "minecraft legends", Format.UNKNOWN),
        ("Kirby's Return to Dream Land Deluxe Nintendo Switch", "SWITCH", "STANDARD", "Kirby's Return to Dream Land Deluxe", Format.UNKNOWN),
        ("Mario Kart 8 Deluxe Nintendo Switch Game", "SWITCH", "STANDARD", "mario kart 8 deluxe", Format.UNKNOWN),
        ("NBA 2K24 Kobe Bryant Edition (Nintendo Switch)", "SWITCH", "BRYANT", "nba 2k24 kobe", Format.UNKNOWN),
        ("Hitman World of Assassination Signature Edition Nintendo Switch 2", "SWITCH2", "SIGNATURE", "hitman world assassination", Format.UNKNOWN),
        ("Mario Kart World – Switch 2 – Digital", "SWITCH2", "STANDARD", "mario kart world", Format.DOWNLOAD_CODE),
        ("Super Mario Galaxy + Super Mario Galaxy 2 switch", "SWITCH", "STANDARD", "super mario galaxy super mario galaxy 2", Format.UNKNOWN),
        ("The Legend of Zelda Breath of the Wild Nintendo Switch 2 Edition", "SWITCH2", "SWITCH2_EDITION", "legend zelda breath wild", Format.UNKNOWN),
        ("Animal Crossing New Horizons Collector's Edition Nintendo Switch", "SWITCH", "COLLECTORS", "animal crossing new horizons", Format.UNKNOWN),
        ("Animal Crossing New Horizons Collectors Edition Nintendo Switch", "SWITCH", "COLLECTORS", "animal crossing new horizons", Format.UNKNOWN),
        ("Persona 5 Royal GOTY Nintendo Switch", "SWITCH", "GOTY", "persona 5 royal", Format.UNKNOWN),
        ("Metroid Prime 4 Game-Key Card Nintendo Switch 2", "SWITCH2", "STANDARD", "metroid prime 4", Format.GAME_KEY_CARD),
        ("Example Game Code in a Box Nintendo Switch", "SWITCH", "STANDARD", "example game", Format.CODE_IN_BOX),
        ("Example Game Bundle Nintendo Switch", "SWITCH", "STANDARD", "example game", Format.UNKNOWN),
        ("Mario + Rabbids Sparks of Hope Nintendo Switch", "SWITCH", "STANDARD", "mario rabbids sparks hope", Format.UNKNOWN),
        ("Clubhouse Games 51 Worldwide Classics Nintendo Switch", "SWITCH", "STANDARD", "clubhouse games 51 worldwide classics", Format.UNKNOWN),
        ("Example Game Deluxe Edition Gold Edition Nintendo Switch", "SWITCH", "DELUXE", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch", "SWITCH", "STANDARD", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Game Card", "SWITCH", "STANDARD", "example game", Format.FULL_GAME_CARD),
        ("Example Game Nintendo Switch Cartridge", "SWITCH", "STANDARD", "example game", Format.FULL_GAME_CARD),
        ("Example Game Nintendo Switch Download Code", "SWITCH", "STANDARD", "example game", Format.DOWNLOAD_CODE),
        ("Example Game Nintendo Switch Digital Code", "SWITCH", "STANDARD", "example game", Format.DOWNLOAD_CODE),
        ("Example Game Nintendo Switch eShop Code", "SWITCH", "STANDARD", "example game", Format.DOWNLOAD_CODE),
        ("Example Game Nintendo Switch Voucher", "SWITCH", "STANDARD", "example game", Format.DOWNLOAD_CODE),
        ("Example Game Nintendo Switch Steelbook", "SWITCH", "STEELBOOK", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Launch Edition", "SWITCH", "LAUNCH", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Day One Edition", "SWITCH", "LAUNCH", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Gold Edition", "SWITCH", "GOLD", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Ultimate Edition", "SWITCH", "ULTIMATE", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Anniversary Edition", "SWITCH", "ANNIVERSARY", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Special Edition", "SWITCH", "SPECIAL", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Limited Edition", "SWITCH", "LIMITED", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Definitive Edition", "SWITCH", "DEFINITIVE", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Complete Edition", "SWITCH", "COMPLETE", "example game", Format.UNKNOWN),
        ("Example Game Nintendo Switch Game of the Year Edition", "SWITCH", "GOTY", "example game", Format.UNKNOWN),
    ],
)
def test_extracts_title_attributes(title, platform, edition, key, fmt):
    attrs = extract(title, "SKU-1", "UNKNOWN", "IN")
    assert (attrs.platform, attrs.edition, attrs.key, attrs.format) == (platform, edition, match_key(key), fmt)


def test_unknown_platform_is_unmatched():
    attrs = extract("A Game With No Platform", "SKU", "UNKNOWN", "IN")
    assert attrs.unmatched == "platform unknown"


def test_bundle_is_unmatched():
    attrs = extract("A Game Bundle Nintendo Switch", "SKU", "SWITCH", "IN")
    assert attrs.unmatched == "bundle: several products in one listing"


@pytest.mark.parametrize(
    ("sku", "title", "platform", "expected_code", "expected_platform", "expected_format"),
    [
        ("", "Mario Kart World BEE-P-AAAAA Nintendo Switch 2", "UNKNOWN", "PC:BEE-P-AAAAA", "SWITCH2", Format.FULL_GAME_CARD),
        ("", "Yoshi and the Mysterious Book BEE P AAKGA SEA Nintendo Switch 2", "SWITCH2", None, "SWITCH2", Format.UNKNOWN),
        ("", "Yoshi and the Mysterious Book BEE-P-AAKGA-SEA Nintendo Switch 2", "UNKNOWN", "PC:BEE-P-AAKGA-SEA", "SWITCH2", Format.FULL_GAME_CARD),
        ("pot-p-abcde", "A Game Nintendo Switch 2", "UNKNOWN", "PC:POT-P-ABCDE", "SWITCH2", Format.GAME_KEY_CARD),
        ("", "A Game NXS-J-ABCDE Nintendo Switch 2", "UNKNOWN", "PC:NXS-J-ABCDE", "SWITCH2", Format.CODE_IN_BOX),
        ("", "A Game HAC-P-ABCDE Nintendo Switch", "UNKNOWN", "PC:HAC-P-ABCDE", "SWITCH", Format.FULL_GAME_CARD),
    ],
)
def test_product_code_prefixes(sku, title, platform, expected_code, expected_platform, expected_format):
    attrs = extract(title, sku, platform, "IN")
    assert attrs.platform == expected_platform
    assert attrs.format == expected_format
    assert (expected_code in attrs.codes) if expected_code else not any(c.startswith("PC:") for c in attrs.codes)


def test_code_platform_conflict_is_reported():
    attrs = extract("A Game Nintendo Switch BEE-P-ABCDE", "", "SWITCH", "IN")
    assert "product code says SWITCH2, title says SWITCH" in attrs.problems


def test_code_format_conflict_is_reported():
    attrs = extract("A Game Game-Key Card Nintendo Switch 2 BEE-P-ABCDE", "", "UNKNOWN", "IN")
    assert any("product code says FULL_GAME_CARD, title says GAME_KEY_CARD" == p for p in attrs.problems)


def test_multiple_product_codes_are_ambiguous():
    attrs = extract("A Game Nintendo Switch HAC-P-ABCDE HAC-P-FGHIJ", "", "UNKNOWN", "IN")
    assert "several product codes" in attrs.problems


@pytest.mark.parametrize("code", ["HAC-P-ABCD", "XYZ-P-ABCDE"])
def test_invalid_product_code_shapes_are_ignored(code):
    attrs = extract(f"A Game Nintendo Switch {code}", "", "UNKNOWN", "IN")
    assert not any(value.startswith("PC:") for value in attrs.codes)


def test_sku_product_id_is_never_assumed_to_be_a_barcode():
    attrs = extract("A Game Nintendo Switch", "7146135519291", "SWITCH", "IN")
    assert not any(value.startswith("EAN:") for value in attrs.codes)


@pytest.mark.parametrize(
    ("label", "digits", "expected"),
    [
        ("EAN", "0045496590420", "EAN:0045496590420"),
        ("UPC", "045496590420", "EAN:0045496590420"),
        ("EAN", "0045496590421", None),
    ],
)
def test_only_valid_labelled_barcodes_are_extracted(label, digits, expected):
    attrs = extract(f"A Game Nintendo Switch {label}: {digits}", "", "SWITCH", "IN")
    assert (expected in attrs.codes) if expected else not any(value.startswith("EAN:") for value in attrs.codes)


def test_region_is_preserved():
    attrs = extract("A Game Nintendo Switch", "", "SWITCH", "JP")
    assert attrs.region == "JP"


def test_unknown_format_is_not_guessed():
    attrs = extract("A Game Nintendo Switch", "", "SWITCH", "IN")
    assert attrs.format is Format.UNKNOWN
