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
