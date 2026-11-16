"""Appearances and physical properties: which appearance a body ends up with.

``set_color``, ``set_appearance`` and ``get_physical_properties`` were executed by no
test at all: the fakes withheld ``design.appearances``, ``app.materialLibraries``,
``body.appearance`` and ``body.getPhysicalProperties``, so the add-in's three
commands that use them could only be guarded by source scans.  The four fusions this
module reads are named where each test asserts on them:

* ``design.appearances.itemByName`` / ``add`` / ``addByCopy`` — the design's own
  collection, which ``set_color`` reuses and ``set_appearance`` must copy into;
* ``app.materialLibraries`` → ``.itemByName`` / ``.count`` / ``.item(i)`` →
  ``library.appearances.count`` / ``.item(i)`` → ``.name`` — the library search;
* ``body.appearance`` — what gets assigned;
* ``body.getPhysicalProperties(accuracy)`` → ``.mass``, ``.volume``, ``.area``,
  ``.density``, ``.centerOfMass`` (``.x``/``.y``/``.z``) — the physical reply.

Every positive fixture puts a **decoy appearance or body first** in the collection
the handler walks, so a lookup that stopped comparing names - or a body read that
took the first one it found - answers with the decoy and the test goes red.

Three numbers here are the **fake's**, not Fusion's, and are marked where they are
asserted: the appearances' colour (nothing models a material), the physical
properties (nothing weighs a solid), and the library names (no measurement of a
Fusion install).  The *units* are Fusion's: grams, cm^3, cm^2, g/cm^3.
"""

from __future__ import annotations

import pytest

from tests.fakes.app import FakeApplication
from tests.fakes.appearance import (
    FakeAppearance,
    FakeMaterialLibraries,
    FakeMaterialLibrary,
)
from tests.fakes.bodies import (
    FakeBody,
    FakeBoundingBox,
    FakeFace,
    FakePhysicalProperties,
)
from tests.fakes.design import FakeDesign


def _plate() -> FakeBody:
    """The body the commands act on, boxed so its geometry differs from the decoy."""
    return FakeBody(
        "Plate", bounding_box=FakeBoundingBox((0.0, 0.0, 0.0), (2.0, 2.0, 2.0))
    )


def _spacer() -> FakeBody:
    """A decoy body, placed *before* the named one in every fixture that uses it."""
    return FakeBody(
        "Spacer", bounding_box=FakeBoundingBox((9.0, 9.0, 9.0), (9.5, 9.5, 9.5))
    )


def _handler_and_bodies(bound_handler, app=None):
    """A design holding the decoy body then the plate, plus the plate itself."""
    design = FakeDesign(features=0, bodies=[_spacer(), _plate()])
    handler = bound_handler(design, app=app)
    return handler, design, design.rootComponent.bRepBodies.item(1)


def _app_with(library: FakeMaterialLibrary) -> FakeApplication:
    app = FakeApplication()
    app.materialLibraries = FakeMaterialLibraries([library])
    return app


# ── set_color ────────────────────────────────────────────────────────


def test_set_color_on_a_body_with_no_appearance_assigns_one(bound_handler):
    handler, design, plate = _handler_and_bodies(bound_handler)
    # A decoy first in the design's own collection: a lookup that stopped
    # comparing names would hand this back instead of creating the colour.
    design.appearances.add("Steel")

    out = handler.set_color("Plate", 255, 0, 0)

    assigned = plate.appearance
    assert assigned is not None, "a body with no appearance gets one"
    assert assigned.name == "MCP_255_0_0_255"
    assert assigned.color.channels() == (255, 0, 0, 255)
    assert assigned is design.appearances.itemByName("MCP_255_0_0_255")
    assert design.appearances.count == 2, "the decoy plus the one colour"
    assert out == {
        "body": "Plate",
        "color": [255, 0, 0],
        "opacity": 1.0,
        "appearance": "MCP_255_0_0_255",
    }


def test_set_color_leaves_the_decoy_body_alone(bound_handler):
    handler, design, _plate_body = _handler_and_bodies(bound_handler)

    handler.set_color("Plate", 0, 0, 255)

    assert design.rootComponent.bRepBodies.item(0).appearance is None, (
        "the decoy body was never named, so nothing may be assigned to it"
    )


def test_set_color_reuses_the_appearance_a_second_identical_call_made(bound_handler):
    handler, design, plate = _handler_and_bodies(bound_handler)
    design.appearances.add("Steel")

    handler.set_color("Plate", 0, 128, 255)
    first = plate.appearance
    handler.set_color("Plate", 0, 128, 255)

    assert plate.appearance is first, "the same colour is the same appearance"
    assert design.appearances.count == 2, "the decoy plus one colour, not two"


def test_set_color_clamps_channels_and_rounds_opacity_into_the_name(bound_handler):
    handler, _design, plate = _handler_and_bodies(bound_handler)
    alpha = round(0.5 * 255)

    out = handler.set_color("Plate", 300, -20, 128, opacity=0.5)

    assert out["color"] == [255, 0, 128], "channels outside 0..255 are clamped"
    assert out["opacity"] == alpha / 255.0, "the reply reports Fusion's 0..255 alpha"
    assert plate.appearance.name == f"MCP_255_0_128_{alpha}"
    assert plate.appearance.color.channels() == (255, 0, 128, alpha)


# ── set_appearance ───────────────────────────────────────────────────


