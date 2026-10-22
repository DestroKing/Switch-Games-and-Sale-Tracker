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


def test_review_previews_a_rematch_without_changing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    path = tmp_path / "t.db"
    seed(path, "Tales of Vesperia Definitive Edition(tbd)", 2999)
    conn = db.connect(path)
    conn.execute(
        "INSERT INTO listing (id, store_id, sku, url, raw_title, platform, region, first_seen, last_seen)"
        " VALUES (2, 'fk', 's2', 'https://f/p/2', 'Tales Of Vesperia - Definitive Edition (Switch)',"
        " 'SWITCH', 'IN', 't', 't')"
    )
    conn.execute(
        "INSERT INTO game (canonical_title, platform, region)"
        " VALUES ('tales vesperia definitive tbd', 'SWITCH', 'IN')"
    )
    conn.execute("UPDATE listing SET game_id = 1 WHERE id = 1")
    conn.close()

    check_data.main(["--db", str(path), "--review"])
    out = capsys.readouterr().out
    assert "A rematch would merge 1 group(s)" in out
    assert "'tales vesperia definitive'" in out
    # Read-only: the stored grouping is untouched.
    assert db.connect(path).execute("SELECT game_id FROM listing WHERE id = 2").fetchone()["game_id"] is None


def test_missing_database_is_reported_not_created(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.db"
    assert check_data.main(["--db", str(missing)]) == 1
    assert not missing.exists()
    assert str(missing) in capsys.readouterr().out
