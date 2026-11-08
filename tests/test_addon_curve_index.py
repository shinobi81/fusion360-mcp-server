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

None of these handlers had ever run under a test: the fake sketch had no
``geometricConstraints``, ``sketchDimensions`` or ``sketchPoints`` at all, so the
guards below had to be preceded by a fake that can express the call.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from fusion360_mcp.mock import mock_command
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
        handler.sweep(
            profile_index=0, path_sketch_name="Sketch_path", path_curve_index=7
        )

    assert classify(raised.value)[0] == "INVALID_INPUT"


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

    ``radial``/``diameter`` are *not* covered here: the handler demands
    ``entity_two`` for every dimension type, so they cannot be created at all
    without a meaningless second index (measured live, filed not fixed).
    """
    design, sketch = four_curve_design()
    handler = bound_handler(design)

    handler.add_dimension("distance", 3.5, entity_one=1, entity_two=3)

    method, args = sketch.sketchDimensions.calls[0]
    assert method == "addDistanceDimension"
    curves = list(sketch.sketchCurves)
    assert args[0] is curves[1].startSketchPoint, "the curve the caller named"
    written = sketch.sketchDimensions.last_dimension
    assert written is not None and written.parameter.value == 3.5, (
        "the caller's value reached the dimension's parameter"
    )


# ── mock parity: the checks that need no geometry ─────────────────────


@pytest.mark.parametrize("index", [-1, 1.5, True])
def test_mock_refuses_an_index_that_cannot_name_a_curve(index):
    """Mock mode has no sketch, so it can only refuse what is never valid."""
    result = mock_command(
        "add_constraint", {"constraint_type": "parallel", "entity_one": index}
    )

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert result["hints"]


@pytest.mark.parametrize("index", [-1, 0.5])
def test_mock_dimension_refuses_a_negative_index(index):
    result = mock_command(
        "add_dimension",
        {"dimension_type": "distance", "value": 1.0, "entity_one": index},
    )

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
