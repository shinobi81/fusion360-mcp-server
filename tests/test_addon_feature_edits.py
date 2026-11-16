"""A mirror, the two patterns, the five edit features and the parametric box.

Every one of these handlers builds one input object from the arguments, `add` it,
and report `feat.name` plus numbers taken from those same arguments.  So the
assertions here are on the input the fake records - which body, which faces, which
plane, which transform - because that is the only part of the call Fusion's own
answer would depend on.  Where a reply repeats the request the test says so; a
reply field is never read as a measurement of what Fusion built.

Provenance: ``FakeMirrorFeatures.add`` models one copied body per input body, and
``FakeExtrudeFeatures.add`` one created body; both counts are the *fake's* model of
what the feature does, not something measured in Fusion.  Nothing else here is
geometry: a split, an offset, a scale and a move all record their request and
leave the shapes alone, because how far geometry moves is not something a count
could report honestly.
"""

from __future__ import annotations

import json

import pytest

from fusion360_mcp.hints import classify
from tests.fakes.bodies import FakeBody, FakeBoundingBox, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakeMatrix3D, FakeValueInput


@pytest.fixture
def handler(bound_handler):
    """Two bodies, so a name-blind pick takes "Base" instead of "Bracket"."""
    return bound_handler(FakeDesign(bodies=[FakeBody("Base"), FakeBody("Bracket")]))


def test_mirror_across_the_xy_plane_adds_one_body(handler):
    """One body in, one body out, across the plane the caller named."""
    root = handler._root()
    bodies_before = root.bRepBodies.count

    result = handler.mirror("xy", body_name="Bracket")

    mirrored = root.features.mirrorFeatures.added[0]
    assert [body.name for body in mirrored.objects] == ["Bracket"]
    assert mirrored.mirrorPlane is root.xYConstructionPlane
    # The extra body is the fake's model of a mirror, not a Fusion measurement.
    assert root.bRepBodies.count == bodies_before + 1
    assert result["mirror_plane"] == "xy"


def test_mirror_reports_the_feature_fusion_created(handler):
    """Two calls, two different features named - and the second plane is honoured."""
    root = handler._root()
    features = root.features.mirrorFeatures

    first = handler.mirror("xy", body_name="Bracket")
    second = handler.mirror("xz", body_name="Base")

    assert features.added[1].mirrorPlane is root.xZConstructionPlane
    assert first["feature_name"] == features.created[0].name
    assert second["feature_name"] == features.created[1].name
    # Kills a name the handler invented instead of reading `feat.name`.
    assert first["feature_name"] != second["feature_name"]


def test_rectangular_pattern_hands_fusion_both_directions(handler):
    """Two directions reach the input: X and Y, with their own counts and spacings."""
    root = handler._root()

    handler.rectangular_pattern(
        "Bracket", x_count=3, x_spacing=2.5, y_count=2, y_spacing=1.5
    )

    inp = root.features.rectangularPatternFeatures.added[0]
    assert [body.name for body in inp.inputEntities] == ["Bracket"]
    assert inp.directionOne is root.xConstructionAxis
    assert inp.directionTwo is root.yConstructionAxis
    assert (inp.quantityOne.value, inp.quantityTwo.value) == (3, 2)
    assert (inp.distanceOne.value, inp.distanceTwo.value) == (2.5, 1.5)
    assert inp.patternDistanceType == "SpacingPatternDistanceType"


def test_rectangular_pattern_echoes_the_counts_it_asked_for(handler):
    """The reply repeats the request; the only Fusion-backed field is the name."""
    features = handler._root().features.rectangularPatternFeatures

    result = handler.rectangular_pattern(
        "Bracket", x_count=3, x_spacing=2.5, y_count=2, y_spacing=1.5
    )

    assert (result["x_count"], result["y_count"]) == (3, 2)
    assert result["feature_name"] == features.created[0].name


