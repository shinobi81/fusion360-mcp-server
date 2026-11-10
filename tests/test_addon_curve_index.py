"""A curve index names a curve, or the call is refused.

`add_constraint`, `add_dimension`, `offset_curve`, `trim_curve`, `extend_curve`
and `sweep` all did `curves[index]` before any guard.  Three of Python's
behaviours then decide what the caller sees, and none of them is an answer:

* an index past the end raises ``IndexError`` -> ``UNKNOWN`` with **no hints**,
* a **negative** index silently wraps — ``curves[-1]`` is the last curve, so
  ``add_dimension(entity_one=-1)`` dimensioned a curve the caller never named and
  reported ``ok: true``,
* a fractional or boolean index raises ``TypeError``/indexes 0/1, and ``True`` is
  an ``int`` in Python.

Measured live on Fusion 2706 against a four-curve sketch: index 99 gave
``error_kind: UNKNOWN``, ``error_message: "list index out of range"``, and
``entity_one=-1, entity_two=-2`` gave ``ok: true``.  So this file pins identity —
*which* curve was chosen — not merely that something was.

None of the five sketch handlers had ever run under a test: the fake sketch had
no ``geometricConstraints``, ``sketchDimensions`` or ``sketchPoints`` at all, so
the guards below had to be preceded by a fake that can express the call.
``sweep`` is the exception — it already ran, but only ever with the default path
curve index, so its non-default index is what is new here.
"""

from __future__ import annotations

import pytest

import fusion360_mcp.mock as mock_mod
from fusion360_mcp.hints import classify
from fusion360_mcp.tools import TOOLS
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakePoint3D
from tests.fakes.sketch import FakeSketch


def sketch_with_lines(count: int, name: str = "Sketch1") -> FakeSketch:
    """A sketch holding *count* real line objects, which the handler indexes."""
    sketch = FakeSketch(name=name)
    for row in range(count):
        sketch.sketchCurves.sketchLines.addByTwoPoints(
            FakePoint3D(0.0, float(row), 0.0), FakePoint3D(1.0, float(row), 0.0)
        )
    # Setup, not subject: the assertions below read what the *handler* recorded.
    sketch.curve_calls.clear()
    return sketch


def four_curve_design() -> tuple[FakeDesign, FakeSketch]:
    """A design whose only sketch holds four lines, and that sketch."""
    sketch = sketch_with_lines(4)
    return FakeDesign(sketches=[sketch]), sketch


# ── the two handlers §23.2 named ──────────────────────────────────────


def test_add_constraint_refuses_an_index_past_the_last_curve(bound_handler):
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("parallel", entity_one=4, entity_two=0)

    assert classify(raised.value)[0] == "INVALID_INPUT"
    message = str(raised.value)
    assert "'Sketch1'" in message, "the refusal must name the sketch"
    assert "has 4 curve(s)" in message, "and how many there are to choose from"
    assert "0..3" in message, "and which indices are in range"


def test_add_constraint_refuses_a_negative_index(bound_handler):
    """``curves[-1]`` is the last curve — a silent wrong answer, not an error."""
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("parallel", entity_one=-1, entity_two=0)

    assert classify(raised.value)[0] == "INVALID_INPUT"
    assert sketch.geometricConstraints.added == [], (
        "no constraint may be added for a negative index"
    )


def test_add_dimension_refuses_a_negative_index(bound_handler):
    """Measured live: ``entity_one=-1, entity_two=-2`` returned ``ok: true``."""
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_dimension("distance", 5.0, entity_one=-1, entity_two=-2)

    assert classify(raised.value)[0] == "INVALID_INPUT"
    assert sketch.sketchDimensions.calls == [], (
        "no dimension may be added for a negative index"
    )


def test_add_dimension_refuses_an_index_past_the_last_curve(bound_handler):
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_dimension("distance", 5.0, entity_one=0, entity_two=99)

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    # A phrase unique to the new rule: the generic INVALID_INPUT rule would give
    # different hints, so this is what proves the rule matched rather than the
    # fallback (§19.4 - a rule sharing an error_kind with a generic one is
    # invisible unless a test asserts its own wording).
    assert any("0-based" in hint for hint in hints), hints


def test_the_symmetry_line_is_indexed_like_the_two_entities(bound_handler):
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("symmetry", entity_one=0, entity_two=1, symmetry_line=9)

    assert classify(raised.value)[0] == "INVALID_INPUT"
    assert "symmetry_line" in str(raised.value)


