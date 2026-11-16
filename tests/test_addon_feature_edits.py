"""A mirror and the two patterns: what each one tells Fusion to build.

All three handlers build one input object, `add` it, and report `feat.name`
plus numbers taken from their own arguments.  So the assertions here are on the
input the fake records - which body, which plane, which axis, which quantities -
because that is the only part of the call Fusion's own answer would depend on.
The reply's counts are the request repeated, never a measurement of what Fusion
built; where a test reads one it says so.

Provenance: only ``FakeMirrorFeatures.add`` models geometry at all, and only its
*count* - one copy per mirrored body, appended to the root.  The copy's name and
shape are the fake's, and no test reads either.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakeValueInput


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
