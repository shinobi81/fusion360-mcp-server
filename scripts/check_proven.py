#!/usr/bin/env python3
"""Check which tools have been answered by a real Fusion, and optionally re-probe.

``docs/TOOLS.md`` carries one row per tool with the record beside the description: the
``Evidence`` cell says what a caller can rely on and, for a tool nobody has called, why
it cannot.  Three invented ``adsk`` names in this repo's history were all found by hand,
and ``scripts/check_fusion_api.py`` proves *names* - neither says a tool was ever
called, or that the answer it gave was the answer its row claims.  This script is that
record's guard.

    uv run python scripts/check_proven.py         # validate against the tools
    uv run python scripts/check_proven.py --live  # also probe the read-only tools
    uv run python scripts/check_proven.py --live --host 127.0.0.1 --port 9876

The default run needs no Fusion and no network: it checks that every tool in
``src/fusion360_mcp/tools.py`` has exactly one row, that no row names a tool that does
not exist, and that every ``proven`` row cites a date, an ``app.version`` and a PR.

``--live`` sends the read-only tools in ``LIVE_CALLS``/``LIVE_BODY_CALLS`` to the
running add-in and reports a mismatch **in either direction**: a row that claims a
probe and gets a refusal, and a row that says ``unproven`` for a tool that answers
``ok`` (the table is then out of date, not wrong). It is a subset on purpose: most
mutations cannot be smoke-called without arguments, and a mutation's evidence is a
measured envelope in a PR body, not something this script can reproduce. A *proven*
row it sends no call to is reported as not probed, never as passing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fusion360_mcp.tools import _READ_ONLY, TOOLS

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs" / "TOOLS.md"

#: The four cells a tool row carries: the name, the derived build, the description and
#: the record.  The evidence is the *last* cell so a description may grow without moving
#: it, and so the audit reads at the end of the row.
TOOL_HEADER = "Tool"
EVIDENCE_COLUMN = 3
ROW_WIDTH = 4

#: `proven — 2026-11-26, `2706.1.17`, #158: what was measured`.  The three fields are
#: mandatory so a row cannot claim a probe without saying when, against which build, and
#: where the envelope is recorded.
_PROVEN_RE = re.compile(
    r"^proven — (?P<date>\d{4}-\d{2}-\d{2}), "
    r"`(?P<version>\d+(?:\.\d+)+)`, "
    r"#(?P<pr>\d+): (?P<what>.+)$"
)

#: `unproven — why`.  One line, so the table stays a table.
_UNPROVEN_RE = re.compile(r"^unproven — (?P<why>.+)$")

#: Words that fill the "why" slot without saying anything.  The preamble says "not yet"
#: is not a reason, and a rule that only checks for *something* would accept it.
_PLACEHOLDER_RE = re.compile(
    r"^(not yet|todo|tbd|n/?a|unknown|none|nothing|-+)\.?$", re.IGNORECASE
)

#: The read-only calls that need no name from the document, keyed by tool name.  A
#: *proven* row for a tool absent from both dicts is reported by ``not_probed``.
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


#: The table's honesty depends on `--live` never mutating the caller's document, so the
#: subset is checked against the tool annotation that says which tools are read-only -
#: a mutating tool added here would otherwise be executed silently.
_LIVE_TOOLS = frozenset(LIVE_CALLS) | frozenset(LIVE_BODY_CALLS)
assert _LIVE_TOOLS <= _READ_ONLY, f"not read-only: {sorted(_LIVE_TOOLS - _READ_ONLY)}"


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
        if self.state not in ("proven", "unproven"):
            return f"unknown state {self.state!r}: a row is `proven` or `unproven`"
        if self.proven:
            match = _PROVEN_RE.match(self.evidence)
            if match is None:
                return (
                    "a proven row must read "
                    "`proven — YYYY-MM-DD, `<version>`, #<pr>: <what was measured>`"
                )
            return None
        match = _UNPROVEN_RE.match(self.evidence)
        if match is None:
            return "an unproven row must read `unproven — <why>`"
        why = match.group("why").strip()
        if _PLACEHOLDER_RE.fullmatch(why):
            return f"{why!r} is a placeholder, not a reason: say what is missing"
        return None


def _cells(line: str) -> list[str]:
    """The cells of a ``|``-line, stripped."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_header_or_separator(cells: list[str]) -> bool:
    """The two ``|``-lines that are not rows, judged the same way by both readers.

    A separator is dashes or dashes with alignment colons (``| :--- | ---: |`` is what a
    formatter writes), and an empty first cell is a stray ``| |`` line rather than a
    row.
    """
    first = cells[0]
    return first in ("Tool", "---") or not first or set(first) <= set("-:")


