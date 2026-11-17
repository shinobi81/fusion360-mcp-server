"""``ruled_surface`` and ``project_geometry``: both tools called an API they could not.

Two separate defects, one shape.  ``ruled_surface`` passed a raw edge and two
arguments to ``RuledSurfaceFeatures.createInput``, whose shipped signature is::

    createInput(profile, distance, angle, ruledSurfaceType)

with a **Profile** first — ``TypeError: Wrong number or type of arguments`` on
every call, so the tool had never created a surface.  ``project_geometry`` called
``Sketch.project``, which the SDK marks retired precisely because it cannot
express linkage, so its ``is_linked`` argument was dropped.

The fakes below declare Fusion's arity and input types, and refuse anything else
the way Fusion does, which is what makes these tests fail on the old code instead
of passing for the wrong reason.

``thicken_surface`` is here for a different shape of defect: the argument names
were right but the values were crossed, so ``direction`` never reached
``isSymmetric``.  ``ThickenFeatures.createInput`` ships
``(inputFaces, thickness, isSymmetric, operation, isChainSelection=True)``, and
``ThickenFeatureInput`` has no direction member - so the tool's ``positive`` and
``negative`` are the same one-sided thicken, which the tests pin rather than
paper over.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import (
    FakeBody,
    FakeBoundingBox,
    FakeFace,
    FakePhysicalProperties,
    body_with_edges,
)
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import PARAMETRIC, FakePoint3D
from tests.fakes.sketch import FakeSketch


def _design_with_a_sketch() -> tuple[FakeDesign, FakeSketch]:
    sketch = FakeSketch(name="Sketch1")
    body = body_with_edges(
        "Body1",
        [
            ((0.0, 0.0, 0.0), (0.0, 10.0, 0.0)),
            ((0.0, 10.0, 0.0), (10.0, 10.0, 0.0)),
        ],
    )
    return FakeDesign(bodies=[body], sketches=[sketch], design_type=PARAMETRIC), sketch


def test_a_ruled_surface_is_built_from_a_profile_and_carries_its_rule(
    bound_handler,
):
    design, _ = _design_with_a_sketch()
    handler = bound_handler(design)

    out = handler.ruled_surface(
        "Body1", edge_index=0, distance=2.5, rule_type="tangent"
    )

    created = design.rootComponent.features.ruledSurfaceFeatures.inputs[0]
    assert created.ruleType == "TangentRuledSurfaceType"
    assert created.distance.value == 2.5
    assert created.profile.chainEdges is True
    assert out["feature_name"] == "Ruled Surface1"


def test_the_default_rule_is_normal_not_the_query_default(bound_handler):
    design, _ = _design_with_a_sketch()
    handler = bound_handler(design)

    handler.ruled_surface("Body1", edge_index=1)

    created = design.rootComponent.features.ruledSurfaceFeatures.inputs[0]
    assert created.ruleType == "NormalRuledSurfaceType"
    assert created.distance.value == 1.0


def test_projection_is_unlinked_when_the_caller_asks(bound_handler):
    design, sketch = _design_with_a_sketch()
    handler = bound_handler(design)

    handler.project_geometry("Body1", is_linked=False, sketch_name="Sketch1")

    assert sketch.projected, "nothing was projected at all"
    assert [is_linked for _, is_linked in sketch.projected] == [False, False]


def test_projection_is_linked_by_default(bound_handler):
    design, sketch = _design_with_a_sketch()
    handler = bound_handler(design)

    out = handler.project_geometry("Body1")

    assert [is_linked for _, is_linked in sketch.projected] == [True, True]
    assert out["projected_curves"] == 2


def test_a_patch_of_a_sketch_profile_hands_that_profile_to_the_feature(bound_handler):
    """The requested sketch's profile at the requested index is the boundary.

    The decoy sketch is listed first, and the chosen sketch holds two profiles, so
    a lookup that took the first of either would hand over a different boundary.
    """
    decoy = FakeSketch(name="Decoy")
    boundary = FakeSketch(name="Boundary", profile_count=2)
    design = FakeDesign(bodies=[FakeBody("Body1")], sketches=[decoy, boundary])
    handler = bound_handler(design)

    out = handler.patch_surface("Boundary", profile_index=1)

    created = design.rootComponent.features.patchFeatures.inputs[0]
    assert created.boundaryCurve.sketch is boundary
    assert boundary.profiles.requested == [1]
    assert created.operation == "new_body"
    assert created.groupContinuity == "ConnectedSurfaceContinuityType"
    assert out == {"feature_name": "Patch1", "continuity": "connected"}


def test_a_patch_takes_the_continuity_the_caller_asked_for(bound_handler):
    """``continuity="tangent"`` reaches ``groupContinuity``, the shipped member.

    The handler used to write ``boundaryContinuity``, which is not a member: the
    write did nothing, the reply said ``tangent`` and Fusion patched with the
    connected default.
    """
    design, _ = _design_with_a_sketch()
    handler = bound_handler(design)

    out = handler.patch_surface("Sketch1", continuity="tangent")

    created = design.rootComponent.features.patchFeatures.inputs[0]
    assert created.groupContinuity == "TangentSurfaceContinuityType"
    assert out["continuity"] == "tangent"


def test_a_stitch_of_bodies_that_do_not_touch_still_hands_over_both(bound_handler):
    """Whether two surfaces meet is Fusion's judgement, so both are forwarded.

    The decoy body is in the root and must not join the collection, and the two
    named bodies are requested out of root order, so the reply's count cannot
    come from the collection's length by accident.
    """
    first, second, decoy = FakeBody("SurfaceA"), FakeBody("SurfaceB"), FakeBody("Decoy")
    design = FakeDesign(bodies=[first, second, decoy])
    handler = bound_handler(design)

    out = handler.stitch_surfaces(["SurfaceB", "SurfaceA"], tolerance=0.05)

    created = design.rootComponent.features.stitchFeatures.inputs[0]
    assert list(created.stitchSurfaces) == [second, first]
    assert created.tolerance.kind == "real"
    assert created.tolerance.value == 0.05
    assert created.operation == "new_body"
    assert out == {"feature_name": "Stitch1", "body_count": 2}


def _thicken_design() -> tuple[FakeDesign, FakeBody]:
    """A decoy body first; the named surface carries two faces in a known order."""
    faces = FakeCollection([FakeFace(planar=True), FakeFace(planar=False)])
    surface = FakeBody("Surface", faces=faces)
    return FakeDesign(bodies=[FakeBody("DecoyBody"), surface]), surface


def test_a_symmetric_thicken_sets_the_symmetric_flag_on_the_named_body(
    bound_handler,
):
    """``direction="symmetric"`` reaches ``isSymmetric``, for the named body's faces.

    The decoy body is first in the root, so a lookup that took the first body
    would thicken the wrong one.  The fifth argument, ``isChainSelection``, is
    omitted and so stays at Fusion's shipped default of ``True``.
    """
    design, surface = _thicken_design()
    handler = bound_handler(design)

    out = handler.thicken_surface("Surface", thickness=0.2)

    created = design.rootComponent.features.thickenFeatures.inputs[0]
    assert list(created.inputFaces) == list(surface.faces)
    assert created.isSymmetric is True
    assert created.isChainSelection is True
    assert (created.thickness.kind, created.thickness.value) == ("real", 0.2)
    assert created.operation == "new_body"
    assert out == {"feature_name": "Thicken1", "thickness": 0.2}


def test_both_one_sided_directions_are_indistinguishable_at_the_api(bound_handler):
    """``positive`` and ``negative`` reach Fusion as the same one-sided thicken.

    The shipped ``ThickenFeatureInput`` has no direction or flip member, so the
    tool's three direction names describe two behaviours: symmetric or not.
    Nothing here models a direction, so a handler that wrote a property of its
    own would not be caught by this fake; what the test proves is that the two
    directions reach the five modelled members identically.
    """
    design, _surface = _thicken_design()
    handler = bound_handler(design)

    handler.thicken_surface("Surface", thickness=0.2, direction="positive")
    handler.thicken_surface("Surface", thickness=0.2, direction="negative")

    first, second = design.rootComponent.features.thickenFeatures.inputs
    assert (first.isSymmetric, second.isSymmetric) == (False, False)
    assert (first.isChainSelection, second.isChainSelection) == (True, True)
    assert first.thickness.value == second.thickness.value == 0.2


def test_an_unknown_rule_type_is_refused_as_invalid_input(bound_handler):
    """The refusal must classify, not fall through to UNKNOWN.

    The handler names both accepted values; without a rule in ``hints.py`` (both
    mirrors) the message matched nothing and the caller got a traceback and no
    advice, which is the failure mode every rule in that table exists to stop.
    """
    from addon.server.hints import classify

    design, _sketch = _design_with_a_sketch()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.ruled_surface("Body1", edge_index=0, rule_type="Tangent")

    kind, hints = classify(str(raised.value))
    assert kind == "INVALID_INPUT"
    assert any("normal or tangent" in hint for hint in hints), hints


# ── trim_surface ───────────────────────────────────────────────────────


def _cells_of(design) -> list:
    """The cells the last trim input carries, with the input proven to exist."""
    created = design.rootComponent.features.trimFeatures.last_input
    assert created is not None
    return [created.bRepCells.item(i) for i in range(created.bRepCells.count)]


def _cell_at(x: float, y: float) -> FakeBody:
    """A transient cell whose centroid sits at ``(x, y, 0)``."""
    return FakeBody(
        "Cell",
        physical_properties=FakePhysicalProperties(center_of_mass=(x, y, 0.0)),
    )


def _trim_design(cells):
    """A target surface, a tool solid around the origin, and Fusion's cells."""
    tool = FakeBody("Cutter", bounding_box=FakeBoundingBox((-1, -1, -1), (1, 1, 1)))
    design = FakeDesign(bodies=[FakeBody("DecoyBody"), FakeBody("Surf1"), tool])
    design.rootComponent.features.trimFeatures.cell_bodies = cells
    return design, tool


