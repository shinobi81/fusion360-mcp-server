"""The reload script's comparison: what the files declare vs what Fusion runs.

The socket half is exercised by running the script (it needs a live add-in); the
comparison is the part that can be wrong in a way nobody notices, so it is tested
here.  It went wrong once already: ``dir(cls)`` lists the class's attribute tables
as well as its methods, so the first version reported every ``_VIEW_DIRS`` and
``_MUTATION_COMMANDS`` as "extra in the running class".

The same hazard returns once ``CommandHandler`` is a base plus one mixin per domain:
``vars(cls)`` alone then sees none of the mixins' methods, and reading only
``command_handler.py`` declares none of them either.  The file half reads every module
in ``COMMAND_MODULES`` and the running half walks ``cls.__mro__``, so both halves cross
the inheritance line - the pair of tests at the bottom run each half against the real
add-in.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fakes.design import FakeDesign

REPO_ROOT = Path(__file__).resolve().parent.parent


def _script():
    """``scripts/reload_addin.py``, imported by path (``scripts`` is not a package)."""
    path = REPO_ROOT / "scripts" / "reload_addin.py"
    spec = importlib.util.spec_from_file_location("_reload_addin", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def one_command_module(monkeypatch):
    """``_script()`` with a one-module tuple: these tests hand-build a source map.

    ``declared_methods`` requires every module ``COMMAND_MODULES`` names to appear in
    the map it is given, and the real tuple gains a module per task while these maps
    stay hand-written.  Pinning it here keeps the requirement itself tested - by
    ``test_a_command_module_the_tuple_forgets_is_reported``, which sets its own tuple -
    without these tests restating the layout of ``addon/server``.
    """
    module = _script()
    monkeypatch.setattr(module, "COMMAND_MODULES", ("command_handler",))
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


def test_only_the_handlers_own_methods_are_declared(one_command_module):
    """Methods, not attributes; the command classes, not the module."""
    declared = one_command_module.declared_methods({"command_handler.py": SOURCE})

    assert declared == {"extract", "_helper"}
    assert "not_a_handler_method" not in declared


def test_dunders_and_attribute_tables_are_ignored(one_command_module):
    """``dir()`` sees ``_CONSTANTS`` and ``__init__``; the comparison must not."""
    declared = one_command_module.declared_methods({"command_handler.py": SOURCE})

    assert "_CONSTANTS" not in declared
    assert not [name for name in declared if name.startswith("__")]


def test_inherited_methods_count_as_declared(one_command_module):
    """A helper in the base counts as the running class's, because it is inherited."""
    sources = {
        "handler_base.py": "class HandlerBase:\n    def helper(self): pass\n",
        "handler_sketch.py": (
            "class SketchCommands:\n    def create_sketch(self): pass\n"
        ),
        "command_handler.py": "class CommandHandler(SketchCommands):\n    pass\n",
    }

    assert one_command_module.declared_methods(sources) == {"helper", "create_sketch"}


def test_a_command_module_the_tuple_forgets_is_reported(monkeypatch):
    """A name in the tuple that no source answers must stop the check, not shrink it."""
    module = _script()
    monkeypatch.setattr(
        module, "COMMAND_MODULES", ("handler_sketch", "command_handler")
    )
    sources = {"command_handler.py": "class CommandHandler:\n    pass\n"}

    with pytest.raises(SystemExit, match="handler_sketch"):
        module.declared_methods(sources)


