"""Which joint axis `axis` picks, and what `add_joint` reports about it.

`axis` used to be handed to Fusion as a literal ``JointDirections`` member, which
selects the **joint's own** axis, not the model's.  Measured on Fusion 2706 by reading
``slideDirectionVector`` back for each member, the frame is

    XAxisJointDirection -> secondaryAxisVector
    YAxisJointDirection -> thirdAxisVector
    ZAxisJointDirection -> primaryAxisVector

verified across four quadrants of a cylinder-Z body, a cylinder whose bore is world
X, and a cone.  For the fixture body (bore world Z, ``quadrant="middle"``) that frame is
X = -Y, Y = +Z, Z = -X, so world +X is only reachable as joint Z, sliding along -X.

The direction vectors asserted here are literals from those measurements, not values the
fake derives from the handler's own mapping, so a one-sided change fails.
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


def test_an_off_axis_bore_is_still_resolved_through_the_frame(joint):
    """A 45 degree bore: no joint axis is a model axis, and passthrough would show.

    Frame measured as 45 degrees in XZ: primary=(0.707,0,0.707), secondary=(0,1,0),
    third=(-0.707,0,0.707), so joint X=+Y, joint Y=(-0.707,0,0.707), joint Z=+X-ish.
    Asking for world X has no exact answer; asking for world Y has an exact one
    (joint X) and passthrough would have answered joint Y instead.
    """
    off_axis = {
        "origin": (0.0, 0.0, 0.0),
        "primary": (0.7071, 0.0, 0.7071),
        "secondary": (0.0, 1.0, 0.0),
        "third": (-0.7071, 0.0, 0.7071),
    }

    _, result_y, inp_y = joint(axis="y", frame=off_axis)

    assert inp_y.motion_directions == ("XAxisJointDirection",)
    assert result_y["axis_world"] == pytest.approx([0.0, 1.0, 0.0])


def test_a_two_direction_joint_never_gets_the_same_member_twice(joint):
    """Same 45 degree frame: world X and world Z both resolve to joint Y.

    pin_slot and ball take two directions, and Fusion refuses one that repeats
    ("Invalid parameter pitchDirection"), so the runner-up is used for the second.
    """
    off_axis = {
        "origin": (0.0, 0.0, 0.0),
        "primary": (0.7071, 0.0, 0.7071),
        "secondary": (0.0, 1.0, 0.0),
        "third": (-0.7071, 0.0, 0.7071),
    }

    _, _, inp = joint(axis="x", joint_type="pin_slot", frame=off_axis)

    slide, rotation = inp.motion_directions
    assert slide != rotation, (
        "pin_slot got the same JointDirections member twice, which Fusion refuses"
    )


def test_a_rigid_joint_still_takes_no_direction_argument(joint):
    _, _, inp = joint(joint_type="rigid")

    assert inp.motion_directions == ()


def test_the_design_is_recomputed_once_after_the_joint_is_added(joint):
    """Fusion needs the recompute after a joint moves components; it is counted."""
    handler, _, _ = joint(axis="x")

    assert handler._design().compute_all_calls == 1


def test_pin_slot_slides_along_the_axis_asked_for(joint):
    """Measured on 2706: `setAsPinSlotJointMotion(a, b)` makes `a` the ROTATION.

    Before pin_slot joined the reversed set, `axis` landed on the rotation and the
    slide stayed on the perpendicular default, so a pin slot never slid where it
    was told. The fake now reports the same order Fusion does, so this test fails
    on the old call order.
    """
    _, result, inp = joint(axis="x", joint_type="pin_slot")

    assert result["directions"]["slideDirection"] == pytest.approx(
        result["axis_world"]
    ), "the slide must follow the axis the caller asked for, not the default"
    assert inp.motion_directions[1] == "ZAxisJointDirection", (
        "the caller's axis must be passed SECOND, because Fusion reads the first "
        "argument as the rotation"
    )


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


@pytest.mark.parametrize(
    ("axis", "expected"),
    [
        # Literal, measured vectors — not what the fake derives from the handler's
        # own mapping, so a one-sided change to either fails here.
        ("x", [-1.0, 0.0, 0.0]),
        ("y", [0.0, -1.0, 0.0]),
        ("z", [0.0, 0.0, 1.0]),
    ],
)
def test_the_result_reports_the_direction_fusion_gives(joint, axis, expected):
    _, result, _ = joint(axis=axis)

    assert result["directions"]["slideDirection"] == pytest.approx(expected)
    assert result["axis_world"] == pytest.approx(expected)


def test_a_revolute_joint_reports_its_rotation_axis_and_no_slide(joint):
    """Measured on 2706: revolute exposes ``rotationAxisVector`` and nothing else."""
    _, result, _ = joint(axis="z", joint_type="revolute")

    assert "rotationAxis" in result["directions"]
    assert "slideDirection" not in result["directions"]


def test_a_planar_joint_reports_two_slide_directions(joint):
    """Measured: planar exposes normal + primary/secondary slide — it DOES slide.

    A single ``slide_direction`` field would have reported null for it, which is
    what the review caught before this shipped.
    """
    _, result, _ = joint(axis="z", joint_type="planar")

    directions = result["directions"]
    assert "normalDirection" in directions
    assert "primarySlideDirection" in directions
    assert "secondarySlideDirection" in directions


def test_a_cylindrical_joint_reports_only_a_rotation_axis(joint):
    """Measured: cylindrical's slide has no vector attribute on 2706."""
    _, result, _ = joint(axis="z", joint_type="cylindrical")

    assert set(result["directions"]) == {"rotationAxis"}


# ── isFlipped is not the lever ────────────────────────────────────────


def test_the_handler_never_flips_the_joint_to_fix_a_sign(joint):
    """Measured on 2706: setting ``JointInput.isFlipped`` did NOT reverse the slide.

    A flipped input still reported [0, -1, 0] for XAxis, so a handler that used it
    to chase a sign would be adjusting nothing.
    """
    _, _, inp = joint(axis="x")

    assert inp.isFlipped is False
