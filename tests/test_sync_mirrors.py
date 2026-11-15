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

    assert rendered == HEADER + "import re\n\n\nRULES = [('a', 'b')]\n"
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

    assert rendered == (
        HEADER + "from __future__ import annotations\n\n\nRULES = [('a', 'b')]\n"
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

    with pytest.raises(ValueError, match="no 'import ' line"):
        SYNC.render(canonical, HEADER)


@pytest.mark.parametrize(("canonical", "mirror"), EXPECTED_MIRRORS)
def test_every_mirror_the_tree_has_is_declared(canonical, mirror):
    """An emptied or typo'd MIRRORS would make every other check here vacuous."""
    pairs = {(canonical, mirror) for canonical, mirror, _ in SYNC.MIRRORS}

    assert (canonical, mirror) in pairs


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
        HEADER + "import re\n\nRULES = [1]\n"
    )
    assert SYNC.main(["--check"]) == 0
