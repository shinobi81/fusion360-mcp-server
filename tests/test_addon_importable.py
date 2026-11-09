"""The add-in imports Autodesk's API through one lazy adapter.

Outside Fusion there is no ``adsk``, so nothing under ``addon/`` may import it at module
scope.  These tests drive the adapter itself with a synthetic ``adsk`` package (the real
one exists only inside Fusion), and drive the *import* of the add-in modules in a
subprocess where no ``adsk`` exists at all.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import pathlib
import subprocess
import sys
import types

import pytest

from addon.server import fusion_api


@pytest.fixture(autouse=True)
def _clean_adapter():
    """Leave the adapter unresolved after every test in this module.

    ``test_reset_forgets_an_injected_name`` ends by *re-caching* a synthetic ``core``,
    and a fake left installed would be handed to the next module instead of failing
    loudly - the hazard ``fake_runtime``'s docstring exists to describe.
    """
    yield
    fusion_api.reset()


@pytest.fixture
def _clean_logging():
    """``configure()`` is deliberately global; restore what it changes.

    Without this the handlers outlive the test: the file handler points at a finished
    test's temp path, and the stream handler at a capture object nothing owns any more.
    """
    import addon.server as server

    logger = logging.getLogger("fusion360mcp")
    saved_handlers = logger.handlers[:]
    yield
    logger.handlers[:] = saved_handlers
    server.configure.cache_clear()


def _synthetic_adsk(monkeypatch):
    """A stand-in ``adsk`` with one submodule and one package-level function."""
    calls = []
    adsk = types.ModuleType("adsk")
    core = types.ModuleType("adsk.core")
    setattr(adsk, "core", core)
    setattr(adsk, "doEvents", lambda: calls.append("doEvents"))
    monkeypatch.setitem(sys.modules, "adsk", adsk)
    monkeypatch.setitem(sys.modules, "adsk.core", core)
    return adsk, core, calls


def test_a_submodule_resolves_lazily(monkeypatch):
    _, core, _ = _synthetic_adsk(monkeypatch)
    fusion_api.reset()

    assert fusion_api.core is core


def test_a_package_level_function_resolves_as_itself(monkeypatch):
    """``adsk.doEvents`` is a function on the package, not a submodule.

    Seven call sites call it.  A resolver that only maps name -> submodule raises
    ``AttributeError`` here, and inside Fusion there is no test to notice.
    """
    _, _, calls = _synthetic_adsk(monkeypatch)
    fusion_api.reset()

    fusion_api.doEvents()
    assert calls == ["doEvents"]


def test_an_unknown_name_is_an_AttributeError():
    fusion_api.reset()
    with pytest.raises(AttributeError, match="no attribute"):
        fusion_api.nonexistent


def test_reset_forgets_an_injected_name(monkeypatch):
    _, core, _ = _synthetic_adsk(monkeypatch)
    fusion_api.reset()
    fusion_api.core = "injected"
    assert fusion_api.core == "injected"
    fusion_api.reset()
    assert fusion_api.core is core


_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _import_in_subprocess(tmp_path, *modules: str):
    """Import *modules* in a fresh interpreter with no ``adsk`` and a temp ``HOME``.

    ``LOG_PATH`` follows ``HOME`` on POSIX and ``USERPROFILE`` on Windows; both point
    into *tmp_path*, so a log file created by importing shows up as a new entry there.
    """
    source = "\n".join(
        [
            "import os, pathlib",
            "home = pathlib.Path(os.environ['HOME'])",
            "before = {p.name for p in home.iterdir()}",
            *[f"import {name}" for name in modules],
            "after = {p.name for p in home.iterdir()}",
            "print(sorted(after - before))",
        ]
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "PYTHONPATH": str(_ROOT),
    }
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_importing_the_package_creates_no_log_file(tmp_path):
    """``RotatingFileHandler`` opens its file when constructed.

    It used to be constructed at import of ``addon.server``, so merely importing the
    add-in created ``~/fusion360mcp.log``.  Making ``get_logger`` lazy is not enough:
    three modules call it at module scope.
    """
    result = _import_in_subprocess(tmp_path, "addon.server")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", "importing the package must create no file"


def test_configure_is_idempotent(tmp_path, monkeypatch, _clean_logging):
    """A second ``run()`` must not double every log line."""
    from addon.server import configure

    log_path = tmp_path / "fusion360mcp.log"
    monkeypatch.setattr("addon.server.LOG_PATH", str(log_path))

    configure()
    configure()

    logger = logging.getLogger("fusion360mcp")
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]
    stream_handlers = [
        handler for handler in logger.handlers if type(handler) is logging.StreamHandler
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(log_path)
    assert len(stream_handlers) == 1, "the guard protects both handlers, not just one"


def test_command_handler_imports_without_adsk(tmp_path):
    """The invariant: no ``adsk``, and no log file, on the import path."""
    result = _import_in_subprocess(tmp_path, "addon.server.command_handler")

    assert result.returncode == 0, result.stderr
    assert "No module named 'adsk'" not in result.stderr
    assert result.stdout.strip() == "[]", "importing the handler must create no file"


def test_the_bridge_and_socket_import_without_adsk(tmp_path):
    """The two modules that still reach ``adsk`` at import: both must be lazy now."""
    result = _import_in_subprocess(
        tmp_path, "addon.server.event_bridge", "addon.server.socket_server"
    )

    assert result.returncode == 0, result.stderr
    assert "No module named 'adsk'" not in result.stderr
    assert result.stdout.strip() == "[]", "importing the bridge must create no file"


def test_a_missing_adsk_raises_AttributeError(monkeypatch):
    """``__getattr__`` must not let an ImportError escape.

    ``getattr(x, name, default)``, ``hasattr`` and ``monkeypatch.setattr`` all catch
    AttributeError only, so an ImportError from here breaks every one of them - it did,
    as a teardown failure that looked like a fixture bug.
    """
    monkeypatch.delitem(sys.modules, "adsk", raising=False)
    fusion_api.reset()

    with pytest.raises(AttributeError, match="adsk is not importable"):
        fusion_api.core


def test_the_fixture_installs_its_fakes_on_the_adapter():
    """The seam is the same code path production uses: a module attribute."""
    from tests.fakes.runtime import fake_runtime

    with fake_runtime():
        point = fusion_api.core.Point3D.create(1, 2, 3)
        assert type(point).__name__ == "FakePoint3D", "the fake, not Fusion"

    assert "core" not in vars(fusion_api), "the fixture must reset the adapter"


def test_a_reload_after_the_adapter_change_still_swaps_the_handler():
    """``reload_handler`` is the hot path the add-in uses between edits.

    It reloads the sibling modules and builds a fresh ``CommandHandler()`` — the one
    place a real construction happens outside Fusion, and the reason the fake core
    needs ``Application``.  ``FakeApplication.get()`` is memoised, so the reloaded
    handler is wired to the same session the bridge was given.
    """
    from addon.server import event_bridge
    from tests.fakes.app import FakeApplication
    from tests.fakes.runtime import fake_runtime

    class Handler:
        """A stand-in with no Fusion behind it; the reload replaces it anyway."""

        def execute_command(self, command):
            return {"ok": True}

    with fake_runtime():
        app = FakeApplication.get()
        bridge = event_bridge.EventBridge(app, Handler())
        try:
            before = bridge._handler
            bridge.reload_handler()

            assert bridge._handler is not before
            assert bridge._handler.app is app, "the reloaded handler shares the session"
        finally:
            bridge.stop()


def test_a_resolved_name_survives_adsk_leaving_sys_modules(monkeypatch):
    """The cache is a module attribute, not a lookup: resolution happens once.

    This is the mechanism the design calls the reason an injected fake and a resolved
    module are indistinguishable — both are ordinary attributes after the first access.
    """
    _, core, _ = _synthetic_adsk(monkeypatch)
    fusion_api.reset()
    assert fusion_api.core is core

    monkeypatch.delitem(sys.modules, "adsk.core", raising=False)

    assert fusion_api.core is core
