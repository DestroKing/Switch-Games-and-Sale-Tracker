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


def sku_from_url(url: str, id_params: tuple[str, ...] = ()) -> str:
    """The stable product id for this URL.

    ``id_params`` names query parameters that ARE the product id on this store,
    checked after Flipkart's ``pid`` and before the path tail. It exists because
    the path-tail rule fails outright on a shop that routes every product
    through one path: CeX is ``/product-detail?id=847362`` for its whole
    catalogue, so every row derived the tail "product-detail" and
    UNIQUE(store_id, sku) collapsed 69 scraped products into 1, reporting Ok.

    Opt-in rather than a global "also read ?id=", because this function's job is
    the SAME answer across runs -- a shop with an unrelated ``?id=`` tracking
    parameter would have every SKU change and every price series restart.
    """
    parsed = urlparse(url)

    asin = _ASIN.search(parsed.path)
    if asin:
        return asin.group(1)

    query = parse_qs(parsed.query)

    # Flipkart's own product id, carried in the query string.
    pid = query.get("pid")
    if pid and pid[0]:
        return pid[0]

    for name in id_params:
        values = query.get(name)
        if values and values[0]:
            return values[0][:_MAX_LENGTH]

    # Otherwise the last path segment. The query string is deliberately
    # excluded: session ids and tracking parameters churn between runs, and
    # letting them into the SKU would mint a new listing every time.
    segments = [s for s in parsed.path.split("/") if s]
    tail = segments[-1] if segments else parsed.path
    return tail[:_MAX_LENGTH]
