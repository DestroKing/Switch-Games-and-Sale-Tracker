"""Physical-release market catalogue and evidence primitives.

Separate from the price watchlist's game/listing identity. A retailer SKU is
an offer identifier, not a physical-release ID.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MarketFormat(StrEnum):
    FULL_GAME_CARD = "FULL_GAME_CARD"
    GAME_KEY_CARD = "GAME_KEY_CARD"
    CODE_IN_BOX = "CODE_IN_BOX"
    DOWNLOAD_CODE = "DOWNLOAD_CODE"
    UNKNOWN = "UNKNOWN"


class CoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ScopeType(StrEnum):
    RETAILER_CATALOGUE = "RETAILER_CATALOGUE"
    PHYSICAL_GAME_CATEGORY = "PHYSICAL_GAME_CATEGORY"
    SEARCH_RESULTS = "SEARCH_RESULTS"
    CONFIGURED_COLLECTION = "CONFIGURED_COLLECTION"
    MANUAL_GROUP = "MANUAL_GROUP"


class ObservationState(StrEnum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    LISTED = "LISTED"
    NOT_LISTED = "NOT_LISTED"
    UNKNOWN = "UNKNOWN"


class RetailerRelationship(StrEnum):
    VERIFIED_INDEPENDENT = "VERIFIED_INDEPENDENT"
    VERIFIED_SAME_GROUP = "VERIFIED_SAME_GROUP"
    MARKETPLACE = "MARKETPLACE"
    UNVERIFIED = "UNVERIFIED"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity_part(value: str) -> str:
    return re.sub(r"\\s+", " ", value.strip()).casefold()


def identity_key(title: str, platform: str, edition: str, region: str, physical_format: str) -> str:
    """Stable identity over release dimensions, not retailer SKU."""
    parts = [_identity_part(v) for v in (title, platform, edition, region, physical_format)]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def create_product(
    conn: sqlite3.Connection,
    *,
    title: str,
    platform: str,
    edition: str = "STANDARD",
    region: str = "UNKNOWN",
    physical_format: MarketFormat | str = MarketFormat.UNKNOWN,
    release_date: str | None = None,
    linked_game_id: int | None = None,
    source_url: str | None = None,
    verified_at: str | None = None,
) -> int:
    """Create or return an exact identity; ambiguous matches are never guessed."""
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("title must not be empty")
    if platform not in {"SWITCH", "SWITCH2"}:
        raise ValueError("platform must be SWITCH or SWITCH2")
    fmt = MarketFormat(physical_format).value
    edition_value = edition.strip() or "UNKNOWN"
    region_value = region.strip().upper() or "UNKNOWN"
    key = identity_key(clean_title, platform, edition_value, region_value, fmt)
    conn.execute(
        """INSERT INTO market_catalogue
           (identity_key, title, platform, edition, region, physical_format,
            release_date, linked_game_id, source_url, verified_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(identity_key) DO NOTHING""",
        (key, clean_title, platform, edition_value, region_value, fmt,
         release_date, linked_game_id, source_url, verified_at, now_iso(), now_iso()),
    )
    row = conn.execute("SELECT id FROM market_catalogue WHERE identity_key = ?", (key,)).fetchone()
    assert row is not None
    return int(row["id"])


def record_scan(
    conn: sqlite3.Connection,
    *,
    store_id: str,
    scope_key: str,
    scope_type: ScopeType | str,
    coverage_status: CoverageStatus | str,
    run_id: int | None = None,
    expected_count: int | None = None,
    pages_expected: int | None = None,
    pages_seen: int = 0,
    detail: str | None = None,
) -> int:
    status = CoverageStatus(coverage_status)
    scope = ScopeType(scope_type)
    if not scope_key.strip():
        raise ValueError("scope_key must not be empty")
    if status is CoverageStatus.COMPLETE:
        if pages_expected is not None and pages_seen < pages_expected:
            raise ValueError("a COMPLETE scan cannot have fewer pages_seen than pages_expected")
        if expected_count is not None and expected_count < 0:
            raise ValueError("expected_count cannot be negative")
    cursor = conn.execute(
        """INSERT INTO market_scan
           (run_id, store_id, scope_key, scope_type, coverage_status, expected_count,
            pages_expected, pages_seen, started_at, completed_at, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, store_id, scope_key, scope.value, status.value, expected_count,
         pages_expected, pages_seen, now_iso(), now_iso(), detail),
    )
    return int(cursor.lastrowid)


