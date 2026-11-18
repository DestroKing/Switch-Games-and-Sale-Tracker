"""The market tracker can be switched off, and removed, without the price tracker noticing.

Written before the feature rather than after it: a boundary that is only
checked at the end has usually been crossed several times by then.

Subprocesses throughout, for the reason tests/test_import_boundary.py gives:
once pytest has imported a module for some other test, an in-process check of
sys.modules proves nothing.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from switch_tracker import paths, settings
from switch_tracker.services.collect_worker import market_observer


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


class TestOffSwitch:
    def test_on_by_default(self, data_dir: Path) -> None:
        assert settings.load().market_tracker is True

    def test_settings_json_turns_it_off(self, data_dir: Path) -> None:
        (data_dir / "settings.json").write_text(json.dumps({"market_tracker": False}), encoding="utf-8")
        assert settings.load().market_tracker is False

    def test_only_a_real_boolean_counts(self, data_dir: Path) -> None:
        """``"false"`` as a string is truthy; it must not be read as a choice."""
        (data_dir / "settings.json").write_text(json.dumps({"market_tracker": "false"}), encoding="utf-8")
        assert settings.load().market_tracker is True


class TestWorkerHook:
    def test_switched_off_opens_nothing(self, data_dir: Path) -> None:
        assert market_observer(False) is None
        assert not (data_dir / "market.db").exists()

    def test_switched_on_opens_market_db(self, data_dir: Path) -> None:
        observer = market_observer(True)
        assert observer is not None
        observer.close()
        assert (data_dir / "market.db").exists()

    def test_a_market_db_it_cannot_open_costs_the_market_data_not_the_run(
        self, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        conn = sqlite3.connect(data_dir / "market.db")
        conn.execute("PRAGMA user_version = 999")
        conn.close()
        assert market_observer(True) is None
        assert "newer than this build" in capsys.readouterr().err


#: Every legacy module a price-only install runs. None may load the market
#: package merely by being imported -- integration happens lazily, behind the flag.
LEGACY_MODULES = (
    "switch_tracker.__main__",
    "switch_tracker.web.app",
    "switch_tracker.web.routers.pages",
    "switch_tracker.web.routers.data",
    "switch_tracker.services.collect",
    "switch_tracker.services.collect_worker",
    "switch_tracker.adapters.registry",
    "switch_tracker.core.db",
    "switch_tracker.schedule",
)


def test_legacy_modules_never_import_the_market_package_eagerly() -> None:
    code = (
        "import importlib, sys\n"
        f"for name in {LEGACY_MODULES!r}: importlib.import_module(name)\n"
        "leaked = sorted(m for m in sys.modules if m.startswith('switch_tracker.market'))\n"
        "print('LEAKED: ' + ', '.join(leaked) if leaked else 'CLEAN')\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CLEAN"


def test_the_market_package_never_imports_playwright_or_an_adapter() -> None:
    """Its read side runs inside the dashboard process, which must never scrape."""
    code = (
        "import importlib, pkgutil, sys\n"
        "import switch_tracker.market as m\n"
        "for info in pkgutil.walk_packages(m.__path__, 'switch_tracker.market.'):\n"
        "    importlib.import_module(info.name)\n"
        "bad = sorted(x for x in sys.modules if x.startswith(('playwright', 'switch_tracker.adapters')))\n"
        "print('LEAKED: ' + ', '.join(bad) if bad else 'CLEAN')\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CLEAN"


def test_the_price_tracker_runs_with_the_market_package_gone(tmp_path: Path) -> None:
    """Removal, simulated: the package is made unimportable, the feature switched off.

    The dashboard must build and serve its page, and a collection must run,
    exactly as before the market tracker existed.
    """
    (tmp_path / "settings.json").write_text(json.dumps({"market_tracker": False}), encoding="utf-8")
    code = f"""
import asyncio, os, sys
os.environ["TRACKER_DATA_DIR"] = {str(tmp_path)!r}
sys.modules["switch_tracker.market"] = None   # any import of it now raises

from fastapi.testclient import TestClient
from switch_tracker.web.app import create_app
client = TestClient(create_app(4173), base_url="http://127.0.0.1:4173")
assert client.get("/").status_code == 200, "dashboard page"
assert client.get("/api/summary").status_code == 200, "legacy API"
assert client.get("/market").status_code == 404, "no market page when removed"

from switch_tracker.core import db
from switch_tracker.core.models import AdapterKind, Ok, Platform, RawListing, Region, Condition, StoreConfig
from switch_tracker.services.collect import CollectService

class Fake:
    kind = AdapterKind.SHOPIFY
    async def fetch(self, store, sink):
        return Ok((RawListing(store.id, "S1", "https://x.example/p", "Game", "INR", 100.0, True,
                              Platform.SWITCH, Region.IN, Condition.NEW),))

conn = db.connect()
db.ensure_schema(conn)
store = StoreConfig("x", "X", "https://x.example", AdapterKind.SHOPIFY, "INR", 2, True)
asyncio.run(CollectService(conn, adapters={{AdapterKind.SHOPIFY: Fake()}}, fx=None).run([store]))
assert conn.execute("SELECT COUNT(*) FROM price_point").fetchone()[0] == 1, "collection"
assert not os.path.exists(os.path.join({str(tmp_path)!r}, "market.db")), "no market.db"

# Removed but still switched on (settings left behind): the worker carries on without it.
from switch_tracker.services.collect_worker import market_observer
assert market_observer(True) is None, "worker hook with the package gone"
print("OK")
"""
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("OK")
