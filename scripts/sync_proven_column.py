#!/usr/bin/env python3
"""Regenerate the ``Proven`` column of ``docs/TOOLS.md`` from each row's evidence.

One row per tool now carries both: the ``Evidence`` cell is the record - when the call
was made, against which build, and where the envelope is, or why nothing has answered -
and the ``Proven`` cell beside it is the build a reader can scan for.  The cell is
**generated**, never typed: two places to type the same fact is two places to disagree,
and the evidence is the one that wins.

This script is the only writer.  It reads the version out of each row's evidence and
rewrites the cells, re-padding the four columns so the seventeen tables stay aligned.

    uv run python scripts/sync_proven_column.py           # rewrite the column
    uv run python scripts/sync_proven_column.py --check   # print a diff, exit 1

``tests/test_proven.py`` runs the same renderer and fails while the file on disk
differs, which makes a stale cell a red suite rather than a slowly wrong doc.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs" / "TOOLS.md"

#: The header of a table whose first cell names a tool.  Other tables in the file - the
#: ``x``/``y``/``z`` legend, the argument breakdowns - are left byte for byte alone.
TOOL_HEADER = "Tool"

#: What an unproven tool's cell says.  One glyph, because the cell answers "which build"
#: and "none" is not a build; the sentence a reader needs is the evidence beside it.
UNPROVEN = "—"

#: The cells a tool row carries: name, derived build, description, evidence.
_WIDTH = 4

#: A table's separator row: dashes, optionally with alignment colons.
_SEPARATOR = set("-: ")


def _checker():
    """``scripts/check_proven.py`` by path - ``scripts/`` is not a package.

    The row parser lives there, and one parser for a table read by two scripts is the
    whole point: a second copy would answer a different question about the same bytes.
    """
    path = ROOT / "scripts" / "check_proven.py"
    spec = importlib.util.spec_from_file_location("check_proven", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cells_by_tool(tools_text: str) -> dict[str, str]:
    """``tool -> `version``` for every proven row, and ``—`` for every unproven one.

    The version comes from the row's own evidence - ``proven — date, `version`, #pr`` -
    read with the checker's pattern, so the two cells cannot disagree about what
    ``proven`` means.
    """
    checker = _checker()
    cells: dict[str, str] = {}
    for row in checker.parse_table(tools_text):
        match = checker._PROVEN_RE.match(row.evidence) if row.proven else None
        # The checker reports a malformed proven row itself; reaching here without a
        # match means this script and that pattern have drifted apart.
        if row.proven and match is None:
            raise RuntimeError(f"{row.tool}: proven row with no version")
        cells[row.tool] = f"`{match.group('version')}`" if match else UNPROVEN
    return cells


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and set("".join(cells)) <= _SEPARATOR


def _render_row(cells: list[str], widths: list[int]) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths, strict=True)]
    return "| " + " | ".join(padded) + " |"


def _render_table(block: list[str], cells: dict[str, str]) -> list[str]:
    """One ``Tool`` table: header, separator and rows, re-padded around the column.

    A table whose header is not four cells wide, or whose rows are not, is returned
    untouched: ``check_proven.py`` reports that shape, and a generator that silently
    reflowed a broken table would hide the defect it was handed.
    """
    header = _cells(block[0])
    if header[0] != TOOL_HEADER or len(header) != _WIDTH:
        return block
    data = [_cells(line) for line in block[2:]]
    if any(len(row) != _WIDTH for row in data):
        return block

    rows = [
        [row[0], cells.get(row[0].strip("`"), row[1]), row[2], row[3]] for row in data
    ]
    widths = [
        max([len(header[index])] + [len(row[index]) for row in rows])
        for index in range(_WIDTH)
    ]
    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    rendered = [_render_row(header, widths), separator]
    rendered.extend(_render_row(row, widths) for row in rows)
    return rendered


def render(tools_text: str) -> str:
    """``docs/TOOLS.md`` with every ``Tool`` table's ``Proven`` column regenerated."""
    cells = cells_by_tool(tools_text)
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

    on_disk = CATALOGUE.read_text(encoding="utf-8")
    expected = render(on_disk)
    if on_disk == expected:
        print(f"{CATALOGUE.name}: the Proven column matches each row's evidence")
        return 0
    if args.check:
        sys.stdout.writelines(
            difflib.unified_diff(
                on_disk.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=f"{CATALOGUE.name} (on disk)",
                tofile=f"{CATALOGUE.name} (from its Evidence cells)",
            )
        )
        print(f"{CATALOGUE.name}: the Proven column is stale", file=sys.stderr)
        return 1
    CATALOGUE.write_text(expected, encoding="utf-8", newline="\n")
    print(f"{CATALOGUE.name}: Proven column rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
