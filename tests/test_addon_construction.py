"""Construction geometry: planes, axes, UCSs, rigid groups, and the sketch pair.

``create_construction_plane``, ``create_construction_axis``, ``create_ucs``,
``create_component``, ``create_rigid_group``, ``create_sketch``, ``auto_constrain``
and ``offset_curve`` were each executed by fewer than half their statements: the
only tests that reached them asserted the *parameter* refusal ahead of the call.
These tests pin the call — the definition a plane was built from, the anchor a UCS
was placed on, the option an auto-constrain was asked for — because that is what a
wrong argument would change while still returning ``ok: true``.

Two of the fakes are the *sketch* pair the brief named, and both declare the arity
of the handler's call site, which is Fusion's: ``Sketch.offset(entities, direction,
distance)`` (three arguments, an ``ObjectCollection`` first) and the AutoConstrain
input/result pair, whose ``autoConstrain`` may answer ``None`` for a sketch Fusion
will not adjust.  The construction surface these tests also need - the plane and
axis inputs, the UCS input, ``rigidGroups``, ``userCoordinateSystems`` - is new in
``tests/fakes/design.py`` too, and every default *name* it invents ("Construction
Plane1", "UCS1", "Rigid Group1") is the fake's: no test here pins one as Fusion's.
"""

from __future__ import annotations

import math

import pytest

from addon.server import hints as addon_hints
from tests.fakes.bodies import FakeBody, FakeFace, body_with_edges
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence
from tests.fakes.runtime import CONE_SURFACE_TYPE, FakePoint3D
from tests.fakes.sketch import FakeAutoConstrainResult, FakeSketch


def _four_curve_sketch(name: str = "Sketch1") -> FakeSketch:
    """A sketch holding four real line objects, which the handler indexes."""
    sketch = FakeSketch(name=name)
    for row in range(4):
        sketch.sketchCurves.sketchLines.addByTwoPoints(
            FakePoint3D(0.0, float(row), 0.0), FakePoint3D(1.0, float(row), 0.0)
        )
    # Setup, not subject: the assertions read what the *handler* recorded.
    sketch.curve_calls.clear()
    return sketch


def _coords(point) -> tuple[float, float, float]:
    return (point.x, point.y, point.z)


# ── construction planes ───────────────────────────────────────────────


def test_create_construction_plane_by_offset_records_the_plane_and_the_distance(
    bound_handler,
):
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_construction_plane(method="offset", plane="xy", offset=2.5)

    created = root.constructionPlanes.last_input
    assert created.setter == "setByOffset"
    plane, distance = created.args
    assert plane is root.xYConstructionPlane
    assert (distance.kind, distance.value) == ("real", 2.5), (
        "an offset is a distance in cm, so it is created by real value"
    )
    assert out == {"created": True, "name": "Construction Plane1", "method": "offset"}


def test_create_construction_plane_by_angle_measures_from_the_axis_and_the_plane(
    bound_handler,
):
    """``edge_name`` defaults to the model X axis; the angle is a string in deg."""
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    handler.create_construction_plane(method="angle", plane="yz", angle=30)

    axis, angle, plane = root.constructionPlanes.last_input.args
    assert axis is root.xConstructionAxis
    assert (angle.kind, angle.value) == ("string", "30 deg"), (
        "the angle carries its unit, so Fusion parses it rather than reading radians"
    )
    assert plane is root.yZConstructionPlane


def test_a_construction_plane_and_its_axis_take_the_same_letter_case(bound_handler):
    """``_construction_plane`` lowercased its argument and the axis did not.

    So ``"X"`` was refused for an axis and accepted for a plane; both lookups
    lowercase now, as this call - which needs one of each - shows.
    """
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    handler.create_construction_plane(
        method="angle", plane="XZ", angle=30, edge_name="X"
    )

    axis, _, plane = root.constructionPlanes.last_input.args
    assert axis is root.xConstructionAxis
    assert plane is root.xZConstructionPlane


def test_create_construction_plane_by_midplane_sits_between_the_two_planes(
    bound_handler,
):
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    handler.create_construction_plane(method="midplane", plane_one="xy", plane_two="xz")

    created = root.constructionPlanes.last_input
    assert created.setter == "setByTwoPlanes"
    assert created.args == (root.xYConstructionPlane, root.xZConstructionPlane)


