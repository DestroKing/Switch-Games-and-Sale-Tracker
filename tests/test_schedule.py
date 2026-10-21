"""Scheduled collection: it must go through the same guards as the button."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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

    def test_the_task_passes_its_own_slot(self) -> None:
        assert schedule.task_command("07:30")[-3:] == ["collect-now", "--slot", "07:30"]

    def test_the_task_catches_up_a_missed_day(self) -> None:
        """The one setting `schtasks /SC DAILY` cannot express, and the reason for XML."""
        root = ET.fromstring(schedule.task_xml("07:30", ["C:/app/x.exe", "collect-now", "--slot", "07:30"]))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        assert root.findtext("t:Settings/t:StartWhenAvailable", namespaces=ns) == "true"
        assert root.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=ns).endswith(
            "T07:30:00"
        )
        assert root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns) == "collect-now --slot 07:30"
        # Runs as the user with least privilege, so registering needs no admin.
        assert root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns) == "LeastPrivilege"

    def test_a_path_with_xml_characters_cannot_break_the_definition(self) -> None:
        xml = schedule.task_xml("07:30", [r"C:\Tom & Jerry <x>\app.exe", "collect-now"])
        root = ET.fromstring(xml)  # still well-formed
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns) == r"C:\Tom & Jerry <x>\app.exe"

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
        written: list[str] = []

        def fake(*args: str) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            # Read it NOW: register deletes the temporary file afterwards.
            written.append(Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16"))
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(schedule, "_schtasks", fake)
        assert schedule.register("07:30") == 0
        [args] = calls
        assert args[:4] == ("/Create", "/F", "/TN", schedule.TASK_NAME)
        assert "<StartWhenAvailable>true</StartWhenAvailable>" in written[0]


class TestCatchUp:
    @staticmethod
    def _collection(runs: RunLauncher, finished: datetime, status: str = "ok") -> None:
        run_id = runs.conn.execute(
            "INSERT INTO run (started_at, finished_at) VALUES ('x', ?)", (finished.isoformat(),)
        ).lastrowid
        runs.conn.execute("INSERT OR IGNORE INTO store VALUES ('s','S','u','SHOPIFY','INR',2,1)")
        runs.conn.execute(
            "INSERT INTO run_store (run_id, store_id, status) VALUES (?, 's', ?)", (run_id, status)
        )

    @staticmethod
    def _slot_an_hour_ago() -> str:
        return f"{datetime.now().astimezone() - timedelta(hours=1):%H:%M}"

    def test_skips_when_this_slot_was_already_collected(self, data_dir: Path) -> None:
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        self._collection(runs, datetime.now(UTC) - timedelta(minutes=20))  # after the slot
        assert schedule.collect_now(poll_s=0, launcher=runs, slot=self._slot_an_hour_ago()) == 0
        assert spawned == []

    def test_runs_when_the_last_collection_predates_the_slot(self, data_dir: Path) -> None:
        """The review's case: yesterday's late catch-up must not swallow today's run."""
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        self._collection(runs, datetime.now(UTC) - timedelta(hours=17))  # before the slot
        schedule.collect_now(poll_s=0, launcher=runs, slot=self._slot_an_hour_ago())
        assert spawned  # a rolling 20-hour window would have skipped this

    def test_a_collection_where_every_store_failed_does_not_count(self, data_dir: Path) -> None:
        """A catch-up with no network writes all-failed rows; today is not done."""
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        self._collection(runs, datetime.now(UTC) - timedelta(minutes=20), status="failed")
        schedule.collect_now(poll_s=0, launcher=runs, slot=self._slot_an_hour_ago())
        assert spawned

    def test_a_timestamp_without_a_time_zone_does_not_crash_the_check(self, data_dir: Path) -> None:
        """Seen on a live run: '2026-10-21 11:05:37'. Aware minus naive raises."""
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        naive = (datetime.now(UTC) - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
        run_id = runs.conn.execute(
            "INSERT INTO run (started_at, finished_at) VALUES ('x', ?)", (naive,)
        ).lastrowid
        runs.conn.execute("INSERT INTO store VALUES ('s','S','u','SHOPIFY','INR',2,1)")
        runs.conn.execute("INSERT INTO run_store (run_id, store_id, status) VALUES (?, 's', 'ok')", (run_id,))
        assert schedule.collect_now(poll_s=0, launcher=runs, slot=self._slot_an_hour_ago()) == 0
        assert spawned == []  # read as UTC: after the slot, so skipped

    def test_a_probe_run_is_not_a_collection(self, data_dir: Path) -> None:
        """Probe/fx runs write no run_store rows; they must not suppress a catch-up."""
        spawned: list[list[str]] = []
        runs = launcher(data_dir, spawned)
        runs.conn.execute(
            "INSERT INTO run (started_at, finished_at) VALUES ('x', ?)", (datetime.now(UTC).isoformat(),)
        )
        schedule.collect_now(poll_s=0, launcher=runs, slot=self._slot_an_hour_ago())
        assert spawned

    def test_rejects_a_malformed_slot(self, data_dir: Path) -> None:
        spawned: list[list[str]] = []
        assert schedule.collect_now(poll_s=0, launcher=launcher(data_dir, spawned), slot="7am") == 2
        assert spawned == []

    def test_latest_slot_is_today_once_passed_otherwise_yesterday(self) -> None:
        tz = datetime.now().astimezone().tzinfo
        morning = datetime(2026, 10, 21, 6, 0, tzinfo=tz)
        evening = datetime(2026, 10, 21, 20, 0, tzinfo=tz)
        assert schedule.latest_slot("07:30", morning) == datetime(2026, 10, 20, 7, 30, tzinfo=tz)
        assert schedule.latest_slot("07:30", evening) == datetime(2026, 10, 21, 7, 30, tzinfo=tz)


class TestNotifications:
    def test_only_hits_that_are_new_since_before_the_run_are_announced(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(schedule, "_toast", lambda title, body: shown.append((title, body)))
        best = {"title": "Kirby", "best_price": 3999.0, "best_store": "NI"}
        status = [
            {"game": "kirby", "platform": "SWITCH", "target": 4000.0, "hit": True, "best": best},
            {"game": "zelda", "platform": "SWITCH", "target": 4000.0, "hit": True, "best": best},
        ]
        monkeypatch.setattr(schedule, "_watch_status", lambda conn: status)
        assert schedule.notify_new_hits(None, before={("zelda", "SWITCH")}) == 1  # type: ignore[arg-type]
        assert shown == [("Kirby: \u20b93,999", "At or below your \u20b94,000 target, at NI.")]

    @pytest.mark.skipif(sys.platform != "win32", reason="the toast is Windows-only")
    def test_a_hostile_title_reaches_powershell_only_as_escaped_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            captured["cmd"], captured["env"] = cmd, kw["env"]
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(schedule.subprocess, "run", fake_run)
        schedule._toast("Evil'; Remove-Item C:\\ </text><x>", "body")
        assert captured["cmd"][-1] == schedule._TOAST_SCRIPT  # the script never varies
        xml = captured["env"]["SWITCH_TRACKER_TOAST"]  # type: ignore[index]
        assert "&lt;/text&gt;&lt;x&gt;" in xml and "</text><x>" not in xml


class TestStatus:
    @pytest.mark.skipif(sys.platform != "win32", reason="schtasks is Windows-only")
    def test_reads_next_and_last_run_by_column_not_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No labels at all (/NH): this must work on a non-English Windows too."""
        row = (
            '"PC","\\switch-tracker daily collection","22-10-2026 07:30:00","Bereit",'
            '"Interaktiv","21-10-2026 07:30:00","0","user","x.exe collect-now --slot 07:30"\n'
        )
        monkeypatch.setattr(schedule, "_schtasks", lambda *a: subprocess.CompletedProcess(a, 0, row, ""))
        assert schedule.status() == {
            "supported": True,
            "registered": True,
            "next_run": "22-10-2026 07:30:00",
            "last_run": "21-10-2026 07:30:00",
            "last_result": "0",
        }

    @pytest.mark.skipif(sys.platform != "win32", reason="schtasks is Windows-only")
    def test_a_missing_task_reads_as_not_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(schedule, "_schtasks", lambda *a: subprocess.CompletedProcess(a, 1, "", "ERROR"))
        assert schedule.status() == {"supported": True, "registered": False}
