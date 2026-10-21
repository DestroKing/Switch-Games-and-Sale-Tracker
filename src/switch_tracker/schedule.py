"""Collecting on a schedule, so history accumulates without anyone pressing a button.

``collect-now`` goes through the SAME RunLauncher the dashboard's button uses,
so a scheduled run gets every guard a manual one does: stale-run reaping, the
one-active-run unique index, and the PID lock that catches a second copy of
the app. A scheduled task that bypassed those would be the one way left to
start two collections at once.

It also WAITS for the worker instead of returning the moment it is spawned.
Task Scheduler considers a task finished when its process exits, and a task
that "finishes" in 50ms while a 20-minute collection runs on unseen is a task
whose history says nothing true -- and one whose child an "end task" could
not reach.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from switch_tracker import paths
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.web.runs import PidLock, RunAlreadyActive, RunLauncher, worker_command

TASK_NAME = "switch-tracker daily collection"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def latest_slot(at: str, now: datetime | None = None) -> datetime:
    """The most recent moment the daily task was due, in LOCAL time (the
    trigger's own clock): today at ``at`` if that has passed, else yesterday."""
    now = now or datetime.now().astimezone()
    hour, minute = (int(part) for part in at.split(":"))
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return slot if slot <= now else slot - timedelta(days=1)


def last_collection_finished(conn: sqlite3.Connection) -> datetime | None:
    """When the newest SUCCESSFUL collection ended.

    Only collections write run_store, so probe/fx/inspect runs do not count
    (the same rule as has_ever_collected) -- and a collection counts only if
    at least one store came back ok or partial: a catch-up that ran with no
    network writes a row for every store, all failed, and must not convince
    the next scheduled run that today is already done.
    """
    row = conn.execute(
        "SELECT MAX(r.finished_at) FROM run r WHERE r.finished_at IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM run_store rs WHERE rs.run_id = r.id AND rs.status IN ('ok', 'partial'))"
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        finished = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    except ValueError:
        return None
    # A naive timestamp (seen live: "2026-10-21 11:05:37") would make the
    # aware-minus-naive comparison in collect_now raise. The app writes UTC.
    return finished if finished.tzinfo else finished.replace(tzinfo=UTC)


def collect_now(poll_s: float = 5.0, launcher: RunLauncher | None = None, *, slot: str | None = None) -> int:
    """Start a collection and block until it ends. Exit 0 unless it could not start.

    ``slot`` (what the scheduled task passes, its daily HH:MM): do nothing if a
    successful collection has already finished since the most recent slot --
    i.e. this slot's work is done, by hand or by an earlier catch-up.

    Anchored to the SLOT, not a rolling window. A rolling "collected in the
    last 20 h" check skipped whole days: a 07:30 run missed and caught up at
    15:00 made the NEXT morning's 07:30 run see a collection 16.5 h old and
    skip, leaving ~40 h between collections.
    """
    # The same refusal the dashboard makes on launch (web/app.py): collecting
    # against an unchecked store list produces a screen of failures that look
    # like broken code.
    if not overrides.has_been_probed():
        print("Stores have never been checked. Open the dashboard and press 'Check stores' once.")
        return 2

    if launcher is None:
        conn = db.connect()
        db.ensure_schema(conn)
        launcher = RunLauncher(conn, PidLock(paths.lock_path()))

    if slot is not None and not _HHMM.match(slot):
        print("--slot must be HH:MM (24-hour), e.g.  collect-now --slot 07:30")
        return 2
    if slot is not None:
        due = latest_slot(slot)
        finished = last_collection_finished(launcher.conn)
        if finished is not None and finished >= due:
            print(f"Already collected since the {slot} run was due ({due:%Y-%m-%d %H:%M}); skipping.")
            return 0

    hits_before = _hit_keys(launcher.conn)
    try:
        handle = launcher.start("collect")
    except RunAlreadyActive:
        # Not an error for a schedule: the prices are being collected either way.
        print("A run is already going; leaving it to finish.")
        return 0

    print(f"Collection {handle.run_id} started (worker pid {handle.pid}).")
    while launcher.active() == handle.run_id and launcher.worker_alive():
        time.sleep(poll_s)
    # A worker that died mid-run never wrote finished_at; this closes its run
    # with a readable reason rather than leaving the next launch to find it.
    launcher.reap_stale()
    print(f"Collection {handle.run_id} finished.")
    notify_new_hits(launcher.conn, hits_before)
    return 0


def _watch_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    # Imported here: these are dashboard modules, needed only once a run ends.
    from switch_tracker.core import matcher
    from switch_tracker.web import queries, watchlist

    return queries.watch_status(conn, watchlist.read(), matcher.load_aliases())


def _hit_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    try:
        return {(w["game"], w["platform"]) for w in _watch_status(conn) if w["hit"]}
    except Exception:  # noqa: BLE001 - a broken watchlist must never stop a collection
        return set()


def notify_new_hits(conn: sqlite3.Connection, before: set[tuple[str, str]]) -> int:
    """A Windows notification for each watch that became a hit during this run.

    Only NEW hits: a game that sits under target for a week must not pop up
    every morning. "New" needs no stored state -- it is the hits after the run
    minus the hits before it. Returns how many were shown.
    """
    try:
        fresh = [w for w in _watch_status(conn) if w["hit"] and (w["game"], w["platform"]) not in before]
    except Exception as exc:  # noqa: BLE001 - notifying is an extra; the prices are saved
        print(f"(could not check the watchlist: {exc})")
        return 0
    for w in fresh:
        best = w["best"]
        _toast(
            f"{best['title']}: ₹{best['best_price']:,.0f}",
            f"At or below your ₹{w['target']:,.0f} target, at {best['best_store']}.",
        )
    return len(fresh)


#: The AppUserModelID Windows shows the toast under. PowerShell's own is
#: registered on every Windows install, so no shortcut or installer is needed.
_TOAST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

#: A CONSTANT script. The toast's XML -- which carries shop-supplied titles --
#: arrives through an environment variable, never spliced into this text, so
#: a hostile product name cannot become PowerShell code.
_TOAST_SCRIPT = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime] > $null; "
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
    "ContentType = WindowsRuntime] > $null; "
    "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml($env:SWITCH_TRACKER_TOAST); "
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:SWITCH_TRACKER_APP)"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($x))"
)


