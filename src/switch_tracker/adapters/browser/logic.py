"""Pure browser-adapter decisions that do not require a browser runtime."""

from __future__ import annotations

from switch_tracker.adapters.browser.extract import Extracted
from switch_tracker.adapters.browser.profiles import StoreProfile
from switch_tracker.core.models import Condition
from switch_tracker.core.parse import infer_condition


def _condition_for(profile: StoreProfile, row: Extracted) -> Condition:
    """New or pre-owned, from the strongest signal the store actually gives.

    Narrowest first: a profile that ASSERTS it (CeX, whose listings never say),
    then the card text if the profile opted in (GameLand, where it is a badge),
    then the title -- the default, and what every store did before.

    Tier 2 is opt-in on purpose; ``StoreProfile.condition_from_context`` has
    the Amazon case that makes enabling it globally a corruption bug.
    """
    if profile.default_condition is not None:
        return profile.default_condition
    if profile.condition_from_context and row.context:
        return infer_condition(row.context)
    return infer_condition(row.title)


def rejects_url(profile: StoreProfile, url: str) -> bool:
    """Is this href something other than a product?

    Public and module-level rather than a method: it holds no adapter state, and
    keeping it out of the class means it is testable without launching a browser
    -- the same reason ``sku_from_url`` lives where it does.

    Fails OPEN by construction. A row is dropped only on a POSITIVE match, so a
    badly chosen rule leaves junk listings in the database, which is
    recoverable. The alternative shape -- a regex the URL must match to survive
    -- fails closed, and a mis-anchored one silently deletes an entire store's
    history. That asymmetry is why this is substring matching and not a pattern.
    """
    if not profile.reject_url_parts and not profile.require_digit_in_url:
        # The default for every store that has not opted in: no string work.
        return False
    if any(part in url for part in profile.reject_url_parts):
        return True
    return profile.require_digit_in_url and not any(char.isdigit() for char in url)
