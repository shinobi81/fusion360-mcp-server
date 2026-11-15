"""The reload script's comparison: what the file declares vs what Fusion runs.

The socket half is exercised by running the script (it needs a live add-in); the
comparison is the part that can be wrong in a way nobody notices, so it is tested
here.  It went wrong once already: ``dir(cls)`` lists the class's attribute tables
as well as its methods, so the first version reported every ``_VIEW_DIRS`` and
``_MUTATION_COMMANDS`` as "extra in the running class".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _script():
    """``scripts/reload_addin.py``, imported by path (``scripts`` is not a package)."""
    path = REPO_ROOT / "scripts" / "reload_addin.py"
    spec = importlib.util.spec_from_file_location("_reload_addin", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = """
class CommandHandler:
    _CONSTANTS = {"a": 1}

    def __init__(self):
        self._cache = None

    def __dunder_is_ignored(self):
        return None

    @staticmethod
    def _helper():
        return None

    def extract(self, height):
        return height


class Other:
    def not_a_handler_method(self):
        return None
"""


def test_only_the_handlers_own_methods_are_declared():
    """Methods, not attributes; this class, not the module."""
    declared = _script().declared_methods(SOURCE)

    assert declared == {"extract", "_helper"}
    assert "not_a_handler_method" not in declared


def test_dunders_and_attribute_tables_are_ignored():
    """``dir()`` sees ``_CONSTANTS`` and ``__init__``; the comparison must not."""
    declared = _script().declared_methods(SOURCE)

    assert "_CONSTANTS" not in declared
    assert not [name for name in declared if name.startswith("__")]


def test_a_method_the_file_declares_is_missing_from_the_running_class():
    """The dangerous direction: the file is newer than what Fusion loaded."""
    missing, extra = _script().compare({"a", "b"}, {"a"})

    assert missing == {"b"}
    assert extra == set()


def test_a_method_the_running_class_has_and_the_file_dropped_is_extra():
    missing, extra = _script().compare({"a"}, {"a", "b"})

    assert missing == set()
    assert extra == {"b"}


def test_identical_sets_report_nothing():
    assert _script().compare({"a", "b"}, {"a", "b"}) == (set(), set())


def test_a_file_without_the_class_is_refused():
    """A check that silently found no class would pass vacuously for ever."""
    import pytest

    with pytest.raises(SystemExit):
        _script().declared_methods("class SomethingElse:\n    pass\n")
