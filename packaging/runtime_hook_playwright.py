"""PyInstaller runtime hook: make the bundle safe for spawning real browsers.

Two jobs, both of which must happen before Playwright is first imported --
which is precisely what a runtime hook guarantees.

This is the ONE place ``sys._MEIPASS`` is legitimate. The rest of the codebase
is banned from it (see switch_tracker/resources.py) because application code
must behave identically frozen and unfrozen. A runtime hook is not application
code: it is bootstrap that by definition only ever runs frozen.
"""

import os
import sys

if hasattr(sys, "_MEIPASS"):
    # --- 1. Point Playwright at the Chromium we shipped (HLD option B1).
    bundled = os.path.join(sys._MEIPASS, "ms-playwright")
    if os.path.isdir(bundled):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled

    # --- 2. Un-poison the dynamic linker for CHILD processes.
    #
    # PyInstaller sets LD_LIBRARY_PATH to its own bundle so the frozen
    # interpreter finds its libraries. Every child inherits that -- and
    # Playwright's chain is python -> node driver -> chrome, so Chromium
    # ends up resolving against PyInstaller's bundled glibc/NSS instead of
    # the system's. It launches, then dies mid-navigation with a bare
    # TargetClosedError that names nothing useful. Observed on Linux while
    # building this spike; cost an hour to bisect.
    #
    # Harmless on Windows (no such variable), kept unconditional so the
    # behaviour cannot diverge between the machine that builds and the
    # machine that runs.
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = os.environ.get(f"{var}_ORIG")
        if original is not None:
            os.environ[var] = original
        else:
            os.environ.pop(var, None)