def _toast(title: str, body: str) -> None:
    if sys.platform != "win32":
        print(f"{title} -- {body}")
        return
    xml = (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(body)}</text>"
        "</binding></visual></toast>"
    )
    env = {**os.environ, "SWITCH_TRACKER_TOAST": xml, "SWITCH_TRACKER_APP": _TOAST_APP_ID}
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                _TOAST_SCRIPT,
            ],
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"(notification not shown: {exc})")


def task_command(at: str) -> list[str]:
    """argv for the scheduled task, which passes its own slot (``--slot HH:MM``).

    Unfrozen, ``pythonw.exe`` rather than ``python.exe`` where one exists, or
    every scheduled run would flash a console window up over whatever the user
    is doing. The frozen exe is already built windowless (switch_tracker.spec).
    """
    command = [*worker_command("collect-now"), "--slot", at]
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        windowless = Path(command[0]).with_name("pythonw.exe")
        if windowless.exists():
            command[0] = str(windowless)
    return command


def register(at: str | None) -> int:
    """Create (or replace) the daily task. Windows only; elsewhere, print a cron line."""
    if not at or not _HHMM.match(at):
        print("Give a daily time as HH:MM (24-hour), e.g.  schedule --at 07:30")
        return 2
    # The task runs in a fresh environment, so it would NOT see these and would
    # quietly collect into the default database instead of the one this shell
    # is pointed at -- or exit 2 there because those stores were never checked.
    overridden = [name for name in ("TRACKER_DATA_DIR", "TRACKER_DB") if os.environ.get(name)]
    if overridden:
        print(
            f"{' and '.join(overridden)} is set in this shell, but a scheduled task would not see it "
            "and would collect into the default data folder. Unset it to schedule the default "
            "database; a scheduled run against a custom location is not supported."
        )
        return 2

    command = subprocess.list2cmdline(task_command(at))
    if sys.platform != "win32":
        hour, minute = at.split(":")
        print("Add this line with `crontab -e`:")
        print(f"{int(minute)} {int(hour)} * * * {command}")
        return 0

    # Registered from XML, not `schtasks /SC DAILY`, for one setting the flags
    # cannot express: StartWhenAvailable. A plain DAILY trigger simply skips a
    # day the PC was off at that time; with this, the missed run starts at the
    # next chance (and `--slot` stops it re-collecting a slot already done).
    with tempfile.TemporaryDirectory() as tmp:
        definition = Path(tmp) / "task.xml"
        # Task Scheduler wants the XML file in UTF-16, as its own export writes it.
        definition.write_text(task_xml(at, task_command(at)), encoding="utf-16")
        result = _schtasks("/Create", "/F", "/TN", TASK_NAME, "/XML", str(definition))
    if result.returncode != 0:
        print(f"Could not create the scheduled task: {result.stderr.strip() or result.stdout.strip()}")
        return 1
    print(
        f"Prices will be collected every day at {at} (or as soon as the PC is next on, if it was off). "
        "Remove with:  schedule --off"
    )
    return 0


