"""Argv dispatch -- the exe's five personalities (LLD 3.4).

    serve     the dashboard (default). Launches the others as subprocesses.
    collect   worker: a full collection run
    probe     worker: detect each store's backend, write corrections
    fx        worker: refresh exchange rates
    inspect   worker: the click-to-pick tool, in a VISIBLE window
    spike     the packaging self-check

The UI process must never import Playwright or an adapter, so every worker
import lives INSIDE its own branch and never at module level.
tests/test_import_boundary.py asserts this in a subprocess -- it is the test
that keeps a hung Chromium from being able to take the dashboard down.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import multiprocessing
import sys, os

if sys.stdout is None or sys.stderr is None:
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", "."), "switch-tracker")
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "windowed.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or log_file
    sys.stderr = sys.stderr or log_file

WORKERS = ("collect", "probe", "fx", "inspect")


def _owns_its_console() -> bool:
    """True when Windows created this console for us -- i.e. we were double-clicked.

    Such a console is destroyed the instant the process exits, so any output
    flashes past unread. GetConsoleProcessList reports how many processes are
    attached; exactly one means nobody else is here, so we made it.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        buf = (ctypes.c_uint32 * 8)()
        return bool(windll.kernel32.GetConsoleProcessList(buf, 8) == 1)
    except Exception:  # noqa: BLE001 - a console probe must never break startup
        return False


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="switch-tracker", add_help=True)
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", *WORKERS, "spike"],
    )
    parser.add_argument("store_id", nargs="?", help="for 'inspect': which store to open")
    parser.add_argument("--run-id", type=int, default=None, help="internal: the run to report into")
    parser.add_argument("--no-collect", action="store_true", help="serve without collecting first")
    return parser.parse_args(argv)


def _run_worker(command: str, run_id: int, store_id: str | None) -> int:
    if command == "collect":
        from switch_tracker.services import collect_worker

        return asyncio.run(collect_worker.run(run_id))
    if command == "probe":
        from switch_tracker.services import probe_worker

        return asyncio.run(probe_worker.run(run_id))
    if command == "fx":
        from switch_tracker.services import fx_refresh

        return asyncio.run(fx_refresh.run(run_id))

    from switch_tracker.services import inspect

    if not store_id:
        print("inspect needs a store id", file=sys.stderr)
        return 2
    return asyncio.run(inspect.run(run_id, store_id))


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "spike":
        from switch_tracker.spike import run

        return run()

    if args.command == "serve":
        from switch_tracker.web.app import serve

        return serve(collect_on_launch=False if args.no_collect else None)

    if args.run_id is None:
        print(f"'{args.command}' is started by the dashboard, not run directly.", file=sys.stderr)
        return 2
    return _run_worker(args.command, args.run_id, args.store_id)


def main(argv: list[str] | None = None) -> int:
    # Must precede any import that could spawn, or a frozen build re-executes
    # itself recursively on Windows.
    multiprocessing.freeze_support()

    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        return 130
    finally:
        # Without this, double-clicking the exe shows a window that vanishes in
        # under a second and the user has no way to learn why. Only fires when
        # Windows created the console for us.
        if _owns_its_console():
            print("\nPress Enter to close this window...", file=sys.stderr)
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input()


if __name__ == "__main__":
    raise SystemExit(main())
