"""Sheet metal: ``create_flange``, ``create_bend``, ``flat_pattern``, ``unfold``.

Each command resolves a name to an entity and then fills a feature input, so the
tests assert exactly that: which edge, which bend line, which body, which face,
and which of the input's properties the call site writes.  Each test carries one
claim, and each puts a decoy in every collection the handler searches — a second
body in the root, a second edge on the body, a second sketch in the root, a
non-planar face before the flat ones — so a lookup that took the first item would
hand over the wrong entity and fail.

Which claims are the **fake's**, not Fusion's:

* The flange and bend arities (two positional arguments for
  ``flangeFeatures.createInput``, three for ``bendFeatures.createInput``) come
  from the call sites in ``handler_surface.py``; no SDK text was to hand when
  those four fakes were written, so only the count and the order are claimed, not
  the parameter names.
* The recorded attribute names on the flange and bend inputs (``edge``,
  ``isTangentChain``, ``baseObject``, ``bendLine``, ``isBendLineExtended``) are
  the fake's arrangement for reading a call back; no test treats one as a Fusion
  property.  ``unfold``'s input is the exception: ``stationaryFace``,
  ``bendFaces`` and ``isUnfoldAllBends`` are the shipped names
  (``UnfoldFeatureInput.h:46-62``), which is why a call site that set a name Fusion
  does not ship would leave them at their defaults and fail here.
* ``feature_name`` is the fake's own numbering.  Nothing here claims what Fusion
  names a feature, nor whether a flange, a bend, a flat pattern or an unfold is
  geometrically possible on the entity it was given — that needs the geometry,
  which these fakes do not carry.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody, FakeFace, body_with_edges
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakePoint3D
from tests.fakes.sketch import FakeSketch


def _body_with_two_edges() -> FakeBody:
    return body_with_edges(
        "Panel",
        [
            ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            ((0.0, 10.0, 0.0), (10.0, 10.0, 0.0)),
        ],
    )


def _flange_design() -> FakeDesign:
    """The decoy body first, so "the first body in the root" is the wrong one."""
    return FakeDesign(bodies=[FakeBody("DecoyBody"), _body_with_two_edges()])


def _line(sketch: FakeSketch, y: float) -> None:
    sketch.sketchCurves.sketchLines.addByTwoPoints(
        FakePoint3D(0.0, y, 0.0), FakePoint3D(10.0, y, 0.0)
    )


def _bend_design() -> tuple[FakeDesign, FakeSketch, FakeSketch]:
    """A decoy sketch first, then the one the bend is asked for, with two lines."""
    bend_line = FakeSketch(name="BendLine")
    _line(bend_line, 5.0)
    _line(bend_line, 7.0)
    decoy = FakeSketch(name="Decoy")
    _line(decoy, 0.0)
    design = FakeDesign(
        bodies=[FakeBody("DecoyBody"), _body_with_two_edges()],
        sketches=[decoy, bend_line],
    )
    return design, bend_line, decoy


def test_a_flange_is_built_on_the_edge_its_index_selects(bound_handler):
    """The second edge of the *named* body — not the first edge, not the decoy body."""
    design = _flange_design()
    body = design.rootComponent.bRepBodies.item(1)
    handler = bound_handler(design)

    handler.create_flange("Panel", edge_index=1)

    created = design.rootComponent.features.flangeFeatures.inputs[0]
    assert created.edge is body.edges.item(1)


def test_a_flange_is_added_and_reports_the_feature_that_was_added(bound_handler):
    design = _flange_design()
    handler = bound_handler(design)

    out = handler.create_flange("Panel", edge_index=0)

    flanges = design.rootComponent.features.flangeFeatures
    assert flanges.added == flanges.inputs
    assert out["feature_name"] == flanges.created[0].name


def test_the_default_flange_height_is_one_centimetre(bound_handler):
    design = _flange_design()
    handler = bound_handler(design)

    out = handler.create_flange("Panel", edge_index=0)

    created = design.rootComponent.features.flangeFeatures.inputs[0]
    assert (created.height.value, out["height"]) == (1.0, 1.0)


def test_the_default_flange_angle_is_ninety_degrees(bound_handler):
    design = _flange_design()
    handler = bound_handler(design)

    out = handler.create_flange("Panel", edge_index=0)

    created = design.rootComponent.features.flangeFeatures.inputs[0]
    assert (created.angle.value, out["angle"]) == ("90 deg", 90)


def test_a_flange_height_is_handed_over_as_a_real(bound_handler):
    """``createByReal``, read in internal centimetres — not a string expression."""
    design = _flange_design()
    handler = bound_handler(design)

    handler.create_flange("Panel", edge_index=0, height=2.5)

    created = design.rootComponent.features.flangeFeatures.inputs[0]
    assert (created.height.kind, created.height.value) == ("real", 2.5)


def test_a_flange_angle_is_handed_over_as_a_degree_expression(bound_handler):
    """``createByString`` with the unit: a real would be read in radians."""
    design = _flange_design()
    handler = bound_handler(design)

    handler.create_flange("Panel", edge_index=0, angle=60)

    created = design.rootComponent.features.flangeFeatures.inputs[0]
    assert (created.angle.kind, created.angle.value) == ("string", "60 deg")


def test_a_flange_leaves_the_bend_radius_unset_when_none_is_asked_for(bound_handler):
    design = _flange_design()
    handler = bound_handler(design)

    handler.create_flange("Panel", edge_index=0)

    assert design.rootComponent.features.flangeFeatures.inputs[0].bendRadius is None


def test_a_flange_bend_radius_is_handed_over_as_a_real(bound_handler):
    design = _flange_design()
    handler = bound_handler(design)

    handler.create_flange("Panel", edge_index=0, bend_radius=0.4)

    radius = design.rootComponent.features.flangeFeatures.inputs[0].bendRadius
    assert (radius.kind, radius.value) == ("real", 0.4)


def test_a_bend_is_built_on_the_base_body_that_was_named(bound_handler):
    design, _bend_line, _decoy = _bend_design()
    body = design.rootComponent.bRepBodies.item(1)
    handler = bound_handler(design)

    handler.create_bend("Panel", bend_line_sketch="BendLine")

    created = design.rootComponent.features.bendFeatures.inputs[0]
    assert created.baseObject is body


def test_a_bend_takes_the_first_line_of_the_named_sketch(bound_handler):
    """The decoy sketch is first in the root and holds the first line overall."""
    design, bend_line, decoy = _bend_design()
    handler = bound_handler(design)

    handler.create_bend("Panel", bend_line_sketch="BendLine")

    created = design.rootComponent.features.bendFeatures.inputs[0]
    assert created.bendLine is bend_line.lines[0]
    assert created.bendLine is not decoy.lines[0]


def test_a_bend_without_a_bend_line_sketch_is_refused_before_any_feature(
    bound_handler,
):
    design, _bend_line, _decoy = _bend_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.create_bend("Panel")

    assert design.rootComponent.features.bendFeatures.inputs == []


def test_a_bend_angle_is_handed_over_as_a_degree_expression(bound_handler):
    design, _bend_line, _decoy = _bend_design()
    handler = bound_handler(design)

    handler.create_bend("Panel", bend_line_sketch="BendLine", angle=45)

    angle = design.rootComponent.features.bendFeatures.inputs[0].bendAngle
    assert (angle.kind, angle.value) == ("string", "45 deg")


def test_the_default_bend_angle_is_ninety_degrees(bound_handler):
    design, _bend_line, _decoy = _bend_design()
    handler = bound_handler(design)

    out = handler.create_bend("Panel", bend_line_sketch="BendLine")

    angle = design.rootComponent.features.bendFeatures.inputs[0].bendAngle
    assert (angle.value, out["angle"]) == ("90 deg", 90)


def test_a_bend_leaves_the_bend_radius_unset_when_none_is_asked_for(bound_handler):
    design, _bend_line, _decoy = _bend_design()
    handler = bound_handler(design)

    handler.create_bend("Panel", bend_line_sketch="BendLine")

    assert design.rootComponent.features.bendFeatures.inputs[0].bendRadius is None


def test_a_bend_radius_is_handed_over_as_a_real(bound_handler):
    design, _bend_line, _decoy = _bend_design()
    handler = bound_handler(design)

    handler.create_bend("Panel", bend_line_sketch="BendLine", bend_radius=0.25)

    radius = design.rootComponent.features.bendFeatures.inputs[0].bendRadius
    assert (radius.kind, radius.value) == ("real", 0.25)


def _sheet_metal_design() -> tuple[FakeDesign, FakeBody, list[FakeFace]]:
    """A strip whose **first** face is a bend wall, not a flat one.

    The decoy body is first in the root, and the faces are ordered so nothing but
    the planar test can pick the stationary face: index 0 is cylindrical, so a scan
    that took the first face, or a handler that passed the collection it built,
    hands over the wrong entity.  Faces 1 and 2 are the two flat faces this body
    has, and the bend tests ask for index 2 **before** index 0, so a collection
    that kept the body's order, or sorted the indices, is caught.
    """
    faces = [FakeFace(planar=False), FakeFace(planar=True), FakeFace(planar=True)]
    body = FakeBody("Bracket", faces=FakeCollection(faces))
    return FakeDesign(bodies=[FakeBody("DecoyBody"), body]), body, faces


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
    """The refusal happens before anything is handed to Fusion."""
    faces = FakeCollection([FakeFace(planar=False), FakeFace(planar=False)])
    design = FakeDesign(
        bodies=[FakeBody("DecoyBody"), FakeBody("Tube", faces=faces)],
    )
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.unfold("Tube")

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
