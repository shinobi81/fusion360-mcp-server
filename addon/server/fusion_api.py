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
    from typing import Any

    #: Fusion's own modules are only resolvable inside Fusion, so ``Any`` is the honest
    #: type for them offline - saying ``ModuleType`` would be a lie that then breaks
    #: every ``adsk.core.Application`` annotation in the add-in.
    cam: Any
    core: Any
    fusion: Any
    doEvents: Callable[[], None]

#: The names ``__getattr__`` serves.  Keep in step with the declarations above.
_NAMES = ("cam", "core", "fusion", "doEvents")


def __getattr__(name: str):
    if name not in _NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = _resolve(name)
    except ImportError as exc:  # the submodule or the package itself would not import
        # ``__getattr__`` that raises ImportError breaks ``getattr(x, n, default)``,
        # ``hasattr`` and ``monkeypatch.setattr``: all three catch AttributeError only.
        # Blame ``adsk`` only when it is what is missing - a broken install has its own
        # message, and saying "adsk is not importable" then would send the reader the
        # wrong way.
        cause = f"adsk is not importable: {exc}" if _adsk_missing(exc) else str(exc)
        raise AttributeError(
            f"module {__name__!r} cannot resolve {name!r}: {cause}"
        ) from exc
    # Cached as a real attribute: later lookups never reach this function, which is why
    # an injected fake and a resolved module behave identically.
    globals()[name] = value
    return value


def _adsk_missing(exc: ImportError) -> bool:
    """Whether *exc* is "there is no ``adsk`` here" rather than "``adsk`` is broken"."""
    if not isinstance(exc, ModuleNotFoundError):
        return False
    return (exc.name or "").split(".")[0] == "adsk"


def __dir__() -> list[str]:
    """Include the lazy names, so ``dir(fusion_api)`` shows what it serves."""
    return sorted(set(globals()) | set(_NAMES))


def _resolve(name: str):
    try:
        return importlib.import_module(f"adsk.{name}")
    except ImportError:
        return getattr(importlib.import_module("adsk"), name)


def reset() -> None:
    """Forget every resolved or injected name, returning to the unresolved state."""
    for name in _NAMES:
        globals().pop(name, None)
