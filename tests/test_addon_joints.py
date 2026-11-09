"""Table-and-schema agreement for the joint tools — and nothing else.

The add-in's *tables* are read statically: ``ast`` is the only way to check a
class-level table against a schema, and Fusion itself is not available to ask.  The
add-in is importable in CI now - see ``tests/test_addon_importable.py`` - so that is no
longer the reason: the reason is that a table is data, not behaviour.

**Every claim about behaviour has moved out.** It used to be the other way round:
this file parsed the source to check that ``add_joint`` returned certain keys, did
not swallow exceptions, drove joint values without recomputing, converted degrees
inside the right branch, and validated a face it cannot build from. A source scan
can see the shape of a statement; it cannot see whether the code runs.

* ``add_joint`` / ``create_as_built_joint`` → ``tests/test_addon_joint_frame.py``
  (result shape, refusal without geometry, failure propagation, frame resolution);
* driving a joint → ``tests/test_addon_joint_values.py`` (no recompute, viewport
  refresh, degrees only for angles, read-back failure, rigid has no value);
* "``createByPoint`` takes exactly one argument" → the fake declares Fusion's real
  single-argument signature, so a two-argument call raises ``TypeError`` in any
  test that reaches it, instead of needing a scan to notice.

What remains below is table-against-schema and table-against-literal. That cannot
be behavioural by nature: the schema is data, and a table asserting itself proves
nothing. Each test fails when the add-in's table and the published tool schema
drift apart, which is the one thing only a source read can catch.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fusion360_mcp.tools import TOOLS

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLER = REPO_ROOT / "addon" / "server" / "command_handler.py"


def _class_assign(attr: str):
    """Return the literal value of ``CommandHandler.<attr>`` parsed via AST."""
    tree = ast.parse(HANDLER.read_text())
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        if cls.name != "CommandHandler":
            continue
        for stmt in cls.body:
            # The tables are static, whether declared plain (``X = {...}``) or
            # annotated (``X: ClassVar[...] = {...}``, which is ast.AnnAssign and
            # has a single target).  Both are the same invariant; skipping the
            # annotated form would let a table drift out of this guard silently.
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            if stmt.value is not None and any(
                isinstance(t, ast.Name) and t.id == attr for t in targets
            ):
                value = stmt.value
                # frozenset({...}) / set({...}) -> unwrap the set literal
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in {"frozenset", "set"}
                    and value.args
                ):
                    return ast.literal_eval(value.args[0])
                return ast.literal_eval(value)
    raise AssertionError(f"CommandHandler.{attr} not found in {HANDLER}")


def _schema() -> dict:
    for tool in TOOLS:
        if tool["name"] == "add_joint":
            return tool["inputSchema"]
    raise AssertionError("add_joint schema missing from TOOLS")


def test_joint_motion_setters_cover_every_schema_type():
    """Every joint_type in the schema must map to a motion setter in the add-in."""
    setters = _class_assign("_JOINT_MOTION_SETTERS")
    schema_types = set(_schema()["properties"]["joint_type"]["enum"])

    assert set(setters) == schema_types, (
        "joint_type values in tools.py and _JOINT_MOTION_SETTERS drifted.\n"
        f"  only in schema: {sorted(schema_types - set(setters))}\n"
        f"  only in addon:  {sorted(set(setters) - schema_types)}"
    )
    for joint_type, (setter, _directions) in setters.items():
        assert setter.startswith("setAs") and setter.endswith("JointMotion"), (
            f"{joint_type!r} maps to {setter!r}, which is not a JointInput "
            "motion setter. A missing setter means the joint is added with no "
            "motion and Fusion infers one silently."
        )


def test_motion_setter_arities_are_pinned():
    """Pin the direction counts in _JOINT_MOTION_SETTERS against drift.

    A table read cannot prove Fusion accepts these arities: a wrong table would
    carry the same wrong numbers. All seven counts were confirmed by creating
    every joint type in Fusion, which raises TypeError on a wrong argument count.
    """
    setters = _class_assign("_JOINT_MOTION_SETTERS")

    assert setters["rigid"][1] == 0
    assert setters["pin_slot"][1] == 2
    assert setters["ball"][1] == 2
    for joint_type in ("revolute", "slider", "cylindrical", "planar"):
        assert setters[joint_type][1] == 1, (
            f"{joint_type} takes exactly one JointDirections argument"
        )


def test_the_world_axis_table_covers_the_joint_axes():
    """``_joint_direction`` indexes ``_WORLD_AXES`` with a key it checked against
    ``_JOINT_AXES``, so a fourth axis added to one and not the other would raise a
    bare ``KeyError`` instead of the "Use one of ..." refusal.
    """
    assert set(_class_assign("_WORLD_AXES")) == set(_class_assign("_JOINT_AXES"))


def test_direction_and_quadrant_enums_match_the_schema():
    """Schema enums must mirror the add-in's lookup tables."""
    props = _schema()["properties"]

    axes = set(_class_assign("_JOINT_AXES"))
    assert set(props["axis"]["enum"]) == axes
    assert set(props["second_axis"]["enum"]) == axes

    quadrants = set(_class_assign("_JOINT_QUADRANTS"))
    assert set(props["quadrant"]["enum"]) == quadrants

    key_points = set(_class_assign("_JOINT_KEY_POINTS"))
    assert set(props["key_point"]["enum"]) == key_points


