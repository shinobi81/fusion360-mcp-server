"""Driving a joint: no recompute, and degrees converted only where angles live.

`set_joint_value` had no behavioural test. Two source scans stood in for the
behaviour:

* "never recomputes the design" — because `design.computeAll()` resets a joint
  value to zero, so a naive set-then-recompute looks exactly like the API
  silently ignoring the assignment;
* "converts degrees only inside the angle branch" — because `slideValue` and the
  planar slides are lengths in centimetres, and converting them is wrong by
  180/pi.

Both are now observed on a real fake joint: the fake counts `computeAll`, and it
exposes the driveable value attributes each motion actually has (a ball joint has
pitch/yaw/roll and no `rotationValue`), so a handler writing the wrong attribute
raises instead of having it conjured by `setattr`.
"""

from __future__ import annotations

import math

import pytest

from tests.fakes.bodies import FakeBody, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence

#: The measured frame of a cylinder whose axis is world Z (see test_addon_joint_frame).
MEASURED = {
    "origin": (-2.0, 0.0, 5.0),
    "primary": (-1.0, 0.0, 0.0),
    "secondary": (0.0, -1.0, 0.0),
    "third": (0.0, 0.0, 1.0),
}


class FakeViewport:
    def __init__(self):
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


class FakeApp:
    """``app.activeViewport``: the one thing ``set_joint_value`` touches."""

    def __init__(self):
        self.activeViewport = FakeViewport()


def _design(frame: dict) -> FakeDesign:
    """Two components, one body each, both faces carrying *frame*."""
    design = FakeDesign(features=0)
    for name in ("A", "B"):
        face = FakeFace(joint_frame=frame)
        body = FakeBody(f"{name}Body", faces=FakeCollection([face]))
        component = FakeComponent(name, [body])
        design.rootComponent.occurrences.add(FakeOccurrence(component))
    return design


def _driven_joint(bound_handler, joint_type: str = "slider", axis: str = "z"):
    """``(handler, joint)`` after creating one joint of *joint_type*."""
    design = _design(MEASURED)
    handler = bound_handler(design, app=FakeApp())
    handler.add_joint(
        component_one="A",
        component_two="B",
        joint_type=joint_type,
        body_one="ABody",
        face_one=0,
        body_two="BBody",
        face_two=0,
        axis=axis,
    )
    return handler, design.rootComponent.joints.item(0)


def test_set_joint_value_does_not_recompute_the_design(bound_handler):
    """A recompute resets the value to zero, which is why driving looked inert."""
    handler, joint = _driven_joint(bound_handler)
    # add_joint recomputes once; the claim is that driving a value adds none.
    before = handler._design().compute_all_calls

    handler.set_joint_value(value=2.5, joint_name=joint.name, as_built=False)

    assert handler._design().compute_all_calls == before, (
        "set_joint_value recomputed the design; Fusion resets the joint value on "
        "computeAll, so the value the caller just set is silently lost"
    )


def test_set_joint_value_refreshes_the_viewport(bound_handler):
    """The value has to be visible, and refresh is the only thing it should call."""
    handler, joint = _driven_joint(bound_handler)

    handler.set_joint_value(value=2.5, joint_name=joint.name, as_built=False)

    assert handler.app.activeViewport.refreshes == 1


def test_degrees_are_converted_for_an_angle_attribute(bound_handler):
    """Fusion stores angles in radians; the tool documents degrees by default."""
    handler, joint = _driven_joint(bound_handler, joint_type="revolute")

    result = handler.set_joint_value(
        value=90.0, joint_name=joint.name, units="deg", as_built=False
    )

    assert joint.jointMotion.rotationValue == pytest.approx(math.radians(90.0))
    assert result["attribute"] == "rotationValue"
    assert result["units"] == "deg"


def test_a_slide_value_is_left_in_centimetres(bound_handler):
    """Converting a length by 180/pi is a silent factor-of-57 error."""
    handler, joint = _driven_joint(bound_handler, joint_type="slider")

    result = handler.set_joint_value(
        value=2.5, joint_name=joint.name, units="deg", as_built=False
    )

    assert joint.jointMotion.slideValue == pytest.approx(2.5), (
        "a slide is a length in cm and must not be converted as if it were an angle"
    )
    assert result["units"] == "cm", "the response must say the units it applied"


def test_set_joint_value_raises_when_fusion_drops_the_value(bound_handler):
    """Fusion resets a joint value on the next computeAll — that must be reported."""
    handler, joint = _driven_joint(bound_handler)

    class Stubborn:
        """A motion that reports the same value however often it is written."""

        objectType = "adsk::fusion::SliderJointMotion"
        slideValue = 0.0

        def __setattr__(self, name, value):
            pass

    joint.jointMotion = Stubborn()

    with pytest.raises(RuntimeError) as raised:
        handler.set_joint_value(value=2.5, joint_name=joint.name, as_built=False)

    assert "did not keep" in str(raised.value)
    assert "computeAll" in str(raised.value), (
        "the refusal should name the cause, since that is the repair"
    )


def test_a_rigid_joint_has_nothing_to_drive(bound_handler):
    """Rigid motion is a real motion object with no value on it."""
    handler, joint = _driven_joint(bound_handler, joint_type="rigid")

    with pytest.raises(RuntimeError) as raised:
        handler.set_joint_value(value=1.0, joint_name=joint.name, as_built=False)

    assert "rigid" in str(raised.value).lower()


def test_the_fake_refuses_a_value_that_motion_does_not_have(bound_handler):
    """A ball joint has pitch/yaw/roll and no rotationValue.

    Without this, ``setattr`` would conjure whatever name a wrong table named and
    the read-back would confirm it — the fake agreeing with the bug, which is how
    the shell defect survived 813 tests.
    """
    _, joint = _driven_joint(bound_handler, joint_type="ball")

    with pytest.raises(AttributeError):
        joint.jointMotion.rotationValue = 1.0

    assert joint.jointMotion.pitchValue == 0.0


def test_a_planar_joint_can_be_driven(bound_handler):
    """Planar has rotationValue *and* two slides — the stub says so explicitly.

    Measured from Fusion's shipped ``fusion.py``: ``PlanarJointMotion`` exposes
    ``rotationValue``/``rotationLimits`` alongside ``primarySlideValue`` and
    ``secondarySlideValue``. A fake that omitted ``rotationValue`` would refuse a
    write Fusion accepts, which is the opposite failure to the one the strictness
    guard exists for.
    """
    handler, joint = _driven_joint(bound_handler, joint_type="planar")

    result = handler.set_joint_value(
        value=1.5, joint_name=joint.name, units="rad", as_built=False
    )

    assert result["attribute"] == "rotationValue"
    assert joint.jointMotion.rotationValue == pytest.approx(1.5)
