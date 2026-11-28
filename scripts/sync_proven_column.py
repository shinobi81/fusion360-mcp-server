#!/usr/bin/env python3
"""Keep the ``Proven`` column of ``docs/TOOLS.md`` in step with ``docs/PROVEN.md``.

``docs/PROVEN.md`` is the record: one row per tool, saying when it was called, against
which build, and where its envelope is - or why nothing has answered yet.  A reader of
``docs/TOOLS.md`` should not have to open a second file to learn whether a tool has ever
worked, so the catalogue carries the build it was proved against in one cell.

That cell is **generated**, never written by hand: two places to type the same fact is
two places to disagree, and the audit table is the one that must win.  This script is
the only writer - it reads the version out of each ``proven`` row and rewrites the
column for every tool row of every ``Tool`` table, padding the cells so the hand
alignment of the tables survives.  A row with nothing proven gets an em dash; the reason
lives in ``docs/PROVEN.md``, which is where a reader who cares about it is already
going.

    uv run python scripts/sync_proven_column.py           # rewrite the column
    uv run python scripts/sync_proven_column.py --check   # print a diff, exit 1

``tests/test_proven.py`` runs the same renderer and fails while the file on disk
differs, which makes a stale column a red suite rather than a rotting doc.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVEN = ROOT / "docs" / "PROVEN.md"
TOOLS = ROOT / "docs" / "TOOLS.md"

#: The header of a table whose first cell names a tool.  Other tables in the file - the
#: ``x``/``y``/``z`` legend, the argument breakdowns - are left byte for byte alone.
TOOL_HEADER = "Tool"

#: What an unproven tool's cell says.  One glyph, because the cell answers "which build"
#: and "none" is not a build; the sentence a reader needs is the ``unproven`` row's own.
UNPROVEN = "—"

#: A table's separator row: dashes, optionally with alignment colons.
_SEPARATOR = set("-: ")


def _checker():
    """``scripts/check_proven.py``, loaded by path - ``scripts/`` is not a package."""
    path = ROOT / "scripts" / "check_proven.py"
    spec = importlib.util.spec_from_file_location("check_proven", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cells_by_tool(proven_text: str) -> dict[str, str]:
    """``tool -> `version``` for every proven row, and ``-`` for every unproven one.

    The version comes from the row's own ``proven — date, `version`, #pr: ...`` text,
    read with the checker's pattern so the two files cannot disagree about what a
    proven row is.
    """
    checker = _checker()
    cells: dict[str, str] = {}
    for row in checker.parse_table(proven_text):
        if not row.proven:
            cells[row.tool] = UNPROVEN
            continue
        match = checker._PROVEN_RE.match(row.evidence)
        # The checker reports a malformed proven row itself; reaching here without a
        # match means this script and that pattern have drifted apart.
        if match is None:
            raise RuntimeError(f"{row.tool}: proven row with no version")
        cells[row.tool] = f"`{match.group('version')}`"
    return cells


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and set("".join(cells)) <= _SEPARATOR


def _render_row(cells: list[str], widths: list[int]) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths, strict=True)]
    return "| " + " | ".join(padded) + " |"


def _render_table(block: list[str], cells: dict[str, str]) -> list[str]:
    """One ``Tool`` table: header, separator and rows, re-padded around the new column.

    A two-cell row gains the new cell; a three-cell one has it replaced.  The
    description is always the last cell, so a table that grows a further column later
    keeps working.
    """
    header = _cells(block[0])
    if header[0] != TOOL_HEADER:
        return block
    # Two shapes in the file: `Tool | Description` before the column existed and
    # `Tool | Proven | Description` after it.
    if len(header) == 2:
        header = [TOOL_HEADER, "Proven", header[1]]

    rows: list[list[str]] = []
    for line in block[2:]:
        row = _cells(line)
        if len(row) == 2:
            row = [row[0], cells.get(row[0].strip("`"), UNPROVEN), row[1]]
        elif len(row) == 3:
            row = [row[0], cells.get(row[0].strip("`"), row[1]), row[2]]
        rows.append(row)

    widths = [
        max(len(header[0]), *(len(row[0]) for row in rows)),
        max(len(header[1]), *(len(row[1]) for row in rows)),
        max(len(header[2]), *(len(row[2]) for row in rows)),
    ]
    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    rendered = [_render_row(header, widths), separator]
    rendered.extend(_render_row(row, widths) for row in rows)
    return rendered


def render(tools_text: str, proven_text: str) -> str:
    """``docs/TOOLS.md`` with every ``Tool`` table's ``Proven`` column regenerated."""
    cells = cells_by_tool(proven_text)
    lines = tools_text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("|"):
            out.append(line)
            index += 1
            continue
        # One table: its ``|``-lines, which markdown ends at the first other line.
        end = index
        while end < len(lines) and lines[end].startswith("|"):
            end += 1
        block = lines[index:end]
        if len(block) > 2 and _is_separator(_cells(block[1])):
            out.extend(_render_table(block, cells))
        else:
            out.extend(block)
        index = end
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the Proven column.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report a stale column and exit 1 instead of writing it",
    )
    args = parser.parse_args(argv)

    on_disk = TOOLS.read_text(encoding="utf-8")
    expected = render(on_disk, PROVEN.read_text(encoding="utf-8"))
    if on_disk == expected:
        print(f"{TOOLS.name}: the Proven column matches docs/PROVEN.md")
        return 0
    if args.check:
        sys.stdout.writelines(
            difflib.unified_diff(
                on_disk.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=f"{TOOLS.name} (on disk)",
                tofile=f"{TOOLS.name} (from docs/PROVEN.md)",
            )
        )
        print(f"{TOOLS.name}: the Proven column is stale", file=sys.stderr)
        return 1
    TOOLS.write_text(expected, encoding="utf-8", newline="\n")
    print(f"{TOOLS.name}: Proven column rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
