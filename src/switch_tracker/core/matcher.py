"""Grouping listings into games -- the cross-store matching pass.

Re-runnable by design: it reads only ``listing.raw_title``/``platform``/
``region``, which are already stored, and rewrites ``game`` and
``listing.game_id`` from scratch. Improving the key below therefore never
requires re-scraping a single shop -- the next pass simply re-groups history
that already exists.

The key is deliberately crude: ``normalise_title`` plus a short stop list.
A missed merge ("Zelda: Tears of the Kingdom" vs "The Legend of Zelda: Tears
of the Kingdom") costs one line in ``matches.local.json``; a WRONG merge would
put two different games' prices in one series and nothing would report it, so
the key errs on the side of splitting. That asymmetry is the same one
parse_price runs on: a missing answer is recoverable, a wrong one is not.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Mapping

from switch_tracker import paths
from switch_tracker.core.parse import normalise_title

# Words that differ between shops' spellings of one game without changing which
# game it is. Region words are here because Play-Asia writes them into the
# title ("Asia English") where normalise_title only strips the parenthesised
# form; the region itself is never lost -- it is its own column on the listing.
#
# NOT "a"/"an": "Pokemon Legends Z-A" tokenises to "... z a", and dropping the
# "a" merges it with any "Legends Z". Single letters carry meaning in titles.
# "for" is here because normalise_title strips "Nintendo Switch 2" before its
# own "for nintendo" rule can fire, leaving "Mario Kart World for".
_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "and",
        "for",
        "nintendo",
        "asia",
        "asian",
        "english",
        "chinese",
        "japanese",
        "eng",
        "version",
        "multi",
        "language",
        "pal",
        "ntsc",
    }
)

# Publisher names Amazon India prepends to the title. Stripped only at the START
# of the key, longest first, and only if a real title is left behind. Left out on
# purpose because titles genuinely begin with them: "sega" (Sega Genesis
# Classics), "capcom" (Capcom Fighting Collection), "konami" (Konami Collection),
# "namco" (Namco Museum), "ea" (EA Sports FC -- "electronic arts" is stripped,
# leaving "ea sports fc 25" as other shops write it).
# ponytail: hand-curated list; extend it from real splits seen in a run, or use
# matches.local.json aliases for one-offs.
_PUBLISHER_PREFIXES = sorted(
    (
        tuple(p.split())
        for p in (
            "warner bros interactive entertainment uk",
            "warner bros interactive entertainment",
            "warner bros interactive",
            "warner bros",
            "square enix",
            "bandai namco entertainment",
            "bandai namco",
            "u i entertainment",
            "ubisoft",
            "electronic arts",
        )
    ),
    key=len,
    reverse=True,
)

#: Straight, curly (U+2019, which shops paste from Word) and backtick.
_APOSTROPHES = str.maketrans("", "", "'\u2019`")


def match_key(title: str) -> str:
    """The grouping key for one raw title. Empty means "cannot match"."""
    # Accents are FOLDED, not stripped: normalise_title drops non-ASCII, which
    # turned "Pokémon" into "pok mon" and split it from every shop that writes
    # "Pokemon". Apostrophes are removed outright for the same reason --
    # "Luigi's Mansion" must not become "luigi s mansion" beside "Luigis".
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    words = normalise_title(folded.translate(_APOSTROPHES)).split()
    words = [w for w in words if w not in _STOPWORDS]
    for prefix in _PUBLISHER_PREFIXES:
        if tuple(words[: len(prefix)]) == prefix:
            rest = words[len(prefix) :]
            # Two words at least: one left over is a stub ("Ubisoft" -> "") or a
            # generic word ("Square Enix Collection" -> "collection") that two
            # different publishers' games would wrongly merge under.
            if len(rest) >= 2:
                words = rest
            break
    return " ".join(words)


def load_aliases() -> dict[str, str]:
    """``matches.local.json``: {"title as one shop writes it": "title to group it under"}.

    Both sides go through match_key, so a person can paste raw titles straight
    from the dashboard instead of having to know the key format. A corrupt
    file is ignored, as stores.local.json is: matching without aliases is
    degraded, not broken.
    """
    path = paths.matches_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {match_key(k): match_key(v) for k, v in loaded.items() if isinstance(v, str) and match_key(v)}


def rematch(conn: sqlite3.Connection, aliases: Mapping[str, str] | None = None) -> int:
    """Recompute every listing's game. Returns how many listings were matched.

    One transaction: a dashboard reading mid-pass sees the old grouping or the
    new one, never half of each. Games left with no listing are deleted, so a
    key that improved does not leave its old spelling behind as an empty game.
    """
    aliases = aliases or {}
    listings = conn.execute("SELECT id, raw_title, platform, region FROM listing").fetchall()

    keyed: list[tuple[int, str, str, str]] = []
    for row in listings:
        key = match_key(row["raw_title"])
        key = aliases.get(key, key)
        # UNKNOWN platform is not a game we can compare; matching it would
        # group a PS5 title with its Switch namesake.
        if key and row["platform"] != "UNKNOWN":
            keyed.append((row["id"], key, row["platform"], row["region"]))

    conn.execute("BEGIN")
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO game (canonical_title, platform, region) VALUES (?, ?, ?)",
            {(key, platform, region) for _, key, platform, region in keyed},
        )
        ids = {
            (r["canonical_title"], r["platform"], r["region"]): r["id"]
            for r in conn.execute("SELECT id, canonical_title, platform, region FROM game")
        }
        conn.execute("UPDATE listing SET game_id = NULL")
        conn.executemany(
            "UPDATE listing SET game_id = ? WHERE id = ?",
            [(ids[(key, platform, region)], listing_id) for listing_id, key, platform, region in keyed],
        )
        conn.execute(
            "DELETE FROM game WHERE id NOT IN (SELECT game_id FROM listing WHERE game_id IS NOT NULL)"
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(keyed)
