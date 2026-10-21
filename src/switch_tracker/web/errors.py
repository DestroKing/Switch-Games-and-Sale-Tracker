"""Error responses that are honest about being errors.

Returning ``{"error": "..."}`` with HTTP **200** lets the page dereference
the missing field -- so a backend fault reaches the user as a
JavaScript type error rendered into the page body. A real status code lets the
client tell "no data yet" from "something broke".
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


async def json_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # The detail stays out of the response: exception text routinely carries
    # local paths (the data dir, the user's name in it), and a page served
    # beyond this machine -- the planned snapshot -- must not echo them.
    #
    # Nothing is logged HERE on purpose. Starlette re-raises after calling this
    # handler, so uvicorn already prints the full traceback to the console (or
    # to windowed.log in the packaged app); logging it again doubled every one.
    return JSONResponse(
        status_code=500,
        content={
            "error": f"Something went wrong ({type(exc).__name__}). The full error is in the "
            "dashboard's console window (windowed.log for the packaged app)."
        },
    )


def problem(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def ok(payload: Any) -> JSONResponse:
    return JSONResponse(content=payload)