@pytest.mark.parametrize("index", [1.5, 4.0, True])
def test_an_index_that_is_not_a_whole_number_is_refused(bound_handler, index):
    """A float raises TypeError and ``True`` is an int — both reach Fusion's list."""
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("parallel", entity_one=index, entity_two=0)

    assert classify(raised.value)[0] == "INVALID_INPUT"


# ── the same unguarded index in four more handlers ────────────────────


CURVE_INDEX_CALLS = [
    ("offset_curve", {"offset_distance": 0.5}),
    ("trim_curve", {"point_x": 0.5, "point_y": 0.0}),
    ("extend_curve", {"point_x": 0.5, "point_y": 0.0}),
]


@pytest.mark.parametrize(("method", "kwargs"), CURVE_INDEX_CALLS)
@pytest.mark.parametrize("index", [9, -1, 1.5])
def test_every_curve_index_tool_refuses_a_bad_index(
    bound_handler, method, kwargs, index
):
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        getattr(handler, method)(curve_index=index, **kwargs)

    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_sweep_refuses_a_path_curve_index_past_the_end(bound_handler):
    profile = sketch_with_lines(4, name="Sketch_profile")
    path = sketch_with_lines(2, name="Sketch_path")
    handler = bound_handler(FakeDesign(sketches=[profile, path]))

    with pytest.raises(RuntimeError) as raised:
        # The profile has to be named: without it the handler takes the *last*
        # sketch, which is the path one, and the call would pass for the wrong
        # reason.
        handler.sweep(
            profile_index=0,
            path_sketch_name="Sketch_path",
            path_curve_index=7,
            sketch_name="Sketch_profile",
        )

    assert classify(raised.value)[0] == "INVALID_INPUT"
    assert "path_curve_index" in str(raised.value), (
        "the refusal names the field, not just the sketch"
    )
    assert "has 2 curve(s)" in str(raised.value), (
        "and the path sketch's count, not the profile's four"
    )


# ── the ordinary case still works ─────────────────────────────────────


def test_a_valid_index_still_adds_that_constraint(bound_handler):
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    result = handler.add_constraint("parallel", entity_one=0, entity_two=2)

    added = sketch.geometricConstraints.added
    assert result["constraint_type"] == "parallel"
    assert len(added) == 1
    method, args = added[0]
    assert method == "addParallel"
    curves = list(sketch.sketchCurves)
    assert args == (curves[0], curves[2]), "the two curves the caller named"


def test_a_valid_dimension_still_sets_its_value(bound_handler):
    """A distance dimension is the two-entity shape the tool documents.

    The one-entity types have their own tests below, where each type's needs are
    stated rather than inferred from the two-entity ones.
    """
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    handler.add_dimension("distance", 3.5, entity_one=1, entity_two=3)

    method, args = sketch.sketchDimensions.calls[0]
    assert method == "addDistanceDimension"
    curves = list(sketch.sketchCurves)
    assert args[0] is curves[1].startSketchPoint, "the curve the caller named"
    assert args[1] is curves[3].startSketchPoint, "and the second one it named"
    written = sketch.sketchDimensions.last_dimension
    assert written is not None and written.parameter.value == 3.5, (
        "the caller's value reached the dimension's parameter"
    )


@pytest.mark.parametrize(
    ("dimension_type", "orientation"),
    [
        ("distance", "aligned"),
        ("horizontal", "horizontal"),
        ("vertical", "vertical"),
    ],
)
def test_the_three_distance_shapes_ask_for_their_own_orientation(
    bound_handler, dimension_type, orientation
):
    """They share one branch, so only the enum argument tells them apart.

    A copy-paste that left the aligned orientation in the horizontal or vertical
    entry would dimension the right curves the wrong way and stay green.
    """
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    handler.add_dimension(dimension_type, 2.0, entity_one=0, entity_two=3)

    method, args = sketch.sketchDimensions.calls[0]
    assert method == "addDistanceDimension"
    assert args[2] == orientation


# ── mock parity: the checks that need no geometry ─────────────────────


@pytest.mark.parametrize("index", [-1, 1.5, True])
def test_mock_refuses_an_index_that_cannot_name_a_curve(index):
    """Mock mode has no sketch, so it can only refuse what is never valid."""
    result = mock_mod.mock_command(
        "add_constraint",
        {"constraint_type": "parallel", "entity_one": index, "entity_two": 1},
    )

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    message = result["error_message"]
    assert "0-based" in message or "whole-number" in message, (
        "the index check fired, not the shape one"
    )