def test_create_construction_plane_by_three_points_passes_the_points_in_order(
    bound_handler,
):
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    handler.create_construction_plane(
        method="three_points",
        point_one=[0, 0, 0],
        point_two=[4, 0, 0],
        point_three=[0, 3, 0],
    )

    created = root.constructionPlanes.last_input
    assert created.setter == "setByThreePoints"
    assert [_coords(point) for point in created.args] == [
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        (0.0, 3.0, 0.0),
    ]


def test_create_construction_plane_needs_a_reference_or_an_offset(bound_handler):
    """``method="offset"`` with no plane has nothing to offset from.

    The refusal names the planes the tool takes and creates nothing.  It is
    ``INVALID_INPUT``: the argument is what has to change, and the hint says the
    value is lowercased, so ``XZ`` would have worked.
    """
    design = FakeDesign(features=2)
    root = design.rootComponent

    with pytest.raises(RuntimeError, match="Unknown plane") as raised:
        bound_handler(design).create_construction_plane(method="offset", offset=2.5)

    assert addon_hints.classify(raised.value) == (
        "INVALID_INPUT",
        ["Pass xy, yz or xz; the plane is lowercased, so XZ works."],
    )
    assert root.constructionPlanes.count == 0, "no plane was created"


def test_an_unknown_construction_axis_names_the_axis_it_takes(bound_handler):
    """``method="angle"`` resolves its edge name as an axis; ``w`` is not one."""
    design = FakeDesign(features=2)
    root = design.rootComponent

    with pytest.raises(RuntimeError, match="Unknown axis") as raised:
        bound_handler(design).create_construction_plane(
            method="angle", plane="xy", angle=30, edge_name="w"
        )

    assert addon_hints.classify(raised.value) == (
        "INVALID_INPUT",
        ["Pass x, y or z; the axis is lowercased, so Y works."],
    )
    assert root.constructionPlanes.count == 0


def test_three_points_with_a_missing_point_names_that_point(bound_handler):
    """The label is the parameter's name, and each point is judged in place.

    ``point_one`` is complete and ``point_two`` is not, so the refusal names the
    second: unpacking the short list into ``Point3D.create`` said nothing a caller
    could act on.
    """
    design = FakeDesign(features=2)
    root = design.rootComponent

    with pytest.raises(RuntimeError, match="point_two must be") as raised:
        bound_handler(design).create_construction_plane(
            method="three_points",
            point_one=[0, 0, 0],
            point_two=[4, 0],
            point_three=[0, 3, 0],
        )

    assert addon_hints.classify(raised.value) == (
        "INVALID_INPUT",
        ["Pass three numbers, in centimetres: [x, y, z]."],
    )
    assert root.constructionPlanes.count == 0


def test_a_point_that_is_not_a_list_is_refused_rather_than_raising(bound_handler):
    """``len()`` of a number is a TypeError, which reached the caller as UNKNOWN.

    The shape is judged before the length for that reason: a bare ``3`` is not a
    three-coordinate point, and neither is a string that happens to be three
    characters long.
    """
    design = FakeDesign(features=2)

    with pytest.raises(RuntimeError, match="point_one must be") as raised:
        bound_handler(design).create_construction_plane(
            method="three_points",
            point_one=3,
            point_two=[4, 0, 0],
            point_three=[0, 3, 0],
        )

    assert addon_hints.classify(raised.value)[0] == "INVALID_INPUT"
    assert design.rootComponent.constructionPlanes.count == 0


def test_a_tangent_plane_at_an_angle_takes_the_face_and_the_reference_plane(
    bound_handler,
):
    """``setByTangent(face, angle, planarEntity)``, the stub's three arguments.

    The angle carries its unit, as the ``angle`` method's does, and the reference is
    the plane the caller named; ``plane`` is required for this form because an angle
    is measured from something.
    """
    body = FakeBody(
        name="Shaft",
        faces=FakeCollection([FakeFace(), FakeFace(planar=False, radius=1.0)]),
    )
    design = FakeDesign(features=2, bodies=[body])
    root = design.rootComponent
    handler = bound_handler(design)

    result = handler.create_construction_plane(
        method="tangent",
        body_name="Shaft",
        face_index=1,
        plane="xz",
        angle=45,
    )

    assert result == {
        "created": True,
        "name": "Construction Plane1",
        "method": "tangent",
    }
    created = root.constructionPlanes.last_input
    assert created.setter == "setByTangent"
    face, angle, reference = created.args
    assert face is body.faces.item(1), "the face the index named, not the first one"
    assert (angle.kind, angle.value) == ("string", "45 deg")
    assert reference is root.xZConstructionPlane


