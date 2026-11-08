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

from fusion360_mcp.hints import classify
from tests.fakes.bodies import FakeBody, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence
from tests.fakes.runtime import FakeJointGeometry, FakePoint3D

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


# ── as-built joints: the same frame plumbing, behaviourally ───────────


def _as_built(handler, **kwargs):
    """``create_as_built_joint`` with the fixture design's bodies filled in."""
    params = {
        "component_one": "A",
        "component_two": "B",
        "body_one": "ABody",
        "face_one": 0,
        "body_two": "BBody",
        "face_two": 0,
    }
    params.update(kwargs)
    return handler.create_as_built_joint(**params)


def test_an_as_built_joint_honours_its_joint_type(bound_handler):
    """It used to be rigid whatever was asked, and the AST guard could not see it.

    ``asBuiltJoints`` had no fake, so the only check on this was a source scan for
    ``_JOINT_MOTION_SETTERS``. Now the input records the motion that was set, which
    is the thing that was silently wrong.
    """
    design = _design(MEASURED)
    handler = bound_handler(design)

    result = _as_built(handler, joint_type="revolute", axis="z")

    inp = design.rootComponent.asBuiltJoints.last_input
    assert inp is not None, "no as-built input was created"
    assert inp.motion_setter == "setAsRevoluteJointMotion"
    assert result["motion"] == "RevoluteJointMotion"


def test_a_rigid_as_built_joint_needs_no_geometry(bound_handler):
    """Rigid is the one motion Fusion accepts without geometry."""
    design = _design(MEASURED)
    handler = bound_handler(design)

    _as_built(handler, joint_type="rigid")

    inp = design.rootComponent.asBuiltJoints.last_input
    assert inp is not None
    assert inp.motion_setter == "setAsRigidJointMotion"
    assert inp.geometry is None, "a rigid as-built joint must not need a face"


def test_a_non_rigid_as_built_joint_without_faces_is_refused(bound_handler):
    """Fusion: "Geometry should not be null if joint motion is not rigid"."""
    design = _design(MEASURED)
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.create_as_built_joint(
            component_one="A", component_two="B", joint_type="revolute"
        )

    assert "geometry" in str(raised.value).lower()
    assert design.rootComponent.asBuiltJoints.inputs == []


def test_an_unusable_face_two_is_reported_not_ignored(bound_handler):
    """``createInput`` takes one geometry, so face_two can be silently dropped.

    That is the failure the source scan was guarding: it asserted ``_joint_face``
    was called twice. Here the call is made and its refusal observed.
    """
    design = _design(MEASURED)
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        _as_built(handler, joint_type="revolute", face_two=9)

    assert design.rootComponent.asBuiltJoints.inputs == []


def test_an_as_built_joint_resolves_its_axis_through_the_frame(bound_handler):
    """The frame plumbing the AST guard could not reach at all.

    Same measured frame as ``add_joint``: world Z is joint Y here, so a passthrough
    would report ``ZAxisJointDirection`` and rotate about the wrong axis.
    """
    design = _design(MEASURED)
    handler = bound_handler(design)

    _as_built(handler, joint_type="revolute", axis="z")

    inp = design.rootComponent.asBuiltJoints.last_input
    assert inp is not None
    assert inp.motion_directions == ("YAxisJointDirection",)


# ── a degenerate frame has nothing to resolve against ─────────────────


def test_a_zero_length_axis_is_refused_instead_of_reported(joint):
    """``_joint_direction`` ranks by |dot|, so a zero vector wins every tie.

    With a degenerate frame the ranking is arbitrary and the chosen member carries
    [0, 0, 0] — which then reached the caller as ``axis_world`` and Fusion as a
    direction. There is no direction there to normalise.
    """
    degenerate = {
        "origin": (0.0, 0.0, 0.0),
        "primary": (1.0, 0.0, 0.0),
        "secondary": (0.0, 0.0, 0.0),
        "third": (0.0, 0.0, 1.0),
    }

    with pytest.raises(RuntimeError) as raised:
        joint(axis="y", frame=degenerate)

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert hints
    assert "zero-length" in str(raised.value)


def test_a_frame_with_no_axes_at_all_is_refused(joint):
    """Every member degenerate: no ranking question is even askable.

    This is the only case the rule's ``.*`` has to carry (the message joins the
    names as ``x/y/z``), so it asserts the classification too.
    """
    empty = {
        "origin": (0.0, 0.0, 0.0),
        "primary": (0.0, 0.0, 0.0),
        "secondary": (0.0, 0.0, 0.0),
        "third": (0.0, 0.0, 0.0),
    }

    with pytest.raises(RuntimeError) as raised:
        joint(axis="z", frame=empty)

    assert "zero-length" in str(raised.value)
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_a_rigid_joint_does_not_need_a_usable_frame(bound_handler):
    """Rigid resolves no axis, so a degenerate frame it never reads must not refuse.

    ``rigid`` is the default ``joint_type``, and the frame is built from the same
    geometry every joint takes — so a frame-wide guard would have turned a working
    default call into a refusal about an axis nothing was asked for.
    """
    design = _design({**MEASURED, "secondary": (0.0, 0.0, 0.0)})
    handler = bound_handler(design)

    result = handler.add_joint(
        component_one="A",
        component_two="B",
        joint_type="rigid",
        body_one="ABody",
        face_one=0,
        body_two="BBody",
        face_two=0,
    )

    assert result["created"] is True


