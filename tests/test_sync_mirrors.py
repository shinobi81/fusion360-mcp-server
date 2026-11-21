"""The mirror generator's rules: what it drops, and what it refuses to drop.

``scripts/sync_mirrors.py`` renders a mirror as a fixed header plus the canonical text
from its first import line — the first line starting with ``import `` or ``from ``.
The canonical docstring is dropped by design, which is what keeps ``--check`` stable
while the docstring is edited.  Anything *else* above that line is refused, because a
table placed there would reach the add-in and nowhere else — the failure class this task
exists to remove, so it must not be assertable-as-expected behaviour.

The ``--check`` guard against a stale committed mirror is ``tests/test_addon_sync.py``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _generator():
    """``scripts/sync_mirrors.py``, imported by path (``scripts`` is not a package)."""
    path = REPO_ROOT / "scripts" / "sync_mirrors.py"
    spec = importlib.util.spec_from_file_location("_sync_mirrors", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNC = _generator()

HEADER = '"""A generated mirror."""\n\n'

#: What ``render`` puts between the header and the body: the formatter-off directive.
#: Named here so a third element cannot be added without one of these tests seeing it.
FORMAT_OFF = SYNC._FORMAT_OFF

MARKER = "GENERATED, do not edit"

#: Every mirror the tree ships, as ``MIRRORS`` must declare it.
EXPECTED_MIRRORS = [
    (Path("addon/server/hints.py"), Path("src/fusion360_mcp/hints.py")),
    (
        Path("addon/server/mutation_commands.py"),
        Path("src/fusion360_mcp/_mutation_commands.py"),
    ),
    (Path("addon/server/rules.py"), Path("src/fusion360_mcp/_rules.py")),
]


def test_the_preamble_docstring_never_reaches_the_mirror(tmp_path):
    """The docstring is dropped by design, so editing it cannot drift the mirror."""
    canonical = tmp_path / "canonical.py"
    canonical.write_text(
        '"""Canonical table.\n'
        "\n"
        f"This docstring says {MARKER} and would fool a reader of the mirror.\n"
        '"""\n'
        "\n"
        "import re\n"
        "\n"
        "\n"
        "RULES = [('a', 'b')]\n",
        encoding="utf-8",
    )

    rendered = SYNC.render(canonical, HEADER)

    assert rendered == HEADER + FORMAT_OFF + "import re\n\n\nRULES = [('a', 'b')]\n"
    assert MARKER not in rendered


def test_a_future_import_is_a_cut_point_too(tmp_path):
    """`from ... import` ends the preamble: a canonical opening with it is generated."""
    canonical = tmp_path / "canonical.py"
    canonical.write_text(
        '"""Canonical table."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "RULES = [('a', 'b')]\n",
        encoding="utf-8",
    )

    rendered = SYNC.render(canonical, HEADER)

    assert rendered == HEADER + FORMAT_OFF + (
        "from __future__ import annotations\n\n\nRULES = [('a', 'b')]\n"
    )


def test_a_table_above_the_first_import_is_refused(tmp_path):
    """Load-bearing code above the import would be dropped silently: refuse it."""
    canonical = tmp_path / "canonical.py"
    canonical.write_text(
        '"""Canonical table."""\n\nEXTRA_RULE = [1, 2]\n\nimport re\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 3 holds code above the first import"):
        SYNC.render(canonical, HEADER)


def test_a_canonical_file_without_an_import_line_is_refused(tmp_path):
    """No import line means no body: refuse, rather than write a bodyless mirror."""
    canonical = tmp_path / "canonical.py"
    canonical.write_text(
        '"""Only a docstring, and a table above where the imports should be."""\n'
        "\n"
        "RULES = [('a', 'b')]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="has no import line"):
        SYNC.render(canonical, HEADER)


@pytest.mark.parametrize(("canonical", "mirror"), EXPECTED_MIRRORS)
def test_every_mirror_the_tree_has_is_declared(canonical, mirror):
    """An emptied or typo'd MIRRORS would make every other check here vacuous."""
    pairs = {(canonical, mirror) for canonical, mirror, _ in SYNC.MIRRORS}

    assert (canonical, mirror) in pairs


def test_the_render_directive_disarms_the_formatter_to_the_end_of_the_file():
    """``src/`` is format-gated and ``addon/`` is not, so the body must be exempt.

    A ``# fmt: on`` would re-arm the formatter over a rendered copy of a file this
    package does not own - the tension that produced fourteen unstaged drift patches
    against this branch, every one of them reverted.
    """
    assert FORMAT_OFF.startswith("# fmt: off\n")
    assert "# fmt: on" not in FORMAT_OFF


def test_check_survives_an_interpreter_that_strips_docstrings():
    """``-OO`` empties every ``__doc__`` and drops docstrings from ``ast.parse``.

    Two readings in ``--check`` depended on that.  The ``argparse`` description
    subscripted ``(__doc__ or "").splitlines()``, which raises ``IndexError`` on the
    empty list ``-OO`` produces.  And ``_refuse_code_above_the_imports`` parses the
    preamble, where ``-OO`` leaves a tree with the canonical docstring already
    stripped - so the guard saw the file's own docstring as code above the import and
    refused it.  A docstring is not a statement to the optimising interpreter, and this
    guard must still see it, which is why the parse is pinned to ``optimize=0``.  Run
    the real command line, because either reading only breaks in a process launched with
    the flag.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-OO",
            str(REPO_ROOT / "scripts" / "sync_mirrors.py"),
            "--check",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, (
        "`python -OO scripts/sync_mirrors.py --check` must exit 0: -OO empties "
        f"__doc__ and strips docstrings from ast.parse; stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )


def test_writing_creates_a_mirror_that_does_not_exist_yet(tmp_path, monkeypatch):
    """Adding a MIRRORS entry is the documented way to start a mirror.

    The write path read the mirror before deciding it was stale, so a new entry
    raised FileNotFoundError instead of creating the file.
    """
    canonical = tmp_path / "canonical.py"
    canonical.write_text('"""C."""\n\nimport re\n\nRULES = [1]\n', encoding="utf-8")
    monkeypatch.setattr(SYNC, "ROOT", tmp_path)
    monkeypatch.setattr(
        SYNC, "MIRRORS", ((Path("canonical.py"), Path("mirror.py"), HEADER),)
    )

    assert SYNC.main([]) == 0
    assert (tmp_path / "mirror.py").read_text(encoding="utf-8") == (
        HEADER + FORMAT_OFF + "import re\n\nRULES = [1]\n"
    )
    assert SYNC.main(["--check"]) == 0
