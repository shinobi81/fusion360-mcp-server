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

from tests.fakes.bodies import FakeBody, FakeFace, body_with_edges
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import PARAMETRIC
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


def _trim_design(cells):
    """A target surface, a patch tool, and the cells Fusion computed."""
    tool = FakeBody("Cutter")
    design = FakeDesign(bodies=[FakeBody("DecoyBody"), FakeBody("Surf1"), tool])
    design.rootComponent.features.trimFeatures.cell_bodies = cells
    return design, tool


def test_a_trim_removes_every_cell_it_was_not_asked_to_keep(bound_handler):
    """``isSelected`` means *remove* for a trim, so the kept cells are unselected.

    Measured on 2706: both cells of a patch report ``centerOfMass`` as
    ``(0, 0, 0)``, so a side cannot be computed - the caller names the cells and
    every other one is selected for removal (``Features/BRepCell.h:40-45``).
    """
    design, _tool = _trim_design([FakeBody("Cell0"), FakeBody("Cell1")])
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep_cells=[0], tool_name="Cutter")

    cells = _cells_of(design)
    assert cells[0].isSelected is False
    assert cells[1].isSelected is True


def test_a_trim_keeping_the_other_cell_moves_the_selection(bound_handler):
    """The mirror image: same two cells, the opposite selection."""
    design, _tool = _trim_design([FakeBody("Cell0"), FakeBody("Cell1")])
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep_cells=[1], tool_name="Cutter")

    cells = _cells_of(design)
    assert cells[0].isSelected is True
    assert cells[1].isSelected is False


def test_a_trim_reports_how_many_cells_it_had_to_choose_from(bound_handler):
    """The reply carries the count, so a caller can retry with a valid index."""
    design, _tool = _trim_design([FakeBody("Cell0"), FakeBody("Cell1")])
    handler = bound_handler(design)

    out = handler.trim_surface("Surf1", keep_cells=[1], tool_name="Cutter")

    assert out["cells"] == 2
    assert out["kept_cells"] == [1]


def test_a_trim_refuses_a_cell_index_past_the_end_before_fusion_adds(
    bound_handler,
):
    """An out-of-range index is refused by us, and the transaction is cancelled."""
    design, _tool = _trim_design([FakeBody("Cell0"), FakeBody("Cell1")])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError, match="out of range"):
        handler.trim_surface("Surf1", keep_cells=[2], tool_name="Cutter")

    created = design.rootComponent.features.trimFeatures.last_input
    assert created is not None
    assert created.cancelled is True
    assert design.rootComponent.features.trimFeatures.created == []


def test_a_trim_cancels_the_transaction_when_fusion_refuses(bound_handler):
    """Keeping every cell selects none, and Fusion refuses; we must cancel first.

    ``createInput`` opens a transaction - the header says leaving it open leaves
    Fusion in a bad state and can crash it.
    """
    design, _tool = _trim_design([FakeBody("Cell0")])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.trim_surface("Surf1", keep_cells=[0], tool_name="Cutter")

    created = design.rootComponent.features.trimFeatures.last_input
    assert created is not None
    assert created.cancelled is True


def test_a_trim_takes_either_a_body_or_a_plane_and_refuses_both(bound_handler):
    """Two tools, or none, is a refusal before Fusion is asked for anything."""
    design, _tool = _trim_design([])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError, match="exactly one of"):
        handler.trim_surface(
            "Surf1", keep_cells=[0], tool_name="Cutter", tool_plane="xy"
        )

    assert design.rootComponent.features.trimFeatures.inputs == []


def test_a_trim_reads_the_cells_of_a_plane_tool_too(bound_handler):
    """A construction plane is a valid tool, and the cells come back the same."""
    design, _tool = _trim_design([FakeBody("Cell0"), FakeBody("Cell1")])
    handler = bound_handler(design)

    handler.trim_surface("Surf1", keep_cells=[0], tool_plane="xy")

    created = design.rootComponent.features.trimFeatures.last_input
    assert created is not None
    assert created.trimTool is design.rootComponent.xYConstructionPlane
