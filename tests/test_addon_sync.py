"""Drift guards: assert addon-side and package-side tables stay in agreement.

The Fusion add-in is installed into Fusion's AddIns folder and cannot
import from this package, so a couple of tables are duplicated:

* ``src/fusion360_mcp/hints.py``, ``src/fusion360_mcp/_mutation_commands.py`` and
  ``src/fusion360_mcp/_rules.py`` are generated from the add-in's files by
  ``scripts/sync_mirrors.py``; ``test_no_mirror_is_stale`` runs it with ``--check``,
  and the header check reads that script's ``MIRRORS`` so a fourth entry is covered.
* ``HandlerBase._COMMAND_NAMES``  ↔  ``tools.py``'s tool names
* ``tools.VIEW_PRESETS``  ↔  ``HandlerBase._VIEW_DIRS``

If they drift, agents see different error envelopes / delta payloads / enums
depending on whether they're running against Fusion or mock mode.  These
tests fail loudly the moment a maintainer updates one side without the
other.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The tables are read from the base, not from ``command_handler.py``: the split
#: left the three class attribute tables on ``HandlerBase`` and put only commands in
#: the domain modules, so emptying ``command_handler.py`` must not move this path.
HANDLER_BASE = REPO_ROOT / "addon" / "server" / "handler_base.py"
MUTATION_COMMANDS = REPO_ROOT / "addon" / "server" / "mutation_commands.py"


def _declared_mirrors() -> tuple[Path, ...]:
    """The mirror paths ``MIRRORS`` declares (``scripts`` is not a package)."""
    path = REPO_ROOT / "scripts" / "sync_mirrors.py"
    spec = importlib.util.spec_from_file_location("_sync_mirrors_paths", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(mirror for _canonical, mirror, _header in module.MIRRORS)


def _set_literal(value: ast.expr) -> set[str]:
    """The strings in a ``{...}`` / ``frozenset({...})`` literal."""
    # frozenset({...})  →  unwrap the set literal arg
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "frozenset"
        and value.args
    ):
        return set(ast.literal_eval(value.args[0]))
    return set(ast.literal_eval(value))


def _extract_class_attr_set(path: Path, class_name: str, attr: str) -> set[str]:
    """Pull ``ClassName.attr`` (a set/frozenset literal) out of *path* via AST.

    The invariant is "this table matches that schema", which is a property of the
    source rather than of running it, so the literal is read instead of imported.
    A dict literal reads as its keys, which is what ``_VIEW_DIRS`` is asked for.
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
            return _set_literal(value)
    raise AssertionError(f"{class_name}.{attr} not found in {path}")


def _extract_module_attr_set(path: Path, attr: str) -> set[str]:
    """``path``'s module-level ``attr`` literal — the same read, one scope up."""

    def found(target: ast.expr, value: ast.expr | None) -> set[str] | None:
        if isinstance(target, ast.Name) and target.id == attr and value is not None:
            return _set_literal(value)
        return None

    tree = ast.parse(path.read_text())
    for stmt in tree.body:
        # Annotated (``attr: frozenset[str] = frozenset({...})``) and plain
        # assignments are the same invariant; see ``_extract_class_attr_set``.
        hit = None
        if isinstance(stmt, ast.AnnAssign):
            hit = found(stmt.target, stmt.value)
        elif isinstance(stmt, ast.Assign) and stmt.targets:
            hit = found(stmt.targets[0], stmt.value)
        if hit is not None:
            return hit
    raise AssertionError(f"{attr} not found at module level in {path}")


def _view_dirs() -> set[str]:
    """The camera presets ``HandlerBase._VIEW_DIRS`` declares."""
    return _extract_class_attr_set(HANDLER_BASE, "HandlerBase", "_VIEW_DIRS")


@pytest.mark.parametrize("mirror", _declared_mirrors(), ids=str)
def test_every_declared_mirror_carries_the_generated_header(mirror):
    """Read from ``MIRRORS``, so a fourth mirror cannot be added without the header."""
    text = (REPO_ROOT / mirror).read_text(encoding="utf-8")

    assert "GENERATED, do not edit" in text.split("\n\n")[0], mirror


