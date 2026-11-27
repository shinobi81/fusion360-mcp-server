#!/usr/bin/env python3
"""Poll Fusion's main thread and report; never pretend to fix it.

``ping`` is answered by the add-in's socket thread before a command is queued, so a
Fusion blocked on a modal dialog still answers ``pong``.  ``health`` is a normal queued
command: its reply proves the *main thread* executed something, and it carries the app
version, the open document and how many commands are waiting behind the poll.

    uv run python scripts/health_check.py                  # one poll
    uv run python scripts/health_check.py --interval 5 -n 12   # watch for a minute
    uv run python scripts/health_check.py --json           # machine-readable lines

Exit codes are the contract, because a supervisor scripts against them:

    0  the main thread answered
    1  it did not answer inside the bound (wedged, or a modal dialog is up front)
    2  there is no add-in to ask (nothing listening on the port)

What this cannot do, and does not pretend to:

* **Reload or restart Fusion.**  ``scripts/reload_addin.py`` is itself a main-thread
  command, so it cannot run while the thread it would fix is blocked - and a process
  that kills Fusion takes the user's unsaved document with it.
* **Tell a busy thread from a dead one.**  A long CAM run looks exactly like a wedge
  from here.  ``queue_depth`` rising over several polls is the hint that it is working
  through a backlog rather than stuck, which is why the watch mode prints it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from fusion360_mcp.connection import Fusion360Connection, FusionError


def poll(connection: Fusion360Connection, timeout: float) -> tuple[int, dict]:
    """One health call; returns (exit code, what to print)."""
    try:
        reply = connection.health(timeout=timeout)
    except FusionError as exc:
        # A structured refusal from the add-in (the command itself failed).
        return 1, {"answered": False, "error_kind": exc.error_kind, "error": str(exc)}
    except ConnectionError as exc:
        # The socket's bound expired: the main thread never answered.  `health()` sends
        # with retries=0, so this is the wedge case rather than a transient drop.
        return 1, {"answered": False, "error_kind": "NO_ANSWER", "error": str(exc)}
    return 0, {
        "answered": True,
        "app_version": reply.get("app_version"),
        "active_document": reply.get("active_document"),
        "queue_depth": reply.get("queue_depth"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll Fusion's main thread.")
    parser.add_argument("--host", default=None, help="default: the package's")
    parser.add_argument("--port", default=None, type=int, help="default: the package's")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="seconds to wait for the main thread to answer (default 5)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="seconds between polls (default: once)",
    )
    parser.add_argument(
        "-n", "--count", type=int, default=1, help="number of polls (default 1)"
    )
    parser.add_argument(
        "--json", action="store_true", help="one JSON object per poll, for a supervisor"
    )
    args = parser.parse_args(argv)

    connection = Fusion360Connection(host=args.host, port=args.port)
    if not connection.connect():
        print(
            f"no add-in listening on {connection.host}:{connection.port}",
            file=sys.stderr,
        )
        print("start Fusion and run the Fusion360MCP add-in", file=sys.stderr)
        return 2

    code = 0
    try:
        for index in range(max(1, args.count)):
            if index:
                time.sleep(args.interval)
            code, report = poll(connection, args.timeout)
            if args.json:
                print(json.dumps(report))
            elif report["answered"]:
                print(
                    f"ok  version={report['app_version']}  "
                    f"document={report['active_document']}  "
                    f"queue_depth={report['queue_depth']}"
                )
            else:
                print(
                    f"NO ANSWER ({report.get('error_kind')}): {report.get('error')}",
                    file=sys.stderr,
                )
                print(
                    f"ping is answered by the socket thread, so it may still reply; "
                    f"the main thread did not answer within {args.timeout}s.",
                    file=sys.stderr,
                )
    finally:
        connection.disconnect()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
