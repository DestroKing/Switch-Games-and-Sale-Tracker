# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build (HLD packaging option B1: bundled Chromium).

Build:   uv run pyinstaller switch_tracker.spec --noconfirm
Output:  dist/switch-tracker/

onedir, not onefile, deliberately:
  * onefile re-extracts ~500 MB to a temp dir on EVERY launch (slow), and
    dropping a node.exe into temp is what antivirus heuristics dislike most.
  * The deliverable is a folder regardless, since Chromium ships alongside.
"""

import os
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

# --- Playwright: the Node driver + its JS. collect_all is what sweeps in
# --- driver/node, which PyInstaller cannot infer from imports alone.
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

# --- certifi: an outbound HTTPS call fails in a frozen build without this.
cert_datas = collect_data_files("certifi")

# --- Our own bundled read-only resources (templates, CSS, vendored htmx).
app_datas = [
    ("src/switch_tracker/web/templates", "switch_tracker/web/templates"),
    ("src/switch_tracker/web/static", "switch_tracker/web/static"),
]


def _browser_datas():
    """Bundle Chromium so the exe needs no download and no installed browser.

    ffmpeg is excluded: it exists for Playwright's video recording, which this
    application never uses, and it is dead weight in the shipped folder.
    """
    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    root = Path(cache) if cache else Path.home() / (
        "AppData/Local/ms-playwright" if os.name == "nt" else ".cache/ms-playwright"
    )
    if not root.is_dir():
        raise SystemExit(
            f"Chromium not found at {root}.\n"
            "Run `playwright install chromium` before building."
        )
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith((".", "ffmpeg")):
            out.append((str(child), f"ms-playwright/{child.name}"))
    if not out:
        raise SystemExit(f"No browser builds under {root}.")
    return out


a = Analysis(
    ["src/switch_tracker/__main__.py"],
    pathex=["src"],
    binaries=pw_binaries,
    datas=pw_datas + cert_datas + app_datas + _browser_datas(),
    hiddenimports=pw_hidden + ["uvicorn.logging", "uvicorn.protocols", "uvicorn.lifespan"],
    hookspath=[],
    runtime_hooks=["packaging/runtime_hook_playwright.py"],
    excludes=["tkinter", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="switch-tracker",
    debug=False,
    strip=False,
    upx=False,           # UPX-packed binaries trip antivirus far harder
    console=True,        # keep a console for now; flip to False once stable
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="switch-tracker",
)
