"""The scene reads: what Fusion is asked, and what the reply says back.

``get_object_info``, ``get_bounding_box``, ``measure_angle``, ``get_parameters``,
``delete_parameter``, ``get_design_type``, ``list_components`` and ``rename_body``
were each executed by fewer than a quarter of their statements: the only tests that
reached them asserted the *parameter* refusal ahead of the call, so nothing pinned
the call itself.  Every test below therefore reads what the handler asked Fusion
for — the body it resolved, the face it measured, the parameter it deleted — not
merely that something came back.

Two behaviours the plan guessed at do not exist, and these tests state what the
handler does instead rather than inventing a refusal that Fusion has not been
measured making:

* a read of a name that is not there answers ``{"found": False}`` — the browse
  commands do not raise — so the BODY_NOT_FOUND half of that pair is pinned on
  ``rename_body``, the command that *needs* the body to exist;
* no measured Fusion refusal exists for renaming a body onto another body's name,
  so nothing here pins a collision refusal.

The positive fixtures hold a decoy first in the collection the handler walks, so a
read that stopped comparing names would answer for the decoy: each "the object that
was asked for" test goes red if the comparison is deleted.  One name below is the
*fake's*, not Fusion's: ``FakeRoot`` invents ``"Component1"`` for the root
component, so ``test_list_components_names_the_root_and_each_occurrence`` pins that
the root is named in the reply, not what Fusion calls it.
"""

from __future__ import annotations

import inspect
import math

import pytest

from addon.server import handler_scene
from addon.server import hints as addon_hints
from addon.server.hints import classify
from tests.fakes.bodies import (
    FakeBody,
    FakeBoundingBox,
    FakeEdge,
    FakeEdges,
    FakeFace,
)
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence
from tests.fakes.features import FakeMeasureManager
from tests.fakes.runtime import DIRECT, PARAMETRIC, FakePoint3D, FakeValueInput
from tests.fakes.sketch import FakeSketch


def _plate() -> FakeBody:
    """A body the reads can name, with a box that differs on every axis."""
    return FakeBody(
        "Plate", bounding_box=FakeBoundingBox((0.0, 0.0, 0.0), (10.0, 4.0, 1.0))
    )


def _spacer() -> FakeBody:
    """A decoy body, placed *before* the named one in every fixture that uses it.

    A read that answered for the first body it saw, instead of the one it was
    asked for, would report this box (20..21, not 0..10).
    """
    return FakeBody(
        "Spacer", bounding_box=FakeBoundingBox((20.0, 20.0, 20.0), (21.0, 21.0, 21.0))
    )


def _measuring_app(manager: FakeMeasureManager):
    """The handler app ``measure_angle`` needs: it reads ``app.measureManager`` only."""
    return type("FakeApp", (), {"measureManager": manager})()


def test_get_object_info_of_a_body_reports_its_counts_and_box(bound_handler):
    handler = bound_handler(FakeDesign(features=0, bodies=[_spacer(), _plate()]))

    assert handler.get_object_info("Plate") == {
        "found": True,
        "type": "body",
        "name": "Plate",
        "volume": 1.0,
        "area": 6.0,
        "material": None,
        "is_visible": True,
        "faces_count": 1,
        "edges_count": 0,
        "vertices_count": 0,
        "bounding_box": {"min": [0.0, 0.0, 0.0], "max": [10.0, 4.0, 1.0]},
    }


def test_get_object_info_of_a_sketch_reports_its_profiles_and_curves(bound_handler):
    sketch = FakeSketch(name="Sketch1", profile_count=2)
    for row in range(4):
        sketch.sketchCurves.sketchLines.addByTwoPoints(
            FakePoint3D(0.0, float(row), 0.0), FakePoint3D(1.0, float(row), 0.0)
        )
    decoy = FakeSketch(name="Sketch2", profile_count=7)
    handler = bound_handler(FakeDesign(features=0, sketches=[decoy, sketch]))

    assert handler.get_object_info("Sketch1") == {
        "found": True,
        "type": "sketch",
        "name": "Sketch1",
        "is_visible": True,
        "profile_count": 2,
        "curve_count": 4,
    }