@pytest.mark.parametrize("index", [-1, 0.5])
def test_mock_dimension_refuses_a_negative_index(index):
    result = mock_mod.mock_command(
        "add_dimension",
        {
            "dimension_type": "distance",
            "value": 1.0,
            "entity_one": index,
            "entity_two": 1,
        },
    )

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"


# Every tool the add-in guards takes an index; mock mode must not answer `ok` for
# one it can refuse without a sketch (negative, fractional, boolean).
MOCK_CURVE_INDEX_CALLS = [
    ("offset_curve", {"curve_index": -1, "offset_distance": 0.5}),
    ("trim_curve", {"curve_index": -1, "point_x": 0.5, "point_y": 0.0}),
    ("extend_curve", {"curve_index": 1.5, "point_x": 0.5, "point_y": 0.0}),
    ("sweep", {"profile_index": 0, "path_sketch_name": "P", "path_curve_index": -1}),
    ("sweep", {"profile_index": 0, "path_sketch_name": "P", "path_curve_index": True}),
]


@pytest.mark.parametrize(("method", "payload"), MOCK_CURVE_INDEX_CALLS)
def test_mock_refuses_a_bad_index_in_every_guarded_tool(method, payload):
    result = mock_mod.mock_command(method, payload)

    assert result["ok"] is False, f"mock mode accepted {method} with {payload}"
    assert result["error_kind"] == "INVALID_INPUT"
    assert result["hints"]


# ── what each type actually needs ─────────────────────────────────────


def test_a_radial_dimension_needs_only_the_curve_it_measures(bound_handler):
    """``radial`` measures one curve; demanding a second index made it impossible.

    Measured live before the fix: ``add_dimension("radial", 2.0, entity_one=0)`` was
    refused with "indices 0 and None must both name one" - a schema-legal call that
    could not be made at all.
    """
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    result = handler.add_dimension("radial", 2.0, entity_one=1)

    method, args = sketch.sketchDimensions.calls[0]
    assert method == "addRadialDimension"
    assert args[0] is list(sketch.sketchCurves)[1], "the curve the caller named"
    assert result["dimension_type"] == "radial"


def test_an_angular_dimension_gets_both_curves_in_the_order_named(bound_handler):
    """``angular`` is the other two-entity type, and it takes the curves themselves.

    ``distance`` hands over sketch points; ``angular`` hands over the curves, so
    the ``first``/``second`` narrowing has to reach it unchanged as well.
    """
    design, sketch = four_curve_design()
    handler = bound_handler(design)
    curves = list(sketch.sketchCurves)

    result = handler.add_dimension("angular", 30.0, entity_one=0, entity_two=3)

    method, (first, second, _text_point) = sketch.sketchDimensions.calls[0]
    assert method == "addAngularDimension"
    assert first is curves[0], "the curve the caller named"
    assert second is curves[3], "and the second one it named"
    assert (result["sketch"], result["value"]) == ("Sketch1", 30.0), (
        "the reply names the sketch and echoes the value"
    )


def test_a_diameter_dimension_needs_only_the_curve_it_measures(bound_handler):
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    handler.add_dimension("diameter", 4.0, entity_one=2)

    method, args = sketch.sketchDimensions.calls[0]
    assert method == "addDiameterDimension"
    assert args[0] is list(sketch.sketchCurves)[2]


def test_a_two_entity_dimension_without_its_second_index_is_refused(bound_handler):
    """The refusal names the field that is missing, not both of them."""
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_dimension("distance", 1.0, entity_one=0)

    message = str(raised.value)
    kind, hints = classify(message)
    assert kind == "INVALID_INPUT" and hints
    assert "entity_two" in message


def test_a_midpoint_constraint_indexes_a_point_not_a_curve(bound_handler):
    """``midpoint``'s first entity is a POINT; a curve index names the wrong item.

    A sketch with four curves and five points makes the two index spaces differ, so
    a point index of 4 cannot be mistaken for a curve index.
    """
    design, sketch = four_curve_design()
    for row in range(4):
        sketch.sketchPoints.add(FakePoint3D(float(row), 5.0, 0.0))
    handler = bound_handler(design)

    handler.add_constraint("midpoint", entity_one=4, entity_two=0)

    method, args = sketch.geometricConstraints.added[0]
    assert method == "addMidPoint"
    assert args[0] is sketch.sketchPoints.item(4), "the point the caller named"
    assert args[1] is next(iter(sketch.sketchCurves))