def test_a_trim_keeping_the_inside_removes_the_outside_cells(bound_handler):
    """A **selected** cell is removed, so keeping the inside selects the rest.

    ``BRepCell.isSelected`` means "trim this away" for a trim feature
    (``Features/BRepCell.h:40-45``) - the opposite of a boundary fill - so the
    side the caller keeps must be the unselected one.
    """
    design, _tool = _trim_design([_cell_at(0.0, 0.0), _cell_at(5.0, 0.0)])
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep="inside", tool_name="Cutter")

    cells = _cells_of(design)
    assert cells[0].isSelected is False
    assert cells[1].isSelected is True


def test_a_trim_keeping_the_outside_removes_the_inside_cells(bound_handler):
    """The same two cells, the opposite selection: ``keep`` really moves it."""
    design, _tool = _trim_design([_cell_at(0.0, 0.0), _cell_at(5.0, 0.0)])
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep="outside", tool_name="Cutter")

    cells = _cells_of(design)
    assert cells[0].isSelected is True
    assert cells[1].isSelected is False


def test_a_trim_against_a_plane_keeps_the_side_its_normal_points_to(bound_handler):
    """A plane has no inside, so ``positive`` means the normal's side.

    The XY plane at the origin runs +Z, and both cells here sit at z=0, so the
    test moves one of them below the plane: that is what separates the sides.
    """
    below = _cell_at(0.0, 0.0)
    below.physicalProperties.centerOfMass = FakePoint3D(0.0, 0.0, -2.0)
    above = _cell_at(0.0, 0.0)
    above.physicalProperties.centerOfMass = FakePoint3D(0.0, 0.0, 2.0)
    design = FakeDesign(bodies=[FakeBody("DecoyBody"), FakeBody("Surf1")])
    design.rootComponent.features.trimFeatures.cell_bodies = [below, above]
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep="positive", tool_plane="xy")

    cells = _cells_of(design)
    assert cells[0].isSelected is True
    assert cells[1].isSelected is False


