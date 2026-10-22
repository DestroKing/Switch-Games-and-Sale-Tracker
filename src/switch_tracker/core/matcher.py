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
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping

from switch_tracker import paths
from switch_tracker.core.models import Platform
from switch_tracker.core.parse import MARKS, named_platform, normalise_title, platform_of

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
        # Flipkart's "Nintendo Switch Games CD": the medium, never part of a name.
        "cd",
        # Amazon's catalogue notes, written outside brackets too: "Sonic Mania
        # Plus(tbd)", "Lego Worlds Nla" (no longer available).
        "tbd",
        "nla",
        # Italian "video game", on an Amazon import listing.
        "videogioco",
    }
)

# Flipkart (and some Amazon) titles are "Name | marketing | marketing ...", and
# the marketing differs per listing, so the whole title splits every game. The
# part before the first "|" is the name -- but Amazon also writes "Shinobi: Art
# of Vengeance | Deluxe Edition | Switch 2", where cutting at the "|" would merge
# the Deluxe with the Standard. So the head is used ONLY when the tail names no
# edition and none of these words or a number; otherwise the whole title is
# keyed as before. Unsure means split: a missed merge is an alias, a wrong one
# is silent.
VARIANT_WORDS = frozenset(
    {
        "deluxe", "definitive", "complete", "collector", "collectors", "limited", "special", "gold",
        "ultimate", "goty", "year", "anniversary", "bundle", "pack", "twin", "steelbook", "amiibo",
        "dlc", "season", "pass", "expansion", "royal", "remaster", "remastered", "hd", "trilogy",
        "collection", "directors", "cut", "plus", "launch", "chapter", "part", "episode", "volume",
        "vol", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii",
    }
)  # fmt: skip
_EDITION = re.compile(r"\bedition\b", re.IGNORECASE)

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

# Publishers Amazon also prepends, whose names real titles DO begin with ("Sega
# Genesis Classics", "Capcom Fighting Collection"). So these come off only when
# the rest is CONFIRMED: another listing on the same platform already keys to it
# ("Sega Sonic Forces" -> "sonic forces" because a shop sells "Sonic Forces").
# Every one of these was seen prepended on Amazon, live, or is the same kind.
_CONFIRMED_PREFIXES = sorted(
    (
        tuple(p.split())
        for p in (
            # Without "Games": normalise_title has already dropped that word, so
            # "Maximum Games Alfred Hitchcock" arrives here as "maximum alfred ...".
            "sega", "capcom", "konami", "atlus", "activision", "bandai", "namco", "koei tecmo",
            "thq nordic", "wb", "ubi soft", "fireshine", "2k", "rockstar", "maximum gaming",
            "maximum", "outright", "funbox media", "merge", "microids", "gearbox publishing",
            "nighthawk interactive", "fangamer", "tesura", "nis america", "marvelous", "xseed",
            "pqube", "deep silver", "plaion", "focus entertainment", "nacon", "bigben", "numskull",
            "limited run", "team17", "devolver digital",
        )
    ),
    key=len,
    reverse=True,
)  # fmt: skip

#: Straight, curly (U+2019, which shops paste from Word) and backtick.
_APOSTROPHES = str.maketrans("", "", "'\u2019`")


def _words(text: str) -> list[str]:
    # Accents are FOLDED, not stripped: normalise_title drops non-ASCII, which
    # turned "Pokémon" into "pok mon" and split it from every shop that writes
    # "Pokemon". Apostrophes are removed outright for the same reason --
    # "Luigi's Mansion" must not become "luigi s mansion" beside "Luigis".
    folded = unicodedata.normalize("NFKD", text.translate(MARKS)).encode("ascii", "ignore").decode()
    return [w for w in normalise_title(folded.translate(_APOSTROPHES)).split() if w not in _STOPWORDS]


def _tail_is_marketing(tail: str) -> bool:
    for segment in tail.split("|"):
        words = _words(segment)
        if _EDITION.search(segment) and words:  # "Deluxe Edition"; "Standard Edition" keys to nothing
            return False
        if any(w in VARIANT_WORDS or any(ch.isdigit() for ch in w) for w in words):
            return False
    return True


def match_key(title: str) -> str:
    """The grouping key for one raw title. Empty means "cannot match"."""
    head, bar, tail = title.partition("|")
    # The head is the whole name only when it ENDS the name itself by naming the
    # console ("Neon White Nintendo Switch Games CD | ..."), as Flipkart's do.
    # "Fire Emblem | Engage" has no console before the bar: the tail is the
    # subtitle, and dropping it would merge Engage with Three Houses.
    words = _words(head) if bar and platform_of(head) is not Platform.UNKNOWN else []
    if not words or not _tail_is_marketing(tail):
        words = _words(title)
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


