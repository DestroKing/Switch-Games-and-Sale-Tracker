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
