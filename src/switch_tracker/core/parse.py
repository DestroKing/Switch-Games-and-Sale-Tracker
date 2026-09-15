"""Price parsing, product classification, region and condition inference.

A direct port of src/core/parse.ts.  The regex sets and -- critically -- their
ORDER are reproduced exactly; several of them encode bugs that were found the
hard way, and the comments explaining why are as valuable as the patterns.
"""

from __future__ import annotations

import re
from math import isfinite

from switch_tracker.core.models import Classification, Condition, Platform, ProductKind, Region

# --------------------------------------------------------------------- prices

# Currency markers are removed BEFORE the non-numeric strip. This is a
# deviation from parse.ts, and it fixes a real defect there: the period in
# "Rs." is inside the [^\d.,] allow-list, so it survives the strip and is then
# read as a decimal point. The original turns "Rs. 4499" into 0.4499 and
# "Rs. 4,499" into 4.499 -- silently, with no error -- even though its own
# docstring lists "Rs. 4499" as a supported format. Reachable via
# browser.ts's parsePrice(r.priceText) on any store that writes prices that
# way, which is common on Indian storefronts.
_CURRENCY_MARKER = re.compile(r"₹|\brs\.?|\binr\b", re.IGNORECASE)
_NON_NUMERIC = re.compile(r"[^\d.,]")
# Mimics JavaScript's Number.parseFloat, which takes the longest valid numeric
# prefix and ignores the rest. Python's float() raises instead, so a value like
# "4.4.9" would become an exception where the original quietly produced 4.4.
_FLOAT_PREFIX = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)")


def _parse_float_prefix(text: str) -> float | None:
    match = _FLOAT_PREFIX.match(text)
    if match is None:
        return None
    value = float(match.group(0))
    return value if isfinite(value) else None


