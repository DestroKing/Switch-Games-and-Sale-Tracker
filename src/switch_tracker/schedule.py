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

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from switch_tracker import paths
from switch_tracker.config import overrides
from switch_tracker.core import db
from switch_tracker.web.runs import PidLock, RunAlreadyActive, RunLauncher, worker_command

TASK_NAME = "switch-tracker daily collection"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def collect_now(poll_s: float = 5.0, launcher: RunLauncher | None = None) -> int:
    """Start a collection and block until it ends. Exit 0 unless it could not start."""
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
    return 0


def task_command() -> list[str]:
    """argv for the scheduled task.

    Unfrozen, ``pythonw.exe`` rather than ``python.exe`` where one exists, or
    every scheduled run would flash a console window up over whatever the user
    is doing. The frozen exe is already built windowless (switch_tracker.spec).
    """
    command = worker_command("collect-now")
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

    command = subprocess.list2cmdline(task_command())
    if sys.platform != "win32":
        hour, minute = at.split(":")
        print("Add this line with `crontab -e`:")
        print(f"{int(minute)} {int(hour)} * * * {command}")
        return 0

    # ponytail: plain DAILY trigger -- a PC that is off at that time skips the
    # day. "Run as soon as possible after a missed start" needs a task XML
    # (StartWhenAvailable); add it if missed days turn out to matter.
    result = _schtasks("/Create", "/F", "/SC", "DAILY", "/ST", at, "/TN", TASK_NAME, "/TR", command)
    if result.returncode != 0:
        print(f"Could not create the scheduled task: {result.stderr.strip() or result.stdout.strip()}")
        return 1
    print(f"Prices will be collected every day at {at}. Remove with:  schedule --off")
    return 0


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
