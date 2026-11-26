#!/usr/bin/env python3
"""Check which tools have been answered by a real Fusion, and optionally re-probe.

``docs/PROVEN.md`` holds one row per tool: what a caller can rely on, and the evidence
for it.  Three invented ``adsk`` names in this repo's history were all found by hand,
and ``scripts/check_fusion_api.py`` proves *names* — neither says a tool was ever
called, or that the answer it gave was the answer its row claims.  This script is that
record's guard.

    uv run python scripts/check_proven.py         # validate against the tools
    uv run python scripts/check_proven.py --live  # also probe the read-only tools
    uv run python scripts/check_proven.py --live --host 127.0.0.1 --port 9876

The default run needs no Fusion and no network: it checks that every tool in
``src/fusion360_mcp/tools.py`` has exactly one row, that no row names a tool that does
not exist, and that every ``proven`` row cites a date, an ``app.version`` and a PR.

``--live`` sends the read-only tools in ``LIVE_CALLS`` to the running add-in and reports
a mismatch when a row claims a probe and the call does not answer ``ok: true``.  It is a
subset on purpose: most mutations cannot be smoke-called without arguments, and a
mutation's evidence is a measured envelope in a PR body, not something this script can
reproduce.  A tool without an entry in ``LIVE_CALLS`` is reported as not probed, never
as passing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fusion360_mcp.tools import TOOLS

ROOT = Path(__file__).resolve().parents[1]
PROVEN = ROOT / "docs" / "PROVEN.md"

#: `proven — 2026-11-26, `2706.1.17`, #157: what was measured`.  The three fields are
#: mandatory so a row cannot claim a probe without saying when, against which build, and
#: where the envelope is recorded.
_PROVEN_RE = re.compile(
    r"^proven — (?P<date>\d{4}-\d{2}-\d{2}), "
    r"`(?P<version>\d+\.\d+\.\d+)`, "
    r"#(?P<pr>\d+): (?P<what>.+)$"
)

#: `unproven — why`.  One line, so the table stays a table.
_UNPROVEN_RE = re.compile(r"^unproven — (?P<why>.+)$")

#: The read-only calls `--live` can make with no document state at all, keyed by tool
#: name.  A tool absent from here is reported as not probed.
LIVE_CALLS: dict[str, dict] = {
    "ping": {},
    "get_scene_info": {},
    "get_design_type": {},
    "list_components": {},
    "get_parameters": {},
    "cam_list_setups": {},
    "render_view": {"view": "iso"},
}

#: Tools whose call needs a name from the open document, and the parameter each spells
#: it with; `--live` fills it in from `get_scene_info`'s first body.  Five tools, two
#: spellings - passing both is refused as an unexpected argument.
LIVE_BODY_CALLS: dict[str, str] = {
    "list_faces": "body_name",
    "list_edges": "body_name",
    "get_physical_properties": "body_name",
    "get_object_info": "name",
    "get_bounding_box": "name",
}


class Row:
    """One table row: the tool, its state, and the text after the state word."""

    def __init__(self, tool: str, evidence: str):
        self.tool = tool
        self.evidence = evidence

    @property
    def state(self) -> str:
        return self.evidence.split(" — ", 1)[0]

    @property
    def proven(self) -> bool:
        return self.state == "proven"

    def problem(self) -> str | None:
        """Why this row is malformed, or None when it is well formed."""
        if self.proven:
            match = _PROVEN_RE.match(self.evidence)
            if match is None:
                return (
                    "a proven row must read "
                    "`proven — YYYY-MM-DD, `<version>`, #<pr>: <what was measured>`"
                )
            if not match.group("what").strip():
                return "a proven row must say what was measured"
            return None
        match = _UNPROVEN_RE.match(self.evidence)
        if match is None:
            return "an unproven row must read `unproven — <why>`"
        if not match.group("why").strip():
            return "an unproven row must say why"
        return None


def parse_table(text: str) -> list[Row]:
    """The rows of ``docs/PROVEN.md``, in file order.

    Only the two-column table is read: a row is a line that starts with ``|`` and is not
    the header or the separator.
    """
    rows: list[Row] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0] in ("Tool", "---") or set(cells[0]) == {"-"}:
            continue
        rows.append(Row(cells[0].strip("`"), cells[1]))
    return rows


def check(text: str) -> list[str]:
    """Every problem with the table, as messages a caller can act on."""
    problems: list[str] = []
    rows = parse_table(text)
    names = [row.tool for row in rows]

    declared = {tool["name"] for tool in TOOLS}
    for duplicate in sorted({name for name in names if names.count(name) > 1}):
        problems.append(f"{duplicate}: listed more than once")
    for missing in sorted(declared - set(names)):
        problems.append(f"{missing}: a tool with no row")
    for extra in sorted(set(names) - declared):
        problems.append(f"{extra}: a row naming no tool")
    for row in rows:
        if problem := row.problem():
            problems.append(f"{row.tool}: {problem}")
    return problems


def probe(host: str | None, port: int | None) -> dict[str, dict]:
    """Send the read-only calls to Fusion; return tool -> its reply."""
    from fusion360_mcp.connection import Fusion360Connection

    if host is not None and port is not None:
        connection = Fusion360Connection(host=host, port=port)
    elif host is not None:
        connection = Fusion360Connection(host=host)
    elif port is not None:
        connection = Fusion360Connection(port=port)
    else:
        connection = Fusion360Connection()
    if not connection.connect():
        raise SystemExit("not connected: is the Fusion360MCP add-in running?")

    replies: dict[str, dict] = {}
    try:
        replies["get_scene_info"] = connection.send_command("get_scene_info", {})
        bodies = replies["get_scene_info"].get("bodies") or []
        body_name = bodies[0].get("name") if bodies else None

        for tool, params in LIVE_CALLS.items():
            replies[tool] = connection.send_command(tool, params)
        if body_name is not None:
            for tool, parameter in LIVE_BODY_CALLS.items():
                replies[tool] = connection.send_command(tool, {parameter: body_name})
    finally:
        connection.disconnect()
    return replies


def live_mismatches(replies: dict[str, dict], rows: list[Row]) -> list[str]:
    """Rows that claim a probe their reply contradicts, or tools nobody probed."""
    by_tool = {row.tool: row for row in rows}
    problems: list[str] = []
    for tool, reply in sorted(replies.items()):
        row = by_tool.get(tool)
        answered = reply.get("ok") is True
        if row is not None and row.proven and not answered:
            problems.append(
                f"{tool}: the table says proven, the call answered "
                f"{reply.get('error_kind')}: {reply.get('error_message')}"
            )
        if row is not None and not row.proven and answered:
            problems.append(
                f"{tool}: the table says unproven, the call answered ok - record it"
            )
    return problems


def not_probed(replies: dict[str, dict], rows: list[Row]) -> list[str]:
    """Proven tools `--live` could not call.  Information, not a failure.

    Most of the table is mutations, which cannot be smoke-called without arguments, so a
    non-zero exit for "not probed" would make ``--live`` useless as a check.
    """
    by_tool = {row.tool: row for row in rows}
    return [
        f"{tool}: proven, but --live has no call for it (unverified here)"
        for tool in sorted(set(by_tool) - set(replies))
        if by_tool[tool].proven
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate docs/PROVEN.md.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="also probe the read-only tools against a running Fusion",
    )
    parser.add_argument("--host", default=None, help="default 127.0.0.1")
    parser.add_argument("--port", default=None, type=int, help="default 9876")
    args = parser.parse_args(argv)

    text = PROVEN.read_text(encoding="utf-8")
    problems = check(text)
    rows = parse_table(text)
    proven = sum(1 for row in rows if row.proven)
    print(
        f"docs/PROVEN.md: {len(rows)} rows, {proven} proven, "
        f"{len(rows) - proven} unproven"
    )

    if args.live:
        replies = probe(args.host, args.port)
        problems.extend(live_mismatches(replies, rows))
        print(f"probed {len(replies)} read-only tool(s) live")
        for note in not_probed(replies, rows):
            print(note)

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(json.dumps({"rows": len(rows), "proven": proven, "ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
