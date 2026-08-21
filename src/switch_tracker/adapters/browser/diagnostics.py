"""Dumping a page that produced nothing.

A failure you can open in a browser beats a failure that is just a zero.
Written ONLY on a genuine zero-row page: capturing a full-page screenshot for
every store on every run was tried, and it is pure overhead once a store
actually works.
"""

from __future__ import annotations

from playwright.async_api import Page

from switch_tracker import paths


async def dump(page: Page, name: str) -> None:
    try:
        directory = paths.diagnostics_dir()
        (directory / f"{name}.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(directory / f"{name}.png"), full_page=True)
    except Exception:  # noqa: BLE001 - diagnostics must never mask the original problem
        return
