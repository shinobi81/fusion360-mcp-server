#!/usr/bin/env python3
"""Reload the add-in's handler modules, then prove the running class is that file.

The add-in loads ``command_handler`` from the checkout and keeps it in memory, so a
``git pull`` changes what is on disk and nothing about what Fusion executes.  Worse,
``inspect.getsource`` reads *from disk*: asking the running handler to describe itself
answers with the new file even when the loaded class is old, which is how a live check
can pass for days after a merge that was never loaded.

So the check is not "does the file look right" but "does the running class have
exactly the methods the file declares".  A merge that adds or removes a method is
caught, and the loaded file's path is printed - a copy in the AddIns folder masquerading
as the checkout is visible rather than assumed.

    uv run python scripts/reload_addin.py            # reload, then verify
    uv run python scripts/reload_addin.py --check    # verify only, change nothing

``reload_handler`` reloads ``hints``, ``rules``, ``hole_geometry``, ``parameter_units``,
``mutation_commands`` and ``command_handler``.  It does **not** reload ``event_bridge``
or ``socket_server``: a change in either still needs the add-in stopped and started.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from fusion360_mcp.connection import Fusion360Connection, FusionError

HANDLER = (
    Path(__file__).resolve().parent.parent / "addon" / "server" / "command_handler.py"
)


def declared_methods(source: str, path: Path = HANDLER) -> set[str]:
    """The methods ``CommandHandler`` declares in *source*, ignoring dunders."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CommandHandler":
            return {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("__")
            }
    raise SystemExit(f"{path} declares no CommandHandler; this check would be vacuous")


def compare(declared: set[str], loaded: set[str]) -> tuple[set[str], set[str]]:
    """``(missing, extra)`` - what the file has that the running class does not.

    ``missing`` is the dangerous direction: the file is newer and Fusion is executing
    the old class.  ``extra`` means the add-in is running code that is no longer on
    disk, which is the same problem seen from the other side.
    """
    return declared - loaded, loaded - declared


def loaded_class(connection: Fusion360Connection) -> dict:
    """Ask the add-in which file it loaded and which methods its class has."""
    # ``vars(cls)`` with a callable test, not ``dir(cls)``: the latter also lists the
    # class's attribute tables (_VIEW_DIRS, _MUTATION_COMMANDS, ...) - the first
    # version counted those as "extra" methods - and walks the MRO, so an inherited
    # method would read as drift the day this class gains a base.
    code = (
        "import sys\n"
        "mods = [m for n, m in sys.modules.items()\n"
        '        if n.endswith("command_handler") and getattr(m, "__file__", None)]\n'
        "if not mods:\n"
        '    raise RuntimeError("no command_handler module is loaded")\n'
        "cls = mods[0].CommandHandler\n"
        "{\n"
        '    "file": mods[0].__file__,\n'
        '    "methods": sorted(\n'
        "        name\n"
        "        for name in vars(cls)\n"
        '        if callable(getattr(cls, name)) and not name.startswith("__")\n'
        "    ),\n"
        "}\n"
    )
    reply = connection.send_command("execute_code", {"code": code})
    if not reply.get("ok"):
        raise SystemExit(
            f"the add-in could not report its class: {reply.get('error_message')} "
            "(execute_code needs an open document - it reads the active design)"
        )
    return reply["result"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only: do not reload the handler modules",
    )
    parser.add_argument("--host", default=None, help="add-in host")
    parser.add_argument("--port", type=int, default=None, help="add-in port")
    parser.add_argument(
        "--file",
        type=Path,
        default=HANDLER,
        help=f"the file to compare against (default: {HANDLER})",
    )
    args = parser.parse_args(argv)

    connection = Fusion360Connection(
        **{
            key: value
            for key, value in (("host", args.host), ("port", args.port))
            if value is not None
        }
    )
    if not connection.connect():
        print("not connected: is the Fusion360MCP add-in running?", file=sys.stderr)
        return 1

    try:
        if not args.check:
            # ``reload_handler`` is absent from ``mock._MUTATION_MOCKS``, so
            # ``send_command`` may retry it. That is safe here and only here: a reload
            # is idempotent, which is exactly what the no-retry rule for mutations
            # exists to protect.
            #
            # Flat reply, unlike execute_code's {"executed": ..., "result": ...}
            # envelope: the bridge answers with {"ok": True, "reloaded": True}.
            reply = connection.send_command("reload_handler")
            if not reply.get("ok") or not reply.get("reloaded"):
                print(f"reload refused: {reply}", file=sys.stderr)
                return 1
            print(
                "reloaded: hints, rules, hole_geometry, parameter_units, "
                "mutation_commands, command_handler"
            )
            print("  not reloaded: event_bridge, socket_server")

        loaded = loaded_class(connection)
    except (FusionError, ConnectionError) as exc:
        # A fused add-in raises rather than replying: a TIMEOUT or UNKNOWN_COMMAND
        # arrives as FusionError, and a dropped socket as ConnectionError. Both are
        # "could not check", not a traceback for the reader.
        print(f"the add-in did not answer: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.disconnect()

    declared = declared_methods(args.file.read_text(encoding="utf-8"), args.file)
    missing, extra = compare(declared, set(loaded["methods"]))

    print(f"add-in loaded: {loaded['file']}")
    print(f"comparing with: {args.file}")
    if loaded["file"] and Path(loaded["file"]).resolve() != args.file.resolve():
        print("  (a different file is loaded - is an AddIns copy in use?)")
    if missing:
        print(f"MISSING from the running class: {', '.join(sorted(missing))}")
    if extra:
        print(f"EXTRA in the running class:     {', '.join(sorted(extra))}")
    if missing or extra:
        print(
            "\nThe running class is not this file. Reload with "
            "`uv run python scripts/reload_addin.py`, or restart the add-in if the "
            "change is in event_bridge.py or socket_server.py.",
            file=sys.stderr,
        )
        return 1

    print(f"ok: {len(declared)} method names match; bodies are not compared")
    print("    (edit a method body and this still says ok until you reload)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