def test_a_tangent_plane_through_a_point_takes_the_face_and_the_point(bound_handler):
    """``setByTangentAtPoint(face, point)``: the point wins when it is given.

    The point need not lie on the face - Fusion's own docstring says so - which is why
    this form takes no reference plane and no angle.
    """
    body = FakeBody(
        name="Shaft",
        faces=FakeCollection([FakeFace(), FakeFace(planar=False, radius=1.0)]),
    )
    design = FakeDesign(features=2, bodies=[body])
    root = design.rootComponent
    handler = bound_handler(design)

    result = handler.create_construction_plane(
        method="tangent",
        body_name="Shaft",
        face_index=1,
        point_one=[1.0, 2.0, 3.0],
    )

    assert result["method"] == "tangent"
    created = root.constructionPlanes.last_input
    assert created.setter == "setByTangentAtPoint"
    face, point = created.args
    assert face is body.faces.item(1)
    assert _coords(point) == (1.0, 2.0, 3.0)


def test_a_tangent_plane_refuses_a_reference_plane_perpendicular_to_the_axis(
    bound_handler,
):
    """Measured on 2706.1.17: Fusion refuses `add` with an InternalValidationError.

    The angle is measured *around* the face's axis, so the reference plane has to
    contain that axis. On a Z cylinder `plane="xy"` is perpendicular to it and the
    add fails with `2 : InternalValidationError : data_->execute(&obj, apiName)` -
    a sentence that names neither the argument nor the fix. `yz` and `xz` succeed,
    at angle 0 and at 45, and the planes differ, so the angle is honoured.
    """
    body = FakeBody(
        name="Shaft",
        faces=FakeCollection([FakeFace(planar=False, radius=1.0)]),
    )
    design = FakeDesign(features=2, bodies=[body])

    with pytest.raises(RuntimeError) as raised:
        bound_handler(design).create_construction_plane(
            method="tangent", body_name="Shaft", face_index=0, plane="xy", angle=45
        )

    refusal = raised.value
    assert addon_hints.classify(refusal)[0] == "INVALID_INPUT"
    assert "perpendicular to the face's axis" in str(refusal)
    assert any("contains the axis" in hint for hint in refusal.hints)
    assert design.rootComponent.constructionPlanes.count == 0


def test_a_tangent_plane_measures_from_a_reference_that_contains_the_axis(
    bound_handler,
):
    """`xz` on a Z cylinder: allowed, and nothing about the call changes."""
    body = FakeBody(
        name="Shaft",
        faces=FakeCollection([FakeFace(planar=False, radius=1.0)]),
    )
    design = FakeDesign(features=2, bodies=[body])

    bound_handler(design).create_construction_plane(
        method="tangent", body_name="Shaft", face_index=0, plane="xz", angle=45
    )

    created = design.rootComponent.constructionPlanes.last_input
    assert created.setter == "setByTangent"
    assert created.args[2] is design.rootComponent.xZConstructionPlane


def test_a_tangent_plane_refuses_a_face_it_cannot_be_tangent_to(bound_handler):
    """``setByTangent`` documents a cylindrical or conical face; a flat one is neither.

    The refusal names the face's own surface type and sends the caller to
    ``list_faces``, and nothing is created: the check runs before the add.
    """
    body = FakeBody(name="Plate", faces=FakeCollection([FakeFace()]))
    design = FakeDesign(features=2, bodies=[body])

    with pytest.raises(RuntimeError) as raised:
        bound_handler(design).create_construction_plane(
            method="tangent", body_name="Plate", face_index=0, plane="xy"
        )

    refusal = raised.value
    assert addon_hints.classify(refusal)[0] == "GEOMETRY_UNSUPPORTED"
    assert "Plane" in str(refusal), "the sentence names what the face is"
    assert design.rootComponent.constructionPlanes.count == 0


def test_a_tangent_plane_on_a_conical_face_is_built(bound_handler):
    """The docstring's other accepted surface type: a cone, not only a cylinder."""
    cone = FakeFace(planar=False, radius=1.0)
    cone.geometry.surfaceType = CONE_SURFACE_TYPE
    body = FakeBody(name="Cone", faces=FakeCollection([cone]))
    design = FakeDesign(features=2, bodies=[body])

    bound_handler(design).create_construction_plane(
        method="tangent", body_name="Cone", face_index=0, plane="xz"
    )

    assert design.rootComponent.constructionPlanes.last_input.setter == "setByTangent"


