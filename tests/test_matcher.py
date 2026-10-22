"""Cross-store matching: the key, the re-runnable pass, and its hook into a run.

The cases that matter most are the ones that must NOT merge. A missed merge
costs one alias; a wrong merge puts two games' prices in one series and
nothing reports it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from switch_tracker import paths
from switch_tracker.core import db, matcher
from switch_tracker.core.matcher import match_key


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "m.db")
    db.ensure_schema(c)
    c.execute("INSERT INTO store VALUES ('a','A','https://a','SHOPIFY','INR',2,1)")
    c.execute("INSERT INTO store VALUES ('b','B','https://b','SHOPIFY','INR',2,1)")
    return c


def add(
    conn: sqlite3.Connection, lid: int, store: str, title: str, platform: str = "SWITCH", region: str = "IN"
) -> None:
    conn.execute(
        "INSERT INTO listing (id, store_id, sku, url, raw_title, platform, region, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,'t','t')",
        (lid, store, f"sku{lid}", f"https://x/{lid}", title, platform, region),
    )


def game_of(conn: sqlite3.Connection, lid: int) -> int | None:
    return conn.execute("SELECT game_id FROM listing WHERE id = ?", (lid,)).fetchone()["game_id"]


class TestMatchKey:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Pokémon Legends: Z-A (Nintendo Switch 2)", "Pokemon Legends Z-A - Switch 2"),
            ("Luigi\u2019s Mansion 3 Nintendo Switch", "Luigis Mansion 3"),
            (
                "Mario Kart World (Asia English) for Nintendo Switch 2",
                "Mario Kart World - Nintendo Switch 2 Game",
            ),
            ("Zelda Tears of the Kingdom - Pre-Owned", "Zelda: Tears of the Kingdom (Nintendo Switch)"),
            # Amazon India prepends the publisher.
            ("Warner Bros Interactive Entertainment LEGO City Undercover", "LEGO City Undercover"),
            (
                "Warner Bros. Interactive Entertainment UK Harry Potter Quidditch Champions Deluxe",
                "Harry Potter: Quidditch Champions Deluxe",
            ),
            (
                "Square Enix Final Fantasy VII & VIII Remastered Twin Pack",
                "Final Fantasy VII VIII Remastered Twin Pack",
            ),
            ("U&I Entertainment Hotline Miami Collection", "Hotline Miami Collection"),
            ("Electronic Arts EA Sports FC 25", "EA Sports FC 25"),
            # Flipkart: "Name | marketing | marketing" -- real titles from a live run.
            (
                "Mario Kart World Nintendo Switch 2 | Premium Racing Adventure | Best Physical Switch",
                "Mario Kart World - Nintendo Switch 2",
            ),
            (
                "Neon White Nintendo Switch Games CD | Lightning-Fast First-Person Action Platformer",
                "Neon White - Nintendo Switch",
            ),
            ("Taxi Chaos 2 | Standard Edition | Switch", "Taxi Chaos 2 - Nintendo Switch"),
            # Tales of Vesperia, live: three spellings were three games. Play-Asia's
            # "NSW™" folded to "nswtm", its "[Definitive Edition]" was deleted
            # outright, and Amazon's "(tbd)" stayed in the key.
            (
                "NSW™, NSW2™ Tales of Vesperia [Definitive Edition] (Europe)",
                "Tales Of Vesperia - Definitive Edition (Switch)",
            ),
            ("Tales of Vesperia Definitive Edition(tbd)", "Tales Of Vesperia - Definitive Edition (Switch)"),
            # Trademark signs anywhere (mcubegames, live).
            ("Mario Tennis™ Fever - Nintendo Switch 2", "Mario Tennis fever - Nintendo Switch 2"),
            # Store notes in brackets, or Amazon's outside them -- all live.
            ("Dragon Ball Xenoverse 2 (Replen)", "Dragon Ball Xenoverse 2 Nintendo Switch"),
            ("Lego Worlds Nla", "LEGO Worlds Nintendo Switch"),
            ("Lego Jurassic World (NA)", "LEGO Jurassic World Nintendo Switch"),
            (
                "Lego Marvel Superheroes 2 | Standard Edition | Nintendo Switch (CIB)",
                "LEGO Marvel Superheroes 2",
            ),
            (
                "Pokémon: Let\u2019s Go, Eevee! (Nintendo Switch) (NORMAL)",
                "Pokemon Lets Go Eevee Nintendo Switch",
            ),
            ("Switch - New Super Mario Bros. U Deluxe - [PAL EU - NO NTSC]", "New Super Mario Bros U Deluxe"),
            (
                "LEGO Star Wars: The Skywalker Saga (Nintendo Switch) [AT-PEGI]",
                "Lego Star Wars Skywalker Saga",
            ),
            ("Spyro Reignited Trilogy - [Nintendo Switch]", "Spyro Reignited Trilogy Nintendo Switch"),
            (
                "Bayonetta 2 Nintendo Switch (Includes Bayonetta Digital Code)",
                "Bayonetta 2 - Nintendo Switch",
            ),
            # A condition note in brackets must not leave "owned" behind (gameloot, live).
            ("13 Sentinels Aegis Rim Nintendo Switch (Pre-owned)", "13 Sentinels Aegis Rim Nintendo Switch"),
            # Play-Asia's cover-art variants and notes, from a home run.
            (
                "NSW™, NSW2™ Clock Tower Rewind (Multi-Language) (Cover - English) (Asia)",
                "Clock Tower: Rewind Nintendo Switch",
            ),
            ("NSW™, NSW2™ Capcom Fighting Collection 2 (French Cover) (US)", "Capcom Fighting Collection 2"),
            ("NSW™, NSW2™ Astral Chain (MDE)", "Astral Chain Nintendo Switch"),
            (
                "NSW™, NSW2™ Atelier Sophie 2: The Alchemist of the Mysterious Dream (Korea)",
                "NSW™, NSW2™ Atelier Sophie 2: The Alchemist of the Mysterious Dream (Japan)",
            ),
            (
                "NSW™, NSW2™ Capcom Belt Action Collection [Best Price] (Multi-Language) (Japan)",
                "Capcom: Belt Action Collection Nintendo Switch",
            ),
            ("60 in 1 Game Collection (Dates Tbd)", "60 IN 1 GAME COLLECTION (SWITCH)"),
            ("Cat Quest \u2013 Nintendo Switch [video game]", "Cat Quest Nintendo Switch"),
            (
                "NSW2™ Back to the Dawn [Limited Edition] (Multi-Language) Game Key Cart (Japan)",
                "NSW2™ Back to the Dawn [Limited Edition] (Multi-Language) (Japan)",
            ),
            # Condition, subtitles, compatibility and shop typos (home run, live).
            ("Nintendo Ring Fit Adventure Switch (OPEN BOX)", "Ring Fit Adventure Nintendo Switch"),
            (
                "NSW™, NSW2™ Dragon Quest Builders 2 (Chinese Subs) (Asia)",
                "Dragon Quest Builders 2 Nintendo Switch",
            ),
            (
                "Super Mario 3D World + Bowser\u2019s Fury for Nintendo Switch Lite & OLED",
                "Super Mario 3D World + Bowser's Fury",
            ),
            (
                "Ni No Kuni Wrath of the White Witch Ninteno Switch",
                "Ni No Kuni Wrath of the White Witch - Nintendo Switch",
            ),
            # The physical format, said three ways (Flipkart, hadiro, live).
            ("PRAGMATA (Game-Key Card) for Nintendo Switch 2", "Pragmata - Nintendo Switch 2"),
            ("Princess Peach Showtime Nintendo Game Card", "Princess Peach Showtime! Nintendo Switch"),
        ],
    )
    def test_merges_spellings_of_one_game(self, a: str, b: str) -> None:
        assert match_key(a) == match_key(b)

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            # A single letter is part of the title: dropping "a" as an article
            # would merge these.
            ("Pokemon Legends Z-A", "Pokemon Legends Z"),
            ("Mario Kart 8 Deluxe", "Mario Kart 8"),
            ("Xenoblade Chronicles 2", "Xenoblade Chronicles 3"),
            ("EA Sports FC 24", "EA Sports FC 25"),
            # The publisher word IS the title here: never stripped.
            ("Sega Genesis Classics", "Genesis Classics"),
            ("Capcom Fighting Collection", "Fighting Collection"),
            # Only a prefix is stripped, never a word mid-title.
            ("Mario & Sonic at the Olympic Games", "Mario at the Olympic Games"),
            # An edition, a variant word or a number after "|" is part of the product.
            ("Shinobi: Art of Vengeance | Deluxe Edition | Switch 2", "Shinobi: Art of Vengeance"),
            ("Sonic Frontiers | Definitive Edition | Switch 2", "Sonic Frontiers"),
            ("Pikmin | Twin Pack", "Pikmin"),
            ("Little Nightmares | Switch Complete Edition", "Little Nightmares"),
            ("Xenoblade Chronicles | 3", "Xenoblade Chronicles"),
            # No console before the bar: the tail is a subtitle, sequel or DLC.
            ("Fire Emblem | Three Houses", "Fire Emblem | Engage"),
            ("Mario + Rabbids | Sparks of Hope", "Mario + Rabbids | Kingdom Battle"),
            ("Persona 5 | Tactica", "Persona 5"),
            ("Splatoon 3 | Side Order", "Splatoon 3"),
            # A partial copy is less than the product (gameloot, live).
            (
                "Borderlands Legendary Collection (Includes only Borderlands 1 Full Game) Nintendo Switch",
                "Borderlands Legendary Collection Nintendo Switch",
            ),
            # Brackets keep the product: an edition or format inside them is real.
            ("Tales of Vesperia [Definitive Edition] (Europe)", "Tales of Vesperia (Europe)"),
            ("Persona 5 Royal [Deluxe Edition] (Asia)", "Persona 5 Royal (Asia)"),
            (
                "LEGO Marvel Superheroes 2 [Code In A Box] (Switch)",
                "LEGO Marvel Superheroes 2 Nintendo Switch",
            ),
            ("Fire Emblem Engage : Divine Edition - Nintendo Switch", "Fire Emblem Engage - Nintendo Switch"),
            ("Mario + Rabbids Sparks of Hope - Cosmic Edition /Switch", "Mario + Rabbids Sparks of Hope"),
            (
                "Resident Evil Requiem Lenticular Edition - Nintendo Switch 2",
                "Resident Evil Requiem - Switch 2",
            ),
            # "card" is only the format when it says "game card" or "key card".
            ("Pokemon Trading Card Game", "Pokemon Trading Game"),
            # Region notes are dropped only INSIDE brackets: outside, they're words.
            ("Among Us - Nintendo Switch", "Among - Nintendo Switch"),
        ],
    )
    def test_keeps_different_games_apart(self, a: str, b: str) -> None:
        assert match_key(a) != match_key(b)

    def test_a_title_that_is_all_noise_cannot_match(self) -> None:
        assert match_key("Nintendo Switch Game (Asia)") == ""

    def test_a_head_that_is_all_noise_keys_the_whole_title(self) -> None:
        assert match_key("Nintendo Switch 2 | Mario Kart World") == "mario kart world"

    @pytest.mark.parametrize(
        ("title", "key"),
        [
            ("Ubisoft", "ubisoft"),
            ("Square Enix Collection", "square enix collection"),
            ("Bandai Namco Museum", "bandai namco museum"),
        ],
    )
    def test_a_publisher_prefix_never_leaves_an_empty_or_stub_key(self, title: str, key: str) -> None:
        assert match_key(title) == key


class TestRematch:
    def test_groups_one_game_across_stores(self, conn) -> None:
        add(conn, 1, "a", "Luigi's Mansion 3")
        add(conn, 2, "b", "Luigis Mansion 3 - Nintendo Switch")
        assert matcher.rematch(conn) == 2
        assert game_of(conn, 1) == game_of(conn, 2) is not None

    def test_platform_and_region_stay_separate_games(self, conn) -> None:
        """The schema keys region: Play-Asia's regional SKUs are different products."""
        add(conn, 1, "a", "Mario Kart World", platform="SWITCH2", region="IN")
        add(conn, 2, "b", "Mario Kart World", platform="SWITCH2", region="JP")
        add(conn, 3, "b", "Mario Kart World", platform="SWITCH", region="IN")
        matcher.rematch(conn)
        assert len({game_of(conn, 1), game_of(conn, 2), game_of(conn, 3)}) == 3

    def test_unknown_platform_is_never_matched(self, conn) -> None:
        add(conn, 1, "a", "Hogwarts Legacy", platform="UNKNOWN")
        assert matcher.rematch(conn) == 0
        assert game_of(conn, 1) is None

    def test_is_idempotent_and_removes_games_nothing_points_at(self, conn) -> None:
        add(conn, 1, "a", "Metroid Prime")
        matcher.rematch(conn)
        conn.execute("UPDATE listing SET raw_title = 'Metroid Prime Remastered' WHERE id = 1")
        matcher.rematch(conn)
        matcher.rematch(conn)
        titles = [r["canonical_title"] for r in conn.execute("SELECT canonical_title FROM game")]
        assert titles == ["metroid prime remastered"]

    def test_an_alias_merges_what_the_key_misses(self, conn) -> None:
        add(conn, 1, "a", "The Legend of Zelda: Tears of the Kingdom")
        add(conn, 2, "b", "Zelda Tears of the Kingdom")
        matcher.rematch(conn)
        assert game_of(conn, 1) != game_of(conn, 2)
        aliases = {
            match_key("Zelda Tears of the Kingdom"): match_key("The Legend of Zelda: Tears of the Kingdom")
        }
        matcher.rematch(conn, aliases)
        assert game_of(conn, 1) == game_of(conn, 2)

    def redirects(self, conn) -> dict[str, str]:
        return {r["old_title"]: r["new_title"] for r in conn.execute("SELECT * FROM game_redirect")}

    def test_a_re_keyed_game_records_where_it_went(self, conn) -> None:
        """Watches are stored by key; a matcher change must leave a forwarding address."""
        add(conn, 1, "a", "Mario Kart World Nintendo Switch 2 | Premium Racing Adventure")
        conn.execute(
            "INSERT INTO game (canonical_title, platform, region) VALUES ('old key', 'SWITCH', 'IN')"
        )
        conn.execute("UPDATE listing SET game_id = last_insert_rowid()")
        matcher.rematch(conn)
        assert self.redirects(conn) == {"old key": "mario kart world"}

    def test_a_key_split_across_new_games_records_no_guess(self, conn) -> None:
        add(conn, 1, "a", "Mario Kart World")
        add(conn, 2, "b", "Donkey Kong Bananza")
        conn.execute(
            "INSERT INTO game (canonical_title, platform, region) VALUES ('old key', 'SWITCH', 'IN')"
        )
        conn.execute("UPDATE listing SET game_id = last_insert_rowid()")
        matcher.rematch(conn)
        assert self.redirects(conn) == {}

    def test_a_key_still_in_use_is_not_redirected(self, conn) -> None:
        add(conn, 1, "a", "Mario Kart World")
        matcher.rematch(conn)
        matcher.rematch(conn)
        assert self.redirects(conn) == {}

    def test_a_key_back_in_use_drops_its_old_redirect(self, conn) -> None:
        conn.execute("INSERT INTO game_redirect VALUES ('mario kart world', 'SWITCH', 'something else')")
        add(conn, 1, "a", "Mario Kart World")
        matcher.rematch(conn)
        assert self.redirects(conn) == {}

    def test_rematching_existing_listings_consolidates_and_redirects_old_groups(self, conn) -> None:
        """Tales of Vesperia end to end: the old three-way split, fixed by a rematch alone."""
        titles = [
            (1, "a", "NSW™, NSW2™ Tales of Vesperia [Definitive Edition] (Europe)", "EU"),
            (2, "a", "Tales of Vesperia Definitive Edition(tbd)", "IN"),
            (3, "b", "Tales Of Vesperia - Definitive Edition (Switch)", "IN"),
        ]
        old_keys = [
            "nswtm nsw2tm tales vesperia",
            "tales vesperia definitive tbd",
            "tales vesperia definitive",
        ]
        for (lid, store, title, region), key in zip(titles, old_keys, strict=True):
            add(conn, lid, store, title, region=region)
            conn.execute(
                "INSERT INTO game (canonical_title, platform, region) VALUES (?, 'SWITCH', ?)", (key, region)
            )
            conn.execute("UPDATE listing SET game_id = last_insert_rowid() WHERE id = ?", (lid,))
        matcher.rematch(conn)
        keys = {r["canonical_title"] for r in conn.execute("SELECT canonical_title FROM game")}
        assert keys == {"tales vesperia definitive"}  # one game; the EU copy is its own region row
        assert self.redirects(conn) == {
            "nswtm nsw2tm tales vesperia": "tales vesperia definitive",
            "tales vesperia definitive tbd": "tales vesperia definitive",
        }


