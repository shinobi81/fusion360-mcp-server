"""Sheet metal: ``flat_pattern``, ``unfold``, ``create_flange`` and ``create_bend``.

Each command resolves a name to an entity and then fills a feature input, so the
fakes here model the input surface the handler writes to, not the geometry Fusion
builds from it.

``create_flange`` and ``create_bend`` reach Fusion through APIs that do not look
like the ones the handlers first used - ``createEdgeFlangeInput(edges, distance)``,
not `FlangeFeatures.createInput`, and ``foldFeatures`` rather than
``features.bendFeatures`` - which is why the fakes beside them
(`FakeEdgeFlangeInput`) declare those signatures and not the handlers'.
"""

from __future__ import annotations

import pytest

from addon.server import hints as addon_hints
from tests.fakes.bodies import FakeBody, FakeEdges, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakePoint3D
from tests.fakes.sketch import FakeSketch


def _sheet_metal_design() -> tuple[FakeDesign, FakeBody, list[FakeFace]]:
    """A strip whose **first** face is a bend wall, not a flat one.

    The decoy body is first in the root, and the faces are ordered so nothing but
    the planar test can pick the stationary face: index 0 is cylindrical, so a scan
    that took the first face, or a handler that passed the collection it built,
    hands over the wrong entity.  Faces 1 and 2 are the two flat faces this body
    has, and the bend tests ask for index 2 **before** index 0, so a collection
    that kept the body's order, or sorted the indices, is caught.

    ``Sketch1`` carries one line, because a fold needs a bend line that already
    exists - the handler refuses a sketch with none rather than inventing one.
    """
    faces = [FakeFace(planar=False), FakeFace(planar=True), FakeFace(planar=True)]
    body = FakeBody("Bracket", faces=FakeCollection(faces))
    sketch = FakeSketch(name="Sketch1")
    sketch.sketchCurves.sketchLines.addByTwoPoints(
        FakePoint3D(4, 0, 0), FakePoint3D(4, 4, 0)
    )
    design = FakeDesign(bodies=[FakeBody("DecoyBody"), body], sketches=[sketch])
    return design, body, faces


def test_an_unfold_takes_the_first_planar_face_as_stationary(bound_handler):
    """The stationary face is a flat face of the named body, not the leading wall.

    ``UnfoldFeatureInput`` keeps this face fixed while the sheet unfolds, and
    ``createInput`` takes it as its only argument, so handing over a bend's
    cylindrical wall would fold the part about something that is not a face of it.
    """
    design, _body, faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.unfold("Bracket", bend_indices=[2])

    created = design.rootComponent.features.unfoldFeatures.inputs[0]
    assert created.stationaryFace is faces[1]
    assert created.stationaryFace is not faces[0]


def test_an_unfold_of_named_bends_hands_over_those_faces_in_order(bound_handler):
    """The two indices asked for, in that order, and every-bend left off.

    ``bendFaces`` is a vector, so the order reaches Fusion; ``isUnfoldAllBends``
    true would make Fusion ignore the vector entirely, which is why it is asserted
    false in the same breath.
    """
    design, _body, faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.unfold("Bracket", bend_indices=[2, 0])

    created = design.rootComponent.features.unfoldFeatures.inputs[0]
    assert created.bendFaces == [faces[2], faces[0]]
    assert created.isUnfoldAllBends is False


def test_an_unfold_without_bend_indices_asks_for_every_bend(bound_handler):
    """No indices means the flag, and no face list: they are not both sent."""
    design, _body, _faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.unfold("Bracket")

    created = design.rootComponent.features.unfoldFeatures.inputs[0]
    assert created.isUnfoldAllBends is True
    assert created.bendFaces == []


def test_an_unfold_of_a_body_with_no_flat_face_builds_no_input(bound_handler):
    """The refusal happens before anything is handed to Fusion.

    The body has no planar face to stay fixed, so the arguments are fine and the
    body lacks the geometry: ``GEOMETRY_UNSUPPORTED``.
    """
    faces = FakeCollection([FakeFace(planar=False), FakeFace(planar=False)])
    design = FakeDesign(
        bodies=[FakeBody("DecoyBody"), FakeBody("Tube", faces=faces)],
    )
    handler = bound_handler(design)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.unfold("Tube")

    assert raised.value.error_kind == "GEOMETRY_UNSUPPORTED"
    assert str(raised.value) == "No planar face found for stationary face"
    assert raised.value.hints == (
        "Pick a body with a planar face to use as the stationary face.",
    )
    assert design.rootComponent.features.unfoldFeatures.inputs == []


def test_a_flat_pattern_is_built_from_the_first_planar_face(bound_handler):
    """The component is handed a flat face of the named body.

    The leading face is a bend wall and the decoy body comes first in the root, so
    a scan that took the first face, or a lookup that took the first body, hands
    over something that is not a face of this part.
    """
    design, _body, faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.flat_pattern("Bracket")

    root = design.rootComponent
    assert root.flat_pattern_faces == [faces[1]]
    assert root.flat_pattern_faces[0] is not faces[0]


def test_a_flat_pattern_reports_the_name_of_the_flat_pattern_it_created(bound_handler):
    """``feature_name`` is the returned ``FlatPattern``'s name, not a made-up one."""
    design, _body, _faces = _sheet_metal_design()
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.flat_pattern("Bracket")

    assert len(root.flat_patterns) == 1
    assert out == {"feature_name": root.flat_patterns[0].name}


