"""Domain vocabulary.

Two decisions carried from the TypeScript original are load-bearing and must
not be quietly softened:

1. A listing carries its NATIVE currency and price.  INR is derived, never
   captured.  Play-Asia's rupee figure is a display conversion; storing it as
   if it were a price makes every currency wobble look like a sale.
2. ``game_id`` is nullable.  An unmatched listing still gets collected.
   Matching is a separate, re-runnable pass over data already on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    SWITCH = "SWITCH"
    SWITCH2 = "SWITCH2"
    UNKNOWN = "UNKNOWN"


class Region(StrEnum):
    """First-class, not a tag.

    Play-Asia splits one title across Asia-English, Asia-Chinese, Japan and
    Western SKUs.  Those are different products with different playability --
    collapsing them into one canonical game would be wrong.
    """

    IN = "IN"
    ASIA_EN = "ASIA_EN"
    ASIA_ZH = "ASIA_ZH"
    JP = "JP"
    US = "US"
    EU = "EU"
    UNKNOWN = "UNKNOWN"


class Condition(StrEnum):
    """Inferred per-listing from the store's own text, not asserted per store.

    At least one real store sells new and pre-owned out of one catalogue, so a
    per-store flag would be wrong for it.
    """

    NEW = "NEW"
    PRE_OWNED = "PRE_OWNED"


class ProductKind(StrEnum):
    GAME = "GAME"
    HARDWARE = "HARDWARE"
    ACCESSORY = "ACCESSORY"
    DIGITAL = "DIGITAL"
    SERVICE = "SERVICE"
    UNKNOWN = "UNKNOWN"


class AdapterKind(StrEnum):
    """JSON_API and MANUAL are deliberately absent.

    The TypeScript original declared both, neither had an adapter, and the
    registry returned undefined for them -- so collect recorded a 'skipped'
    row that read like a failure.  A kind with no fetcher is not a kind.
    """

    SHOPIFY = "SHOPIFY"
    WOOCOMMERCE = "WOOCOMMERCE"
    BROWSER = "BROWSER"


@dataclass(frozen=True, slots=True)
class Classification:
    platform: Platform
    kind: ProductKind


@dataclass(frozen=True, slots=True)
class StoreConfig:
    id: str
    name: str
    base_url: str
    kind: AdapterKind
    #: ISO 4217 of the prices this store quotes NATIVELY. Not what it displays
    #: after a conversion widget -- Play-Asia shows rupees but sells in USD.
    currency: str
    tier: int
    enabled: bool
    #: Shopify/Woo: restrict the crawl to these collection or category slugs.
    collections: tuple[str, ...] = ()
    #: BROWSER adapters: category or search URLs to walk, "{p}" substituted.
    search_urls: tuple[str, ...] = ()
    #: Asserted platform for stores whose catalogue is known to be Switch-only.
    #: Lets a terse title with no console marker still be classified instead of
    #: dropped. Deliberately absent on general retailers -- see designinfo.
    platform_hint: Platform | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class RawListing:
    """What an adapter returns. Deliberately dumb: no matching, no normalising.

    ``native_currency`` / ``native_price`` are the captured FACT. INR is
    derived later from a dated exchange rate and never captured as if it were
    the price -- a store that only displays a converted rupee figure would
    otherwise make a currency wobble look like a catalogue-wide sale.
    """

    store_id: str
    #: The store's own identifier where one exists, else derived from the URL.
    #: Stability across runs is what makes price history accumulate.
    sku: str
    url: str
    title: str
    native_currency: str
    native_price: float
    in_stock: bool
    platform: Platform
    region: Region
    condition: Condition
    image_url: str | None = None


@dataclass(frozen=True, slots=True)
class Ok:
    listings: tuple[RawListing, ...]


@dataclass(frozen=True, slots=True)
class Partial:
    """Rows were collected, but there is reason to think some are missing."""

    listings: tuple[RawListing, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class Failed:
    """No usable rows. ``reason`` must be readable by a human on the dashboard."""

    reason: str


FetchOutcome = Ok | Partial | Failed
