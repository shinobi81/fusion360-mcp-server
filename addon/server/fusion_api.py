"""The one place the add-in imports Autodesk's API.

Resolved lazily, so the add-in imports outside Fusion: nothing here touches ``adsk``
until a handler actually calls it.  That is what lets the test suite import
``addon.server`` as an ordinary module and inject the fakes through a single seam.

Under test, assign the names (``fusion_api.core = fake_core``) and call :func:`reset`
afterwards — a module attribute is the same thing a real resolution produces, so a test
never takes a branch production cannot.

``doEvents`` is a function on the ``adsk`` package rather than a submodule, and seven
call sites use it, so resolution tries the submodule first and falls back to the package
attribute.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # declared for type checkers; resolved lazily at runtime instead
    from collections.abc import Callable
    from types import ModuleType

    cam: ModuleType
    core: ModuleType
    fusion: ModuleType
    doEvents: Callable[[], None]

#: The names ``__getattr__`` serves.  Keep in step with the declarations above.
_NAMES = ("cam", "core", "fusion", "doEvents")


def __getattr__(name: str):
    if name not in _NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = _resolve(name)
    # Cached as a real attribute: later lookups never reach this function, which is why
    # an injected fake and a resolved module behave identically.
    globals()[name] = value
    return value


def _resolve(name: str):
    try:
        return importlib.import_module(f"adsk.{name}")
    except ImportError:
        return getattr(importlib.import_module("adsk"), name)


def reset() -> None:
    """Forget every resolved or injected name, returning to the unresolved state."""
    for name in _NAMES:
        globals().pop(name, None)