def test_get_object_info_of_a_name_that_is_not_there_reports_found_false(
    bound_handler,
):
    """A browse read that finds nothing answers; it does not raise.

    ``get_object_info`` is the command an agent calls *before* it knows what the
    document holds, so a name that is not there is an answer, not an error — its
    peer ``get_bounding_box`` answers the same way.  BODY_NOT_FOUND is pinned on
    ``rename_body`` below, where the handler really does refuse.
    """
    handler = bound_handler(FakeDesign(features=0, bodies=[_plate()]))

    assert handler.get_object_info("Ghost") == {"found": False, "name": "Ghost"}


def test_get_bounding_box_reports_the_body_it_was_asked_for(bound_handler):
    """The box, its size and its centre all come from the body that was named.

    ``_body_by_name`` walks the collection in order, so a lookup that stopped
    comparing names answers with the decoy's box, twenty centimetres out.
    """
    handler = bound_handler(FakeDesign(features=0, bodies=[_spacer(), _plate()]))

    assert handler.get_bounding_box("Plate") == {
        "found": True,
        "type": "body",
        "name": "Plate",
        "min": [0.0, 0.0, 0.0],
        "max": [10.0, 4.0, 1.0],
        "size": [10.0, 4.0, 1.0],
        "center": [5.0, 2.0, 0.5],
    }


def test_get_bounding_box_of_a_component_unions_the_bodies_it_holds(bound_handler):
    """A component has no box of its own: it is the union of what it contains.

    A component's own bodies and the bodies of the occurrences placed in it are
    both part of it, so a union that read only one of the two would report a box
    the component does not have.
    """
    component = FakeComponent(
        "Bracket",
        [
            FakeBody("Foot", bounding_box=FakeBoundingBox((0.0, 0.0, 0.0), (2, 2, 2))),
            FakeBody("Web", bounding_box=FakeBoundingBox((3.0, 3.0, 3.0), (5, 5, 5))),
        ],
    )
    component.occurrences.add(
        FakeOccurrence(
            FakeComponent(
                "Rib",
                [
                    FakeBody(
                        "Brace",
                        bounding_box=FakeBoundingBox((6.0, 0.0, 0.0), (8, 1, 1)),
                    )
                ],
            )
        )
    )
    design = FakeDesign(features=0)
    design.rootComponent.occurrences.add(FakeOccurrence(component))

    out = bound_handler(design).get_bounding_box("Bracket")

    assert out["type"] == "component"
    assert out["min"] == [0.0, 0.0, 0.0], "the lowest corner of any body in it"
    assert out["max"] == [8.0, 5.0, 5.0], "and the highest, the nested rib's included"
    assert out["size"] == [8.0, 5.0, 5.0]


def test_get_bounding_box_of_an_empty_component_says_it_is_empty(bound_handler):
    """A union of nothing is not a zero-size box at the origin."""
    design = FakeDesign(features=0)
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("Spare")))

    out = bound_handler(design).get_bounding_box("Spare")

    assert out == {"found": True, "type": "component", "name": "Spare", "empty": True}


def test_get_bounding_box_of_a_name_that_is_neither_reports_found_false(
    bound_handler,
):
    handler = bound_handler(FakeDesign(features=0, bodies=[_plate()]))

    assert handler.get_bounding_box("Ghost") == {"found": False, "name": "Ghost"}


def test_measure_angle_of_two_parallel_faces_is_zero(bound_handler):
    """The bodies are resolved to their first face, which is what gets measured."""
    first, second = FakeBody("A"), FakeBody("B")
    design = FakeDesign(features=0, bodies=[first, second])
    manager = FakeMeasureManager(angle=0.0)

    out = bound_handler(design, _measuring_app(manager)).measure_angle("A", "B")

    assert out == {"angle_degrees": 0.0}
    assert manager.measured == [(first.faces.item(0), second.faces.item(0))]