class TestConfirmedMerges:
    """Merges the key alone can't make safely, made only when the data confirms them."""

    def test_a_publisher_prefix_comes_off_when_another_listing_confirms_the_rest(self, conn) -> None:
        add(conn, 1, "a", "Sega Sonic Forces: Standard Edition - Nintendo Switch")
        add(conn, 2, "b", "Sonic Forces Nintendo Switch")
        add(conn, 3, "a", "Capcom Monster Hunter: Rise")
        add(conn, 4, "b", "Monster Hunter Rise Nintendo Switch")
        # A publisher named "... Games" (normalise_title drops that word first).
        add(conn, 5, "a", "Maximum Games Alfred Hitchcock: Vertigo - Limited Edition (Nintendo Switch)")
        add(conn, 6, "b", "Alfred Hitchcock Vertigo Limited Edition Switch")
        matcher.rematch(conn)
        assert game_of(conn, 1) == game_of(conn, 2)
        assert game_of(conn, 3) == game_of(conn, 4)
        assert game_of(conn, 5) == game_of(conn, 6)

    def test_a_publisher_word_that_is_the_title_stays(self, conn) -> None:
        add(conn, 1, "a", "Sega Genesis Classics")
        add(conn, 2, "b", "Capcom Fighting Collection")
        add(conn, 3, "b", "Marvel vs Capcom Fighting Collection")
        matcher.rematch(conn)
        keys = {r["canonical_title"] for r in conn.execute("SELECT canonical_title FROM game")}
        assert keys == {
            "sega genesis classics",
            "capcom fighting collection",
            "marvel vs capcom fighting collection",
        }

    def test_the_same_words_in_another_order_are_one_game(self, conn) -> None:
        add(conn, 1, "a", "FC 26 EA SPORTS Nintendo Switch")
        add(conn, 2, "b", "EA Sports FC 26 Nintendo Switch")
        add(conn, 3, "b", "EA Sports FC 26 - Nintendo Switch")
        add(conn, 4, "a", "PAW Patrol World - Paw Patrol - Nintendo Switch Game")
        add(conn, 5, "b", "Paw Patrol World Nintendo Switch")
        matcher.rematch(conn)
        assert game_of(conn, 1) == game_of(conn, 2) == game_of(conn, 3)
        assert game_of(conn, 4) == game_of(conn, 5)
        # Named after the spelling most shops use.
        assert "ea sports fc 26" in {
            r["canonical_title"] for r in conn.execute("SELECT canonical_title FROM game")
        }

    def test_word_order_still_matters_around_vs(self, conn) -> None:
        add(conn, 1, "a", "Capcom vs SNK")
        add(conn, 2, "b", "SNK vs Capcom")
        matcher.rematch(conn)
        assert game_of(conn, 1) != game_of(conn, 2)

    def test_an_alias_still_wins_and_joins_the_consolidated_group(self, conn) -> None:
        add(conn, 1, "a", "Sega Sonic Forces")
        add(conn, 2, "b", "Sonic Forces")
        add(conn, 3, "b", "Sonik Forsez")  # a spelling no rule can fix
        aliases = {match_key("Sonik Forsez"): match_key("Sega Sonic Forces")}
        matcher.rematch(conn, aliases)
        assert game_of(conn, 1) == game_of(conn, 2) == game_of(conn, 3)