def _table_blocks(text: str) -> list[tuple[int, list[str]]]:
    """Every ``|`` table with the line number it starts on - markdown ends one at the
    first line that is not a ``|``-line.

    A file with one table needs no such walk; this one has seventeen domain tables, a
    legend and argument breakdowns, so "which lines are rows" is a question about
    blocks, not about the whole file.
    """
    blocks: list[tuple[int, list[str]]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        end = index
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        blocks.append((index + 1, lines[index:end]))
        index = end
    return blocks


def _tool_blocks(text: str) -> list[tuple[int, list[str]]]:
    """The blocks whose header's first cell is ``Tool`` - the catalogue's own tables.

    Everything else in the file - the ``x``/``y``/``z`` legend, the argument
    breakdowns - is somebody else's table and is never read as a row here.
    """
    return [
        (lineno, block)
        for lineno, block in _table_blocks(text)
        if block and _cells(block[0])[0] == TOOL_HEADER
    ]


def parse_table(text: str) -> list[Row]:
    """The tool rows of ``docs/TOOLS.md``, in file order.

    A row is a four-cell line inside a ``Tool`` table: the backticked name, the derived
    build, the description and the evidence.  A line that is neither a header, a
    separator nor four cells is reported by ``malformed_lines`` rather than dropped -
    a row nobody can parse is exactly the row a reader would trust.
    """
    rows: list[Row] = []
    for _lineno, block in _tool_blocks(text):
        for line in block[2:]:
            cells = _cells(line)
            if _is_header_or_separator(cells) or len(cells) != ROW_WIDTH:
                continue
            rows.append(Row(cells[0].strip("`"), cells[EVIDENCE_COLUMN]))
    return rows


def malformed_lines(text: str) -> list[str]:
    """Tool-table lines that are neither a header, a separator, nor a four-cell row."""
    problems: list[str] = []
    for lineno, block in _tool_blocks(text):
        for offset, line in enumerate(block):
            if offset < 2:
                continue
            cells = _cells(line)
            if _is_header_or_separator(cells):
                continue
            if len(cells) != ROW_WIDTH:
                problems.append(
                    f"line {lineno + offset}: a tool row needs four cells "
                    f"(name, proven, description, evidence), not {len(cells)}: {line}"
                )
    return problems


def check(text: str, rows: list[Row] | None = None) -> list[str]:
    """Every problem with the table, as messages a caller can act on."""
    problems = malformed_lines(text)
    rows = parse_table(text) if rows is None else rows
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


def _send(connection, tool: str, params: dict) -> dict:
    """One reply, with a bridge failure turned into a reply rather than a traceback.

    Three exceptions, because the client raises all three: ``FusionError`` for a
    structured refusal, ``ConnectionError`` when a *read-only* command's retries are
    exhausted - a wedged main thread, which is exactly the case where the table's own
    problems still deserve printing - and ``ValueError`` when the reply line is not
    JSON.
    """
    from fusion360_mcp.connection import FusionError

    try:
        return connection.send_command(tool, params)
    except (FusionError, ConnectionError, ValueError) as exc:
        return {
            "ok": False,
            # `CONNECTION_LOST` is this script's own tag for a client-side failure; the
            # wire's kinds are the ones `_hints` documents.
            "error_kind": getattr(exc, "error_kind", "CONNECTION_LOST"),
            "error_message": str(exc),
        }


def probe(host: str | None, port: int | None) -> dict[str, dict] | None:
    """Send the read-only calls to Fusion; return tool -> its reply, or None if there is
    no add-in to ask.  ``main`` prints the table's own problems either way."""
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
        print("not connected: is the Fusion360MCP add-in running?", file=sys.stderr)
        return None

    replies: dict[str, dict] = {}
    try:
        replies["get_scene_info"] = _send(connection, "get_scene_info", {})
        bodies = replies["get_scene_info"].get("bodies") or []
        body_name = bodies[0].get("name") if bodies else None

        for tool, params in LIVE_CALLS.items():
            if tool == "get_scene_info":
                continue  # already answered above, for the body name
            replies[tool] = _send(connection, tool, params)
        if body_name is not None:
            for tool, parameter in LIVE_BODY_CALLS.items():
                replies[tool] = _send(connection, tool, {parameter: body_name})
    finally:
        connection.disconnect()
    return replies


def live_mismatches(replies: dict[str, dict], rows: list[Row]) -> list[str]:
    """Rows whose reply contradicts their state, in either direction."""
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
        f"{tool}: proven, but --live sent it no call here (no root body to name, "
        "or no LIVE_CALLS entry)"
        for tool in sorted(set(by_tool) - set(replies))
        if by_tool[tool].proven
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate docs/TOOLS.md's Evidence rows."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="also probe the read-only tools against a running Fusion",
    )
    parser.add_argument(
        "--host", default=None, help="default: the package's (FUSION_MCP_HOST)"
    )
    parser.add_argument(
        "--port",
        default=None,
        type=int,
        help="default: the package's (FUSION_MCP_PORT)",
    )
    args = parser.parse_args(argv)

    text = CATALOGUE.read_text(encoding="utf-8")
    rows = parse_table(text)
    problems = check(text, rows)
    proven = sum(1 for row in rows if row.proven)
    print(
        f"docs/TOOLS.md: {len(rows)} rows, {proven} proven, "
        f"{len(rows) - proven} unproven"
    )

    if args.live:
        replies = probe(args.host, args.port)
        if replies is not None:
            problems.extend(live_mismatches(replies, rows))
            print(f"probed {len(replies)} read-only tool(s) live")
            for note in not_probed(replies, rows):
                print(note)
        else:
            problems.append(
                "--live could not reach Fusion; the table was checked alone"
            )

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(json.dumps({"rows": len(rows), "proven": proven, "ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