def test_a_trim_cancels_the_transaction_when_fusion_refuses(bound_handler):
    """``createInput`` opens a transaction; leaving it open can crash Fusion.

    With nothing selected the fake's ``add`` refuses, as Fusion does, so the
    handler must cancel before re-raising - the header says an open transaction
    leaves Fusion in a bad state.
    """
    design, _tool = _trim_design([_cell_at(0.0, 0.0)])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.trim_surface("Surf1", keep="inside", tool_name="Cutter")

    created = design.rootComponent.features.trimFeatures.last_input
    assert created is not None
    assert created.cancelled is True


def test_a_trim_takes_either_a_body_or_a_plane_and_refuses_both(bound_handler):
    """Two tools, or none, is a refusal before Fusion is asked for anything."""
    design, _tool = _trim_design([])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError, match="exactly one of"):
        handler.trim_surface(
            "Surf1", keep="inside", tool_name="Cutter", tool_plane="xy"
        )

    assert design.rootComponent.features.trimFeatures.inputs == []


def test_a_trim_refuses_the_word_that_does_not_fit_the_tool(bound_handler):
    """``positive`` is a plane word; a body tool takes ``inside``/``outside``."""
    design, _tool = _trim_design([_cell_at(0.0, 0.0)])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError, match="does not apply to a body tool"):
        handler.trim_surface("Surf1", keep="positive", tool_name="Cutter")


def test_a_trim_with_a_patch_tool_reads_the_side_from_its_planar_face(bound_handler):
    """A patch body has no interior, so its side comes from its face's normal.

    Measured on 2706: a *solid* tool against a surface target makes Fusion raise
    ``!body->isSolid_raw()`` when the cells are counted, and a patch body answers
    ``pointContainment`` with ``Outside`` for every point, so ``inside`` cannot
    mean anything for it.  The concrete side is the tool's first planar face.
    """
    tool = FakeBody("Patch", faces=FakeCollection([FakeFace(normal=(0, 1, 0))]))
    tool.isSolid = False
    design = FakeDesign(bodies=[FakeBody("DecoyBody"), FakeBody("Surf1"), tool])
    design.rootComponent.features.trimFeatures.cell_bodies = [
        _cell_at(0.0, -2.0),
        _cell_at(0.0, 2.0),
    ]
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep="negative", tool_name="Patch")

    cells = _cells_of(design)
    assert cells[0].isSelected is False
    assert cells[1].isSelected is True