def platform_from_title(title: str, stored: str) -> str:
    """The platform a collection would store today. The title's console always
    wins at collection time (core/parse.py), so re-reading it here repairs rows
    saved under an older rule, e.g. Play-Asia's "NSW2™" before it was a Switch 2
    marker, with no re-scrape. A title naming no console keeps what was stored,
    because that came from a store hint or category this pass can't see.
    """
    named = named_platform(title)
    return named.value if named is not None else stored


def assign(
    listings: list[sqlite3.Row], aliases: Mapping[str, str] | None = None
) -> dict[int, tuple[str, str]]:
    """Listing id -> (game key, platform), for every listing that can be matched.

    Two merges on top of match_key, both CONFIRMED by the data rather than
    guessed: a publisher prefix comes off only if the rest is another listing's
    key, and keys made of the same words in another order ("FC 26 EA Sports",
    "EA Sports FC 26") become one. Anything less certain stays split, for
    check_data.py to list and an alias to settle.
    """
    aliases = aliases or {}
    base: dict[int, tuple[str, str]] = {}
    for row in listings:
        platform = platform_from_title(row["raw_title"], row["platform"])
        key = match_key(row["raw_title"])
        # UNKNOWN platform is not a game we can compare; matching it would
        # group a PS5 title with its Switch namesake.
        if key and platform != "UNKNOWN":
            base[row["id"]] = (key, platform)
    known = set(base.values())

    def confirmed(key: str, platform: str) -> str:
        words = key.split()
        for prefix in _CONFIRMED_PREFIXES:
            if tuple(words[: len(prefix)]) == prefix:
                rest = " ".join(words[len(prefix) :])
                return rest if (rest, platform) in known else key
        return key

    stripped = {kp: confirmed(*kp) for kp in known}
    uses = Counter((stripped[kp], kp[1]) for kp in base.values())
    # "vs" is the one place word order IS the game: "Capcom vs SNK", "SNK vs Capcom".
    same_words: dict[tuple[str, frozenset[str]], list[str]] = defaultdict(list)
    for key, platform in set(uses):
        if "vs" not in key.split():
            same_words[(platform, frozenset(key.split()))].append(key)
    # The most-listed spelling names the group; ties go to the shorter, then A-Z.
    canonical = {
        (key, platform): min(keys, key=lambda k: (-uses[(k, platform)], len(k), k))
        for (platform, _), keys in same_words.items()
        for key in keys
    }

    def final(key: str, platform: str) -> str:
        k = stripped.get((key, platform), key)
        return canonical.get((k, platform), k)

    out = {}
    for listing_id, (key, platform) in base.items():
        # An alias written against a raw title wins; its target joins the group
        # that title's own listings ended up in.
        target = aliases.get(key) or aliases.get(final(key, platform))
        out[listing_id] = (final(target, platform) if target else final(key, platform), platform)
    return out


def rematch(conn: sqlite3.Connection, aliases: Mapping[str, str] | None = None) -> int:
    """Recompute every listing's game. Returns how many listings were matched.

    One transaction: a dashboard reading mid-pass sees the old grouping or the
    new one, never half of each. Games left with no listing are deleted, so a
    key that improved does not leave its old spelling behind as an empty game.
    """
    listings = conn.execute("SELECT id, raw_title, platform, region FROM listing").fetchall()
    region_of = {row["id"]: row["region"] for row in listings}
    stored_platform = {row["id"]: row["platform"] for row in listings}
    assigned = assign(listings, aliases)
    keyed = [(lid, key, platform, region_of[lid]) for lid, (key, platform) in assigned.items()]
    relabelled = [
        (platform_from_title(row["raw_title"], row["platform"]), row["id"])
        for row in listings
        if platform_from_title(row["raw_title"], row["platform"]) != stored_platform[row["id"]]
    ]

    conn.execute("BEGIN")
    try:
        conn.executemany("UPDATE listing SET platform = ? WHERE id = ?", relabelled)
        # A key that disappears and whose listings ALL moved to one new key is
        # recorded, so a watch on it can follow. Split across several new keys
        # it is ambiguous, and no guess is recorded.
        new_of = {listing_id: key for listing_id, key, _, _ in keyed}
        moved: dict[tuple[str, str], set[str | None]] = {}
        for row in conn.execute(
            "SELECT l.id, g.canonical_title, g.platform FROM listing l JOIN game g ON g.id = l.game_id"
        ):
            moved.setdefault((row["canonical_title"], row["platform"]), set()).add(new_of.get(row["id"]))
        live = {(key, platform) for _, key, platform, _ in keyed}
        conn.executemany(
            "INSERT OR REPLACE INTO game_redirect (old_title, platform, new_title) VALUES (?, ?, ?)",
            [
                (old, platform, next(iter(targets)))
                for (old, platform), targets in moved.items()
                if (old, platform) not in live and len(targets) == 1 and None not in targets
            ],
        )
        # A key in use again is its own game: a forwarding address left from an
        # earlier pass would send its watch to some other game's price.
        conn.executemany("DELETE FROM game_redirect WHERE old_title = ? AND platform = ?", live)
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