def task_xml(at: str, command: list[str]) -> str:
    """The Task Scheduler definition: daily at ``at``, catch up when missed.

    Runs as the user (InteractiveToken, least privilege) so creating it needs
    no administrator rights, and never on battery restrictions -- a laptop on
    battery at 07:30 would otherwise just skip. IgnoreNew stops a catch-up and
    the regular trigger from overlapping; the 2-hour limit bounds a wedged run.
    """
    executable, *args = command
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>switch-tracker: collect prices once a day</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{at}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(executable)}</Command>
      <Arguments>{escape(subprocess.list2cmdline(args))}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def status() -> dict[str, Any]:
    """Read-only: is the daily collection registered, and when does it run next?

    For the dashboard's status line. Deliberately ONLY reads -- creating or
    changing an OS task from a web endpoint is exactly the kind of capability a
    cross-site request should never be able to reach, so that stays CLI-only.
    """
    if sys.platform != "win32":
        return {"supported": False}
    # CSV, no header, read by COLUMN POSITION: the labels are translated on a
    # non-English Windows ("Nächste Laufzeit"), the column order is not. Looking
    # up "Next Run Time" by name showed no times at all on a localised system.
    result = _schtasks("/Query", "/TN", TASK_NAME, "/FO", "CSV", "/V", "/NH")
    if result.returncode != 0:
        return {"supported": True, "registered": False}
    row = next(csv.reader(io.StringIO(result.stdout.strip())), [])

    def column(index: int) -> str:
        return row[index].strip() if len(row) > index else ""

    return {
        "supported": True,
        "registered": True,
        "next_run": column(_NEXT_RUN),
        "last_run": column(_LAST_RUN),
        "last_result": column(_LAST_RESULT),
    }


#: Fixed column positions in `schtasks /Query /FO CSV /V` output
#: (HostName, TaskName, Next Run Time, Status, Logon Mode, Last Run Time,
#: Last Result, ...), the same on every Windows language.
_NEXT_RUN, _LAST_RUN, _LAST_RESULT = 2, 5, 6


def unregister() -> int:
    if sys.platform != "win32":
        print("Remove the switch-tracker line with `crontab -e`.")
        return 0
    result = _schtasks("/Delete", "/F", "/TN", TASK_NAME)
    if result.returncode != 0:
        print(f"No scheduled collection to remove ({result.stderr.strip() or 'not found'}).")
        return 1
    print("Daily collection removed.")
    return 0


def _schtasks(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