# An unknown method no longer reaches the add-in: the schema gate refuses a value
# outside the tool's enum before either mode sees it.  ``test_schema_gate.py`` owns
# that assertion now.


# ── construction axes ────────────────────────────────────────────────


def test_create_construction_axis_from_two_points(bound_handler):
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_construction_axis(
        "two_points", point_one=[0, 0, 0], point_two=[0, 0, 5]
    )

    created = root.constructionAxes.last_input
    assert created.setter == "setByTwoPoints"
    assert [_coords(point) for point in created.args] == [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 5.0),
    ]
    assert out == {
        "created": True,
        "name": "Construction Axis1",
        "method": "two_points",
    }


def test_create_construction_axis_where_two_planes_meet(bound_handler):
    design = FakeDesign(features=2)
    root = design.rootComponent
    handler = bound_handler(design)

    handler.create_construction_axis("intersection", plane_one="xy", plane_two="yz")

    created = root.constructionAxes.last_input
    assert created.setter == "setByTwoPlanes"
    assert created.args == (root.xYConstructionPlane, root.yZConstructionPlane)


def test_create_construction_axis_perpendicular_at_a_point(bound_handler):
    """The axis is normal to a face at a point, named by body and face index.

    Until `face_index` existed the shipped setter had no face to take, so the method
    was advertised and refused outright. The setter's two arguments are the stub's.
    """
    body = FakeBody(name="Plate", faces=FakeCollection([FakeFace(), FakeFace()]))
    design = FakeDesign(features=2, bodies=[body])
    handler = bound_handler(design)

    result = handler.create_construction_axis(
        "perpendicular_at_point",
        body_name="Plate",
        face_index=1,
        point_one=[0.0, 0.0, 1.0],
    )

    assert result == {
        "created": True,
        # The fake's own default name (Fusion's is not measured here).
        "name": "Construction Axis1",
        "method": "perpendicular_at_point",
    }
    built = design.rootComponent.constructionAxes.last_input
    assert built.setter == "setByPerpendicularAtPoint"
    face, point = built.args
    assert face is body.faces.item(1), "the face the index named, not the first one"
    assert (point.x, point.y, point.z) == (0.0, 0.0, 1.0)


def test_create_construction_axis_perpendicular_names_the_missing_argument(
    bound_handler,
):
    """No face index: refused before anything is created, naming the argument.

    The body exists in the fixture, so the refusal cannot come from a body that is not
    there - only the rule's sentence matches.
    """
    design = FakeDesign(features=2, bodies=[FakeBody(name="Plate")])

    with pytest.raises(RuntimeError) as raised:
        bound_handler(design).create_construction_axis(
            "perpendicular_at_point", body_name="Plate", point_one=[1, 2, 3]
        )

    assert str(raised.value) == (
        "perpendicular_at_point needs face_index - it builds an axis normal to a "
        "face at a point"
    )
    assert design.rootComponent.constructionAxes.count == 0


def test_create_construction_axis_perpendicular_refuses_a_face_the_body_lacks(
    bound_handler,
):
    """A wrong index names the range, before the API is asked."""
    body = FakeBody(name="Plate", faces=FakeCollection([FakeFace(), FakeFace()]))
    design = FakeDesign(features=2, bodies=[body])

    with pytest.raises(addon_hints.Refusal) as raised:
        bound_handler(design).create_construction_axis(
            "perpendicular_at_point",
            body_name="Plate",
            face_index=2,
            point_one=[0.0, 0.0, 1.0],
        )

    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == (
        "Face index 2 is out of range for body 'Plate' (2 faces)"
    )
    assert design.rootComponent.constructionAxes.count == 0


