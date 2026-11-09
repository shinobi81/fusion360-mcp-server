"""``create_hole``, driven through the handler instead of read from its source.

These claims used to be ``ast`` scans of ``create_hole``'s body, and they were
scans because the fake runtime had no hole-feature model: nothing could call the
method at all.  It has one now, so each claim is checked by running the handler
and reading what Fusion was handed, which is the difference between "the call
site looks right" and "the hole lands where it was asked for".

The defects behind each claim shipped at least once, so every one of them is
pinned by a mutation as well: halving the diameter, dropping the conversion,
leaving ``participantBodies`` unset, re-deriving a result from ``Feature.bodies``,
ranking faces on the representative point, and skipping the planar-face test each
make exactly one of these fail.  The planar one is new here - the scans never
covered it, because a source scan can see the cast but not which face wins.
"""

from __future__ import annotations

import math

import pytest

from tests.fakes.bodies import FakeBody, FakeBoundingBox, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakePlane

#: Inside ``create_hole``'s horizontal tolerance (~0.6 degrees), and enough that
#: a 100 cm face's extremes differ from its centre by nearly half a centimetre.
TILT = math.radians(0.5)


def _plate() -> FakeDesign:
    """A 10 x 10 x 2 plate: a top face, a bottom one, and nothing else."""
    top = FakeFace(
        normal=(0.0, 0.0, 1.0),
        bounding_box=FakeBoundingBox((0.0, 0.0, 2.0), (10.0, 10.0, 2.0)),
    )
    bottom = FakeFace(
        normal=(0.0, 0.0, -1.0),
        bounding_box=FakeBoundingBox((0.0, 0.0, 0.0), (10.0, 10.0, 0.0)),
    )
    body = FakeBody("Plate", faces=FakeCollection([top, bottom]))
    return FakeDesign(bodies=[body])


def _design_with_faces(*faces: FakeFace, name: str = "Shoe") -> FakeDesign:
    """A one-body design whose faces are iterated **in the order given**.

    Order is the whole point: Fusion's face order is arbitrary, so a test that
    lists the right answer first cannot tell a real ranking from a first match.
    """
    return FakeDesign(bodies=[FakeBody(name, faces=FakeCollection(list(faces)))])


def _tilted_face(centre_z: float = 5.0) -> FakeFace:
    """A 100 x 10 face tilted 0.5 degrees about Y, with a plane that matches it.

    Its box spans *z* = centre +/- 0.436, so the face's own extremes and its centre
    differ in *z* by a measurable amount - which is where ``pointOnFace`` stops
    being the same thing as the face's high point, and stops being the same thing
    as the plane's *z* above an arbitrary (x, y).
    """
    drop = 50.0 * math.tan(TILT)
    return FakeFace(
        normal=(math.sin(TILT), 0.0, math.cos(TILT)),
        bounding_box=FakeBoundingBox(
            (0.0, 0.0, centre_z - drop), (100.0, 10.0, centre_z + drop)
        ),
        point_on_face=(50.0, 5.0, centre_z),
        area=1000.0,
    )


def _flat_face(size: float = 10.0, z: float = 2.0, area: float = 100.0) -> FakeFace:
    """An exactly horizontal square face at *z*."""
    return FakeFace(
        normal=(0.0, 0.0, 1.0),
        bounding_box=FakeBoundingBox((0.0, 0.0, z), (size, size, z)),
        area=area,
    )


def test_the_requested_diameter_reaches_fusion_unmodified(bound_handler):
    """``createSimpleInput()`` takes the diameter, not the radius.

    Halving it here produced holes at half the requested size, which is the
    reason this claim exists at all.  The response's ``actual_diameter`` is read
    off the feature the fake built *from this same* ``ValueInput``, so asserting
    it here would only re-state the line above; the call site is the claim.
    """
    design = _plate()
    handler = bound_handler(design)

    handler.create_hole(diameter=1.2, depth=0.5, body_name="Plate")

    hole_input = design.rootComponent.features.holeFeatures.last_input
    assert hole_input is not None, "no hole input was created"
    assert hole_input.diameter.value == pytest.approx(1.2)


def test_the_hole_is_limited_to_the_body_it_was_asked_for(bound_handler):
    """``participantBodies`` unset (or empty) cuts every body the hole reaches.

    The defect this pins: ``create_hole`` on a two-body design cut both of them,
    because an empty ``participantBodies`` means "all of them" to Fusion, not
    "none".
    """
    design = _plate()
    design.rootComponent.bRepBodies.add_existing(
        FakeBody("Base", faces=FakeCollection([FakeFace()]))
    )
    handler = bound_handler(design)

    handler.create_hole(diameter=1.0, depth=0.5, body_name="Plate")

    feature = design.rootComponent.features.holeFeatures.item(0)
    assert feature.cut_body_names == ["Plate"], (
        "the hole must reach the named body and no other"
    )