def test_a_flat_pattern_of_a_body_with_no_flat_face_creates_nothing(bound_handler):
    """The refusal happens before the component is asked for a flat pattern."""
    faces = FakeCollection([FakeFace(planar=False), FakeFace(planar=False)])
    design = FakeDesign(
        bodies=[FakeBody("DecoyBody"), FakeBody("Tube", faces=faces)],
    )
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.flat_pattern("Tube")

    assert design.rootComponent.flat_patterns == []


# ── create_flange ──────────────────────────────────────────────────────


class _Edge:
    """An edge, by identity - the handler only ever passes it through."""


def _flange_design():
    """Two edges on the plate, a decoy body first, and a body with no edges last.

    The decoy matters twice: the second body must not be read, and the edge list
    must reach Fusion with **one** member - the one at the index asked for, not
    every edge the body has.
    """
    first, second = _Edge(), _Edge()
    body = FakeBody("Bracket", edges=FakeEdges([first, second]))
    design = FakeDesign(bodies=[FakeBody("DecoyBody"), body])
    return design, body, first, second


def test_a_flange_offers_the_named_edge_as_a_list_and_the_distance(bound_handler):
    """``createEdgeFlangeInput(edges, distance)``: a *list*, and the length.

    The shipped signature takes ``std::vector<Ptr<BRepEdge>>``, so a handler that
    passed the edge alone hands Fusion a ``BRepEdge`` where a vector belongs.
    """
    design, _body, first, second = _flange_design()
    handler = bound_handler(design)

    handler.create_flange("Bracket", edge_index=1, distance=2.5)

    created = design.rootComponent.features.flangeFeatures.edge_inputs[0]
    assert created.edges == [second]
    assert created.edges != [first]
    assert created.distance.value == 2.5


def test_a_flange_sets_the_angle_as_degrees_and_the_radius_as_an_override(
    bound_handler,
):
    """``angle`` is a ``ValueInput`` in degrees; the radius is an override.

    ``EdgeFlangeInput.bendRadiusOverride`` is a *BendRadiusOverride*, not a
    settable property - measured on 2706, assigning to it raises.  So the radius
    must arrive through ``setOverride``, and the fake has no setter to hide it.
    """
    design, _body, _first, _second = _flange_design()
    handler = bound_handler(design)

    handler.create_flange(
        "Bracket", edge_index=0, distance=1.0, angle=45, bend_radius_override=0.2
    )

    created = design.rootComponent.features.flangeFeatures.edge_inputs[0]
    assert created.angle is not None
    assert created.angle.kind == "string"
    assert created.angle.value == "45 deg"
    assert created.bendRadiusOverride.value is not None
    assert created.bendRadiusOverride.value.value == 0.2


def test_a_flange_without_a_radius_leaves_the_override_unset(bound_handler):
    """No radius means no override, not an override of zero."""
    design, _body, _first, _second = _flange_design()
    handler = bound_handler(design)

    handler.create_flange("Bracket", edge_index=0, distance=1.0)

    created = design.rootComponent.features.flangeFeatures.edge_inputs[0]
    assert created.bendRadiusOverride.value is None


# ── create_bend ────────────────────────────────────────────────────────


def test_a_bend_folds_about_the_face_it_was_given_not_the_first(bound_handler):
    """``createInput(stationaryFace)``: the named face, not the leading bend wall."""
    design, _body, faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.create_bend("Bracket", stationary_face_index=2, bend_line_sketch="Sketch1")

    created = design.rootComponent.features.foldFeatures.inputs[0]
    assert created.stationaryFace is faces[2]
    assert created.stationaryFace is not faces[0]


def test_a_bend_adds_one_bend_line_with_its_angle_and_position(bound_handler):
    """One ``bendLines.add(line, angle, position, relief)``, as the header spells it."""
    design, _body, _faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.create_bend(
        "Bracket",
        stationary_face_index=1,
        bend_line_sketch="Sketch1",
        angle=30,
        line_position="start",
        allow_bend_relief=False,
    )

    created = design.rootComponent.features.foldFeatures.inputs[0]
    definitions = created.bendLines.added
    assert len(definitions) == 1
    assert definitions[0].bendAngle.value == "30 deg"
    assert definitions[0].linePosition == "Start"
    assert definitions[0].allowBendRelief is False


def test_a_bend_refuses_a_sketch_with_no_line_before_touching_fusion(
    bound_handler,
):
    """A fold needs a line to bend along, and the refusal names the sketch."""
    body = FakeBody("Bracket", faces=FakeCollection([FakeFace(planar=True)]))
    design = FakeDesign(
        bodies=[FakeBody("DecoyBody"), body],
        sketches=[FakeSketch(name="Blank")],
    )
    handler = bound_handler(design)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.create_bend(
            "Bracket", stationary_face_index=0, bend_line_sketch="Blank"
        )

    assert raised.value.error_kind == "GEOMETRY_UNSUPPORTED"
    assert str(raised.value) == "Blank has no line to bend along"
    assert raised.value.hints == ("Bend along a sketch line that crosses the face.",)
    assert design.rootComponent.features.foldFeatures.inputs == []


def test_a_bend_defaults_to_the_mid_line_and_allows_relief(bound_handler):
    """The defaults are Fusion's centre position and relief on, and they are sent."""
    design, _body, _faces = _sheet_metal_design()
    handler = bound_handler(design)

    handler.create_bend("Bracket", stationary_face_index=1, bend_line_sketch="Sketch1")

    definition = design.rootComponent.features.foldFeatures.inputs[0].bendLines.added[0]
    assert definition.linePosition == "Center"
    assert definition.allowBendRelief is True
