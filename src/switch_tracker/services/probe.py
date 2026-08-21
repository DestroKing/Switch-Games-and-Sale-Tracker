"""Detecting each store's real backend, and correcting the config.

Probe asks one question per store: what does this site actually speak?  It
compares against the EFFECTIVE store list -- shipped defaults plus whatever
has already been corrected -- not the raw shipped list.  Comparing against the
shipped list meant a store corrected on run 1 reported "will switch" on every
run afterwards, forever, because the baseline never moved.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from switch_tracker.config import overrides
from switch_tracker.core.concurrency import bounded_gather
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, StoreConfig

#: Different hosts, so this bounds resource use only. Politeness is still one
#: request at a time per host, enforced in the client regardless.
STORE_CONCURRENCY = 8

#: High on purpose: this only ever runs for a store with no collections set,
#: so real depth costs nothing on every other run. One store had its games
#: category on page 2 of 100+.
MAX_CATEGORY_PAGES = 50

_RELEVANT = re.compile(r"nintendo|switch|\bgames?\b|\bcartridges?\b|\bsoftware\b", re.IGNORECASE)
_SHOPIFY_FINGERPRINT = re.compile(r"cdn\.shopify\.com|Shopify\.shop", re.IGNORECASE)


class Finding(StrEnum):
    """What detection can conclude.

    Only SHOPIFY and WOOCOMMERCE have an adapter. The rest describe something
    probe SAW but cannot act on, and must never be written to config as if
    they were adapter kinds.
    """

    SHOPIFY = "SHOPIFY"
    WOOCOMMERCE = "WOOCOMMERCE"
    UNREACHABLE = "UNREACHABLE"
    SHOPIFY_LOCKED = "SHOPIFY_LOCKED"
    UNKNOWN_HTML = "UNKNOWN_HTML"


_FETCHABLE = {Finding.SHOPIFY: AdapterKind.SHOPIFY, Finding.WOOCOMMERCE: AdapterKind.WOOCOMMERCE}

_DISABLE_REASON = {
    Finding.UNREACHABLE: "unreachable when probed",
    Finding.SHOPIFY_LOCKED: (
        "Shopify storefront, but /products.json is blocked by the merchant -- needs a browser profile"
    ),
    Finding.UNKNOWN_HTML: "no Shopify or WooCommerce API found -- needs a browser profile",
}


@dataclass
class ProbeReport:
    lines: list[str] = field(default_factory=list)
    corrected: int = 0
    disabled: int = 0

    def lines_for(self, store_id: str) -> str:
        return "\n".join(line for line in self.lines if line.startswith(store_id) or line.startswith("  "))


class ProbeService:
    def __init__(self, client: PoliteClient) -> None:
        self._client = client

    async def detect(self, store: StoreConfig) -> Finding | None:
        """None means "not probeable" -- there is no API here to detect."""
        if store.kind is AdapterKind.BROWSER:
            return None

        if await self._contains(f"{store.base_url}/products.json?limit=1", '"products"'):
            return Finding.SHOPIFY
        for path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
            if await self._contains(f"{store.base_url}{path}?per_page=1", '"prices"'):
                return Finding.WOOCOMMERCE

        # Neither API answered, but the homepage still says something. A
        # Shopify fingerprint means real Shopify with the feed switched off,
        # which is a different problem from a site that was never Shopify --
        # both need a browser, only one is worth re-probing later.
        home = await self._client.get(store.base_url)
        if not home.ok:
            return Finding.UNREACHABLE
        if _SHOPIFY_FINGERPRINT.search(home.body):
            return Finding.SHOPIFY_LOCKED
        return Finding.UNKNOWN_HTML

    async def run(self, stores: Sequence[StoreConfig]) -> ProbeReport:
        results = await bounded_gather(list(stores), STORE_CONCURRENCY, self._probe_one)

        report = ProbeReport()
        for store, finding, categories in results:
            if finding is None:
                report.lines.append(f"{store.id}: needs a real browser")
                continue

            report.lines.append(f"{store.id}: expected {store.kind}, found {finding}")
            if categories:
                report.lines.append(f"  categories: {categories}")

            adapter_kind = _FETCHABLE.get(finding)
            if adapter_kind is not None:
                if adapter_kind is not store.kind:
                    overrides.set_override(store.id, kind=adapter_kind, note="corrected by probe")
                    report.corrected += 1
            elif store.enabled:
                # Never write a kind this build cannot fetch with. Disable it
                # with a readable reason instead.
                overrides.set_override(store.id, enabled=False, note=_DISABLE_REASON[finding])
                report.disabled += 1

        return report

    async def _probe_one(self, store: StoreConfig) -> tuple[StoreConfig, Finding | None, str]:
        finding = await self.detect(store)
        if finding is None:
            return store, None, ""

        effective = _FETCHABLE.get(finding)
        categories = ""
        if store.enabled and not store.collections and effective is not None:
            categories = await self._describe_categories(store, effective)
        return store, finding, categories

    async def _describe_categories(self, store: StoreConfig, kind: AdapterKind) -> str:
        found = await self._list_categories(store, kind)
        if not found:
            return ""

        # Whatever looks Switch-related survives the display cap regardless of
        # where it would otherwise sort -- that is specifically the thing
        # someone needs in order to scope the store.
        relevant = [c for c in found if _RELEVANT.search(c[0]) or _RELEVANT.search(c[1])]
        rest = [c for c in found if c not in relevant]
        ordered = relevant + rest
        cap = max(20, len(relevant))
        shown = ", ".join(f"{name} ({slug})" for name, slug in ordered[:cap])
        more = f" ... +{len(ordered) - cap} more" if len(ordered) > cap else ""
        flag = f" [{len(relevant)} look Switch-related]" if relevant else ""
        return f"{flag} {shown}{more}".strip()

    async def _list_categories(self, store: StoreConfig, kind: AdapterKind) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if kind is AdapterKind.WOOCOMMERCE:
            for page in range(1, MAX_CATEGORY_PAGES + 1):
                data = await self._client.get_json(
                    f"{store.base_url}/wp-json/wc/store/v1/products/categories"
                    f"?per_page=100&page={page}"
                )
                if not isinstance(data, list) or not data:
                    break
                out += [(str(c.get("name", "")), str(c.get("slug", ""))) for c in data]
                if len(data) < 100:
                    break
            return out

        for page in range(1, MAX_CATEGORY_PAGES + 1):
            data = await self._client.get_json(f"{store.base_url}/collections.json?limit=250&page={page}")
            collections = data.get("collections") if isinstance(data, dict) else None
            if not collections:
                break
            out += [(str(c.get("title", "")), str(c.get("handle", ""))) for c in collections]
            if len(collections) < 250:
                break
        return out

    async def _contains(self, url: str, needle: str) -> bool:
        result = await self._client.get(url)
        return result.ok and needle in result.body
