"""The exe's import-time behaviour.

Run in a SUBPROCESS: the stdout redirect happens while ``switch_tracker.__main__``
is being imported, so it cannot be observed in an interpreter that has already
imported it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REDIRECT_CHECK = textwrap.dedent(
    """
    import sys
    # What a PyInstaller --windowed build looks like: no standard handles.
    sys.stdout = None
    sys.stderr = None
    import switch_tracker.__main__  # noqa: F401
    print("hello from a windowed build")
    sys.stdout.flush()
    """
)


def test_a_windowed_build_logs_into_the_configured_data_dir(
    tmp_path: Path, monkeypatch: type
) -> None:
    """The log must follow TRACKER_DATA_DIR like every other writable file.

    It used to build its own %LOCALAPPDATA%\\switch-tracker path, so it was the
    single place in the app resolving a writable path outside paths.py -- and it
    ignored TRACKER_DATA_DIR, writing outside the directory the user chose.
    """
    result = subprocess.run(
        [sys.executable, "-c", REDIRECT_CHECK],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "TRACKER_DATA_DIR": str(tmp_path), "PYTHONPATH": "src"},
    )

    assert result.returncode == 0, result.stderr
    log = tmp_path / "windowed.log"
    assert log.exists(), f"no log in the configured data dir; got {list(tmp_path.iterdir())}"
    assert "hello from a windowed build" in log.read_text(encoding="utf-8")