def test_measure_angle_reports_degrees_not_radians(bound_handler):
    """Fusion answers in radians; an un-converted reply would read 1.5708."""
    design = FakeDesign(features=0, bodies=[FakeBody("A"), FakeBody("B")])
    manager = FakeMeasureManager(angle=math.pi / 2)

    out = bound_handler(design, _measuring_app(manager)).measure_angle("A", "B")

    assert out == {"angle_degrees": 90.0}


def test_measure_angle_of_a_name_that_is_not_a_body_refuses(bound_handler):
    """The name was searched for as a body and is not one: enumerate and retry."""
    design = FakeDesign(features=0, bodies=[FakeBody("A")])
    handler = bound_handler(design, _measuring_app(FakeMeasureManager()))

    with pytest.raises(RuntimeError, match="Entity 'Ghost' not found") as raised:
        handler.measure_angle("A", "Ghost")

    assert addon_hints.classify(raised.value) == (
        "NAME_NOT_FOUND",
        ["Call get_scene_info for the entity names in this design."],
    )


def test_get_parameters_lists_what_the_design_holds(bound_handler):
    """All five reported fields, taken from the parameter each one belongs to.

    ``value`` is the *fake's* number, not Fusion's reply: ``FakeParameter.value``
    returns the expression's leading digits, so ``"100 mm"`` reads back as
    ``100.0`` where Fusion answers 10.0 cm.  The assertion pins that the handler
    passes the parameter's own ``value`` through, which is the wiring a wrong
    field name would break; the unit conversion is not modelled by the fake.
    """
    design = FakeDesign(features=2)
    design.userParameters.add(
        "width", FakeValueInput.createByString("100 mm"), "mm", "plate width"
    )
    design.userParameters.add("height", FakeValueInput.createByReal(5.0), "", "")

    out = bound_handler(design).get_parameters()

    assert out["count"] == 2
    assert [param["name"] for param in out["parameters"]] == ["width", "height"]
    assert out["parameters"][0] == {
        "name": "width",
        "value": 100.0,
        "expression": "100 mm",
        "unit": "mm",
        "comment": "plate width",
    }


def test_delete_parameter_removes_only_the_one_it_names(bound_handler):
    design = FakeDesign(features=2)
    design.userParameters.add(
        "width", FakeValueInput.createByString("100 mm"), "mm", ""
    )
    design.userParameters.add(
        "height", FakeValueInput.createByString("50 mm"), "mm", ""
    )
    handler = bound_handler(design)

    assert handler.delete_parameter("width") == {"deleted": True, "name": "width"}
    assert [param["name"] for param in handler.get_parameters()["parameters"]] == [
        "height"
    ], "the other parameter is still there, and the deleted one is gone"


def test_delete_parameter_of_a_name_that_is_not_there_refuses(bound_handler):
    """The refusal names the parameter and deletes nothing.

    ``NAME_NOT_FOUND`` says the next move is to enumerate: the hint names
    ``get_parameters``, which is the command that lists what the design has.
    """
    design = FakeDesign(features=2)

    with pytest.raises(RuntimeError, match="Parameter 'width' not found") as raised:
        bound_handler(design).delete_parameter("width")

    assert addon_hints.classify(raised.value) == (
        "NAME_NOT_FOUND",
        ["Call get_parameters for the names this design has."],
    )


def test_set_parameter_of_a_name_that_is_not_there_refuses(bound_handler):
    """``set_parameter`` writes an expression, so it needs the parameter to exist.

    The value is finite, which is what makes this the name's refusal rather than the
    argument's: ``set_parameter`` judges the number first, then looks the name up.
    """
    design = FakeDesign(features=2)

    with pytest.raises(RuntimeError, match="Parameter 'width' not found") as raised:
        bound_handler(design).set_parameter("width", 5.0)

    assert addon_hints.classify(raised.value) == (
        "NAME_NOT_FOUND",
        ["Call get_parameters for the names this design has."],
    )


