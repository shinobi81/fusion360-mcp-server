"""Which joint axis `axis` picks, and what `add_joint` reports about it.

`axis` used to be handed to Fusion as a literal ``JointDirections`` member, which
selects the **joint's own** axis, not the model's.  Measured on Fusion 2706 with
cylinder-face geometry whose bore is world Z:

    axis="x" -> slideDirectionVector [0, -1, 0]   (joint X is world -Y)
    axis="y" -> slideDirectionVector [0,  0, 1]   (joint Y is the bore)
    axis="z" -> slideDirectionVector [-1, 0, 0]   (joint Z is world -X)

so the joint frame is X = -third, Y = primary, Z = -secondary, and asking for
world +X has to pick Z.  These tests pin that mapping and the measurements
`add_joint` now returns, and they are behavioural: the fake builds the joint and
reports the motion Fusion would.

The quadruples here are the live measurement above; `tests/fakes/design.py`
derives its own `slideDirectionVector` from the same numbers, so a change to
either that is not a change to Fusion shows up as a failure.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence

#: What Fusion 2706 reports for a cylinder whose axis is world Z, radius 2, z 0..5
#: with quadrant="middle", key_point="end". The origin is on the SURFACE, never on
#: the bore, and all sixteen valid combinations were measured to be on it. The
#: frame is the one `createInput` was handed: X_joint = secondary = -Y,
#: Y_joint = third = +Z, Z_joint = primary = -X — measured by reading
#: ``slideDirectionVector`` back for each JointDirections member.
MEASURED = {
    "origin": (-2.0, 0.0, 5.0),
    "primary": (-1.0, 0.0, 0.0),
    "secondary": (0.0, -1.0, 0.0),
    "third": (0.0, 0.0, 1.0),
}


def _face(frame: dict) -> FakeFace:
    return FakeFace(joint_frame=frame)


def _design(frame: dict) -> FakeDesign:
    """Two components, one cylinder body each, both faces carrying *frame*."""
    design = FakeDesign(features=0)
    for name in ("A", "B"):
        body = FakeBody(f"{name}Body", faces=FakeCollection([_face(frame)]))
        component = FakeComponent(name, [body])
        design.rootComponent.occurrences.add(FakeOccurrence(component))
    return design


@pytest.fixture
def joint(bound_handler):
    """``joint(axis="x", joint_type="slider")`` -> (handler, result, input)."""

    def factory(axis="x", joint_type="slider", second_axis=None, frame=None):
        design = _design(frame or MEASURED)
        handler = bound_handler(design)
        result = handler.add_joint(
            component_one="A",
            component_two="B",
            joint_type=joint_type,
            body_one="ABody",
            face_one=0,
            body_two="BBody",
            face_two=0,
            axis=axis,
            second_axis=second_axis,
        )
        return handler, result, design.rootComponent.joints.last_input

    return factory


# ── the mapping ───────────────────────────────────────────────────────


def test_axis_x_picks_the_joint_axis_that_lies_along_world_x(joint):
    """World +X is joint Z (-secondary) on this geometry — and opposite, at that.

    The sign is not achievable: no member of this joint's frame points along +X,
    so the closest axis is -X. That is why the result has to report the world
    direction instead of leaving the caller to assume it.
    """
    _, result, inp = joint(axis="x")

    # The fake's enum members ARE their attribute names, so a test reads them
    # without importing `adsk` (which only exists inside Fusion at run time).
    assert inp.motion_directions == ("ZAxisJointDirection",)
    assert result["axis_world"] == pytest.approx([-1.0, 0.0, 0.0])


def test_axis_y_picks_the_joint_axis_along_world_y(joint):
    _, result, inp = joint(axis="y")

    assert inp.motion_directions == ("XAxisJointDirection",)
    assert result["axis_world"] == pytest.approx([0.0, -1.0, 0.0])


def test_axis_z_picks_the_bore(joint):
    """The one case the old code got right by accident: world Z is joint Y here."""
    _, result, inp = joint(axis="z")

    assert inp.motion_directions == ("YAxisJointDirection",)
    assert result["axis_world"] == pytest.approx([0.0, 0.0, 1.0])


def test_the_mapping_is_not_a_literal_enum_passthrough(joint):
    """The old behaviour — X for "x", Y for "y", Z for "z" — is what was wrong."""
    _, _, inp_x = joint(axis="x")
    _, _, inp_y = joint(axis="y")

    assert inp_x.motion_directions != ("XAxisJointDirection",)
    assert inp_y.motion_directions != ("YAxisJointDirection",)


def test_a_rigid_joint_still_takes_no_direction_argument(joint):
    _, _, inp = joint(joint_type="rigid")

    assert inp.motion_directions == ()


# ── what the result reports ───────────────────────────────────────────


def test_the_result_reports_where_the_joint_origin_landed(joint):
    """§7.1: on the surface, not on the bore. Silent before, so it is reported.

    Measured: every valid quadrant/height combination puts the origin at radius 2
    on the cylinder's surface, and ``CenterKeyPoint`` is refused outright.
    """
    _, result, _ = joint(axis="z")

    assert result["joint_origin"] == pytest.approx([-2.0, 0.0, 5.0])
    # primary is the geometry's own frame vector, -X for this body: the field
    # reports what Fusion said, not what a reader might assume the bore to be.
    assert result["primary_axis"] == pytest.approx([-1.0, 0.0, 0.0])


def test_the_result_reports_the_world_slide_direction(joint):
    _, result, _ = joint(axis="x")

    assert result["slide_direction"] == pytest.approx([-1.0, 0.0, 0.0])


def test_a_revolute_joint_reports_no_slide_direction(joint):
    """Revolute has no slide axis; the field must not claim one."""
    _, result, _ = joint(axis="z", joint_type="revolute")

    assert result["slide_direction"] is None


def test_the_origin_being_on_the_surface_is_visible_for_a_revolute_hinge(joint):
    """The reported origin is what lets a caller notice the offset hinge (§7.1)."""
    _, result, _ = joint(axis="z", joint_type="revolute")

    assert result["joint_origin"][0] == pytest.approx(-2.0)


# ── isFlipped is not the lever ────────────────────────────────────────


def test_the_handler_never_flips_the_joint_to_fix_a_sign(joint):
    """Measured on 2706: setting ``JointInput.isFlipped`` did NOT reverse the slide.

    A flipped input still reported [0, -1, 0] for XAxis, so a handler that used it
    to chase a sign would be adjusting nothing.
    """
    _, _, inp = joint(axis="x")

    assert inp.isFlipped is False
