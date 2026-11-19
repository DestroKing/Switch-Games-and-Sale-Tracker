"""Deterministic product identity extraction and release rematching.

Extraction is pure. Rematching is a full, deterministic recompute over the
stored listings, preserving human decisions and historical release rows.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

from switch_tracker.core.db import now_iso
from switch_tracker.core.matcher import match_key, platform_from_title
from switch_tracker.market.models import Format, MatchTier


@dataclass(frozen=True, slots=True)
class Attributes:
    key: str
    title: str
    platform: str
    edition: str
    region: str
    format: Format
    codes: frozenset[str]
    problems: tuple[str, ...]
    unmatched: str | None


_EDITIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:nintendo\s+)?switch\s*2\s+edition\b", re.I), "SWITCH2_EDITION"),
    (re.compile(r"\bcollector'?s?'?\s+edition\b", re.I), "COLLECTORS"),
    (re.compile(r"\blimited\s+edition\b", re.I), "LIMITED"),
    (re.compile(r"\bdeluxe\s+edition\b", re.I), "DELUXE"),
    (re.compile(r"\bdefinitive\s+edition\b", re.I), "DEFINITIVE"),
    (re.compile(r"\bcomplete\s+edition\b", re.I), "COMPLETE"),
    (re.compile(r"\bgame\s+of\s+the\s+year(?:\s+edition)?\b|\bgoty\b", re.I), "GOTY"),
    (re.compile(r"\bspecial\s+edition\b", re.I), "SPECIAL"),
    (re.compile(r"\b(?:launch|day\s?(?:one|1))\s+edition\b", re.I), "LAUNCH"),
    (re.compile(r"\bgold\s+edition\b", re.I), "GOLD"),
    (re.compile(r"\bultimate\s+edition\b", re.I), "ULTIMATE"),
    (re.compile(r"\banniversary\s+edition\b", re.I), "ANNIVERSARY"),
    (re.compile(r"\bsteelbook(?:\s+edition)?\b", re.I), "STEELBOOK"),
    (re.compile(r"\bstandard\s+edition\b", re.I), "STANDARD"),
    (re.compile(r"\b([a-z0-9]+)\s+edition\b", re.I), "FALLBACK"),
)
_FORMATS: tuple[tuple[re.Pattern[str], Format], ...] = (
    (re.compile(r"\bgame[- ]?key[- ]?card\b|\bkey\s+card\b", re.I), Format.GAME_KEY_CARD),
    (re.compile(r"\bcode[- ]in[- ](?:a[- ])?box\b", re.I), Format.CODE_IN_BOX),
    (re.compile(r"\bdownload\s+code\b|\bdigital\s+code\b|\bdigital\b|\be-?shop\s+code\b|\bvoucher\b", re.I), Format.DOWNLOAD_CODE),
    (re.compile(r"\bgame\s+card\b|\bcartridge\b", re.I), Format.FULL_GAME_CARD),
)
_BUNDLE = re.compile(r"\bbundle\b|\bcombo\b|\btwin\s+pack\b|\bdouble\s+pack\b|\bwith\s+amiibo\b", re.I)
_PRODUCT_CODE = re.compile(r"\b(HAC|BEE|POT|NXS)-([A-Z])-([A-Z0-9]{5})(?:-([A-Z]{3}))?\b", re.I)
_BARCODE = re.compile(r"\b(EAN|UPC|GTIN|barcode)\b[\s:#-]*(\d{12,13})\b", re.I)


def _gtin_valid(digits: str) -> bool:
    values = [int(char) for char in digits]
    check = values.pop()
    total = sum(value * (3 if (len(values) - index) % 2 else 1) for index, value in enumerate(values))
    return (10 - total % 10) % 10 == check


def extract(title: str, sku: str, platform: str, region: str) -> Attributes:
    problems: list[str] = []
    unmatched: str | None = None
    detected_platform = platform_from_title(title, platform)
    edition_matches: list[tuple[re.Pattern[str], str]] = []
    for pattern, label in _EDITIONS:
        found = list(pattern.finditer(title))
        if found:
            edition_matches.append((pattern, found[0].group(1).upper() if label == "FALLBACK" else label))
    editions = list(dict.fromkeys(value for _, value in edition_matches))
    edition = editions[0] if editions else "STANDARD"
    if len(editions) > 1:
        problems.append(f"several editions named: {', '.join(editions)}")
    if "SWITCH2_EDITION" in editions:
        detected_platform = "SWITCH2"

    format_matches = [(pattern, value) for pattern, value in _FORMATS if pattern.search(title)]
    formats = list(dict.fromkeys(value for _, value in format_matches))
    listing_format = formats[0] if formats else Format.UNKNOWN
    if len(formats) > 1:
        problems.append("several formats named")

    if _BUNDLE.search(title):
        unmatched = "bundle: several products in one listing"

    stripped = title
    for pattern, _ in edition_matches + format_matches:
        stripped = pattern.sub(" ", stripped)
    stripped = _BUNDLE.sub(" ", stripped)
    display_title = re.sub(r"\s+", " ", stripped).strip().rstrip(" -|:")
    key = match_key(display_title)
    if not key and unmatched is None:
        unmatched = "title has no matchable words"
    if detected_platform == "UNKNOWN" and unmatched is None:
        unmatched = "platform unknown"

    codes: set[str] = set()
    signals: list[tuple[str, Format | None, bool]] = []
    for source in (sku.upper(), title.upper()):
        for match in _PRODUCT_CODE.finditer(source):
            prefix, kind = match.group(1), match.group(2)
            codes.add(f"PC:{match.group(0)}")
            expected_platform = "SWITCH" if prefix == "HAC" else "SWITCH2"
            expected_format = Format.GAME_KEY_CARD if prefix == "POT" else (
                Format.FULL_GAME_CARD if kind == "P" else Format.CODE_IN_BOX if kind == "J" else None
            )
            signals.append((expected_platform, expected_format, prefix == "NXS"))
    if len(codes) > 1:
        problems.append("several product codes")
    for expected_platform, expected_format, is_switch2_edition in dict.fromkeys(signals):
        if expected_platform != detected_platform:
            problems.append(f"product code says {expected_platform}, title says {detected_platform}")
        if expected_format is not None:
            if listing_format is Format.UNKNOWN:
                listing_format = expected_format
            elif listing_format is not expected_format:
                problems.append(
                    f"product code says {expected_format.value}, title says {listing_format.value}"
                )
        if is_switch2_edition:
            if edition == "STANDARD":
                edition = "SWITCH2_EDITION"
            elif edition != "SWITCH2_EDITION":
                problems.append(f"product code says SWITCH2_EDITION, title says {edition}")

    for match in _BARCODE.finditer(title):
        digits = match.group(2).zfill(13)
        if _gtin_valid(digits):
            codes.add(f"EAN:{digits}")

    return Attributes(
        key, display_title, detected_platform, edition, region, listing_format,
        frozenset(codes), tuple(dict.fromkeys(problems)), unmatched,
    )


def near(a: str, b: str) -> bool:
    left, right = set(a.split()), set(b.split())
    if a == b or min(len(left), len(right)) < 2:
        return False
    return left < right or right < left or len(left & right) / len(left | right) >= 0.8


def get_or_create_release(
    conn: sqlite3.Connection, game_id: int, platform: str, edition: str, region: str, format: Format
) -> int:
    row = conn.execute(
        "INSERT INTO release (game_id, platform, edition, region, format, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(game_id, platform, edition, region, format) "
        "DO UPDATE SET edition = excluded.edition RETURNING id",
        (game_id, platform, edition, region, format.value, now_iso()),
    ).fetchone()
    return int(row[0])


def _final_alias(release_id: int, aliases: dict[int, int]) -> int:
    seen: set[int] = set()
    current = release_id
    while current in aliases:
        if current in seen:
            raise ValueError("release alias cycle detected")
        seen.add(current)
        current = aliases[current]
    return current


def rematch(conn: sqlite3.Connection) -> dict[MatchTier, int]:
    """Recompute every non-confirmed listing match in one deterministic transaction."""
    counts = {tier: 0 for tier in MatchTier}
    with conn:
        listings = conn.execute(
            "SELECT id, storefront_id, sku, title, platform, region FROM listing ORDER BY id"
        ).fetchall()
        current = {
            int(row["listing_id"]): row
            for row in conn.execute("SELECT * FROM listing_match").fetchall()
        }
        rejected: dict[int, set[int]] = defaultdict(set)
        for row in conn.execute("SELECT listing_id, release_id FROM match_rejection"):
            rejected[int(row["listing_id"])].add(int(row["release_id"]))
        aliases = {int(a): int(b) for a, b in conn.execute("SELECT release_id, target_id FROM release_alias")}
        code_rows: dict[str, set[int]] = defaultdict(set)
        for code, release_id in conn.execute("SELECT code, release_id FROM release_code"):
            code_rows[str(code)].add(int(release_id))

        attrs: dict[int, Attributes] = {}
        decisions: dict[int, tuple[int | None, MatchTier, list[str]]] = {}
        families: dict[tuple[str, str, str, str, str], list[int]] = defaultdict(list)
        for row in listings:
            lid = int(row["id"])
            old = current.get(lid)
            attr = extract(row["title"], row["sku"], row["platform"], row["region"])
            attrs[lid] = attr
            if old is not None and old["tier"] == MatchTier.CONFIRMED.value:
                counts[MatchTier.CONFIRMED] += 1
                continue
            if attr.unmatched:
                decisions[lid] = (None, MatchTier.UNMATCHED, [attr.unmatched])
            elif attr.problems:
                decisions[lid] = (None, MatchTier.AMBIGUOUS, list(attr.problems))
            else:
                code_targets = set().union(*(code_rows.get(code, set()) for code in attr.codes)) if attr.codes else set()
                if len(code_targets) > 1:
                    decisions[lid] = (None, MatchTier.AMBIGUOUS, [
                        "codes point at releases " + ", ".join(map(str, sorted(code_targets)))
                    ])
                elif code_targets:
                    target = next(iter(code_targets))
                    target_platform = conn.execute("SELECT platform FROM release WHERE id=?", (target,)).fetchone()
                    if target_platform is None or target_platform[0] != attr.platform:
                        expected = "missing" if target_platform is None else target_platform[0]
                        decisions[lid] = (None, MatchTier.AMBIGUOUS, [
                            f"code says {expected}, title says {attr.platform}"
                        ])
                    elif target not in rejected[lid]:
                        decisions[lid] = (target, MatchTier.EXACT_CODE, [f"known product code identifies release {target}"])
                    else:
                        families[(attr.key, attr.platform, attr.edition, attr.region, attr.format.value)].append(lid)
                else:
                    families[(attr.key, attr.platform, attr.edition, attr.region, attr.format.value)].append(lid)

        # Canonical families are considered in stable order; token index avoids
        # comparing every new family with every existing family.
        canonical: list[tuple[tuple[str, str, str, str, str], int]] = []
        token_index: dict[str, set[int]] = defaultdict(set)
        ordered = sorted(families.items(), key=lambda item: (-len(item[1]), len(item[0][0]), item[0][0]))
        for family, ids in ordered:
            key, platform, edition, region, fmt = family
            candidates: set[int] = set()
            for token in set(key.split()):
                candidates.update(token_index[token])
            matches: list[tuple[tuple[str, str, str, str, str], int]] = []
            for candidate_index in sorted(candidates):
                other, release_id = canonical[candidate_index]
                if other[1:] == family[1:] and near(key, other[0]) and not any(
                    release_id in rejected[lid] for lid in ids
                ):
                    matches.append((other, release_id))
            if not matches:
                game_title_counts = Counter(attrs[lid].title for lid in ids)
                chosen_title = sorted(game_title_counts, key=lambda value: (-game_title_counts[value], len(value), value.casefold()))[0]
                conn.execute(
                    "INSERT INTO game (title, key) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET "
                    "title=CASE WHEN game.title=excluded.title THEN game.title ELSE excluded.title END",
                    (chosen_title, key),
                )
                game_id = int(conn.execute("SELECT id FROM game WHERE key=?", (key,)).fetchone()[0])
                release_id = get_or_create_release(conn, game_id, platform, edition, region, Format(fmt))
                canonical_index = len(canonical)
                canonical.append((family, release_id))
                for token in set(key.split()):
                    token_index[token].add(canonical_index)
                for lid in ids:
                    if release_id in rejected[lid]:
                        decisions[lid] = (None, MatchTier.UNMATCHED, ["rejected by review"])
                    else:
                        decisions[lid] = (release_id, MatchTier.EXACT_KEY, [
                            f"title key '{key}'", f"platform {platform}", f"edition {edition}",
                            f"region {region}", f"format {fmt}", "only release with these dimensions",
                        ])
            elif len(matches) == 1:
                release_id = matches[0][1]
                for lid in ids:
                    decisions[lid] = (release_id, MatchTier.PROBABLE, [
                        f"title key '{key}'", f"probable match to release {release_id}",
                    ])
            else:
                details = []
                for _, release_id in matches:
                    title_row = conn.execute(
                        "SELECT g.title FROM release r JOIN game g ON g.id=r.game_id WHERE r.id=?",
                        (release_id,),
                    ).fetchone()
                    details.append(f"{release_id}: {title_row[0] if title_row else 'unknown'}")
                reason = "multiple near release candidates: " + "; ".join(details)
                for lid in ids:
                    decisions[lid] = (None, MatchTier.AMBIGUOUS, [reason])

        # A product code claimed by distinct identity families is a collision,
        # not evidence that the later family is the same release.
        code_families: dict[str, set[tuple[object, ...]]] = defaultdict(set)
        for lid, attr in attrs.items():
            if attr.unmatched is not None or attr.problems:
                continue
            family = (attr.key, attr.platform, attr.edition, attr.region, attr.format.value)
            for code in attr.codes:
                code_families[code].add(family)

        # Confirmed listings teach codes without changing their human decisions.
        # Conflicting cross-family codes are deliberately not learned.
        for row in listings:
            lid = int(row["id"])
            old = current.get(lid)
            if old is None or old["tier"] != MatchTier.CONFIRMED.value or old["release_id"] is None:
                continue
            confirmed_release = _final_alias(int(old["release_id"]), aliases)
            for code in sorted(attrs[lid].codes):
                if len(code_families[code]) > 1:
                    continue
                if not code_rows.get(code):
                    conn.execute(
                        "INSERT OR IGNORE INTO release_code (code, release_id, source) VALUES (?, ?, ?)",
                        (code, confirmed_release, f"listing:{lid}"),
                    )
                    code_rows[code].add(confirmed_release)

        # Resolve aliases and learn codes in listing-id order.
        for lid in sorted(decisions):
            release_id, tier, reasons = decisions[lid]
            if release_id is not None:
                final = _final_alias(release_id, aliases)
                if final != release_id:
                    reasons = [*reasons, f"merged by review into release {final}"]
                    release_id = final
            if tier is MatchTier.EXACT_KEY and release_id is not None:
                colliding = sorted(code for code in attrs[lid].codes if len(code_families[code]) > 1)
                if colliding:
                    release_id, tier = None, MatchTier.AMBIGUOUS
                    reasons = [f"product code {colliding[0]} is claimed by multiple identity families"]
                known = {_final_alias(owner, aliases) for code in attrs[lid].codes for owner in code_rows.get(code, set())}
                if tier is not MatchTier.EXACT_KEY:
                    known = set()
                if len(known) == 1:
                    known_release = next(iter(known))
                    platform_row = conn.execute("SELECT platform FROM release WHERE id=?", (known_release,)).fetchone()
                    if platform_row is not None and platform_row[0] == attrs[lid].platform:
                        release_id, tier = known_release, MatchTier.EXACT_CODE
                        reasons = [f"known product code identifies release {known_release}"]
                elif len(known) > 1:
                    release_id, tier = None, MatchTier.AMBIGUOUS
                    reasons = ["codes point at releases " + ", ".join(map(str, sorted(known)))]
            if tier is MatchTier.EXACT_KEY and release_id is not None:
                for code in sorted(attrs[lid].codes):
                    owner = next(iter(code_rows.get(code, set())), None)
                    if owner is not None and _final_alias(owner, aliases) != release_id:
                        release_id = None
                        tier = MatchTier.AMBIGUOUS
                        reasons = [f"code {code} already belongs to release {owner}"]
                        break
                    if owner is None:
                        conn.execute(
                            "INSERT OR IGNORE INTO release_code (code, release_id, source) VALUES (?, ?, ?)",
                            (code, release_id, f"listing:{lid}"),
                        )
                        code_rows[code].add(release_id)
            old = current.get(lid)
            reasons_json = json.dumps(reasons, ensure_ascii=False)
            if old is None or (old["release_id"], old["tier"], old["reasons"]) != (
                release_id, tier.value, reasons_json
            ):
                conn.execute(
                    "INSERT INTO listing_match (listing_id, release_id, tier, reasons, decided_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(listing_id) DO UPDATE SET "
                    "release_id=excluded.release_id, tier=excluded.tier, reasons=excluded.reasons, "
                    "decided_at=excluded.decided_at",
                    (lid, release_id, tier.value, reasons_json, now_iso()),
                )
            counts[tier] += 1

        # Confirmed matches are preserved exactly and included in the returned counts.
        for lid, old in current.items():
            if old["tier"] == MatchTier.CONFIRMED.value and lid not in decisions:
                continue
        return counts
