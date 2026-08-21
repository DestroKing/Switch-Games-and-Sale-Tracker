"""Launching worker processes, and refusing to launch two.

The dashboard process never performs a collection.  It creates a run row,
spawns the exe again with a subcommand, and goes back to serving pages.  That
is what keeps Chromium out of the UI process and lets a scrape survive the
browser tab that started it.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from switch_tracker.core.db import now_iso
from switch_tracker.events.writer import EventWriter


class RunAlreadyActive(Exception):
    """A run is already going. The caller should answer 409, not queue."""


@dataclass(frozen=True, slots=True)
class RunHandle:
    run_id: int
    pid: int
    kind: str


class PidLock:
    """A lock file holding the worker's PID.

    Layer 3 of the guard: catches a SECOND EXE INSTANCE, which the database
    index cannot, because that instance would happily open the same file and
    see no active run if the first one crashed without cleaning up.

    A PID is checkable. A timestamp would only ever be a guess, and a real
    600-second browser run would trip any timeout short enough to be useful.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_pid(self) -> int | None:
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            # Missing or truncated. A corrupt lock must not be more permanent
            # than a real one.
            return None

    def write_pid(self, pid: int) -> None:
        self.path.write_text(str(pid), encoding="utf-8")

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def holder_alive(self) -> bool:
        pid = self.read_pid()
        if pid is None:
            return False
        return _process_alive(pid)


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # No signal 0 on Windows; ask the task list instead.
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _default_spawn(command: list[str]) -> int:
    """Start a worker, detached from any console.

    Two Windows-only details, both of which fail ONLY in a frozen build:

      * CREATE_NO_WINDOW -- without it every worker flashes up a console
        window, which for a dashboard-driven app looks like a malfunction.
      * DEVNULL for all three streams -- a --windowed parent has invalid
        standard handles, and a child inheriting them fails to launch at all.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    return process.pid


def worker_command(subcommand: str, run_id: int | None = None, *extra: str) -> list[str]:
    """How the exe re-invokes itself.

    Frozen, ``sys.executable`` IS the exe, so this runs the same binary again
    with a different argv. Unfrozen it is the interpreter, which needs -m.
    """
    if getattr(sys, "frozen", False):
        command = [sys.executable, subcommand]
    else:
        command = [sys.executable, "-m", "switch_tracker", subcommand]
    if run_id is not None:
        command += ["--run-id", str(run_id)]
    return command + list(extra)


class RunLauncher:
    def __init__(
        self,
        conn: sqlite3.Connection,
        lock: PidLock,
        *,
        spawn: Callable[[list[str]], int] = _default_spawn,
    ) -> None:
        self._conn = conn
        self._lock = lock
        self._spawn = spawn

    def active(self) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM run WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None

    def reap_stale(self) -> None:
        """Clear a run whose worker is gone.

        Called on dashboard startup and before every launch, so a killed
        worker or a machine that slept mid-run cannot wedge the app.
        """
        pid = self._lock.read_pid()
        if pid is not None and _process_alive(pid):
            return

        self._lock.release()
        orphan = self.active()
        if orphan is not None:
            self.finish(orphan, detail="interrupted -- the worker process is no longer running")

    def finish(self, run_id: int, detail: str | None = None) -> None:
        self._conn.execute("UPDATE run SET finished_at = ? WHERE id = ?", (now_iso(), run_id))
        EventWriter(self._conn, run_id).run_finished(detail)
        self._lock.release()

    def start(self, kind: str, *extra: str) -> RunHandle:
        self.reap_stale()
        if self.active() is not None:
            raise RunAlreadyActive(kind)

        try:
            cursor = self._conn.execute("INSERT INTO run (started_at) VALUES (?)", (now_iso(),))
        except sqlite3.IntegrityError as exc:
            # The partial unique index caught a race the check above missed.
            raise RunAlreadyActive(kind) from exc

        run_id = int(cursor.lastrowid or 0)

        try:
            pid = self._spawn(worker_command(kind, run_id, *extra))
        except Exception:
            # A launch that never happened must not leave the app permanently
            # convinced something is running.
            self.finish(run_id, detail="worker failed to start")
            raise

        self._lock.write_pid(pid)
        return RunHandle(run_id=run_id, pid=pid, kind=kind)
