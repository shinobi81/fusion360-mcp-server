"""The add-in imports Autodesk's API through one lazy adapter.

Outside Fusion there is no ``adsk``, so nothing under ``addon/`` may import it at module
scope.  These tests drive the adapter itself with a synthetic ``adsk`` package (the real
one exists only inside Fusion), and drive the *import* of the add-in modules in a
subprocess where no ``adsk`` exists at all.
"""

from __future__ import annotations

import sys
import types

import pytest

from addon.server import fusion_api


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