def test_every_file_declaring_a_command_class_is_named_in_the_tuple():
    """The other direction: a module the tuple never names is invisible to both halves.

    ``declared_methods`` reports a name it cannot read and a module that declares no
    command class, and ``main`` compares that set with the running class - so a module
    that declares commands and appears in neither list gives the comparison nothing to
    disagree about.  Edits to it never reach Fusion (``event_bridge`` reloads only
    ``RELOAD_ORDER``) and the check still says ok.  The files come from the directory,
    not from the tuple: the directory is the list that grows by itself.
    """
    module = _script()
    server = REPO_ROOT / "addon" / "server"
    declaring = {
        path.name
        for path in [*server.glob("handler_*.py"), server / "command_handler.py"]
        if any(
            isinstance(node, ast.ClassDef) and module._is_command_class(node.name)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    }
    named = {f"{stem}.py" for stem in module.COMMAND_MODULES}

    unregistered = sorted(declaring - named)
    assert unregistered == [], (
        f"not in COMMAND_MODULES: {', '.join(unregistered)} - each declares a command "
        "class, so reload_handler never re-executes it and its edits never reach "
        "Fusion"
    )
    unreadable = sorted(named - declaring)
    assert unreadable == [], (
        f"named in COMMAND_MODULES, declaring no command class: "
        f"{', '.join(unreadable)} - the comparison would be vacuous for each of them"
    )


def test_the_command_modules_are_reloaded_base_first_and_command_handler_last():
    """The order is load-bearing, and both copies of the tuple say so in a comment.

    ``reload_handler`` re-executes each module in turn.  A module re-executed *after*
    its importer leaves the importer holding the old class object, so the base has to
    be built before the domains that inherit from it and ``command_handler`` - the
    module that imports all of them - has to be last.  Reordered, the reload succeeds
    and Fusion keeps serving a class assembled from the previous load.
    """
    module = _script()

    assert module.COMMAND_MODULES[0] == "handler_base"
    assert module.COMMAND_MODULES[-1] == "command_handler"


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


def test_a_module_without_a_command_class_is_refused():
    """A check that silently found no class would pass vacuously for ever."""
    with pytest.raises(SystemExit):
        _script().declared_methods(
            {"command_handler.py": "class SomethingElse:\n    pass\n"}
        )


class FakeConnection:
    """Stands in for ``Fusion360Connection``: records calls, replays one reply."""

    def __init__(self, methods: list[str], file: str = "handler.py", raises=None):
        self.methods = methods
        self.file = file
        self.raises = raises
        self.sent: list[str] = []
        self.params: dict = {}
        self.connected = False

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def send_command(self, command: str, params=None) -> dict:
        self.sent.append(command)
        self.params = params or {}
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


def _declared(module) -> set[str]:
    """Every command method the checkout's command modules declare."""
    paths = [module.SERVER / f"{stem}.py" for stem in module.COMMAND_MODULES]
    return module.declared_methods(
        {path.name: path.read_text(encoding="utf-8") for path in paths}
    )


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
    connection = FakeConnection(sorted(_declared(module)), file=str(module.HANDLER))
    module = _patched(monkeypatch, connection)

    rc = module.main(["--check"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "method names match" in captured.out
    assert "bodies are not compared" in captured.out


def test_main_says_what_a_reload_does_not_cover(monkeypatch, capsys):
    """The success line must not read as "everything is current"."""
    module = _script()
    connection = FakeConnection(sorted(_declared(module)), file=str(module.HANDLER))
    module = _patched(monkeypatch, connection)

    module.main([])

    # Derived, not retyped: this is the tuple ``main`` prints, so a module added to
    # the reload should not need a second edit here to keep the test honest.
    out = capsys.readouterr().out
    assert f"reloaded: {', '.join(module.RELOAD_ORDER)}" in out
    assert "not reloaded: event_bridge, socket_server" in out


def test_the_sibling_modules_are_named_in_the_reload_order():
    """The line above is derived from ``RELOAD_ORDER``, so it cannot pin it.

    Comparing the printed line with the tuple it was built from agrees with itself:
    drop ``hints`` from *both* copies of ``RELOAD_ORDER`` and every other test in this
    file stays green while Fusion keeps serving the pre-pull ``hints``.  So the
    siblings are named here, and ``COMMAND_MODULES`` is spliced in rather than
    retyped - a new domain module is one edit in ``COMMAND_MODULES``, not two here.
    """
    module = _script()

    # ``expected`` first, not last: SIM300 reads the upper-case attribute name as the
    # constant and flags ``module.RELOAD_ORDER == (...)`` as the Yoda form.
    expected = (
        "hints",
        "rules",
        "hole_geometry",
        "parameter_units",
        "mutation_commands",
        *module.COMMAND_MODULES,
    )
    assert expected == module.RELOAD_ORDER


def test_the_command_line_survives_an_interpreter_that_strips_docstrings():
    """``-OO`` empties ``__doc__``, and ``main`` used to subscript its first line.

    ``(None or "").splitlines()`` is ``[]``, so ``[0]`` raised IndexError before the
    script did anything: a traceback instead of a usage line, for a description that
    does not need to come from the docstring.  ``--help`` because it exits inside
    ``argparse``: the real command line stops at "not connected", so it would never
    reach the description, and on a machine running Fusion it would reload the add-in.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-OO",
            str(REPO_ROOT / "scripts" / "reload_addin.py"),
            "--help",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, (
        "`python -OO scripts/reload_addin.py --help` must exit 0: -OO empties "
        f"__doc__; stderr={result.stderr!r}"
    )


def test_a_fused_addin_is_reported_not_raised(monkeypatch, capsys):
    """A TIMEOUT arrives as FusionError; the reader gets a line, not a traceback."""
    from fusion360_mcp.connection import FusionError

    module = _patched(monkeypatch, FakeConnection([], raises=FusionError("timeout")))

    rc = module.main(["--check"])

    assert rc == 1
    assert "did not answer" in capsys.readouterr().err


def test_the_add_in_reloads_what_this_script_prints():
    """Two hand-maintained lists, because the add-in cannot import the dev tree.

    ``reload_handler`` re-executes its own copy in its own order, so a module added to
    one list and not the other reads as reloaded here and stays stale in Fusion.  The
    add-in's tuple is compared whole, not just its length: the order is the dependency
    order.
    """
    from addon.server import event_bridge

    assert event_bridge.RELOAD_ORDER == _script().RELOAD_ORDER


def test_the_add_in_names_the_same_command_modules_in_the_same_order():
    """``RELOAD_ORDER`` is derived from this tuple, so the test above cannot pin it.

    Both copies build their printed order from their own ``COMMAND_MODULES``, which
    means the additive test passes as long as the two derived lists agree - a copy
    whose tuple was edited without its order following it, or the other way round,
    is invisible there.  Pinning the tuples closes that gap, and a divergence in
    either direction leaves one of the two lists naming a module the other never
    reloads.
    """
    from addon.server import event_bridge

    assert event_bridge.COMMAND_MODULES == _script().COMMAND_MODULES


def test_the_code_it_sends_reports_the_class_through_its_mro(
    handler_module, bound_handler, monkeypatch
):
    """Run Fusion's half of the check here, against the real class.

    That string only ever executes inside Fusion, so nothing else in the suite notices
    it failing to parse, reading the wrong namespace, or reporting what ``vars(cls)``
    alone sees.  The second half swaps in a subclass with one mixin - the shape the
    split produces - where ``vars(cls)``, what the string did before, reports none of
    the inherited methods.
    """
    module = _script()
    handler = bound_handler(FakeDesign())
    connection = FakeConnection([])

    module.loaded_class(connection)
    code = connection.params["code"]

    reported = handler.execute_code(code)["result"]
    assert reported["file"].endswith("command_handler.py")
    assert set(reported["methods"]) == _declared(module)

    class Mixin:
        def inherited_probe(self):
            return None

    class Mixed(handler_module.CommandHandler, Mixin):
        pass

    monkeypatch.setattr(handler_module, "CommandHandler", Mixed)
    inherited = set(handler.execute_code(code)["result"]["methods"])

    assert inherited == set(reported["methods"]) | {"inherited_probe"}


def test_the_declared_names_are_the_running_classs_callables(handler_module):
    """Offline tie between the AST side and the runtime side.

    Without this, a conditional `def`, a decorator that renames a method, or a mixin
    would make the script report drift against a perfectly good file - the opposite
    failure from the one it exists to catch.
    """
    import inspect

    module = _script()
    declared = _declared(module)

    live = {
        name
        for klass in handler_module.CommandHandler.__mro__
        for name in vars(klass)
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

    The identity check alone passes on an empty table, so this also asserts the table
    has entries and that each one is the method of the name it is filed under: an
    emptied ``_COMMAND_NAMES`` builds an empty table and dispatches nothing.
    """
    handler = handler_module.CommandHandler()
    other = handler_module.CommandHandler()

    assert handler._commands, "an empty dispatch table answers no command"
    assert other._commands is not handler._commands
    for name, method in handler._commands.items():
        assert method.__self__ is handler, name
        assert method == getattr(handler, name), name
    assert not hasattr(type(handler), "_COMMANDS"), "the lazy class table is gone"
