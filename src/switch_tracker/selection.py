"""How a store selection is encoded when it crosses a process boundary.

One module because BOTH sides of that boundary need the same answer, and they
cannot share a richer one: the dashboard builds the argv token, the worker parses
it back, and ``services.collect`` -- where the selection is actually applied --
imports ``adapters.base`` and so is unreachable from the web layer without
breaking ``tests/test_import_boundary.py``.

Splitting the encoding across the two callers instead would put "strip
whitespace?" in two places, and a selection that silently fails to match an id
looks exactly like a store that returned nothing.

Deliberately dependency-free: this must stay importable from the dashboard
process, which may not reach an adapter.
"""

from __future__ import annotations

from collections.abc import Iterable

SEPARATOR = ","


def parse_ids(raw: str) -> tuple[str, ...]:
    """``"a, b ,"`` -> ``("a", "b")``. Empty means "every enabled store"."""
    return tuple(part.strip() for part in raw.split(SEPARATOR) if part.strip())


def format_ids(ids: Iterable[str]) -> str:
    """The inverse, for building argv and query strings."""
    return SEPARATOR.join(ids)
