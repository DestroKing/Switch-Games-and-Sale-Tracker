"""Market vocabulary. Values match the CHECK constraints in market/db.py."""

from __future__ import annotations

from enum import StrEnum


class ScopeKind(StrEnum):
    """What a scan walked. Only an enumerable catalogue or category can prove an absence."""

    CATALOGUE = "CATALOGUE"
    CATEGORY = "CATEGORY"
    SEARCH = "SEARCH"
    BROWSE = "BROWSE"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"

    @property
    def enumerable(self) -> bool:
        return self in (ScopeKind.CATALOGUE, ScopeKind.CATEGORY)


class CoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    @property
    def absence_eligible(self) -> bool:
        return self is CoverageStatus.COMPLETE


class Format(StrEnum):
    """Physical or digital packaging format; UNKNOWN is a distinct identity."""

    FULL_GAME_CARD = "FULL_GAME_CARD"
    GAME_KEY_CARD = "GAME_KEY_CARD"
    CODE_IN_BOX = "CODE_IN_BOX"
    DOWNLOAD_CODE = "DOWNLOAD_CODE"
    UNKNOWN = "UNKNOWN"


class MatchTier(StrEnum):
    """How confidently a listing is associated with a release."""

    CONFIRMED = "CONFIRMED"
    EXACT_CODE = "EXACT_CODE"
    EXACT_KEY = "EXACT_KEY"
    PROBABLE = "PROBABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"

    @property
    def counted(self) -> bool:
        return self in (MatchTier.CONFIRMED, MatchTier.EXACT_CODE, MatchTier.EXACT_KEY)
