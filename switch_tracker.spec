# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build (HLD packaging option B1: bundled Chromium).

Build:   uv run pyinstaller switch_tracker.spec --noconfirm
Output:  dist/switch-tracker/
"""

import os
import sys
import shutil
from pathlib import Path

# Add src directory to sys.path so hooks can inspect local modules
sys.path.insert(0, str(Path.cwd() / "src"))

from PyInstaller.utils.hooks import collect_all, collect_data_files

# --- Playwright: Node driver + JS
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

# --- certifi: certificates
cert_datas = collect_data_files("certifi")

# --- playwright-stealth: includes critical JavaScript injection assets (.js)
stealth_datas = collect_data_files("playwright_stealth")

# --- Explicitly collect ALL modules, binaries, and data inside switch_tracker.config
config_datas, config_binaries, config_hidden = collect_all("switch_tracker.config")

# --- App read-only resources
app_datas = [
    ("src/switch_tracker/web/templates", "switch_tracker/web/templates"),
    ("src/switch_tracker/web/static", "switch_tracker/web/static"),
]


def _browser_datas():
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
    binaries=pw_binaries + config_binaries,
    datas=pw_datas + cert_datas + stealth_datas + app_datas + _browser_datas() + config_datas,
    hiddenimports=pw_hidden + config_hidden + [
        "switch_tracker.config",
        "switch_tracker.config.stores",
        "playwright_stealth",
        "uvicorn.logging",
        "uvicorn.protocols",
        "uvicorn.lifespan",
    ],
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
    upx=False,
    console=False,  # Hidden console window
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="switch-tracker",
)