def test_the_revolve_zero_length_message_keeps_its_own_hints():
    """The new rule is anchored so it does not capture a different refusal.

    ``revolve`` already refused a zero-length axis direction, and that message
    contains the same words. The joint rule matches "geometry's ... axis is
    zero-length", not the bare phrase, so the revolve refusal must still classify
    through the generic INVALID_INPUT rule — otherwise a caller building a revolve
    would be told to pick another joint face.
    """
    kind, hints = classify(
        "Invalid input: revolve axis direction is zero-length — pass a direction"
    )

    assert kind == "INVALID_INPUT"
    assert not any("joint" in hint.lower() for hint in hints), (
        f"the revolve refusal picked up the joint-frame hints: {hints}"
    )


def test_the_guard_does_not_fire_on_a_healthy_frame(joint):
    """The refusal is for degenerate frames only, not for every joint."""
    _, result, _ = joint(axis="z")

    assert result["axis_world"] == pytest.approx([0.0, 0.0, 1.0])


# ── behaviour the source scans used to stand in for ───────────────────


def test_add_joint_reports_what_the_snap_moved(joint):
    """A joint snaps components together; the result must say so.

    On a real assembly this surfaced as a 32.6 mm displacement between the halves
    of a hinge — the joint "worked" and quietly rearranged the design.

    **What this does and does not prove.** It observes the keys in the result the
    caller actually gets, which the source scan could not: a key present in one
    return dict but absent from the one that runs would have passed the scan. It
    cannot prove the *values* are right, because the fake never moves an
    occurrence — FakeJoints.createInput is given geometries, not the
    occurrences a snap would move, so moved_components is always empty here.
    Modelling that is a separate change; it is reported rather than papered over.
    """
    _, result, _ = joint(axis="x")

    assert "snapped" in result, f"no snap report in {sorted(result)}"
    assert "moved_components" in result, f"no displacement report in {sorted(result)}"
    # A mapping of component name -> [dx, dy, dz], listing only what moved.
    assert isinstance(result["moved_components"], dict), result["moved_components"]


def test_add_joint_refuses_without_face_geometry(bound_handler):
    """No faces means no joint geometry, and Fusion refuses that outright."""
    design = _design(MEASURED)
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_joint(component_one="A", component_two="B")

    assert "face_one/face_two" in str(raised.value)
    assert design.rootComponent.joints.inputs == [], (
        "no joint input may survive a refusal"
    )


def test_a_failing_joint_add_is_not_swallowed(bound_handler):
    """A swallowed exception is how two joint bugs shipped reporting success.

    The scan looked for `except Exception: pass`. This makes the call fail and
    watches the failure come back, which also covers every other way of hiding it.
    """
    design = _design(MEASURED)
    handler = bound_handler(design)

    def explode(item):
        raise RuntimeError("joints.add blew up")

    design.rootComponent.joints.add = explode

    with pytest.raises(RuntimeError) as raised:
        handler.add_joint(
            component_one="A",
            component_two="B",
            body_one="ABody",
            face_one=0,
            body_two="BBody",
            face_two=0,
            axis="x",
        )

    assert "blew up" in str(raised.value), (
        "add_joint reported success while the API call failed"
    )


def test_a_failing_as_built_add_is_not_swallowed(bound_handler):
    """Same claim as the regular joints, on the as-built path.

    The retired scan read `add_joint` only, so as-built was never covered there
    either — this closes the gap rather than preserving it.
    """
    design = _design(MEASURED)
    handler = bound_handler(design)

    def explode(item):
        raise RuntimeError("asBuiltJoints.add blew up")

    design.rootComponent.asBuiltJoints.add = explode

    with pytest.raises(RuntimeError) as raised:
        _as_built(handler, joint_type="rigid")

    assert "blew up" in str(raised.value), (
        "create_as_built_joint reported success while the API call failed"
    )


def test_the_fake_declares_create_by_point_with_one_argument():
    """Fusion's ``createByPoint`` takes a point, not an occurrence and a point.

    The stub is never called by a handler today, so the guard is Python's own
    arity check — but it only bites if the stub is exercised here.
    """
    geometry = FakeJointGeometry.createByPoint(FakePoint3D(1.0, 2.0, 3.0))

    assert geometry.origin.x == 1.0

    # Unpacked on purpose: the call is *meant* to be wrong, and a literal
    # two-argument call trips CodeQL's wrong-arity rule on the test itself
    # (py/wrong-number-of-arguments). Unpacking keeps the assertion and hides the
    # arity from static analysis, which cannot know a test calls a stub wrongly.
    two_points = (FakePoint3D(0.0, 0.0, 0.0), FakePoint3D(1.0, 0.0, 0.0))
    with pytest.raises(TypeError):
        FakeJointGeometry.createByPoint(*two_points)


#: What each joint_type must map to. Hard-coded from Fusion's JointInput, not read
#: from the handler's table: a test that reads the table cannot notice the table
#: naming the wrong setter.
AS_BUILT_SETTERS = [
    ("rigid", "setAsRigidJointMotion"),
    ("revolute", "setAsRevoluteJointMotion"),
    ("slider", "setAsSliderJointMotion"),
    ("cylindrical", "setAsCylindricalJointMotion"),
    ("planar", "setAsPlanarJointMotion"),
    ("pin_slot", "setAsPinSlotJointMotion"),
    ("ball", "setAsBallJointMotion"),
]


@pytest.mark.parametrize(("joint_type", "setter"), AS_BUILT_SETTERS)
def test_an_as_built_joint_uses_the_setter_its_type_maps_to(
    bound_handler, joint_type, setter
):
    """All seven types, not just revolute and rigid.

    A handler that hard-coded one setter would be caught by the pair of tests
    above; a handler that hard-coded *one of the other five* would not.
    """
    design = _design(MEASURED)
    handler = bound_handler(design)

    _as_built(handler, joint_type=joint_type, axis="z")

    inp = design.rootComponent.asBuiltJoints.last_input
    assert inp is not None, "no as-built input was created"
    assert inp.motion_setter == setter
