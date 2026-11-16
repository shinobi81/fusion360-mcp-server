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

import math

import pytest

from addon.server.hints import classify
from tests.fakes.bodies import FakeBody, FakeBoundingBox
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
    design = FakeDesign(features=0, bodies=[FakeBody("A")])
    handler = bound_handler(design, _measuring_app(FakeMeasureManager()))

    with pytest.raises(RuntimeError, match="Entity 'Ghost' not found"):
        handler.measure_angle("A", "Ghost")


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

    This message reaches the caller as ``error_kind: UNKNOWN`` with no hints:
    ``hints.py`` has no rule for "Parameter '<name>' not found", and that file is
    canonical and mirrored, so it is out of this commit's reach.  The test pins
    the message; the classification gap is reported with the pull request.
    """
    design = FakeDesign(features=2)

    with pytest.raises(RuntimeError, match="Parameter 'width' not found"):
        bound_handler(design).delete_parameter("width")


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