def parse_price(raw: str | float | None) -> float | None:
    """Indian storefronts write prices about six different ways.

    "4,499.00", "Rs. 4499", "INR 4,499", "4.499,00".  Returns None rather than
    0 on failure -- zero is a real value and must not be invented.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw) if isfinite(raw) else None

    cleaned = _NON_NUMERIC.sub("", _CURRENCY_MARKER.sub(" ", str(raw))).strip()
    if not cleaned:
        return None

    last_comma = cleaned.rfind(",")
    last_dot = cleaned.rfind(".")

    if last_dot == -1:
        # A comma with no decimal point anywhere in the string is ALWAYS a
        # thousands separator on these sites -- "3,599" is three thousand five
        # hundred ninety-nine, never 3.599.  Treating it as a decimal point
        # (the earlier "whichever separator is last wins" rule) silently
        # produced a price ~1000x too small for any whole-rupee price written
        # without a trailing ".00", which is the normal way to write one.
        normalised = cleaned.replace(",", "")
    elif last_comma > last_dot:
        # European: dots group thousands, the comma is the decimal point.
        # Only the FIRST comma is swapped, matching JavaScript's
        # String.replace with a string argument.
        normalised = cleaned.replace(".", "").replace(",", ".", 1)
    else:
        normalised = cleaned.replace(",", "")

    return _parse_float_prefix(normalised)


_RUPEE_FIGURE = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d.,]+)", re.IGNORECASE)


def first_rupee_price(text: str | None) -> float | None:
    if not text:
        return None

    match = re.search(
        r"₹\s*([\d,]+(?:\.\d{1,2})?)",
        text,
    )

    if not match:
        return None

    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


# ------------------------------------------------------------- classification


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(s, re.IGNORECASE) for s in sources)


# Anything matching these is not a cartridge, however loudly it says "Switch".
# Checked BEFORE the platform patterns, because "Nintendo Switch Console" and
# "Nintendo Switch Pro Controller" both contain the console's name and would
# otherwise sail straight through as games.
HARDWARE = _patterns(
    r"\bconsole\b",
    r"\b(oled|lite)\s*(model|console|edition)?\b",
    r"\bjoy[\s-]?cons?\b",
    r"\bpro\s*controller\b",
    r"\bdock(ing)?\s*(station|set)?\b",
    r"\bhandheld\b.*\bsystem\b",
)

ACCESSORY = _patterns(
    r"\b(carry(ing)?\s*)?case\b",
    r"\b(screen\s*)?protector\b",
    r"\btempered\s*glass\b",
    r"\b(grip|stand|holder|mount|strap|skin|sticker|decal)\b",
    r"\b(charg(er|ing)|cable|adapter|power\s*bank)\b",
    r"\b(head(set|phone)s?|earbuds?|ear\s*phones?)\b",
    r"\b(micro\s*)?sd\s*card\b",
    r"\bmemory\s*card\b",
    r"\bamiibo\b",
    r"\bsteering\s*wheel\b",
    r"\bthumb\s*(grip|stick)",
    r"\b(t[- ]?shirt|hoodie|mug|keychain|poster|figure|plush)\b",
    r"\bcontrollers?\b",
    r"\bcooling\s*pads?\b",
)

DIGITAL = _patterns(
    r"\b(digital|download)\s*(code|version|key)\b",
    r"\be[- ]?shop\b",
    r"\bgift\s*card\b",
    r"\bswitch\s*online\b",
    r"\bmembership\b",
    r"\bvoucher\b",
    r"\bdlc\b",
    r"\bseason\s*pass\b",
)

# A repair/mod/installation service, not a physical product -- a listing like
# "Nintendo OLED game loading service" names the console and would otherwise
# sail through as a game, exactly as hardware and accessories would.
SERVICE = _patterns(
    r"\b(repair|installation|loading|jailbreak|unlock(ing)?|mod(ding)?|chip(ping)?|flash(ing)?)\s*service\b",
    r"\bgame\s*loading\s*service\b",
    r"\b(console\s*)?repair\b",
)

SWITCH2 = _patterns(r"switch\s*2\b", r"\bns2\b", r"\bswitch\s*two\b", r"\bnintendo\s*switch\s*2")

# Switch markers, loosest last.  "NS" and "NSW" are genuinely used by Indian
# importers in terse titles ("Hogwarts Legacy NSW"), which is exactly the case
# that made stores look empty before.
SWITCH = _patterns(r"\bnintendo\s*switch\b", r"\bswitch\b", r"\bnsw\b", r"\bns\b", r"\bnintendo\b")

# An explicit marker for a DIFFERENT console must beat store_hint.  A hint
# means "assume Switch when the text says nothing about a console", not
# "assume Switch even when the text names a different one".  Without this,
# any store with a SWITCH hint that also sells other consoles leaks every
# PS4/PS5/Xbox title through as a false Switch match.
OTHER_CONSOLE = _patterns(
    r"\bplay\s*station\s*[1-5]?\b",
    r"\bps[1-5]\b",
    r"\bps\s*vita\b",
    r"\bxbox\b",
    r"\bwii\s*u\b",
    r"\bwii\b",
    r"\b3ds\b",
    r"\bnintendo\s*ds\b",
    r"\bgame\s*boy\b",
    r"\bgamecube\b",
    r"\bsteam\s*key\b",
    r"\b(pc|windows)\s*(game|version)\b",
)

_WHITESPACE = re.compile(r"\s+")


def _any(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def platform_of(text: str, hint: Platform | None = None) -> Platform:
    if _any(SWITCH2, text):
        return Platform.SWITCH2
    if _any(SWITCH, text):
        return Platform.SWITCH
    # Text names a different console outright. This must win over the store's
    # hint, or a multi-platform retailer with a SWITCH hint leaks every
    # PS4/Xbox/etc. title through as a false Switch match.
    if _any(OTHER_CONSOLE, text):
        return Platform.UNKNOWN
    # No console named at all. Trust the store's context if it has one -- a
    # title pulled from a Switch-games collection is a Switch game.
    return hint if hint is not None else Platform.UNKNOWN


def classify(context: str, store_hint: Platform | None = None) -> Classification:
    """Classify a listing from everything the store gives us.

    ``context`` should be title + product type + tags + categories +
    breadcrumbs.  Passing only the title is what made terse-titled stores
    report near-zero.

    ``store_hint`` lets a store known to contain only Switch games assert
    that, so "Hogwarts Legacy" in a "Switch Games" collection is kept instead
    of dropped for not naming its console.
    """
    text = _WHITESPACE.sub(" ", context)

    # Order matters. Exclusions first, or hardware wins on a platform match.
    for patterns, kind in (
        (SERVICE, ProductKind.SERVICE),
        (DIGITAL, ProductKind.DIGITAL),
        (HARDWARE, ProductKind.HARDWARE),
        (ACCESSORY, ProductKind.ACCESSORY),
    ):
        if _any(patterns, text):
            return Classification(platform_of(text, store_hint), kind)

    platform = platform_of(text, store_hint)
    if platform is Platform.UNKNOWN:
        return Classification(platform, ProductKind.UNKNOWN)

    # Platform is known and nothing excluded it. Treat as a game -- on a page
    # of Switch results that is overwhelmingly what a leftover row is.
    return Classification(platform, ProductKind.GAME)


def infer_platform(context: str, hint: Platform | None = None) -> Platform:
    """Convenience for callers that only want the platform."""
    return classify(context, hint).platform


def price_looks_wrong(inr: float, kind: ProductKind) -> bool:
    """Prices that make no sense for a cartridge.

    Not a hard reject -- it flags rows worth a look rather than silently
    dropping something real.
    """
    if kind is not ProductKind.GAME:
        return False
    return inr < 299 or inr > 12_000


# --------------------------------------------------------------------- region

REGION_RULES: tuple[tuple[re.Pattern[str], Region], ...] = (
    (re.compile(r"\b(asia|asian)\b.*\b(chinese|chs|cht|zh)\b|\bchinese\s*sub", re.I), Region.ASIA_ZH),
    (re.compile(r"\b(asia|asian)\b.*\b(english|eng|en)\b|\basia\s*english\b", re.I), Region.ASIA_EN),
    (re.compile(r"\b(jpn?|japan|japanese|nts-j)\b", re.I), Region.JP),
    (re.compile(r"\b(usa?|ntsc-u|north\s*america)\b", re.I), Region.US),
    (re.compile(r"\b(eu|pal|europe|uk)\b", re.I), Region.EU),
    (re.compile(r"\b(asia|asian)\b", re.I), Region.ASIA_EN),
)


def infer_region(title: str, store_default: Region) -> Region:
    for pattern, region in REGION_RULES:
        if pattern.search(title):
            return region
    return store_default


# ------------------------------------------------------------------ condition

# Real Indian retail categories say this outright -- one store's Store API
# returns a category literally named "Pre-Owned Games" on the listings that
# belong to it, which lands in the context the same way any other category
# name does.  Detecting it from that real per-listing text is why this needs
# no per-store config: a store's own tagging is the source of truth.
PRE_OWNED = _patterns(
    r"\bpre[- ]?owned\b",
    r"\bused\b",
    r"\brefurbished\b",
    r"\bopen\s*box\b",
    r"\bsecond[\s-]?hand\b",
    r"\brenewed\b",
)


def infer_condition(context: str) -> Condition:
    """Absent an explicit marker, a listing is assumed NEW.

    That is what a retail cartridge listing overwhelmingly is, and UNKNOWN as
    the default would make the filter useless on the vast majority of stores
    that never say "new" outright because there is nothing else it could be.
    """
    return Condition.PRE_OWNED if _any(PRE_OWNED, context) else Condition.NEW


# ---------------------------------------------------------------- title clean

NOISE = _patterns(
    r"\bnintendo\s*switch\s*2\b",
    r"\bnintendo\s*switch\b",
    r"\bswitch\s*2\b",
    r"\bswitch\b",
    r"\b(nsw|ns2|ns)\b",
    r"\b(video\s*)?game(s)?\b",
    r"\b(cartridge|cart|physical|standard|edition)\b",
    r"\((asia|japan|us|eu|english|chinese)[^)]*\)",
    r"\[[^\]]*\]",
    r"\b(pre[- ]?owned|used|new|sealed|import|brand\s*new)\b",
    r"\bfor\s+nintendo\b",
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]")


def normalise_title(title: str) -> str:
    """Crude normalisation; the matcher's first pass."""
    text = title.lower()
    for pattern in NOISE:
        text = pattern.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()
