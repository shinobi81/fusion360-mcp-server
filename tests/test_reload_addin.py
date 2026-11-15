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


class FakeConnection:
    """Stands in for ``Fusion360Connection``: records calls, replays one reply."""

    def __init__(self, methods: list[str], file: str = "handler.py", raises=None):
        self.methods = methods
        self.file = file
        self.raises = raises
        self.sent: list[str] = []
        self.connected = False

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def send_command(self, command: str, params=None) -> dict:
        self.sent.append(command)
        if self.raises is not None:
            raise self.raises
        if command == "reload_handler":
            return {"ok": True, "reloaded": True}
        # execute_code's envelope, exactly as the add-in sends it
        return {
            "ok": True,
            "executed": True,
            "result": {"file": self.file, "methods": self.methods},
            "output": "",
        }


def _patched(monkeypatch, connection: FakeConnection):
    """Point the script's ``Fusion360Connection`` at *connection*."""
    module = _script()
    monkeypatch.setattr(module, "Fusion360Connection", lambda **kwargs: connection)
    return module


def test_loaded_class_unwraps_execute_codes_envelope(monkeypatch):
    connection = FakeConnection(["extract"], file="C:/x/command_handler.py")
    module = _patched(monkeypatch, connection)

    loaded = module.loaded_class(connection)

    assert loaded == {"file": "C:/x/command_handler.py", "methods": ["extract"]}
    assert connection.sent == ["execute_code"]


def test_main_exits_1_when_the_running_class_lags_the_file(monkeypatch, capsys):
    connection = FakeConnection([])
    module = _patched(monkeypatch, connection)

    rc = module.main(["--check"])

    assert rc == 1
    assert "MISSING from the running class" in capsys.readouterr().out


def test_main_exits_0_when_the_sets_match(monkeypatch, capsys):
    module = _script()
    source = module.HANDLER.read_text(encoding="utf-8")
    declared = sorted(module.declared_methods(source))
    connection = FakeConnection(declared, file=str(module.HANDLER))
    module = _patched(monkeypatch, connection)

    rc = module.main(["--check"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "method names match" in captured.out
    assert "bodies are not compared" in captured.out


def test_main_says_what_a_reload_does_not_cover(monkeypatch, capsys):
    """The success line must not read as "everything is current"."""
    module = _script()
    source = module.HANDLER.read_text(encoding="utf-8")
    declared = sorted(module.declared_methods(source))
    module = _patched(monkeypatch, FakeConnection(declared, file=str(module.HANDLER)))

    module.main([])

    out = capsys.readouterr().out
    assert (
        "reloaded: hints, rules, hole_geometry, parameter_units, "
        "mutation_commands, command_handler"
    ) in out
    assert "not reloaded: event_bridge, socket_server" in out


def test_a_fused_addin_is_reported_not_raised(monkeypatch, capsys):
    """A TIMEOUT arrives as FusionError; the reader gets a line, not a traceback."""
    from fusion360_mcp.connection import FusionError

    module = _patched(monkeypatch, FakeConnection([], raises=FusionError("timeout")))

    rc = module.main(["--check"])

    assert rc == 1
    assert "did not answer" in capsys.readouterr().err


def test_the_declared_names_are_the_running_classs_callables(handler_module):
    """Offline tie between the AST side and the runtime side.

    Without this, a conditional `def`, a decorator that renames a method, or a mixin
    would make the script report drift against a perfectly good file - the opposite
    failure from the one it exists to catch.
    """
    import inspect

    module = _script()
    source = (module.HANDLER).read_text(encoding="utf-8")
    declared = module.declared_methods(source)

    live = {
        name
        for name in vars(handler_module.CommandHandler)
        if callable(getattr(handler_module.CommandHandler, name))
        and not name.startswith("__")
    }

    assert declared == live
    assert inspect.isfunction(handler_module.CommandHandler.create_thread)


def test_dispatch_is_built_once_per_instance(handler_module):
    """A fresh instance carries a fresh table, so a reload cannot leave it stale.

    The table used to be a lazily-populated class attribute, which made a reload
    depend on a line that reset it.  Building it in ``__init__`` removes both the
    reset and the window where an instance answers from a table built from another
    instance's bound methods.
    """
    handler = handler_module.CommandHandler()

    assert handler._commands == {
        name: getattr(handler, name) for name in handler._COMMAND_NAMES
    }
    assert not hasattr(type(handler), "_COMMANDS"), "the lazy class table is gone"
