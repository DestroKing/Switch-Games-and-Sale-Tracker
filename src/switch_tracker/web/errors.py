"""Error responses that are honest about being errors.

server.ts returns ``{"error": "..."}`` with HTTP **200**, and the page then
dereferences the missing field -- so a backend fault reaches the user as a
JavaScript type error rendered into the page body. A real status code lets the
client tell "no data yet" from "something broke".
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse


async def json_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": f"{type(exc).__name__}: {exc}", "path": request.url.path},
    )


def error_fragment(message: str, status_code: int = 500) -> HTMLResponse:
    """An htmx-swappable error the user can actually read."""
    return HTMLResponse(f'<div class="error">{message}</div>', status_code=status_code)


def problem(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def ok(payload: Any) -> JSONResponse:
    return JSONResponse(content=payload)
