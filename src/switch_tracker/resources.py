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

from functools import cache
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


@cache
def asset_version() -> str:
    """A token that changes whenever a static file does.

    Appended to the CSS and JS URLs so the browser refetches them after an
    upgrade. index.html is rendered per request, so a template change is live
    immediately -- but app.js is a static file, and a browser holding the
    previous copy renders the NEW markup against the OLD script. The symptom
    is a control that appears correctly and does nothing, with no error
    anywhere, which is close to undiagnosable from the page.

    Newest mtime rather than a content hash: it costs a stat per file instead
    of reading them, and it cannot collide across an upgrade. Cached, because
    the answer cannot change within a process -- the files ship inside it.
    """
    newest = max(
        (path.stat().st_mtime for path in static_dir().iterdir() if path.is_file()),
        default=0.0,
    )
    return f"{int(newest):x}"
