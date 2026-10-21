"""scripts/check_data.py: fails on what a broken collection saves, passes on a clean one."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from switch_tracker.core import db

_SPEC = importlib.util.spec_from_file_location(
    "check_data", Path(__file__).resolve().parent.parent / "scripts" / "check_data.py"
)
assert _SPEC and _SPEC.loader
check_data = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_data)


def seed(path: Path, title: str, price: float) -> None:
    conn = db.connect(path)
    db.ensure_schema(conn)
    conn.execute("INSERT INTO store VALUES ('fk','Flipkart','https://f','BROWSER','INR',1,1)")
    conn.execute("INSERT INTO run (id, started_at, finished_at) VALUES (1, 't', 't')")
    conn.execute(
        "INSERT INTO listing (id, store_id, sku, url, raw_title, platform, region, first_seen, last_seen)"
        " VALUES (1, 'fk', 's1', 'https://f/p/1', ?, 'SWITCH', 'IN', 't', 't')",
        (title,),
    )
    conn.execute(
        "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, native_price, inr_price,"
        " in_stock) VALUES (1, 1, 't', 'INR', ?, ?, 1)",
        (price, price),
    )
    conn.close()


@pytest.mark.parametrize(
    ("title", "price", "code"),
    [
        ("The Legend of Zelda: Breath of the Wild - Nintendo Switch (2017)", 4499, 0),
        ("The Legend of Zelda: Breath of the Wild - Nintendo Swit...", 4499, 1),  # cut title
        ("Pikmin 4", 0, 1),  # zero price
    ],
)
def test_exit_code_flags_cut_titles_and_bad_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, title: str, price: float, code: int
) -> None:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))  # an empty watchlist, not the real one
    seed(tmp_path / "t.db", title, price)
    assert check_data.main(["--db", str(tmp_path / "t.db")]) == code