def test_create_construction_axis_on_a_body_edge(bound_handler):
    """``method="edge"`` names the edge by body and index, not by coordinates."""
    body = body_with_edges(
        "Plate",
        [
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            ((1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
        ],
    )
    design = FakeDesign(features=2, bodies=[body])
    handler = bound_handler(design)

    handler.create_construction_axis("edge", body_name="Plate", edge_index=1)

    created = design.rootComponent.constructionAxes.last_input
    assert created.setter == "setByEdge"
    assert created.args == (body.edges.item(1),), "the edge the caller named"


# ── user coordinate systems ──────────────────────────────────────────


def test_create_ucs_anchors_it_on_a_hidden_reference_sketch(bound_handler):
    """The UCS API is entity-based, so the handler builds the anchor it needs."""
    design = FakeDesign(features=0)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_ucs(
        name="fixture", x=3, y=4, angle_x=10, angle_y=20, angle_z=30
    )

    assert out == {
        "name": "fixture",
        "origin": [3, 4, 0],
        "angles_deg": [10, 20, 30],
        "reference_sketch": "UCS_fixture_ref",
    }
    reference = root.sketches.item(0)
    assert reference.name == "UCS_fixture_ref", "the UCS stays linked to this sketch"
    assert reference.isVisible is False, "and it is hidden, or it draws on the model"
    assert root.userCoordinateSystems.item(0).name == "fixture"

    ucs_input = root.userCoordinateSystems.last_input
    assert _coords(ucs_input.geometry.point.geometry) == (3.0, 4.0, 0.0), (
        "the anchor is the sketch point at the caller's x, y"
    )
    for axis, degrees in (("X", 10), ("Y", 20), ("Z", 30)):
        written = getattr(ucs_input, f"angle{axis}")
        assert written.kind == "real"
        assert written.value == pytest.approx(math.radians(degrees)), (
            f"Fusion reads angle{axis} in radians; degrees would be ~57x off"
        )


def test_create_ucs_leaves_the_angles_the_caller_left_out_unset(bound_handler):
    """An angle that was not asked for is not written, so Fusion keeps its own.

    ``UCS1`` is the fake's own default name; what the test pins is that the reply
    reports the UCS's name rather than the caller's missing one, and that a
    reference sketch is still labelled.
    """
    design = FakeDesign(features=0)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_ucs(x=1)

    assert out["name"] == "UCS1"
    assert out["reference_sketch"] == "UCS_unnamed_ref"
    assert design.rootComponent.sketches.item(0).name == "UCS_unnamed_ref"
    ucs_input = root.userCoordinateSystems.last_input
    assert (ucs_input.angleX, ucs_input.angleY, ucs_input.angleZ) == (
        None,
        None,
        None,
    ), "an angle the caller left out is not written at all"


def test_a_ucs_at_a_height_sketches_on_an_offset_plane(bound_handler):
    """``z`` cannot go into the anchor point: the sketch has to lie on a plane."""
    design = FakeDesign(features=0)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_ucs(name="high", z=2.0)

    assert out["origin"] == [0, 0, 2]
    planes = root.constructionPlanes
    assert planes.count == 1, "the height needs a plane; x/y/z alone do not"
    plane, distance = planes.last_input.args
    assert plane is root.xYConstructionPlane
    assert distance.value == 2.0
    assert root.sketches.item(0).supportingPlane is planes.item(0)


# ── occurrences and rigid groups ─────────────────────────────────────


def test_create_component_places_it_under_the_root(bound_handler):
    design = FakeDesign(features=0)
    handler = bound_handler(design)

    assert handler.create_component("Bracket") == {"created": True, "name": "Bracket"}

    occurrences = design.rootComponent.occurrences
    assert occurrences.count == 1
    assert occurrences.item(0).component.name == "Bracket"


def test_create_component_under_a_named_parent_places_it_there(bound_handler):
    design = FakeDesign(features=0)
    root = design.rootComponent
    root.occurrences.add(FakeOccurrence(FakeComponent("Assy")))
    handler = bound_handler(design)

    handler.create_component("Bolt", parent_name="Assy")

    parent = root.occurrences.item(0).component
    assert parent.occurrences.count == 1
    assert parent.occurrences.item(0).component.name == "Bolt"
    assert root.occurrences.count == 1, "the new component is not also at the root"


@pytest.mark.parametrize("include_children", [True, False])
def test_create_rigid_group_records_every_occurrence_it_was_given(
    bound_handler, include_children
):
    design = FakeDesign(features=0)
    left = FakeOccurrence(FakeComponent("Left"))
    right = FakeOccurrence(FakeComponent("Right"))
    design.rootComponent.occurrences.add(left)
    design.rootComponent.occurrences.add(right)

    out = bound_handler(design).create_rigid_group(
        ["Left", "Right"], include_children=include_children
    )

    assert out == {"created": True, "component_count": 2}
    group = design.rootComponent.rigidGroups.added[0]
    assert group.occurrences == [left, right], "the occurrences the caller named"
    assert group.includeChildren is include_children


def test_create_rigid_group_of_one_component_is_refused(bound_handler):
    """A group of one holds nothing together; the fake would build it if asked."""
    design = FakeDesign(features=0)
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("Solo")))
    handler = bound_handler(design)

    with pytest.raises(RuntimeError, match="at least 2 components"):
        handler.create_rigid_group(["Solo"])

    assert design.rootComponent.rigidGroups.count == 0