def test_circular_pattern_resolves_the_axis_it_was_named(handler):
    """``axis`` selects a construction axis - X by name, Z by default."""
    root = handler._root()
    features = root.features.circularPatternFeatures

    handler.circular_pattern("Bracket", count=4, axis="x")
    handler.circular_pattern("Bracket", count=4)

    assert [body.name for body in features.added[0].inputEntities] == ["Bracket"]
    assert features.added[0].axis is root.xConstructionAxis
    assert features.added[1].axis is root.zConstructionAxis


def test_circular_pattern_refuses_a_plane_where_an_axis_belongs(handler):
    """A plane name is not an axis: the call fails and no feature is built."""
    features = handler._root().features.circularPatternFeatures

    with pytest.raises(RuntimeError):
        handler.circular_pattern("Bracket", count=4, axis="xy")

    assert features.added == []


def test_circular_pattern_sets_the_quantity_and_a_degree_angle(handler):
    """``quantity`` is a plain number; ``totalAngle`` carries its unit."""
    root = handler._root()

    result = handler.circular_pattern("Bracket", count=6, total_angle=180)

    inp = root.features.circularPatternFeatures.added[0]
    assert isinstance(inp.quantity, FakeValueInput)
    assert (inp.quantity.value, inp.quantity.kind) == (6, "real")
    assert (inp.totalAngle.value, inp.totalAngle.kind) == ("180 deg", "string")
    # The reply is the request repeated, not Fusion's own count.
    assert (result["count"], result["total_angle"]) == (6, 180)


# --- the five edit features and the parametric box -------------------------
#
# None of these six commands could run under a test before: the fake ``features``
# had no ``splitBodyFeatures``, ``splitFaceFeatures``, ``offsetFeatures``,
# ``scaleFeatures`` or ``moveFeatures``, and the sketch fake returned nothing from
# ``addTwoPointRectangle``, which ``create_box_parametric`` indexes.  Each fixture
# below therefore carries a decoy: two bodies, and for the face commands a body
# whose faces sit in three different planes.


def face(z0: float, z1: float, normal=(0.0, 0.0, 1.0)) -> FakeFace:
    """A face spanning *z0*..*z1*: flat when the two are equal, a wall otherwise."""
    return FakeFace(
        normal=normal,
        bounding_box=FakeBoundingBox((-1.0, -1.0, z0), (1.0, 1.0, z1)),
    )


def box_faces() -> list[FakeFace]:
    """A 2 cm plate: a top face, a bottom face, and four walls reaching both."""
    wall = (1.0, 0.0, 0.0)
    return [
        face(2.0, 2.0),  # 0 top
        face(0.0, 0.0),  # 1 bottom
        face(0.0, 2.0, wall),  # 2 wall
        face(0.0, 2.0, wall),  # 3 wall
        face(0.0, 2.0, wall),  # 4 wall
        face(0.0, 2.0, wall),  # 5 wall
    ]


@pytest.fixture
def plate(bound_handler):
    """Two bodies; the second - "Bracket", not the first - is a six-faced plate."""
    bracket = FakeBody("Bracket", faces=FakeCollection(box_faces()))
    return bound_handler(FakeDesign(bodies=[FakeBody("Base"), bracket]))


@pytest.fixture
def box(bound_handler):
    """An empty design: the parametric box draws its own sketch and body."""
    return bound_handler(FakeDesign(bodies=[]))


def rectangle_corners(sketch) -> list[tuple[float, float]]:
    """The two corners ``addTwoPointRectangle`` was handed, in sketch space."""
    (payload,) = [recorded for kind, recorded in sketch.curve_calls if kind == "line"]
    return [(point.x, point.y) for point in payload["points"]]


def test_split_body_splits_the_named_body_with_the_named_plane(plate):
    """The body named and the plane named, as two separate arguments."""
    root = plate._root()

    result = plate.split_body("Bracket", splitting_plane="yz")

    splits = root.features.splitBodyFeatures
    inp = splits.added[0]
    assert inp.body is root.bRepBodies.item(1)
    assert inp.splitTool is root.yZConstructionPlane
    assert inp.isSplittingToolExtended is True
    assert result["feature_name"] == splits.created[0].name


