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
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody, body_with_edges
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
    assert out == {"feature_name": "Patch1", "continuity": "connected"}


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