# ── sketches: create, offset, auto-constrain ─────────────────────────


def test_create_sketch_on_a_named_plane(bound_handler):
    design = FakeDesign(features=0)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_sketch("yz")

    assert out == {"sketch_name": "Sketch1", "plane": "yz", "z_offset": None}
    assert root.sketches.item(0).supportingPlane is root.yZConstructionPlane
    assert root.constructionPlanes.count == 0, "no offset, so no plane to build"


def test_create_sketch_at_an_offset_creates_the_plane_it_sits_on(bound_handler):
    design = FakeDesign(features=0)
    root = design.rootComponent
    handler = bound_handler(design)

    out = handler.create_sketch("xy", z_offset=-0.65)

    assert out == {"sketch_name": "Sketch1", "plane": "xy", "z_offset": -0.65}
    plane, distance = root.constructionPlanes.last_input.args
    assert plane is root.xYConstructionPlane
    assert (distance.kind, distance.value) == ("real", -0.65)
    assert root.sketches.item(0).supportingPlane is root.constructionPlanes.item(0), (
        "the sketch sits on the plane the offset created, not on the base one"
    )


def test_offset_curve_measures_from_the_curve_it_names(bound_handler):
    """``Sketch.offset`` takes the entities, a direction point and the distance."""
    sketch = _four_curve_sketch()
    handler = bound_handler(FakeDesign(features=0, sketches=[sketch]))

    out = handler.offset_curve(
        curve_index=2, offset_distance=0.5, direction_x=0, direction_y=1
    )

    entities, direction, distance = sketch.offset_calls[0]
    assert entities.items == [list(sketch.sketchCurves)[2]], (
        "the curve the caller named, wrapped in a collection"
    )
    assert _coords(direction) == (0.0, 1.0, 0.0), (
        "the direction the caller gave, in the axis it named"
    )
    assert distance == 0.5
    assert out == {"sketch": "Sketch1", "offset_distance": 0.5}


def test_auto_constrain_reports_the_count_fusion_returned(bound_handler):
    sketch = FakeSketch(name="Sketch1")
    sketch.auto_constrain_result = FakeAutoConstrainResult(
        is_fully_constrained=True, constraints=3, dimensions=1, moved=0
    )
    handler = bound_handler(FakeDesign(features=0, sketches=[sketch]))

    out = handler.auto_constrain()

    assert out == {
        "sketch": "Sketch1",
        "is_fully_constrained": True,
        "constraints_added": 3,
        "dimensions_added": 1,
        "entities_moved": 0,
        "result_option": 1,
    }


@pytest.mark.parametrize(
    ("option", "result_option"),
    [
        (1, "Option1AutoConstrainResultType"),
        (2, "Option2AutoConstrainResultType"),
        (3, "Option3AutoConstrainResultType"),
    ],
)
def test_auto_constrain_asks_fusion_for_the_option_the_caller_named(
    bound_handler, option, result_option
):
    sketch = FakeSketch(name="Sketch1")
    handler = bound_handler(FakeDesign(features=0, sketches=[sketch]))

    handler.auto_constrain(result_option=option)

    assert sketch.auto_constrain_inputs[0].resultOption == result_option


def test_auto_constrain_that_fusion_declines_to_run_is_refused(bound_handler):
    """Fusion answers ``None`` for a sketch it will not adjust; that is a refusal.

    The handler turns it into an error rather than reporting zero constraints and
    zero dimensions, which would read as "your sketch needed nothing".  Fusion
    declined to run, so the kind is ``FUSION_REFUSED`` and the hint names the two
    options that still work.
    """
    sketch = FakeSketch(name="Sketch1")
    sketch.auto_constrain_results["Option3AutoConstrainResultType"] = None
    handler = bound_handler(FakeDesign(features=0, sketches=[sketch]))

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.auto_constrain(result_option=3)

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert str(raised.value) == (
        "autoConstrain returned no result — the sketch is not eligible for "
        "geometry adjustment. Retry with result_option 1 or 2."
    )
    assert raised.value.hints == ("Retry auto_constrain with result_option 1 or 2.",)
    assert sketch.auto_constrain_inputs, "Fusion was asked before it declined"
