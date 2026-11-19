"""Deterministic product identity extraction and release rematching.

The extraction half is pure: it depends only on the listing fields already
stored in market.db, so improving identity rules never requires another crawl.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from switch_tracker.core.matcher import match_key, platform_from_title
from switch_tracker.market.models import Format


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
    (
        re.compile(r"\bdownload\s+code\b|\bdigital\s+code\b|\bdigital\b|\be-?shop\s+code\b|\bvoucher\b", re.I),
        Format.DOWNLOAD_CODE,
    ),
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


def _format_name(value: Format) -> str:
    return value.value


def extract(title: str, sku: str, platform: str, region: str) -> Attributes:
    """Extract a conservative, explainable identity from one stored listing."""
    problems: list[str] = []
    unmatched: str | None = None
    detected_platform = platform_from_title(title, platform)
    edition_matches: list[tuple[re.Pattern[str], str]] = []
    for pattern, label in _EDITIONS:
        found = list(pattern.finditer(title))
        if found:
            value = found[0].group(1).upper() if label == "FALLBACK" else label
            edition_matches.append((pattern, value))
    editions = list(dict.fromkeys(value for _, value in edition_matches))
    edition = editions[0] if editions else "STANDARD"
    if len(editions) > 1:
        problems.append(f"several editions named: {', '.join(editions)}")
    switch2_edition = any(value == "SWITCH2_EDITION" for value in editions)
    if switch2_edition:
        detected_platform = "SWITCH2"

    format_matches: list[tuple[re.Pattern[str], Format]] = []
    for pattern, value in _FORMATS:
        if pattern.search(title):
            format_matches.append((pattern, value))
    formats = list(dict.fromkeys(value for _, value in format_matches))
    listing_format = formats[0] if formats else Format.UNKNOWN
    if len(formats) > 1:
        problems.append("several formats named")

    bundle_match = _BUNDLE.search(title)
    if bundle_match:
        unmatched = "bundle: several products in one listing"

    stripped = title
    for pattern, _ in edition_matches:
        stripped = pattern.sub(" ", stripped)
    for pattern, _ in format_matches:
        stripped = pattern.sub(" ", stripped)
    if bundle_match:
        stripped = _BUNDLE.sub(" ", stripped)
    display_title = re.sub(r"\s+", " ", stripped).strip().rstrip(" -|:")
    key = match_key(display_title)
    if not key and unmatched is None:
        unmatched = "title has no matchable words"
    if detected_platform == "UNKNOWN" and unmatched is None:
        unmatched = "platform unknown"

    codes: set[str] = set()
    code_signals: list[tuple[str, str, Format | None, bool]] = []
    for source in (sku.upper(), title.upper()):
        for match in _PRODUCT_CODE.finditer(source):
            prefix, kind, _product, suffix = match.groups()
            whole = match.group(0)
            codes.add(f"PC:{whole}")
            expected_platform = "SWITCH" if prefix == "HAC" else "SWITCH2"
            expected_format: Format | None
            if prefix == "POT":
                expected_format = Format.GAME_KEY_CARD
            elif kind == "P":
                expected_format = Format.FULL_GAME_CARD
            elif kind == "J":
                expected_format = Format.CODE_IN_BOX
            else:
                expected_format = None
            code_signals.append((expected_platform, prefix, expected_format, prefix == "NXS"))

    unique_signals = list(dict.fromkeys(code_signals))
    if len(codes) > 1:
        problems.append("several product codes")
    for expected_platform, prefix, expected_format, is_switch2_edition in unique_signals:
        if expected_platform != detected_platform:
            problems.append(f"product code says {expected_platform}, title says {detected_platform}")
        if expected_format is not None:
            if listing_format is Format.UNKNOWN:
                listing_format = expected_format
            elif listing_format is not expected_format:
                problems.append(
                    f"product code says {_format_name(expected_format)}, title says {_format_name(listing_format)}"
                )
        if is_switch2_edition:
            if edition == "STANDARD":
                edition = "SWITCH2_EDITION"
            elif edition != "SWITCH2_EDITION":
                problems.append(f"product code says SWITCH2_EDITION, title says {edition}")

    for match in _BARCODE.finditer(title):
        digits = match.group(2)
        normalised = digits.zfill(13)
        if _gtin_valid(normalised):
            codes.add(f"EAN:{normalised}")

    return Attributes(
        key=key,
        title=display_title,
        platform=detected_platform,
        edition=edition,
        region=region,
        format=listing_format,
        codes=frozenset(codes),
        problems=tuple(dict.fromkeys(problems)),
        unmatched=unmatched,
    )