def test_split_body_with_a_tool_body_names_it_instead_of_a_plane(plate):
    """A splitting body replaces the plane, and extend_tool reaches the input."""
    root = plate._root()

    result = plate.split_body("Bracket", splitting_body="Base", extend_tool=False)

    inp = root.features.splitBodyFeatures.added[0]
    assert inp.body is root.bRepBodies.item(1)
    assert inp.splitTool is root.bRepBodies.item(0)
    assert inp.isSplittingToolExtended is False
    assert result["feature_name"] == root.features.splitBodyFeatures.created[0].name


def test_split_face_splits_the_faces_at_the_indices_given(plate):
    """Explicit indices pick those faces, on the plane and the flag asked for."""
    root = plate._root()
    body = root.bRepBodies.item(1)

    plate.split_face(
        "Bracket", face_indices=[1, 3], splitting_plane="xz", extend_tool=False
    )

    inp = root.features.splitFaceFeatures.added[0]
    selected = [inp.faces.item(index) for index in range(inp.faces.count)]
    assert selected == [body.faces.item(1), body.faces.item(3)]
    assert inp.splittingPlane is root.xZConstructionPlane
    assert inp.isSplittingToolExtended is False


def test_split_face_without_indices_splits_every_face_of_the_named_body(plate):
    """The default is every face of *that* body, on the XY plane, extended."""
    root = plate._root()

    plate.split_face("Bracket")

    inp = root.features.splitFaceFeatures.added[0]
    assert list(inp.faces) == list(root.bRepBodies.item(1).faces)
    assert len(list(inp.faces)) == len(box_faces())
    assert inp.splittingPlane is root.xYConstructionPlane
    assert inp.isSplittingToolExtended is True


def test_offset_faces_defaults_to_the_face_in_the_top_plane(plate):
    """``top`` is the one flat face at the top - not the walls that reach it."""
    root = plate._root()

    plate.offset_faces("Bracket", distance=0.5)

    inp = root.features.offsetFeatures.added[0]
    assert list(inp.faces) == [root.bRepBodies.item(1).faces.item(0)]


def test_offset_faces_offsets_by_the_distance_as_a_new_body(plate):
    """The distance is a real, the operation builds a body of its own."""
    root = plate._root()

    result = plate.offset_faces("Bracket", distance=0.25)

    inp = root.features.offsetFeatures.added[0]
    assert isinstance(inp.distance, FakeValueInput)
    assert (inp.distance.value, inp.distance.kind) == (0.25, "real")
    # FeatureOperations.NewBodyFeatureOperation, the member this fake calls
    # "new_body": an offset face never joins back into the body it came from.
    assert inp.operation == "new_body"
    # The reply repeats the request; the name is the one Fusion returned.
    assert result["distance"] == 0.25
    assert result["feature_name"] == root.features.offsetFeatures.created[0].name


def test_offset_faces_takes_the_indices_over_the_selection(plate):
    """Given indices, the selection is not consulted at all."""
    root = plate._root()

    plate.offset_faces(
        "Bracket", distance=0.5, face_selection="vertical", face_indices=[1]
    )

    inp = root.features.offsetFeatures.added[0]
    # "vertical" would have picked the four walls; the index picks the bottom.
    assert list(inp.faces) == [root.bRepBodies.item(1).faces.item(1)]


def test_offset_faces_with_no_face_in_the_top_plane_is_refused(bound_handler):
    """A body found, a selector that matched nothing: INVALID_INPUT, not a body.

    The brief for this task expected BODY_NOT_FOUND here.  That is not what the
    add-in answers: ``_select_faces`` raises "No faces matched selection" before
    any feature is built, and the hints table classifies that as INVALID_INPUT -
    the body was found, it is the *selector* that does not apply to it.
    """
    wall = (1.0, 0.0, 0.0)
    body = FakeBody("Bracket", faces=FakeCollection([face(0.0, 2.0, wall)]))
    handler = bound_handler(FakeDesign(bodies=[FakeBody("Base"), body]))

    with pytest.raises(RuntimeError) as raised:
        handler.offset_faces("Bracket", distance=0.5, face_selection="top")

    assert classify(raised.value)[0] == "INVALID_INPUT"
    assert handler._root().features.offsetFeatures.added == []