def test_the_reversed_direction_arguments_are_the_two_measured_types():
    """Two joint types take their directions in the opposite order to `axis`.

    ball - Fusion takes (pitchDirection, yawDirection) and rejects a pitch
    parallel to the joint axis: verified on 2705, (X, Z) failed and (Z, X)
    produced a BallJointMotion.

    pin_slot - Fusion takes (rotationDirection, slideDirection), measured on 2706:
    passing the caller's axis first made it the ROTATION axis and left the slide on
    the perpendicular default, so `axis` never controlled the slide. The
    behavioural half is
    tests/test_addon_joint_frame.py::test_pin_slot_slides_along_the_axis_asked_for.
    """
    reversed_types = _class_assign("_JOINT_REVERSED_DIRECTION_ARGUMENTS")
    assert set(reversed_types) == {"ball", "pin_slot"}, (
        "exactly these two are measured to need reversed direction arguments, got "
        f"{reversed_types}"
    )


def test_set_joint_value_covers_every_driveable_motion_type():
    """Every non-rigid motion type maps to the attribute Fusion actually has.

    BallJointMotion exposes pitch/yaw/roll and no rotationValue; cylindrical,
    pin-slot and planar joints carry both an angle and slide values.
    """
    attrs = _class_assign("_JOINT_VALUE_ATTRIBUTES")
    expected = {
        "RevoluteJointMotion",
        "SliderJointMotion",
        "CylindricalJointMotion",
        "PinSlotJointMotion",
        "PlanarJointMotion",
        "BallJointMotion",
    }
    assert set(attrs) == expected, (
        f"driveable motion types changed: {sorted(set(attrs) ^ expected)}"
    )

    assert attrs["RevoluteJointMotion"] == {"rotation": "rotationValue"}
    assert attrs["SliderJointMotion"] == {"slide": "slideValue"}
    assert attrs["CylindricalJointMotion"]["rotation"] == "rotationValue"
    assert attrs["CylindricalJointMotion"]["slide"] == "slideValue"
    assert attrs["PinSlotJointMotion"]["slide"] == "slideValue"
    assert attrs["PlanarJointMotion"]["secondary_slide"] == "secondarySlideValue"

    assert attrs["BallJointMotion"] == {
        "rotation": "pitchValue",
        "pitch": "pitchValue",
        "yaw": "yawValue",
        "roll": "rollValue",
    }
    assert "rotationValue" not in attrs["BallJointMotion"].values(), (
        "BallJointMotion has no rotationValue attribute"
    )


def test_joint_angle_attributes_hold_no_lengths():
    """Only angle attributes may be converted between degrees and radians.

    ``slideValue`` and the planar slides are lengths in Fusion's internal unit,
    centimetres, so converting them is wrong by a factor of 180/pi.
    """
    angle_attrs = _class_assign("_JOINT_ANGLE_ATTRIBUTES")
    assert "rotationValue" in angle_attrs
    assert "pitchValue" in angle_attrs
    assert "slideValue" not in angle_attrs
    assert "primarySlideValue" not in angle_attrs
    assert "secondarySlideValue" not in angle_attrs

    attrs = _class_assign("_JOINT_VALUE_ATTRIBUTES")
    mapped = {name for kinds in attrs.values() for name in kinds.values()}
    assert set(angle_attrs) <= mapped, (
        f"angle attributes that no motion maps to: {sorted(set(angle_attrs) - mapped)}"
    )


def test_add_joint_schema_requires_the_face_pair():
    """The face pair is mandatory geometry, so the schema must say so.

    A caller should fail fast on a missing face instead of reaching Fusion and
    getting a runtime error. This assertion lived inside the behavioural scan that
    was retired; it is a pure schema read, which is exactly what this file keeps.
    """
    required = set(_schema()["required"])

    assert {"face_one", "face_two"} <= required, (
        "face_one/face_two are mandatory joint geometry and must be required in "
        f"the schema, so a caller fails fast (required: {sorted(required)})"
    )


def test_as_built_joint_schema_mirrors_add_joint():
    """Both joint tools take the same geometry arguments."""
    schema = {t["name"]: t["inputSchema"] for t in TOOLS}
    add = set(schema["add_joint"]["properties"])
    built = set(schema["create_as_built_joint"]["properties"])

    assert add == built, (
        "add_joint and create_as_built_joint accept different arguments, which "
        f"makes the snapping/non-snapping pair confusing.\n"
        f"  only in add_joint: {sorted(add - built)}\n"
        f"  only in create_as_built_joint: {sorted(built - add)}"
    )
