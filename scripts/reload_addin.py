#!/usr/bin/env python3
"""Reload the add-in's handler modules, then prove the running class is those files.

The add-in loads ``command_handler`` from the checkout and keeps it in memory, so a
``git pull`` changes what is on disk and nothing about what Fusion executes.  Worse,
``inspect.getsource`` reads *from disk*: asking the running handler to describe itself
answers with the new file even when the loaded class is old, which is how a live check
can pass for days after a merge that was never loaded.

So the check is not "do the files look right" but "does the running class have exactly
the methods the files declare".  Those methods need not sit on one class in one file: a
base plus a mixin per domain is the layout the check is built for, so it reads one
module at a time (``COMMAND_MODULES``) and one class at a time, up ``cls.__mro__``.  A
merge that adds or removes a method is caught, and the loaded file's path is printed - a
copy in the AddIns folder masquerading as the checkout is visible rather than assumed.

    uv run python scripts/reload_addin.py            # reload, then verify
    uv run python scripts/reload_addin.py --check    # verify only, change nothing

``reload_handler`` re-executes ``RELOAD_ORDER``: the sibling modules a handler module
imports at module scope, then ``COMMAND_MODULES``, that list being base first and
``command_handler`` last.  It does **not** reload ``event_bridge`` or ``socket_server``:
a change in either still needs the add-in stopped and started.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from fusion360_mcp.connection import Fusion360Connection, FusionError

SERVER = Path(__file__).resolve().parent.parent / "addon" / "server"
HANDLER = SERVER / "command_handler.py"

#: The modules under ``addon/server/`` that declare command methods, in reload order:
#: anything the next module inherits from first, ``command_handler`` last, because a
#: module re-executed after its importer leaves the importer holding the old class.
#: The add-in keeps its own copy - it cannot import this file - and
#: ``tests/test_reload_addin.py`` fails if the two disagree.
COMMAND_MODULES: tuple[str, ...] = (
    "handler_base",
    "handler_assembly",
    "handler_sketch",
    "handler_features",
    "handler_surface",
    "handler_primitives",
    "handler_scene",
    "handler_export",
    "handler_cam",
    "command_handler",
)

#: Every module ``reload_handler`` re-executes, in order.  The printed success line is
#: this tuple, so a module added to the reload is named in one place.
RELOAD_ORDER: tuple[str, ...] = (
    "hints",
    "rules",
    "hole_geometry",
    "parameter_units",
    "mutation_commands",
    *COMMAND_MODULES,
)


def _is_command_class(name: str) -> bool:
    """Whether a class called *name* declares methods the running class answers.

    "Ends with ``Commands``" alone is not enough: a base class is not named that way,
    and its methods are on ``CommandHandler`` too, so they would read as drift.
    """
    return "Handler" in name or name.endswith("Commands")


def declared_methods(sources: dict[str, str]) -> set[str]:
    """The command methods *sources* declare, dunders excluded.

    *sources* maps a filename under ``addon/server/`` to its text.  Every module in
    ``COMMAND_MODULES`` has to be in it, and has to declare a command class: a check
    that quietly read five of six modules, or found no class in one of them, would pass
    for ever without comparing the commands it exists to compare.
    """
    required = {f"{stem}.py" for stem in COMMAND_MODULES}
    absent = sorted(required - set(sources))
    if absent:
        raise SystemExit(
            f"{', '.join(absent)} named in COMMAND_MODULES but never read; "
            "this check would be vacuous"
        )

    declared: set[str] = set()
    for filename, source in sources.items():
        classes = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ClassDef) and _is_command_class(node.name)
        ]
        if not classes and filename in required:
            raise SystemExit(
                f"{filename} declares no command class; this check would be vacuous"
            )
        declared.update(
            item.name
            for node in classes
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not item.name.startswith("__")
        )
    return declared


def compare(declared: set[str], loaded: set[str]) -> tuple[set[str], set[str]]:
    """``(missing, extra)`` - what the files have that the running class does not.

    ``missing`` is the dangerous direction: a file is newer and Fusion is executing the
    old class.  ``extra`` means the add-in is running code that is no longer on disk,
    which is the same problem seen from the other side.
    """
    return declared - loaded, loaded - declared


def loaded_class(connection: Fusion360Connection) -> dict:
    """Ask the add-in which file it loaded and which methods its class has."""
    # ``cls.__mro__`` with ``vars``, not ``dir(cls)`` alone: a method inherited from a
    # base or a mixin has to count, and taking ``vars`` per class is what keeps the
    # class's attribute tables (_VIEW_DIRS, _MUTATION_COMMANDS, ...) out - ``dir()``
    # lists those, and the first version reported them as "extra".
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
        "        {\n"
        "            name\n"
        "            for klass in cls.__mro__\n"
        "            for name in vars(klass)\n"
        '            if callable(getattr(cls, name)) and not name.startswith("__")\n'
        "        }\n"
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
    # A literal, not the module docstring's first line: under ``python -OO``
    # ``__doc__`` is ``None``, and ``(None or "").splitlines()[0]`` raises IndexError
    # before the script reaches the add-in.  ``main`` needs no help text from it.
    parser = argparse.ArgumentParser(description="Reload the add-in and verify it.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only: do not reload the handler modules",
    )
    parser.add_argument("--host", default=None, help="add-in host")
    parser.add_argument("--port", type=int, default=None, help="add-in port")
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
            print(f"reloaded: {', '.join(RELOAD_ORDER)}")
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

    sources: dict[str, str] = {}
    for stem in COMMAND_MODULES:
        path = SERVER / f"{stem}.py"
        # A module named but missing is left out of the mapping rather than raised on
        # here: ``declared_methods`` names every one of them in a single line, instead
        # of the reader meeting a FileNotFoundError traceback half-way through.
        if path.is_file():
            sources[path.name] = path.read_text(encoding="utf-8")
    declared = declared_methods(sources)
    missing, extra = compare(declared, set(loaded["methods"]))

    print(f"add-in loaded: {loaded['file']}")
    print(f"comparing with: {', '.join(sources)} in {SERVER}")
    # Only ``command_handler`` has a path of its own: the domain modules are reached
    # through it, so a different command_handler.py loaded is a different tree.
    if loaded["file"] and Path(loaded["file"]).resolve() != HANDLER.resolve():
        print("  (a different file is loaded - is an AddIns copy in use?)")
    if missing:
        print(f"MISSING from the running class: {', '.join(sorted(missing))}")
    if extra:
        print(f"EXTRA in the running class:     {', '.join(sorted(extra))}")
    if missing or extra:
        print(
            "\nThe running class is not these files. Reload with "
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