@pytest.mark.parametrize(
    ("design_type", "expected"),
    [(PARAMETRIC, "parametric"), (DIRECT, "direct")],
)
def test_get_design_type_reports_the_design_it_is_in(
    bound_handler, design_type, expected
):
    design = FakeDesign(features=2, design_type=design_type)

    assert bound_handler(design).get_design_type() == {
        "design_type": expected,
        "design_type_id": design_type,
    }


def test_list_components_names_the_root_and_each_occurrence(bound_handler):
    design = FakeDesign(features=0)
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("Left")))
    hidden = FakeOccurrence(FakeComponent("Right"))
    hidden.isVisible = False
    design.rootComponent.occurrences.add(hidden)

    out = bound_handler(design).list_components()

    assert out == {
        "count": 3,
        "components": [
            {"name": "Component1", "is_root": True},
            {"name": "Left", "is_root": False, "is_visible": True},
            {"name": "Right", "is_root": False, "is_visible": False},
        ],
    }


def test_rename_body_reports_the_name_it_replaced(bound_handler):
    body = _plate()
    handler = bound_handler(FakeDesign(features=0, bodies=[body]))

    assert handler.rename_body("Plate", "Base") == {
        "renamed": True,
        "old_name": "Plate",
        "new_name": "Base",
    }
    assert body.name == "Base"


def test_rename_body_reaches_a_body_inside_a_component(bound_handler):
    """``_body_by_name`` walks occurrences too — the half a root-only fake misses."""
    inner = FakeBody("Bracket")
    design = FakeDesign(features=0)
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("Assy", [inner])))
    handler = bound_handler(design)

    handler.rename_body("Bracket", "Mount")

    assert inner.name == "Mount", "the occurrence's body was renamed, not a copy"


def test_rename_body_of_a_name_that_is_not_there_is_BODY_NOT_FOUND(bound_handler):
    handler = bound_handler(FakeDesign(features=0))

    with pytest.raises(RuntimeError) as raised:
        handler.rename_body("Ghost", "Base")

    assert classify(raised.value)[0] == "BODY_NOT_FOUND"


def _plate_with(*faces):
    """A body whose faces are the ones the test passed."""
    return FakeBody(name="Plate", faces=FakeCollection(list(faces)))


def test_list_faces_reports_a_planar_face_with_its_normal(bound_handler):
    """The face behind ``face_indices``, and the normal that says which way it faces.

    Until this tool existed the indices could only be learned through ``execute_code``,
    so a wrong-but-in-range index was accepted silently by every command taking one.
    """
    # A centroid the fake's bounding box would not produce: the assertion is then about
    # the handler reading ``face.centroid``, not about the box centre it defaults to.
    face_with_centroid = FakeFace(centroid=(1.0, 2.0, 3.0))
    handler = bound_handler(
        FakeDesign(features=0, bodies=[_plate_with(face_with_centroid)])
    )

    result = handler.list_faces(body_name="Plate")

    assert result["body_name"] == "Plate"
    face = result["faces"][0]
    assert face["index"] == 0
    assert face["is_planar"] is True
    assert face["normal"] == [0.0, 0.0, 1.0]
    assert face["centroid"] == [1.0, 2.0, 3.0]
    # The area is what tells two coplanar faces apart; FakeFace's default is 1.0.
    assert face["area"] == 1.0
    assert result["count"] == 1
    # The other half of the pair: a list that was not clipped says so.
    assert result["truncated"] is False


def test_list_faces_omits_the_normal_of_a_curved_face(bound_handler):
    """A cylinder has no ``normal``; inventing one describes a direction it lacks."""
    handler = bound_handler(
        FakeDesign(features=0, bodies=[_plate_with(FakeFace(planar=False, radius=1.0))])
    )

    face = handler.list_faces(body_name="Plate")["faces"][0]

    assert face["is_planar"] is False
    assert "normal" not in face


