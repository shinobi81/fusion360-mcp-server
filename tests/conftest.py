"""Fixtures shared by the add-in tests.

``handler_module`` is the whole harness: it installs a fake ``adsk``, imports
``command_handler.py`` under a synthetic package, and restores ``sys.modules``
when the test module finishes.  It is module-scoped, so each test module gets a
clean runtime and no fake leaks into the next one.

``bound_handler`` wires a handler to a fake design without a Fusion application,
which is how most add-in tests reach a method.
"""

from __future__ import annotations

import pytest

from tests.fakes.runtime import fake_runtime


@pytest.fixture(scope="module")
def handler_module():
    """``command_handler.py``, imported once per test module against fake adsk."""
    with fake_runtime() as module:
        yield module


@pytest.fixture
def bound_handler(handler_module):
    """``bound_handler(design, app=None)`` -> a CommandHandler for that design."""

    def factory(design, app=None):
        handler = handler_module.CommandHandler.__new__(handler_module.CommandHandler)
        handler._design = lambda: design
        handler._root = lambda: design.rootComponent
        if app is not None:
            handler.app = app
        return handler

    return factory
