"""Sheet metal: ``flat_pattern`` and ``unfold``.

Each command resolves a name to an entity and then fills a feature input, so the
tests assert exactly that: which body, which face, and which of the input's
properties the call site writes.  Each test carries one claim, and each puts a
decoy in every collection the handler searches — a second body in the root, a
non-planar face before the flat ones — so a lookup that took the first item would
hand over the wrong entity and fail.

The unfold input's names are the shipped ones: ``stationaryFace``, ``bendFaces``
and ``isUnfoldAllBends`` (``UnfoldFeatureInput.h:46-62``), which is why a call
site that set a name Fusion does not ship would leave them at their defaults and
fail here.  ``feature_name`` is the fake's own numbering; nothing here claims
what Fusion names a feature, nor whether a flat pattern or an unfold is
geometrically possible on the body it was given — that needs the geometry, which
these fakes do not carry.

``create_flange`` and ``create_bend`` have no fakes and no tests: the shipped
``FlangeFeatures`` exposes no ``createInput``, and ``root.features.bendFeatures``
does not exist, so both commands raise ``AttributeError`` on every call that
reaches the feature collection (``create_bend`` refuses a missing
``bend_line_sketch`` first, and that argument is optional).  Tests against a fake
named after a missing API would be green fiction.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign


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
