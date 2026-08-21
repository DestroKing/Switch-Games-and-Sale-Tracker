"""The architectural rule, made mechanical.

The dashboard process launches workers; it must never BE one. If it can import
Playwright, a hung Chromium can take the UI down with it -- which is the exact
failure the whole self-invoking-worker design exists to prevent.

Run in a SUBPROCESS on purpose: an in-process assertion is worthless once
pytest has imported the adapters for other tests in the same session.
"""

from __future__ import annotations

import subprocess
import sys

BOUNDARY_CHECK = """
import sys
import switch_tracker.web.app          # the dashboard's whole import graph
import switch_tracker.web.routers.actions
import switch_tracker.web.routers.data
import switch_tracker.web.routers.events
import switch_tracker.web.routers.pages

forbidden = sorted(
    m for m in sys.modules
    if m.startswith("playwright") or m.startswith("switch_tracker.adapters")
)
if forbidden:
    print("LEAKED: " + ", ".join(forbidden))
    raise SystemExit(1)
print("CLEAN")
"""


def test_the_dashboard_never_imports_playwright_or_an_adapter() -> None:
    result = subprocess.run(
        [sys.executable, "-c", BOUNDARY_CHECK],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"boundary violated:\n{result.stdout}{result.stderr}"
    assert "CLEAN" in result.stdout


def test_a_worker_may_import_whatever_it_needs() -> None:
    """The counterpart: the rule constrains the UI process, not the workers."""
    result = subprocess.run(
        [sys.executable, "-c", "import switch_tracker.services.collect_worker; print('OK')"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