def test_no_mirror_is_stale():
    """``--check`` is the guard; its diff belongs in the assertion, not the stream."""
    result = subprocess.run(
        [sys.executable, "scripts/sync_mirrors.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "a mirror is stale - run `uv run python scripts/sync_mirrors.py`:\n"
        + result.stdout
        + result.stderr
    )


def test_the_mutation_list_has_one_source():
    """One literal, two import sites.

    The old guard compared two hand-written literals.  There is one literal now —
    the add-in's module, which the package's copy is generated from — so what is
    left to assert is that both import sites reach it.  The content is pinned by
    ``test_the_mutation_set_is_exactly_these_commands``.
    """
    from fusion360_mcp import _mutation_commands, mock
    from fusion360_mcp.connection import _MUTATION_COMMANDS

    assert mock._MUTATION_MOCKS is _mutation_commands.MUTATION_COMMANDS
    assert _MUTATION_COMMANDS is mock._MUTATION_MOCKS


def test_every_mutation_command_is_a_command():
    """A name in the mutation list with no handler changes nothing and says so.

    It would still reach `mock_command` through the alias, so mock mode would report
    deltas for a command the add-in answers with UNKNOWN_COMMAND.
    """
    commands = _extract_class_attr_set(HANDLER_BASE, "HandlerBase", "_COMMAND_NAMES")
    mutations = _extract_module_attr_set(MUTATION_COMMANDS, "MUTATION_COMMANDS")

    assert mutations <= commands, f"not commands: {sorted(mutations - commands)}"


#: The mutation set as a contract, not a count: a lost name and a gained name are
#: different failures.  A name dropped from ``MUTATION_COMMANDS`` stops that command
#: reporting deltas, and every iterating test above still passes on the shorter set;
#: a name added without this list changing means someone widened what counts as a
#: mutation, which is a decision and not an edit.
_MUTATION_CONTRACT = {
    "auto_constrain",
    "boolean_operation",
    "chamfer",
    "circular_pattern",
    "create_bend",
    "create_box",
    "create_cylinder",
    "create_flange",
    "create_hole",
    "create_sphere",
    "create_thread",
    "create_torus",
    "create_ucs",
    "delete_all",
    "draft_faces",
    "execute_code",
    "extrude",
    "fillet",
    "flat_pattern",
    "loft",
    "mirror",
    "move_body",
    "offset_faces",
    "patch_surface",
    "rectangular_pattern",
    "revolve",
    "ruled_surface",
    "scale_body",
    "set_color",
    "set_parameter",
    "shell",
    "split_body",
    "split_face",
    "stitch_surfaces",
    "suppress_feature",
    "sweep",
    "thicken_surface",
    "trim_surface",
    "undo",
    "unfold",
    "unsuppress_feature",
}


def test_the_mutation_set_is_exactly_these_commands():
    """Pinned by name; see ``_MUTATION_CONTRACT`` for why a count is not enough."""
    assert (
        _extract_module_attr_set(MUTATION_COMMANDS, "MUTATION_COMMANDS")
        == _MUTATION_CONTRACT
    )


def test_the_advertised_view_presets_are_the_ones_the_handler_handles():
    """``render_view``'s enum and ``VIEW_PRESETS`` are both ``_VIEW_DIRS``' keys.

    Read from the add-in source rather than from ``VIEW_PRESETS``, which the schema is
    built from: comparing the two would pass on an empty tuple.  The four isometric
    diagonals were handled and unadvertised, so a caller that asked for ``iso_ne`` was
    refused by the schema and understood by the handler.
    """
    from fusion360_mcp import tools

    advertised = tools.get_tool_by_name("render_view")
    assert advertised is not None
    enum = advertised["inputSchema"]["properties"]["view"]["enum"]

    assert set(tools.VIEW_PRESETS) == _view_dirs() | {"current"}
    assert set(enum) == _view_dirs() | {"current"}


def test_export_view_sheet_offers_the_presets_without_current():
    """Its schema lists ``_VIEW_DIRS`` alone, so it does not take ``VIEW_PRESETS``.

    "current" is not a view to render — the schema refuses it — so adopting the
    wider tuple here would advertise a refusal.
    """
    from fusion360_mcp import tools

    tool = tools.get_tool_by_name("export_view_sheet")
    assert tool is not None
    enum = tool["inputSchema"]["properties"]["views"]["items"]["enum"]

    assert set(enum) == _view_dirs()


def test_tools_match_addon_dispatch():
    """Every MCP tool must have an add-in handler, and vice versa.

    This is the drift guard that catches "added a tool to tools.py but
    forgot the CommandHandler entry" (and the reverse) at CI time.
    """
    from fusion360_mcp.tools import TOOLS

    tool_names = {t["name"] for t in TOOLS}
    dispatch = _extract_class_attr_set(HANDLER_BASE, "HandlerBase", "_COMMAND_NAMES")
    assert tool_names == dispatch, (
        f"tools.py and HandlerBase._COMMAND_NAMES have drifted.\n"
        f"  tools without handler: {sorted(tool_names - dispatch)}\n"
        f"  handlers without tool: {sorted(dispatch - tool_names)}"
    )


def test_every_handler_declares_exactly_its_schema_properties(handler_module):
    """A handler's signature and its schema name the same arguments, both ways.

    The schema is what an MCP caller is validated against; the handler's signature
    is what a direct-wire caller reaches, through the dispatch bind.  An argument
    only one side declares is either unreachable or unvalidated, so the two sets
    must be equal rather than merely overlapping.
    """
    from fusion360_mcp.tools import TOOLS

    mismatched = {}
    for tool in TOOLS:
        name = tool["name"]
        parameters = [
            parameter
            for parameter in inspect.signature(
                getattr(handler_module.CommandHandler, name)
            ).parameters
            if parameter != "self"
        ]
        declared = list((tool["inputSchema"].get("properties") or {}))
        if set(parameters) != set(declared):
            mismatched[name] = {
                "handler_only": sorted(set(parameters) - set(declared)),
                "schema_only": sorted(set(declared) - set(parameters)),
            }

    assert not mismatched, mismatched


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
