#!/usr/bin/env python3
"""Check every ``adsk`` name the add-in uses against the Fusion that is running.

A fake proves the *shape* of a call.  It cannot prove the name exists: the surface
family shipped green tests over ``FlangeFeatures.createInput`` and
``features.bendFeatures``, neither of which any Fusion build has, and a trim test
(since deleted with the helpers it covered) asserted
``PointContainment.InsidePointContainment`` when the member is
``PointInsidePointContainment``.  Each of those was a name this repo invented, and each
was found by reading Fusion rather than by reading the tests.

So ask Fusion.  This sends one ``execute_code`` command that walks every
``adsk.<dotted.path>`` reference under ``addon/server`` and reports the ones the live
module does not have, with the file and line each came from.  A missing name is a
failure: the add-in would raise ``AttributeError`` the first time that command ran.

    uv run python scripts/check_fusion_api.py
    uv run python scripts/check_fusion_api.py --host 127.0.0.1 --port 9876

``--check`` is accepted for symmetry with ``reload_addin.py``; there is nothing to
change, so it is the only thing this script ever does.

It proves *names*, not arities or argument types: ``createInput(edge, 1.0)`` against a
signature that takes ``(edges, distance)`` passes here and fails in Fusion.  Those cases
still need the call itself, which is why ``AGENTS.md`` asks for a live call on every
add-in change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fusion360_mcp.connection import Fusion360Connection

SERVER = Path(__file__).resolve().parent.parent / "addon" / "server"

#: The audit, run inside Fusion.  ``Path.read_text`` on the checkout is deliberate: the
#: add-in already runs from that tree (``reload_addin.py`` checks which), so the files
#: it is checking are the files Fusion executes.
AUDIT = """
import json, pathlib, re, sys
import adsk, adsk.core, adsk.fusion, adsk.cam

root = pathlib.Path({server!r})
pattern = re.compile(r"\\badsk\\.((?:[A-Za-z_]\\w*)(?:\\.[A-Za-z_]\\w*)*)")
missing, refs = [], 0
for path in sorted(root.glob("*.py")):
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for chain in pattern.findall(line):
            refs += 1
            node = adsk
            for part in chain.split("."):
                if not hasattr(node, part):
                    missing.append(f"{{path.name}}:{{lineno}} adsk.{{chain}}")
                    break
                node = getattr(node, part)
print(json.dumps({{"refs": refs, "missing": sorted(missing), "version": app.version}}))
"""


def _audit(host: str | None, port: int | None) -> tuple[int, dict | None]:
    """Send the audit to Fusion and return (exit code, its report)."""
    if host is not None and port is not None:
        connection = Fusion360Connection(host=host, port=port)
    elif host is not None:
        connection = Fusion360Connection(host=host)
    elif port is not None:
        connection = Fusion360Connection(port=port)
    else:
        connection = Fusion360Connection()
    if not connection.connect():
        print("not connected: is the Fusion360MCP add-in running?", file=sys.stderr)
        return 1, None

    try:
        reply = connection.send_command(
            "execute_code", {"code": AUDIT.format(server=str(SERVER))}
        )
    finally:
        connection.disconnect()

    if not reply.get("ok", True) or not reply.get("executed"):
        print(f"the audit did not run: {reply}", file=sys.stderr)
        return 1, None

    result = reply.get("result")
    if isinstance(result, str) and result.strip().startswith("{"):
        # ``execute_code`` returns the script's last expression; the audit prints JSON
        # and ends with a print, so its stdout is the answer when the value is empty.
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = None
    elif not isinstance(result, dict):
        result = None
    return (0 if result else 1), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check every adsk name the add-in uses against the running Fusion"
    )
    parser.add_argument("--host", help="the add-in's host (default: the package's)")
    parser.add_argument("--port", type=int, help="the add-in's port (default: 9876)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="accepted for symmetry with reload_addin.py; nothing is ever changed",
    )
    args = parser.parse_args(argv)

    code, report = _audit(args.host, args.port)
    if report is None:
        return code

    print(f"Fusion {report['version']}: {report['refs']} adsk reference(s) checked")
    if report["missing"]:
        print(
            f"{len(report['missing'])} name(s) Fusion does not have:",
            file=sys.stderr,
        )
        for finding in report["missing"]:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print("no invented names: every one exists in this Fusion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
