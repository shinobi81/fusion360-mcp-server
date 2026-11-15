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

from tests.fakes.bodies import body_with_edges
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