def test_set_appearance_copies_the_library_appearance_into_the_design(bound_handler):
    library = FakeMaterialLibrary(
        "Fusion Appearance Library",
        # Decoy first, so a search that stopped comparing names picks "Steel".
        [FakeAppearance("Steel"), FakeAppearance("Polished Aluminium")],
    )
    handler, design, plate = _handler_and_bodies(bound_handler, _app_with(library))
    # And a decoy in the design's own collection, so a lookup that skipped the name
    # would find "Steel" there and skip the copy.
    design.appearances.add("Steel")

    out = handler.set_appearance("Plate", "Polished Aluminium")

    assigned = plate.appearance
    assert assigned is not None
    assert assigned.name == "Polished Aluminium"
    assert assigned is design.appearances.itemByName("Polished Aluminium"), (
        "the body takes the design's copy, not the library's appearance"
    )
    assert assigned is not library.appearances.itemByName("Polished Aluminium")
    assert design.appearances.count == 2, "the decoy plus the copy"
    assert out == {
        "applied": True,
        "target": "Plate",
        "appearance": "Polished Aluminium",
    }


def test_set_appearance_falls_back_to_a_library_the_known_names_do_not_match(
    bound_handler,
):
    """The library name is the test's: no Fusion install was measured for one."""
    library = FakeMaterialLibrary("Custom Appearances", [FakeAppearance("Brass")])
    handler, _design, plate = _handler_and_bodies(bound_handler, _app_with(library))

    handler.set_appearance("Plate", "Brass")

    assert plate.appearance.name == "Brass"


def test_set_appearance_that_fusion_does_not_have_refuses_and_assigns_nothing(
    bound_handler,
):
    """The handler's own refusal, which classifies as UNKNOWN today, not INVALID_INPUT.

    ``addon/server/hints.py`` has no rule for "Appearance '<name>' not found", and
    this task may not add one; asserted here is the behaviour - the call raises and
    nothing is assigned - rather than the message or the ``error_kind``.
    """
    library = FakeMaterialLibrary(
        "Fusion Appearance Library", [FakeAppearance("Steel")]
    )
    handler, design, plate = _handler_and_bodies(bound_handler, _app_with(library))

    with pytest.raises(RuntimeError):
        handler.set_appearance("Plate", "Unobtainium")

    assert plate.appearance is None
    assert design.appearances.count == 0, "a name Fusion does not have copies nothing"


def test_set_appearance_with_no_appearance_library_refuses_and_assigns_nothing(
    bound_handler,
):
    """Fusion's libraries are the application's, so no library means no appearance."""
    handler, design, plate = _handler_and_bodies(bound_handler, FakeApplication())

    with pytest.raises(RuntimeError):
        handler.set_appearance("Plate", "Steel")

    assert plate.appearance is None
    assert design.appearances.count == 0


def test_set_appearance_on_a_face_lands_on_that_face_and_not_the_body(bound_handler):
    """``face_index`` picks the face: face 0 is the decoy and must stay bare."""
    library = FakeMaterialLibrary(
        "Fusion Appearance Library", [FakeAppearance("Polished Aluminium")]
    )
    handler, _design, plate = _handler_and_bodies(bound_handler, _app_with(library))
    plate.faces.add(FakeFace(normal=(1.0, 0.0, 0.0)))
    first, second = plate.faces.item(0), plate.faces.item(1)

    handler.set_appearance(
        "Plate", "Polished Aluminium", target_type="face", face_index=1
    )

    assert second.appearance is not None
    assert second.appearance.name == "Polished Aluminium"
    assert first.appearance is None, "the face before it is untouched"
    assert plate.appearance is None, "a face appearance is not a body appearance"


def test_set_appearance_on_a_component_lands_on_the_component(bound_handler):
    library = FakeMaterialLibrary(
        "Fusion Appearance Library", [FakeAppearance("Brass")]
    )
    handler, design, plate = _handler_and_bodies(bound_handler, _app_with(library))
    root = design.rootComponent

    handler.set_appearance(root.name, "Brass", target_type="component")

    assert root.appearance is not None
    assert root.appearance.name == "Brass"
    assert plate.appearance is None, "the bodies inside are untouched"


# ── get_physical_properties ──────────────────────────────────────────


def test_get_physical_properties_reports_fusion_units_not_si(bound_handler):
    """Grams, cm^3, cm^2, g/cm^3 - passed straight through, never converted.

    The values are the **fixture's**: this fake weighs nothing, and Fusion's own
    answer would come from the solid's material.  What the test pins is the absence
    of a conversion: the same 8 cm^3 solid is 8e-6 m^3 in SI, and 2.7 g/cm^3 is
    2700 kg/m^3, so any handler that unit-converted would report different numbers.
    All four differ from each other, so a swapped pair of fields also fails.
    """
    properties = FakePhysicalProperties(
        mass=21.6,
        volume=8.0,
        area=24.0,
        density=2.7,
        center_of_mass=(1.0, 1.0, 1.0),
    )
    design = FakeDesign(
        features=0,
        bodies=[_spacer(), FakeBody("Plate", physical_properties=properties)],
    )
    handler = bound_handler(design)

    out = handler.get_physical_properties("Plate")

    assert out == {
        "mass": 21.6,
        "volume": 8.0,
        "area": 24.0,
        "density": 2.7,
        "center_of_mass": [1.0, 1.0, 1.0],
    }


def test_get_physical_properties_asks_fusion_for_the_accuracy_it_was_given(
    bound_handler,
):
    """``very_high`` is Fusion's own enum; anything else falls back to medium."""
    handler, design, plate = _handler_and_bodies(bound_handler)

    handler.get_physical_properties("Plate", accuracy="very_high")
    handler.get_physical_properties("Plate", accuracy="nonsense")

    assert plate.accuracy_requests == [
        "VeryHighCalculationAccuracy",
        "MediumCalculationAccuracy",
    ]
    assert design.rootComponent.bRepBodies.item(0).accuracy_requests == [], (
        "the decoy body was never named, so Fusion was never asked about it"
    )
