"""The fake ``adsk`` runtime the add-in is imported against.

``command_handler.py`` imports ``adsk.cam``, ``adsk.core`` and ``adsk.fusion``
at module level, so no test can import it without them.  This module supplies
those three, loads the handler against them, and restores ``sys.modules`` when
the test module finishes — a fake left behind would be handed to the next module
that imports adsk-dependent code instead of failing loudly.

Two rules keep the fakes honest (design §7):

* they model **state** — a test asserts on the geometry Fusion would build, not
  on which method was called;
* anything the handler uses but the fake does not implement raises
  ``AttributeError`` rather than returning ``None``, so a missing piece of the
  API fails loudly instead of being swallowed.

Geometry lives in ``tests.fakes.sketch`` and the design tree in
``tests.fakes.design``; this module also owns the loader that installs it.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "addon" / "server"

# One synthetic package name for every add-in test: the handler is imported
# once per test module, and a stable name keeps ``sys.modules`` bookkeeping
# trivial.
FAKE_PACKAGE = "addon_handler_under_test"

# One source of truth for the design-type strings: ``undo`` compares against the
# copy the runtime hands the handler, so the fake design must use that same one.
PARAMETRIC = "ParametricDesignType"
DIRECT = "DirectDesignType"


class FakePoint3D:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    @classmethod
    def create(cls, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> FakePoint3D:
        return cls(x, y, z)

    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakePoint3D({self.x}, {self.y}, {self.z})"


class FakeVector3D(FakePoint3D):
    pass


class FakeObjectCollection:
    def __init__(self) -> None:
        self.items: list[object] = []

    @classmethod
    def create(cls) -> FakeObjectCollection:
        return cls()

    def add(self, item: object) -> None:
        self.items.append(item)

    @property
    def count(self) -> int:
        return len(self.items)

    def item(self, index: int) -> object:
        return self.items[index]

    def __iter__(self) -> Iterator[object]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


class FakeValueInput:
    """``adsk.core.ValueInput``: the two constructors, and which one was used.

    ``kind`` records the factory.  Fusion distinguishes them — ``createByReal``
    is read in internal units, ``createByString`` parses the unit — and that is
    the difference the parameter tests exist to pin, so the fake keeps it.
    """

    def __init__(self, value: object, kind: str = "real"):
        self.value = value
        self.kind = kind

    @classmethod
    def createByString(cls, value: object) -> FakeValueInput:
        return cls(value, "string")

    @classmethod
    def createByReal(cls, value: object) -> FakeValueInput:
        return cls(value, "real")


def module(name: str, **attrs: object) -> types.ModuleType:
    """A stub module carrying ``attrs`` (setattr keeps type checkers quiet)."""
    created = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(created, attr, value)
    return created


def _design_types() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        ParametricDesignType=PARAMETRIC,
        DirectDesignType=DIRECT,
    )


def _feature_operations() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        NewBodyFeatureOperation="new_body",
        JoinFeatureOperation="join",
        CutFeatureOperation="cut",
        IntersectFeatureOperation="intersect",
    )


_ADSK_MODULES = ("adsk", "adsk.core", "adsk.fusion", "adsk.cam")


def install() -> None:
    """Put a fake ``adsk`` in ``sys.modules``.

    The surface is the union of what the three add-in test modules need: a
    small, fixed set of constructors and enums.  Adding a name here is the only
    way to widen it, so it stays reviewable.
    """
    core = module(
        "adsk.core",
        Point3D=FakePoint3D,
        Vector3D=FakeVector3D,
        ObjectCollection=FakeObjectCollection,
        ValueInput=FakeValueInput,
    )
    fusion = module(
        "adsk.fusion",
        DesignTypes=_design_types(),
        FeatureOperations=_feature_operations(),
    )
    cam = module("adsk.cam")
    adsk = module(
        "adsk",
        core=core,
        fusion=fusion,
        cam=cam,
        doEvents=lambda: None,
    )
    sys.modules.update(
        {"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion, "adsk.cam": cam}
    )


def _import_handler() -> types.ModuleType:
    """Import ``command_handler.py`` under the synthetic package."""
    package = types.ModuleType(FAKE_PACKAGE)
    package.__path__ = [str(SERVER_DIR.parent)]
    server = types.ModuleType(f"{FAKE_PACKAGE}.server")
    server.__path__ = [str(SERVER_DIR)]
    # The add-in's package __init__ imports Fusion's logger; this is the one
    # piece of it the handler needs.
    setattr(server, "get_logger", lambda name=None: logging.getLogger("addon-test"))
    sys.modules[FAKE_PACKAGE] = package
    sys.modules[f"{FAKE_PACKAGE}.server"] = server
    return importlib.import_module(f"{FAKE_PACKAGE}.server.command_handler")


@contextmanager
def fake_runtime() -> Iterator[types.ModuleType]:
    """Install the fake adsk, load the handler, then restore ``sys.modules``.

    Scoped to the caller, not to the session: two test modules must not share
    the fake, and anything that was in ``sys.modules`` before (a real ``adsk``,
    however unlikely) is put back.
    """
    saved = {
        name: sys.modules[name]
        for name in list(sys.modules)
        if name in _ADSK_MODULES or name.startswith(FAKE_PACKAGE)
    }
    install()
    try:
        yield _import_handler()
    finally:
        for name in list(sys.modules):
            if name in _ADSK_MODULES or name.startswith(FAKE_PACKAGE):
                del sys.modules[name]
        sys.modules.update(saved)