def test_scale_body_scales_the_named_body_about_the_anchor(plate):
    """One body, one factor, the anchor the caller named."""
    root = plate._root()

    plate.scale_body("Bracket", scale=2.0, anchor_x=1.0, anchor_y=2.0, anchor_z=3.0)

    inp = root.features.scaleFeatures.added[0]
    assert [body.name for body in inp.inputEntities] == ["Bracket"]
    assert inp.anchorPoint.coords() == (1.0, 2.0, 3.0)
    assert [value.value for value in inp.scales] == [2.0]


def test_scale_body_takes_three_factors_only_when_all_three_are_given(plate):
    """Two of three factors is still the uniform overload, on ``scale``."""
    root = plate._root()

    plate.scale_body("Bracket", scale=1.5, scale_x=2.0, scale_y=3.0)

    inp = root.features.scaleFeatures.added[0]
    assert [value.value for value in inp.scales] == [1.5]


def test_scale_body_scales_each_axis_when_three_factors_are_given(plate):
    """Three factors replace the uniform one, in x, y, z order."""
    root = plate._root()

    plate.scale_body("Bracket", scale=1.0, scale_x=2.0, scale_y=3.0, scale_z=4.0)

    inp = root.features.scaleFeatures.added[0]
    assert [value.value for value in inp.scales] == [2.0, 3.0, 4.0]


def test_move_body_hands_fusion_one_body_and_a_translation(plate):
    """One body and a Matrix3D whose translation is the offset that was asked for."""
    root = plate._root()

    result = plate.move_body("Bracket", x=1.0, y=2.0, z=3.0)

    inp = root.features.moveFeatures.added[0]
    assert [body.name for body in inp.inputEntities] == ["Bracket"]
    assert isinstance(inp.transform, FakeMatrix3D)
    assert inp.transform.translation.coords() == (1.0, 2.0, 3.0)
    assert result["translation"] == [1.0, 2.0, 3.0]
    assert result["feature_name"] == root.features.moveFeatures.created[0].name


def test_create_box_parametric_sketches_on_the_plane_it_was_named(box):
    """``plane`` selects the base construction plane the rectangle is drawn on."""
    root = box._root()

    box.create_box_parametric(length=2.0, width=1.0, height=0.5, plane="yz")

    assert root.sketches.count == 1
    assert root.sketches.item(0).supportingPlane is root.yZConstructionPlane


def test_create_box_parametric_offsets_a_construction_plane_for_origin_z(box):
    """``origin_z`` lifts the sketch onto a plane offset from the base one."""
    root = box._root()

    box.create_box_parametric(length=1.0, width=1.0, height=1.0)
    box.create_box_parametric(length=1.0, width=1.0, height=1.0, origin_z=2.5)

    assert root.sketches.item(0).supportingPlane is root.xYConstructionPlane
    assert root.constructionPlanes.count == 1
    offset_input = root.constructionPlanes.last_input
    assert offset_input is not None
    assert offset_input.setter == "setByOffset"
    base, distance = offset_input.args
    assert base is root.xYConstructionPlane
    assert (distance.value, distance.kind) == (2.5, "real")
    assert root.sketches.item(1).supportingPlane is root.constructionPlanes.item(0)


def test_create_box_parametric_writes_each_size_the_way_it_was_given(box):
    """A number becomes ``parameter.value``; an expression, ``.expression``."""
    root = box._root()

    box.create_box_parametric(length=4.5, width="wall_w", height=1.0)

    dimensions = root.sketches.item(0).sketchDimensions.dimensions
    assert dimensions[0].parameter.written == [("value", 4.5)]
    assert dimensions[1].parameter.written == [("expression", "wall_w")]