class TestPlatformFromTitle:
    """The title's console wins at collection time, so a rematch can repair rows saved under older rules."""

    def platform(self, conn, lid: int) -> str:
        return conn.execute("SELECT platform FROM listing WHERE id = ?", (lid,)).fetchone()["platform"]

    def test_a_switch_2_edition_saved_as_switch_is_relabelled_and_kept_apart(self, conn) -> None:
        """mcubegames, live: the "™" in "Switch™ 2" hid the Switch 2 marker."""
        add(conn, 1, "a", "Xenoblade Chronicles™ X Definitive Edition \u2013 Nintendo Switch™ 2 Edition")
        add(conn, 2, "a", "Xenoblade Chronicles™ X: Definitive Edition - Nintendo Switch")
        matcher.rematch(conn)
        assert (self.platform(conn, 1), self.platform(conn, 2)) == ("SWITCH2", "SWITCH")
        assert game_of(conn, 1) != game_of(conn, 2)

    def test_nsw2_is_switch_2_but_a_list_of_both_consoles_is_a_switch_game(self, conn) -> None:
        add(conn, 1, "a", "NSW2™ Mario Kart World (Japan)")  # stored under the store's SWITCH hint
        add(conn, 2, "b", "Mario Kart World - Nintendo Switch 2", platform="SWITCH2")
        add(conn, 3, "a", "NSW™, NSW2™ Tales of Vesperia [Definitive Edition] (Europe)")
        # Both listed, but it also says it IS the Switch 2 Edition (Play-Asia, live).
        add(conn, 4, "a", "NSW™, NSW2™ Kuukiyomi 4: Consider It Nintendo Switch 2 Edition+ (Japan)")
        matcher.rematch(conn)
        assert (self.platform(conn, 1), self.platform(conn, 3), self.platform(conn, 4)) == (
            "SWITCH2",
            "SWITCH",
            "SWITCH2",
        )
        assert game_of(conn, 1) == game_of(conn, 2)

    def test_a_title_naming_no_console_keeps_the_stored_platform(self, conn) -> None:
        add(conn, 1, "a", "Hogwarts Legacy", platform="SWITCH2")  # from the store's category
        matcher.rematch(conn)
        assert self.platform(conn, 1) == "SWITCH2"

    def test_genuinely_different_platforms_stay_apart(self, conn) -> None:
        add(conn, 1, "a", "Hades II - Nintendo Switch")
        add(conn, 2, "b", "Hades II - Nintendo Switch 2")
        matcher.rematch(conn)
        assert game_of(conn, 1) != game_of(conn, 2)


class TestAliasesFile:
    def test_raw_titles_on_both_sides_are_keyed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
        paths.data_dir.cache_clear()
        try:
            paths.matches_path().write_text(
                json.dumps({"Zelda: Tears of the Kingdom": "The Legend of Zelda: Tears of the Kingdom"}),
                encoding="utf-8",
            )
            assert matcher.load_aliases() == {"zelda tears kingdom": "legend zelda tears kingdom"}
        finally:
            paths.data_dir.cache_clear()

    def test_a_corrupt_file_means_no_aliases_not_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
        paths.data_dir.cache_clear()
        try:
            paths.matches_path().write_text("{not json", encoding="utf-8")
            assert matcher.load_aliases() == {}
        finally:
            paths.data_dir.cache_clear()
