"""Read-only resources that ship inside the bundle.

Uses :mod:`importlib.resources` rather than ``sys._MEIPASS``.  ``_MEIPASS``
exists only in a frozen build, so any code reaching for it behaves differently
in development than in the shipped exe -- the exact class of bug that only
appears after packaging.  ``importlib.resources`` resolves identically in both.

This assumes a PyInstaller ``onedir`` build (the HLD's chosen packaging), where
bundled data is a real directory on disk.  A ``onefile`` build would need
``importlib.resources.as_file`` to materialise a temporary copy.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def _dir(package: str, name: str) -> Path:
    path = Path(str(files(package).joinpath(name)))
    if not path.is_dir():
        raise RuntimeError(f"bundled resource directory missing: {package}/{name} -> {path}")
    return path


def templates_dir() -> Path:
    return _dir("switch_tracker.web", "templates")


def static_dir() -> Path:
    return _dir("switch_tracker.web", "static")