def test_create_box_parametric_extrudes_the_height_as_the_unit_it_was_given(box):
    """The extent keeps the same real-or-string choice as the dimensions."""
    root = box._root()

    box.create_box_parametric(length=1.0, width=1.0, height=2.5)
    box.create_box_parametric(length=1.0, width=1.0, height="plate_t")

    numeric, expression = root.features.extrudeFeatures.added
    assert (numeric.distance[1].value, numeric.distance[1].kind) == (2.5, "real")
    assert (expression.distance[1].value, expression.distance[1].kind) == (
        "plate_t",
        "string",
    )
    for inp in (numeric, expression):
        assert inp.operation == "new_body"
        assert inp.distance[0] is False


def test_create_box_parametric_lays_the_placeholder_rectangle_out_at_one(box):
    """``_initial``: the number when there is one, a 1 cm placeholder otherwise.

    The placeholder is not a measurement of anything - the dimensions carry the
    real sizes - it is only the rectangle Fusion needs before it is dimensioned.
    """
    root = box._root()

    box.create_box_parametric(
        length=3.0, width=4.0, height=1.0, origin_x=1.0, origin_y=2.0
    )
    box.create_box_parametric(
        length="boxL", width="boxW", height=1.0, origin_x=1.0, origin_y=2.0
    )

    assert rectangle_corners(root.sketches.item(0)) == [(1.0, 2.0), (4.0, 6.0)]
    assert rectangle_corners(root.sketches.item(1)) == [(1.0, 2.0), (2.0, 3.0)]


def test_create_box_parametric_dims_the_length_across_and_the_width_up(box):
    """Length gets the horizontal dimension, width the vertical one."""
    root = box._root()

    box.create_box_parametric(length=4.0, width=2.0, height=1.0)

    orientations = [
        args[2] for _method, args in root.sketches.item(0).sketchDimensions.calls
    ]
    assert orientations == ["horizontal", "vertical"]


def test_create_box_parametric_survives_an_int_too_large_for_float(box):
    """``_initial``'s OverflowError guard keeps the expression path reachable.

    Without it a 401-digit JSON integer raises out of ``float()`` before the
    dimension exists, and ``value_input_for``'s expression fallback - which
    exists for exactly this value - could never run.
    """
    huge = json.loads("1" + "0" * 400)
    root = box._root()

    box.create_box_parametric(length=huge, width=1.0, height=1.0)

    sketch = root.sketches.item(0)
    assert rectangle_corners(sketch) == [(0.0, 0.0), (1.0, 1.0)]
    assert sketch.sketchDimensions.dimensions[0].parameter.written == [
        ("expression", str(huge))
    ]


def test_create_box_parametric_names_the_body_it_built(box):
    """``body_name`` renames the feature's body, and the reply reads it back.

    The body is the extrude fake's model of a new-body feature.  What the handler
    contributes - and what this asserts - is the rename, read off the created
    feature: the reply alone would still say "Crate" if nothing were renamed.
    """
    root = box._root()

    result = box.create_box_parametric(
        length=2.0, width=1.0, height=0.5, body_name="Crate"
    )

    created = root.features.extrudeFeatures.created
    assert created[0].bodies.item(0).name == "Crate"
    assert result["body_name"] == "Crate"


def test_create_box_parametric_builds_in_the_component_it_was_named(box):
    """``component_name`` redirects the sketch and the extrude off the root."""
    root = box._root()
    housing = root.occurrences.addNewComponent(FakeMatrix3D()).component
    housing.name = "Housing"

    result = box.create_box_parametric(
        length=1.0, width=1.0, height=1.0, component_name="Housing"
    )

    assert housing.sketches.count == 1
    assert root.sketches.count == 0
    assert housing.features.extrudeFeatures.added != []
    assert root.features.extrudeFeatures.added == []
    assert result["component"] == "Housing"
