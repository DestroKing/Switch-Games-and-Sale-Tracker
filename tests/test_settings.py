"""Settings and paths: values that look configured but quietly are not."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from switch_tracker import paths, settings


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    for name in ("PORT", "HEADFUL", "TRACKER_DB"):
        monkeypatch.delenv(name, raising=False)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def write(data_dir: Path, **values: object) -> None:
    (data_dir / "settings.json").write_text(json.dumps(values), encoding="utf-8")


@pytest.mark.parametrize("port", [0, -1, 65536, 99999, "abc", None])
def test_an_unusable_port_falls_back_to_the_default(data_dir: Path, port: object) -> None:
    """Port 0 binds a random port, and the cross-site guard is built from this
    number -- so a bad value would lock the page out of its own dashboard."""
    write(data_dir, port=port)
    assert settings.load().port == 4173


def test_a_real_port_is_kept(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(data_dir, port=5000)
    assert settings.load().port == 5000
    monkeypatch.setenv("PORT", "4174")
    assert settings.load().port == 4174


def test_the_string_false_does_not_switch_a_setting_on(data_dir: Path) -> None:
    write(data_dir, headful="false", collect_on_launch="false")
    loaded = settings.load()
    assert loaded.headful is False  # bool("false") was True
    assert loaded.collect_on_launch is True  # not a boolean -> the default


def test_real_booleans_are_honoured(data_dir: Path) -> None:
    write(data_dir, headful=True, collect_on_launch=False)
    loaded = settings.load()
    assert (loaded.headful, loaded.collect_on_launch) == (True, False)


def test_an_empty_tracker_db_means_the_default_not_the_current_folder(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRACKER_DB", "")
    assert paths.db_path() == data_dir / "tracker.db"