def upsert_retailer_item(
    conn: sqlite3.Connection,
    *,
    store_id: str,
    scope_key: str,
    item_key: str,
    url: str,
    product_id: int | None = None,
    sku: str | None = None,
) -> int:
    """Persist retailer identity independently of price parsing or stock."""
    if not item_key.strip():
        raise ValueError("item_key must not be empty")
    now = now_iso()
    conn.execute(
        """INSERT INTO market_retailer_item
           (store_id, scope_key, item_key, sku, url, product_id, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(store_id, scope_key, item_key) DO UPDATE SET
             sku = COALESCE(excluded.sku, market_retailer_item.sku),
             url = excluded.url,
             product_id = COALESCE(excluded.product_id, market_retailer_item.product_id),
             last_seen = excluded.last_seen""",
        (store_id, scope_key, item_key, sku, url, product_id, now, now),
    )
    row = conn.execute(
        """SELECT id FROM market_retailer_item
           WHERE store_id = ? AND scope_key = ? AND item_key = ?""",
        (store_id, scope_key, item_key),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def record_observation(
    conn: sqlite3.Connection,
    *,
    scan_id: int,
    retailer_item_id: int,
    state: ObservationState | str,
    price: float | None = None,
    currency: str | None = None,
) -> int:
    observed_state = ObservationState(state)
    if observed_state is ObservationState.NOT_LISTED:
        raise ValueError("NOT_LISTED is generated only by complete-scan reconciliation")
    if price is not None and price < 0:
        raise ValueError("price cannot be negative")
    cursor = conn.execute(
        """INSERT INTO market_item_observation
           (scan_id, retailer_item_id, observed_at, state, price, currency)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (scan_id, retailer_item_id, now_iso(), observed_state.value, price, currency),
    )
    return int(cursor.lastrowid)


def reconcile_complete_scan(conn: sqlite3.Connection, scan_id: int) -> int:
    """Record scoped NOT_LISTED observations only for a verified complete scan."""
    scan = conn.execute("SELECT * FROM market_scan WHERE id = ?", (scan_id,)).fetchone()
    if scan is None:
        raise ValueError("unknown scan_id")
    if scan["coverage_status"] != CoverageStatus.COMPLETE.value:
        return 0
    cursor = conn.execute(
        """INSERT INTO market_item_observation
           (scan_id, retailer_item_id, observed_at, state)
           SELECT ?, item.id, ?, ?
           FROM market_retailer_item item
           WHERE item.store_id = ? AND item.scope_key = ?
             AND NOT EXISTS (
               SELECT 1 FROM market_item_observation seen
               WHERE seen.scan_id = ? AND seen.retailer_item_id = item.id
             )""",
        (scan_id, now_iso(), ObservationState.NOT_LISTED.value,
         scan["store_id"], scan["scope_key"], scan_id),
    )
    return max(cursor.rowcount, 0)


def overview(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM market_catalogue) AS products,
             (SELECT COUNT(*) FROM market_retailer_item) AS retailer_items,
             (SELECT COUNT(*) FROM market_evidence) AS evidence_records,
             (SELECT COUNT(*) FROM market_scan WHERE coverage_status = 'COMPLETE') AS complete_scans,
             (SELECT COUNT(*) FROM market_scan WHERE coverage_status != 'COMPLETE') AS unverified_scans"""
    ).fetchone()
    return dict(row)


def catalogue(
    conn: sqlite3.Connection, *, q: str = "", platform: str = "", limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    where: list[str] = []
    params: list[Any] = []
    if q.strip():
        where.append("p.title LIKE ? ESCAPE '\\'")
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{escaped}%")
    if platform in {"SWITCH", "SWITCH2"}:
        where.append("p.platform = ?")
        params.append(platform)
    clause = "WHERE " + " AND ".join(where) if where else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM market_catalogue p {clause}", params).fetchone()[0])
    rows = [dict(row) for row in conn.execute(
        f"""SELECT p.id, p.title, p.platform, p.edition, p.region, p.physical_format,
                   p.release_date, p.verified_at,
                   (SELECT COUNT(DISTINCT i.store_id) FROM market_retailer_item i
                    WHERE i.product_id = p.id) AS retailer_count,
                   (SELECT COUNT(*) FROM market_evidence e WHERE e.product_id = p.id) AS evidence_count
            FROM market_catalogue p {clause}
            ORDER BY p.title COLLATE NOCASE, p.platform, p.region
            LIMIT ? OFFSET ?""",
        [*params, safe_limit, safe_offset],
    )]
    return {"total": total, "rows": rows, "limit": safe_limit, "offset": safe_offset}


def product_detail(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    product = conn.execute("SELECT * FROM market_catalogue WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        return None
    items = [dict(row) for row in conn.execute(
        """SELECT i.id, i.store_id, s.name AS store_name, i.scope_key, i.sku, i.url,
                  i.first_seen, i.last_seen,
                  (SELECT o.state FROM market_item_observation o
                   WHERE o.retailer_item_id = i.id ORDER BY o.id DESC LIMIT 1) AS latest_state,
                  (SELECT o.price FROM market_item_observation o
                   WHERE o.retailer_item_id = i.id ORDER BY o.id DESC LIMIT 1) AS latest_price,
                  (SELECT o.currency FROM market_item_observation o
                   WHERE o.retailer_item_id = i.id ORDER BY o.id DESC LIMIT 1) AS latest_currency
           FROM market_retailer_item i JOIN store s ON s.id = i.store_id
           WHERE i.product_id = ? ORDER BY s.name""",
        (product_id,),
    )]
    evidence = [dict(row) for row in conn.execute(
        "SELECT * FROM market_evidence WHERE product_id = ? ORDER BY checked_at DESC, id DESC",
        (product_id,),
    )]
    return {"product": dict(product), "retailer_items": items, "evidence": evidence}


def add_evidence(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    evidence_type: str,
    source_url: str,
    source_name: str | None = None,
    published_at: str | None = None,
    verification: str = "UNVERIFIED",
    confidence: str = "LOW",
    notes: str | None = None,
) -> int:
    """Attach dated, source-backed print-status or format evidence."""
    if not source_url.startswith(("https://", "http://")):
        raise ValueError("evidence source_url must be HTTP(S)")
    cursor = conn.execute(
        """INSERT INTO market_evidence
           (product_id, evidence_type, source_url, source_name, published_at,
            checked_at, verification, confidence, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_id, evidence_type, source_url, source_name, published_at,
         now_iso(), verification, confidence, notes),
    )
    return int(cursor.lastrowid)


def set_retailer_group(
    conn: sqlite3.Connection,
    *,
    store_id: str,
    group_key: str,
    display_name: str,
    relationship: RetailerRelationship | str = RetailerRelationship.UNVERIFIED,
    legal_entity: str | None = None,
    evidence_url: str | None = None,
    confidence: str = "UNVERIFIED",
    notes: str | None = None,
) -> int:
    """Set an auditable retailer grouping; unknown ownership stays unverified."""
    relationship_value = RetailerRelationship(relationship).value
    checked = now_iso() if evidence_url else None
    conn.execute(
        """INSERT INTO market_retailer_group
           (group_key, display_name, relationship, legal_entity, evidence_url, checked_at, confidence, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(group_key) DO UPDATE SET
             display_name=excluded.display_name, relationship=excluded.relationship,
             legal_entity=excluded.legal_entity, evidence_url=excluded.evidence_url,
             checked_at=excluded.checked_at, confidence=excluded.confidence, notes=excluded.notes""",
        (group_key, display_name, relationship_value, legal_entity, evidence_url, checked, confidence, notes),
    )
    group = conn.execute("SELECT id FROM market_retailer_group WHERE group_key = ?", (group_key,)).fetchone()
    assert group is not None
    conn.execute(
        """INSERT INTO market_retailer_group_member (store_id, group_id) VALUES (?, ?)
           ON CONFLICT(store_id) DO UPDATE SET group_id=excluded.group_id""",
        (store_id, int(group["id"])),
    )
    return int(group["id"])
