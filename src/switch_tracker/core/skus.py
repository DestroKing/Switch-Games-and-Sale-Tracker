"""Deriving a stable per-store product id from a URL.

Ported from skuFromUrl in src/adapters/browser.ts.

This is small and load-bearing.  ``listing`` has UNIQUE(store_id, sku), so a
stable SKU is what makes the second run append a price_point to an existing
listing instead of creating a new one.  If the derivation is unstable across
runs, every price series has exactly one point, "moved since last run" stays
permanently empty, and nothing anywhere reports an error.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# Amazon's ASIN is the stable product id; the slug in front of it is not.
_ASIN = re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE)

_MAX_LENGTH = 120


def sku_from_url(url: str) -> str:
    parsed = urlparse(url)

    asin = _ASIN.search(parsed.path)
    if asin:
        return asin.group(1)

    # Flipkart's own product id, carried in the query string.
    pid = parse_qs(parsed.query).get("pid")
    if pid and pid[0]:
        return pid[0]

    # Otherwise the last path segment. The query string is deliberately
    # excluded: session ids and tracking parameters churn between runs, and
    # letting them into the SKU would mint a new listing every time.
    segments = [s for s in parsed.path.split("/") if s]
    tail = segments[-1] if segments else parsed.path
    return tail[:_MAX_LENGTH]