def test_the_response_is_not_derived_from_feature_bodies(bound_handler):
    """``Feature.bodies`` echoes the participants, so it is not a result.

    Measured on 2706: a cut naming a body it never reaches still lists that body,
    so ``cut_bodies`` - the field ``#44`` removed - was the input dressed up as an
    answer.  The fake keeps ``bodies`` doing exactly that.  The response's key set
    is locked deliberately: a new field means asking whether it derives from
    ``bodies``, and the value check below pins that ``feature_name`` comes from the
    feature rather than from the body it named.
    """
    design = _plate()
    handler = bound_handler(design)

    result = handler.create_hole(diameter=1.0, depth=0.5, body_name="Plate")

    assert set(result) == {
        "feature_name",
        "diameter",
        "depth",
        "actual_diameter",
        "resolved_center",
    }
    assert result["feature_name"] == "Hole1", (
        "the feature's own name, not a participant's"
    )


def test_the_hole_centre_lands_on_the_face_where_the_caller_asked(bound_handler):
    """The centre is converted into the face's sketch frame, and solved onto it.

    Two defects in one claim, both of which shipped.  Feeding model XY straight
    into the sketch's own coordinates put the hole somewhere else entirely (the
    0.4.x conversion bug); reading *z* off ``pointOnFace`` instead of solving the
    plane put it off a tilted face.  A tilted face makes both visible: the sketch
    point, mapped back to model space, must sit at the requested x and y *and* on
    the face's own plane - neither holds by accident.
    """
    face = _tilted_face()
    design = _design_with_faces(face)
    handler = bound_handler(design)

    result = handler.create_hole(
        diameter=1.0, depth=0.5, body_name="Shoe", center_x=3.0, center_y=4.0
    )

    sketch = design.rootComponent.sketches.item(0)
    assert sketch.supportingPlane is face, "the sketch belongs on the picked face"
    hole_input = design.rootComponent.features.holeFeatures.last_input
    assert hole_input is not None, "no hole input was created"
    assert hole_input.position is not None, "the hole was never positioned"
    placed = sketch.sketchToModelSpace(hole_input.position.geometry)

    assert (placed.x, placed.y) == pytest.approx((3.0, 4.0))
    plane = face.geometry
    assert isinstance(plane, FakePlane), "a planar face's surface is a Plane"
    normal = plane.normal
    offset = (
        placed.x - face.pointOnFace.x,
        placed.y - face.pointOnFace.y,
        placed.z - face.pointOnFace.z,
    )
    assert offset[0] * normal.x + offset[1] * normal.y + offset[2] * normal.z == (
        pytest.approx(0.0, abs=1e-9)
    ), "the centre must lie on the face's plane, not above the representative point"
    assert result["resolved_center"] == pytest.approx([3.0, 4.0, placed.z])


def test_the_top_face_is_chosen_by_its_own_highest_point(bound_handler):
    """A face's representative point is not its high point; rank on the latter.

    Two near-horizontal faces, both inside the tolerance: a flat pad whose centre
    sits at *z* = 5.0, and a wide slanted flange whose centre is lower (4.6) but
    whose own top edge reaches 5.04.  "Top" is the flange - ranking on the
    representative point drilled the hole into the pad instead.

    The pad comes **first** in the face list on purpose: Fusion's face order is
    arbitrary, so a handler that simply took the first horizontal face would
    otherwise pass this test.
    """
    flange = _tilted_face(centre_z=4.6)
    pad = _flat_face(z=5.0)
    design = _design_with_faces(pad, flange)
    handler = bound_handler(design)

    handler.create_hole(diameter=1.0, depth=0.5, body_name="Shoe")

    sketch = design.rootComponent.sketches.item(0)
    assert sketch.supportingPlane is flange, (
        "the flange's own top edge is above the pad, so the flange is the top face"
    )


def test_a_curved_face_is_never_mistaken_for_the_top(bound_handler):
    """Only a *planar* face can host a hole; ``Plane.cast`` is what skips the rest.

    A crowned top reaches higher than the flat face beside it, and its outward
    normal at the crown can be straight up, so the surface type is the only thing
    that tells them apart - Fusion refuses a hole on a curved face, which is why
    the handler casts before ranking.  The crown is listed first *and* is higher,
    so every way of forgetting the cast (skip the check, rank it, take it first)
    picks it and fails here.
    """
    crown = FakeFace(
        normal=(0.0, 0.0, 1.0),
        bounding_box=FakeBoundingBox((0.0, 0.0, 2.0), (10.0, 10.0, 3.0)),
        planar=False,
    )
    flat = _flat_face()
    design = _design_with_faces(crown, flat)
    handler = bound_handler(design)

    handler.create_hole(diameter=1.0, depth=0.5, body_name="Shoe")

    sketch = design.rootComponent.sketches.item(0)
    assert sketch.supportingPlane is flat