def test_a_midpoint_point_index_past_the_last_point_is_refused(bound_handler):
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("midpoint", entity_one=99, entity_two=0)

    message = str(raised.value)
    kind, hints = classify(message)
    assert kind == "INVALID_INPUT" and hints
    assert "point(s)" in message, "the refusal speaks about points, not curves"


def test_a_two_entity_constraint_without_its_second_index_is_refused(bound_handler):
    """``addParallel(e1, None)`` reached Fusion and reported success."""
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("parallel", entity_one=0)

    message = str(raised.value)
    kind, _hints = classify(message)
    assert kind == "INVALID_INPUT"
    assert "entity_two" in message


# ── mock mode and the handler agree about the shape each type needs ───

#: Derived from the mock's tables, not written out: a fourth copy of the same
#: knowledge is a fourth thing to drift.  ``test_the_*_tables_and_the_schema_agree``
#: then ties the handler's table and the tool schema to these.
DIMENSION_SHAPES = sorted(mock_mod._DIMENSION_NEEDS_TWO.items())
CONSTRAINT_SHAPES = sorted(mock_mod._CONSTRAINT_NEEDS_TWO.items())


@pytest.mark.parametrize("dimension_type, needs_two", DIMENSION_SHAPES)
def test_mock_and_handler_agree_about_a_dimension_shape(
    bound_handler, handler_module, dimension_type, needs_two
):
    """A shape real mode accepts must be accepted in mock mode, and vice versa.

    Mock mode is where an agent develops the sequence it replays, so a shape the
    handler refuses must not come back ``ok`` there - which is how a radial
    dimension became impossible without a meaningless second index.
    """
    needed = handler_module.CommandHandler._DIMENSION_ENTITIES[dimension_type]
    assert (len(needed) == 2) is needs_two, "handler table and mock table agree"

    design, _sketch = four_curve_design()
    handler = bound_handler(design)
    params = {"dimension_type": dimension_type, "value": 1.0, "entity_one": 0}
    if needs_two:
        params["entity_two"] = 1

    handler.add_dimension(**params)
    assert mock_mod.mock_command("add_dimension", dict(params))["ok"] is True

    if needs_two:
        short = {key: value for key, value in params.items() if key != "entity_two"}
        with pytest.raises(RuntimeError, match="entity_two"):
            handler.add_dimension(**short)
        assert mock_mod.mock_command("add_dimension", dict(short))["ok"] is False


@pytest.mark.parametrize("constraint_type, needs_two", CONSTRAINT_SHAPES)
def test_mock_and_handler_agree_about_a_constraint_shape(
    bound_handler, handler_module, constraint_type, needs_two
):
    _kind, handler_needs_two = handler_module.CommandHandler._CONSTRAINT_ENTITIES[
        constraint_type
    ]
    assert handler_needs_two is needs_two, "handler table and mock table agree"

    design, sketch = four_curve_design()
    if constraint_type == "midpoint":
        sketch.sketchPoints.add(FakePoint3D(0.0, 5.0, 0.0))
    handler = bound_handler(design)
    params = {"constraint_type": constraint_type, "entity_one": 0}
    if needs_two:
        params["entity_two"] = 1
    if constraint_type == "symmetry":
        params["symmetry_line"] = 2

    handler.add_constraint(**params)
    assert mock_mod.mock_command("add_constraint", dict(params))["ok"] is True

    if needs_two:
        short = {key: value for key, value in params.items() if key != "entity_two"}
        with pytest.raises(RuntimeError, match="entity_two"):
            handler.add_constraint(**short)
        assert mock_mod.mock_command("add_constraint", dict(short))["ok"] is False


def test_a_one_entity_dimension_labels_outside_the_curve_centre(bound_handler):
    """Fusion refuses a radial label at the curve's centre; the box corner works.

    Measured on 2706: the label point used to be the world origin for every type,
    and ``addRadialDimension`` over a circle centred there raised "3 : Some input
    argument is invalid" - so the dimension could not be created even once the
    index guard stopped refusing it.
    """
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    handler.add_dimension("radial", 2.0, entity_one=1)

    _method, args = sketch.sketchDimensions.calls[0]
    text_point = args[1]
    box = list(sketch.sketchCurves)[1].boundingBox
    assert (
        text_point.x,
        text_point.y,
        text_point.z,
    ) == (box.maxPoint.x, box.maxPoint.y, box.maxPoint.z)


