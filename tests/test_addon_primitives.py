"""``create_box``, driven through the handler: where the box actually lands.

``center_z`` used to mean *base* z.  The orientation matrix was built at
``center_z + height / 2``, so X and Y were centred on the caller's point while Z
*started* there: a 10 x 10 x 2 box asked for at ``center_z=1`` came out spanning
z 1..3, and one asked for with the default ``center_z=0`` sat on the origin plane
instead of straddling it.

The placement *was* reported, but only as the whole design's ``deltas.bbox_after``
- which is the box's own position in a one-body design and nothing legible in any
other, and which no test read.  What stated the intent was the parameter name, and
the name was wrong.  The fake had no primitives at all, which is why this was
never tested: ``TemporaryBRepManager``, ``OrientedBoundingBox3D`` and a base
feature a body can be added to all had to exist before the handler could run.
"""

from __future__ import annotations

import pytest

from tests.fakes.design import FakeDesign


def _first_body(bound_handler, **kwargs):
    """Run ``create_box`` and hand back the body that reached the root component.

    ``features=0`` is an empty design: without it the fake gives the root one
    default body, and ``item(0)`` would be that one rather than the box.
    """
    design = FakeDesign(features=0)
    bound_handler(design).create_box(**kwargs)
    assert design.rootComponent.bRepBodies.count == 1, "exactly one body was created"
    return design.rootComponent.bRepBodies.item(0)


def test_a_box_is_centred_on_the_point_it_is_given(bound_handler):
    """The three sizes straddle the centre point, on every axis.

    X and Y already did; Z did not, which is the defect.  All six numbers are
    asserted together because "centred" is one claim: half the box either side of
    the point, whichever axis you look along.

    Length and width differ (10 and 6) on purpose: with a square footprint, a
    handler that swapped the two directions would land on the same box and this
    test could not tell the two axes apart.
    """
    body = _first_body(
        bound_handler,
        length=10,
        width=6,
        height=2,
        center_x=1,
        center_y=2,
        center_z=1,
    )

    box = body.boundingBox
    assert (
        box.minPoint.x,
        box.minPoint.y,
        box.minPoint.z,
    ) == pytest.approx((-4.0, -1.0, 0.0))
    assert (
        box.maxPoint.x,
        box.maxPoint.y,
        box.maxPoint.z,
    ) == pytest.approx((6.0, 5.0, 2.0))


def test_the_default_box_straddles_the_model_origin(bound_handler):
    """``center_z`` left out means centred on 0, so the box runs -h/2 .. +h/2.

    This is the part of the change a caller notices without passing anything: a
    box used to sit *on* the origin plane and now straddles it, which is what a
    centre always promised.
    """
    body = _first_body(bound_handler, length=10, width=10, height=2)

    assert body.boundingBox.minPoint.z == pytest.approx(-1.0)
    assert body.boundingBox.maxPoint.z == pytest.approx(1.0)


def test_the_base_feature_is_finished_after_the_add(bound_handler):
    """The body is added *inside* the base feature, which is then closed again.

    Fusion's ``BRepBodies.add`` requires the base feature to be in edit for the
    add and says ``finishEdit`` exits that mode; a handler that never calls it
    leaves the design mid-edit.  Nothing else observes this, so it is asserted
    from the design's own state rather than inferred from the call.
    """
    design = FakeDesign(features=0)
    bound_handler(design).create_box(length=1, width=1, height=1)

    feature = design.rootComponent.features.baseFeatures.item(0)
    assert feature.bodies == [design.rootComponent.bRepBodies.item(0)]
    assert not feature.editing, "the base feature is finished after the add"
