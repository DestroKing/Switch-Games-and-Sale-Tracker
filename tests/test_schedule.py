"""Scheduled collection: it must go through the same guards as the button."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from switch_tracker import paths, schedule
from switch_tracker.core import db
from switch_tracker.web.runs import PidLock, RunLauncher

#: A PID that is never alive, so the "wait for the worker" loop ends at once.
_DEAD_PID = 2**22 + 7


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    paths.overrides_path().write_text("{}", encoding="utf-8")  # stores have been checked
    yield tmp_path
    paths.data_dir.cache_clear()


def launcher(tmp_path: Path, spawned: list[list[str]]) -> RunLauncher:
    conn = db.connect(tmp_path / "s.db")
    db.ensure_schema(conn)

    def spawn(command: list[str]) -> int:
        spawned.append(command)
        return _DEAD_PID

    return RunLauncher(conn, PidLock(tmp_path / "run.lock"), spawn=spawn)


class TestCollectNow:
    def test_starts_a_collection_through_the_launcher_and_closes_it(self, data_dir: Path) -> None:
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        assert schedule.collect_now(poll_s=0, launcher=runs) == 0
        assert spawned and "collect" in spawned[0]
        # The fake worker "died" without finishing; the run must still be closed,
        # or the next scheduled day would find it active and do nothing.
        assert runs.active() is None

    def test_an_active_run_is_left_alone_and_is_not_an_error(self, data_dir: Path) -> None:
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        runs._conn.execute("INSERT INTO run (started_at) VALUES ('t')")
        (data_dir / "run.lock").write_text(str(os.getpid()), encoding="utf-8")
        assert schedule.collect_now(poll_s=0, launcher=runs) == 0
        assert spawned == []

    def test_refuses_before_the_stores_have_ever_been_checked(self, data_dir: Path) -> None:
        paths.overrides_path().unlink()
        spawned: list[list[str]] = []
        assert schedule.collect_now(poll_s=0, launcher=launcher(data_dir, spawned)) == 2
        assert spawned == []


class TestRegister:
    def test_rejects_a_time_that_is_not_hh_mm(self) -> None:
        assert schedule.register("7.30am") == 2
        assert schedule.register(None) == 2

    def test_the_task_runs_collect_now(self) -> None:
        assert schedule.task_command()[-1] == "collect-now"

    def test_refuses_while_the_data_dir_is_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The task would not inherit it, and would collect into a different database."""
        monkeypatch.setenv("TRACKER_DATA_DIR", "D:/elsewhere")
        monkeypatch.setattr(schedule, "_schtasks", lambda *a: pytest.fail("must not register"))
        assert schedule.register("07:30") == 2

    @pytest.mark.skipif(sys.platform != "win32", reason="schtasks is Windows-only")
    def test_creates_a_daily_task_at_the_given_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TRACKER_DATA_DIR", raising=False)
        monkeypatch.delenv("TRACKER_DB", raising=False)
        calls: list[tuple[str, ...]] = []

        def fake(*args: str) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(schedule, "_schtasks", fake)
        assert schedule.register("07:30") == 0
        [args] = calls
        assert args[:6] == ("/Create", "/F", "/SC", "DAILY", "/ST", "07:30")
        assert args[args.index("/TR") + 1].endswith("collect-now")