def test_a_two_entity_dimension_keeps_the_origin_label(bound_handler):
    """The two-entity path accepts the origin, measured on the same run."""
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    handler.add_dimension("distance", 1.0, entity_one=0, entity_two=1)

    _method, args = sketch.sketchDimensions.calls[0]
    assert (args[3].x, args[3].y, args[3].z) == (0.0, 0.0, 0.0)


def _tool_enum(tool_name: str, field: str) -> set:
    for tool in TOOLS:
        if tool["name"] == tool_name:
            return set(tool["inputSchema"]["properties"][field]["enum"])
    raise AssertionError(f"{tool_name} is not a tool")


def test_the_dimension_tables_and_the_schema_agree(handler_module):
    """Three copies of the same knowledge - handler, mock, schema - in one place.

    Set equality in both directions: a type added to one and forgotten in another
    is exactly the drift a fixed list of test cases cannot see.
    """
    handler_types = set(handler_module.CommandHandler._DIMENSION_ENTITIES)

    assert handler_types == _tool_enum("add_dimension", "dimension_type")
    assert handler_types == set(mock_mod._DIMENSION_NEEDS_TWO)


def test_the_constraint_tables_and_the_schema_agree(handler_module):
    handler_types = set(handler_module.CommandHandler._CONSTRAINT_ENTITIES)

    assert handler_types == _tool_enum("add_constraint", "constraint_type")
    assert handler_types == set(mock_mod._CONSTRAINT_NEEDS_TWO)


def test_mock_refuses_a_call_missing_its_first_entity():
    """Mock mode invented ``entity_one: 0`` and reported success.

    The handler refuses every type without ``entity_one``, so mock mode teaching
    that shape would send an agent to a guaranteed failure.
    """
    for command, params in (
        (
            "add_dimension",
            {"dimension_type": "distance", "value": 1.0, "entity_two": 1},
        ),
        ("add_constraint", {"constraint_type": "parallel", "entity_two": 1}),
    ):
        result = mock_mod.mock_command(command, params)

        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"
        assert result["hints"]
        assert "entity_one" in result["error_message"]


def test_a_non_integer_point_index_is_refused_with_point_advice(bound_handler):
    """This message matches the POINT rule and nothing else.

    ``is outside sketch`` would be caught by the curve rule, so only a
    non-integer point index proves the point rule exists and is ordered first.
    """
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.add_constraint("midpoint", entity_one=1.5, entity_two=0)

    kind, hints = classify(str(raised.value))
    assert kind == "INVALID_INPUT"
    assert hints[0].startswith("Point indices are 0-based"), hints[0]


@pytest.mark.parametrize(
    "call, message",
    [
        (
            lambda handler: handler.add_dimension("scalar", 1.0, entity_one=0),
            "Unknown dimension type",
        ),
        (
            lambda handler: handler.add_constraint("glue", entity_one=0),
            "Unknown constraint type",
        ),
    ],
)
def test_an_unknown_type_is_refused_with_advice(bound_handler, call, message):
    """A typo used to reach the caller as UNKNOWN with no hints."""
    design, _sketch = four_curve_design()
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        call(handler)

    assert message in str(raised.value)
    kind, hints = classify(str(raised.value))
    assert kind == "INVALID_INPUT" and hints


@pytest.mark.parametrize(
    "command, params",
    [
        ("add_dimension", {"dimension_type": "scalar", "value": 1.0, "entity_one": 0}),
        ("add_constraint", {"constraint_type": "glue", "entity_one": 0}),
    ],
)
def test_mock_refuses_an_unknown_type_with_the_same_kind(command, params):
    result = mock_mod.mock_command(command, params)

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"


def test_an_unhashable_type_name_is_refused_not_crashed():
    """``dimension_type`` as a list used to raise out of ``mock_command``.

    ``table.get(kind)`` needs a hashable key, and a client can send a list.  The
    handler compares with ``==``, so it refuses cleanly; mock mode must match.
    """
    result = mock_mod.mock_command(
        "add_dimension", {"dimension_type": ["distance"], "entity_one": 0}
    )

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
