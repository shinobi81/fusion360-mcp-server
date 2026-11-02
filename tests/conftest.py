"""Fixtures shared by the add-in tests.

``handler_module`` is the whole harness: it installs a fake ``adsk``, imports
``command_handler.py`` under a synthetic package, and restores ``sys.modules``
when the test module finishes.  It is module-scoped, so each test module gets a
clean runtime and no fake leaks into the next one.
"""

from __future__ import annotations

import pytest

from tests.fakes.runtime import fake_runtime


@pytest.fixture(scope="module")
def handler_module():
    """``command_handler.py``, imported once per test module against fake adsk."""
    with fake_runtime() as module:
        yield module
