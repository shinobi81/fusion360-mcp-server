#!/usr/bin/env python3
"""Render the package-side mirrors of add-in files that cannot be imported.

The Fusion add-in is installed into Fusion's AddIns folder and cannot import
``fusion360_mcp``, so a few of its tables exist twice.  The add-in's file is
canonical: this renders each ``src/`` mirror from it, so a change is made once.

    uv run python scripts/sync_mirrors.py           # rewrite the mirrors
    uv run python scripts/sync_mirrors.py --check   # exit 1 if any is stale

A mirror is a fixed header plus the canonical file from its first import line — the
first line starting with ``import `` or ``from `` — to EOF.  The canonical docstring,
and any comments or blank lines above that import, do not reach the mirror: they are
dropped by design, so editing the docstring cannot drift it.  Any other statement
above the import line is refused rather than dropped.  ``--check`` prints a unified
diff of each drifted mirror and is what the test suite runs.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The lines a mirror can start at.  A canonical module that opens with
# `from __future__ import annotations` is rendered from that line, which is still legal
# below the header docstring.
_IMPORT_PREFIXES = ("import ", "from ")

_HINTS_HEADER = (
    '"""Error classification for Fusion API failures — GENERATED, do not edit.\n'
    "\n"
    "Rendered by ``scripts/sync_mirrors.py`` from ``addon/server/hints.py``: the\n"
    "add-in is installed into Fusion's AddIns folder and cannot import this\n"
    "package, so its copy is canonical.  Edit that file and run\n"
    "``uv run python scripts/sync_mirrors.py``; hand edits here are overwritten.\n"
    '"""\n'
    "\n"
)

_MUTATION_HEADER = (
    '"""Which commands change the model — GENERATED, do not edit.\n'
    "\n"
    "Rendered by ``scripts/sync_mirrors.py`` from\n"
    "``addon/server/mutation_commands.py``: the add-in is installed into Fusion's\n"
    "AddIns folder and cannot import this package, so its copy is canonical.  Edit\n"
    "that file and run ``uv run python scripts/sync_mirrors.py``; hand edits here are\n"
    "overwritten.\n"
    '"""\n'
    "\n"
)

_RULES_HEADER = (
    '"""Validation the add-in and mock mode share — GENERATED, do not edit.\n'
    "\n"
    "Rendered by ``scripts/sync_mirrors.py`` from ``addon/server/rules.py``: the\n"
    "add-in is installed into Fusion's AddIns folder and cannot import this\n"
    "package, so its copy is canonical.  Edit that file and run\n"
    "``uv run python scripts/sync_mirrors.py``; hand edits here are overwritten.\n"
    '"""\n'
    "\n"
)

# (canonical, mirror, header).  Paths are relative to the repository root; the header
# is the whole module docstring of the generated file.
MIRRORS: tuple[tuple[Path, Path, str], ...] = (
    (
        Path("addon/server/hints.py"),
        Path("src/fusion360_mcp/hints.py"),
        _HINTS_HEADER,
    ),
    (
        Path("addon/server/mutation_commands.py"),
        Path("src/fusion360_mcp/_mutation_commands.py"),
        _MUTATION_HEADER,
    ),
    (
        Path("addon/server/rules.py"),
        Path("src/fusion360_mcp/_rules.py"),
        _RULES_HEADER,
    ),
)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _refuse_code_above_the_imports(canonical: Path, preamble: list[str]) -> None:
    """Refuse a preamble holding a statement that is not the canonical docstring.

    The mirror starts at the import line, so a table placed above it would reach the
    add-in and nowhere else - which is the silent drop this generator exists to prevent.
    A comment or a blank line is not a statement and is dropped with the docstring.
    """
    text = "".join(preamble)
    if not text.strip():
        return
    try:
        # ``optimize=0``: under ``-OO`` ``ast.parse`` drops docstrings from the tree, so
        # the canonical docstring would read as code above the import and be refused.
        statements = ast.parse(text, optimize=0).body
    except SyntaxError as exc:
        raise ValueError(
            f"{canonical}: line {exc.lineno} is above the first import and is not a "
            "whole statement; the mirror starts at that import, so move it below"
        ) from exc
    offender = next(
        (node for node in statements if not _is_docstring(node)),
        statements[1] if len(statements) > 1 else None,
    )
    if offender is not None:
        raise ValueError(
            f"{canonical}: line {offender.lineno} holds code above the first "
            "import; the mirror starts at that import and would drop it — move it "
            "below the imports"
        )


def render(canonical: Path, header: str) -> str:
    """Return *header* followed by *canonical* from its first import line."""
    lines = canonical.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(_IMPORT_PREFIXES):
            _refuse_code_above_the_imports(canonical, lines[:index])
            return header + "".join(lines[index:])
    raise ValueError(f"{canonical} has no import line: nothing to mirror")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the package-side mirrors.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale mirrors and exit 1 instead of writing them",
    )
    args = parser.parse_args(argv)

    stale: list[Path] = []
    for canonical, mirror, header in MIRRORS:
        rendered = render(ROOT / canonical, header)
        path = ROOT / mirror
        # A mirror that does not exist yet reads as empty, so adding an entry and
        # running this creates it rather than raising FileNotFoundError.
        on_disk = path.read_text(encoding="utf-8") if path.exists() else ""
        if on_disk == rendered:
            continue
        stale.append(mirror)
        if args.check:
            sys.stdout.writelines(
                difflib.unified_diff(
                    on_disk.splitlines(keepends=True),
                    rendered.splitlines(keepends=True),
                    fromfile=f"{mirror} (on disk)",
                    tofile=f"{mirror} (regenerated from {canonical})",
                )
            )
        else:
            # ``newline="\n"``: the host's line ending would otherwise reach
            # the tree, which ``.gitattributes`` normalises to LF.
            path.write_text(rendered, encoding="utf-8", newline="\n")
            print(f"wrote {mirror} from {canonical}")

    if args.check and stale:
        print(
            "stale mirror(s): "
            + ", ".join(str(path) for path in stale)
            + " — run `uv run python scripts/sync_mirrors.py`",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