def test_list_faces_counts_every_face_and_says_when_the_list_was_clipped(
    bound_handler,
):
    """``count`` is the body's total, ``truncated`` the clip - as ``list_edges`` does.

    A caller reading ``faces`` as "how many there are" would plan against a shorter
    list than the body holds, which is the one thing the pair exists to prevent.
    """
    three = [_plate_with(FakeFace(), FakeFace(), FakeFace())]
    handler = bound_handler(FakeDesign(features=0, bodies=three))

    result = handler.list_faces(body_name="Plate", limit=2)

    assert len(result["faces"]) == 2
    assert result["count"] == 3
    assert result["truncated"] is True


def test_list_faces_reports_the_outward_normal_not_the_surface_one(bound_handler):
    """Measured on 2706: a box's bottom face has ``isParamReversed`` true.

    Its *surface* normal is +Z, so reporting ``geometry.normal`` would put the bottom of
    the box and its top in the same direction - two faces claiming one normal. Negating
    where the flag is set is what makes the report outward.
    """
    flipped = FakeFace(normal=(0.0, 0.0, 1.0), is_param_reversed=True)
    handler = bound_handler(FakeDesign(features=0, bodies=[_plate_with(flipped)]))

    normal = handler.list_faces(body_name="Plate")["faces"][0]["normal"]

    assert normal == [0.0, 0.0, -1.0]


def test_list_faces_names_the_surface_the_way_fusion_does(bound_handler):
    """A caller picks a cylinder by name; the names come from the enum's members.

    The mapping is keyed by ``SurfaceTypes.<member>``, so a build that renumbers the
    enum cannot leave the names wrong - and an unknown surface falls through as its raw
    value rather than being guessed at.
    """
    planar = FakeFace()
    curved = FakeFace(planar=False, radius=1.0)
    handler = bound_handler(
        FakeDesign(features=0, bodies=[_plate_with(planar, curved)])
    )

    faces = handler.list_faces(body_name="Plate")["faces"]

    assert faces[0]["surface_type"] == "Plane"
    assert faces[1]["surface_type"] == "Cylinder"


def test_list_faces_compares_against_the_enum_member_not_an_integer():
    """The planar test reads Fusion's member; ``0`` happens to equal it today.

    A literal would pass every behavioural test in this file and break the day the stub
    renumbers the enum, so the claim is pinned where it lives - in the source.
    """
    source = inspect.getsource(handler_scene)

    # The *assignment*, not the name: a comment mentioning the member would satisfy a
    # substring test while the code compared against a literal. The whole comment-free
    # line, indent included: a comment written as the assignment would satisfy a bare
    # substring test.
    assert "\n        plane_type = adsk.core.SurfaceTypes.PlaneSurfaceType\n" in source
    assert "geometry.surfaceType == plane_type" in source


@pytest.mark.parametrize(("limit", "expected"), [(None, 2), (0, 1), (1, 1)])
def test_the_limit_contract_is_one_rule_on_both_sides(bound_handler, limit, expected):
    """``None`` means "no limit given", ``0`` is floored to one - in both tools.

    The two modes disagreed before this was written: ``0`` meant 1 to the handler and
    200 to mock, so the same call returned different lists. These are the three cases
    that differ, and they are asserted for both list tools.
    """
    two_edges = FakeEdges(
        [
            FakeEdge((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            FakeEdge((1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
        ]
    )
    body = FakeBody(
        name="Plate",
        faces=FakeCollection([FakeFace(), FakeFace()]),
        edges=two_edges,
    )
    handler = bound_handler(FakeDesign(features=0, bodies=[body]))

    # Both tools, because the same line was changed in both - and reverting either one
    # used to leave the suite green.
    assert len(handler.list_faces(body_name="Plate", limit=limit)["faces"]) == expected
    assert len(handler.list_edges(body_name="Plate", limit=limit)["edges"]) == expected
