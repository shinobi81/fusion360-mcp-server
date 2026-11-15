"""Drift guards: assert addon-side and package-side mirrors stay in sync.

The Fusion add-in is installed into Fusion's AddIns folder and cannot
import from this package, so a few tables are duplicated:

* ``src/fusion360_mcp/hints.py`` is generated from ``addon/server/hints.py``
  by ``scripts/sync_mirrors.py``; ``test_the_hints_mirror_is_generated`` runs it
  with ``--check``.
* ``CommandHandler._MUTATION_COMMANDS``  ↔  ``mock.py:_MUTATION_MOCKS``

If they drift, agents see different error envelopes / delta payloads
depending on whether they're running against Fusion or mock mode.  These
tests fail loudly the moment a maintainer updates one side without the
other.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _extract_class_attr_set(path: Path, class_name: str, attr: str) -> set[str]:
    """Pull ``ClassName.attr`` (a set/frozenset literal) out of *path* via AST.

    The invariant is "this table matches that schema", which is a property of the
    source rather than of running it, so the literal is read instead of imported.
    """
    tree = ast.parse(path.read_text())
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        if cls.name != class_name:
            continue
        for stmt in cls.body:
            # Annotated (``X: ClassVar[...] = {...}``) and plain assignments are
            # the same invariant; skipping the annotated form would let the table
            # drift out of this guard with a misleading "not found" error.
            if isinstance(stmt, ast.Assign):
                targets, value = stmt.targets, stmt.value
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                targets, value = [stmt.target], stmt.value
            else:
                continue
            if not any(isinstance(t, ast.Name) and t.id == attr for t in targets):
                continue
            # frozenset({...})  →  unwrap the set literal arg
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
                and value.args
            ):
                return set(ast.literal_eval(value.args[0]))
            return set(ast.literal_eval(value))
    raise AssertionError(f"{class_name}.{attr} not found in {path}")


def test_the_hints_mirror_is_generated():
    mirror_path = REPO_ROOT / "src" / "fusion360_mcp" / "hints.py"
    mirror = mirror_path.read_text(encoding="utf-8")
    assert "GENERATED, do not edit" in mirror.split("\n\n")[0]
    subprocess.run(
        [sys.executable, "scripts/sync_mirrors.py", "--check"],
        cwd=REPO_ROOT,
        check=True,
    )


def test_mutation_sets_in_sync():
    """Addon mutation set and mock mutation set must be identical."""
    from fusion360_mcp.mock import _MUTATION_MOCKS

    addon_set = _extract_class_attr_set(
        REPO_ROOT / "addon" / "server" / "command_handler.py",
        "CommandHandler",
        "_MUTATION_COMMANDS",
    )
    mock_set = set(_MUTATION_MOCKS)
    assert addon_set == mock_set, (
        f"_MUTATION_COMMANDS (addon) and _MUTATION_MOCKS (mock.py) have drifted.\n"
        f"  only in addon: {sorted(addon_set - mock_set)}\n"
        f"  only in mock:  {sorted(mock_set - addon_set)}"
    )


def _extract_command_dispatch_keys(path: Path) -> set[str]:
    """Pull the string keys of the ``_COMMANDS`` dict literal out of the
    add-in's command_handler via AST: the table is the contract, and reading a
    literal needs neither Fusion nor the fake runtime."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Attribute) and t.attr == "_COMMANDS" for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Dict):
            keys = {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if keys:
                return keys
    raise AssertionError(f"_COMMANDS dict literal not found in {path}")


# Commands the add-in dispatches that are intentionally not MCP tools.
_DISPATCH_ONLY = {"reload_handler"}


def test_tools_match_addon_dispatch():
    """Every MCP tool must have an add-in handler, and vice versa.

    This is the drift guard that catches "added a tool to tools.py but
    forgot the CommandHandler entry" (and the reverse) at CI time.
    """
    from fusion360_mcp.tools import TOOLS

    tool_names = {t["name"] for t in TOOLS}
    dispatch = (
        _extract_command_dispatch_keys(
            REPO_ROOT / "addon" / "server" / "command_handler.py"
        )
        - _DISPATCH_ONLY
    )
    assert tool_names == dispatch, (
        f"tools.py and CommandHandler._COMMANDS have drifted.\n"
        f"  tools without handler: {sorted(tool_names - dispatch)}\n"
        f"  handlers without tool: {sorted(dispatch - tool_names)}"
    )


def test_an_annotated_table_is_read_the_same_as_a_plain_one(tmp_path):
    """The AnnAssign branch, exercised: a ClassVar table must not slip the guard."""
    source = tmp_path / "annotated.py"
    source.write_text(
        "from typing import ClassVar\n"
        "\n"
        "\n"
        "class Handler:\n"
        "    PLAIN = frozenset({'a'})\n"
        "    ANNOTATED: ClassVar[frozenset[str]] = frozenset({'b', 'c'})\n",
        encoding="utf-8",
    )
    assert _extract_class_attr_set(source, "Handler", "PLAIN") == {"a"}
    assert _extract_class_attr_set(source, "Handler", "ANNOTATED") == {"b", "c"}
