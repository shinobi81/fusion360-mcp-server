"""The draw tools must be able to name their sketch.

They resolved *the most recent sketch* and nothing else, so a part built from two
sketches had to be drawn strictly in creation order: any rectangle meant for the
first one landed in the second.  Every other sketch-consuming command already
takes ``sketch_name`` — ``add_constraint``, ``add_dimension``, ``trim_curve``,
``project_geometry`` — so the draw tools were the exception, and the exception is
what blocked building two sketches' geometry without relying on call order.

These tests run the handler against the shared fake runtime: a design with two
named sketches, drawing into the older one while the newer one is the most
recent.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from fusion360_mcp.mock import mock_command
from tests.fakes.design import FakeDesign
from tests.fakes.sketch import FakeSketch

# Every draw tool, with the smallest call that creates geometry in the fakes.
# ``draw_rectangle`` is first because it is the one whose absence of a target was
# reported (it silently landed in the wrong sketch).
DRAW_CALLS = [
    ("draw_rectangle", {"width": 2.0, "height": 1.0}),
    ("draw_circle", {"radius": 1.0}),
    ("draw_line", {"start_x": 0.0, "start_y": 0.0, "end_x": 1.0, "end_y": 1.0}),
    (
        "draw_arc",
        {
            "center_x": 0.0,
            "center_y": 0.0,
            "start_x": 1.0,
            "start_y": 0.0,
            "sweep_angle": 90.0,
        },
    ),
    ("draw_spline", {"spline_type": "fit_points", "points": [[0.0, 0.0], [1.0, 1.0]]}),
    ("create_polygon", {"sides": 6, "radius": 1.0}),
    ("draw_circles", {"count": 2, "radius": 0.5, "spacing": 2.0}),
]


@pytest.fixture
def two_sketches():
    """``(older, newer)`` in creation order, so ``newer`` is the last sketch."""
    older = FakeSketch(name="Sketch_plate")
    newer = FakeSketch(name="Sketch_slot")
    return older, newer


@pytest.mark.parametrize(("method", "kwargs"), DRAW_CALLS)
def test_a_named_sketch_receives_the_geometry(
    bound_handler, two_sketches, method, kwargs
):
    """Naming the older sketch must win over "the most recent one"."""
    older, newer = two_sketches
    handler = bound_handler(FakeDesign(sketches=[older, newer]))

    result = getattr(handler, method)(sketch_name="Sketch_plate", **kwargs)

    assert result["sketch"] == "Sketch_plate"
    assert older.curve_calls, f"{method} drew nothing into the sketch it named"
    assert newer.curve_calls == [], f"{method} also drew into the most recent sketch"
    # ``draw_circles`` and ``create_polygon`` defer the sketch solve while they
    # insert; resolving the wrong sketch would leave the other one deferred and
    # silently unsolved — a state this assertion is the only guard against.
    assert older.isComputeDeferred is False
    assert newer.isComputeDeferred is False


@pytest.mark.parametrize(("method", "kwargs"), DRAW_CALLS)
def test_the_most_recent_sketch_is_still_the_default(
    bound_handler, two_sketches, method, kwargs
):
    """Omitting the name must keep behaving exactly as before."""
    older, newer = two_sketches
    handler = bound_handler(FakeDesign(sketches=[older, newer]))

    result = getattr(handler, method)(**kwargs)

    assert result["sketch"] == "Sketch_slot"
    assert newer.curve_calls
    assert older.curve_calls == []


@pytest.mark.parametrize(("method", "kwargs"), DRAW_CALLS)
def test_an_unknown_sketch_name_is_refused(bound_handler, two_sketches, method, kwargs):
    """A typo must not silently fall back to the newest sketch."""
    older, newer = two_sketches
    handler = bound_handler(FakeDesign(sketches=[older, newer]))

    with pytest.raises(RuntimeError) as raised:
        getattr(handler, method)(sketch_name="Sketch_typo", **kwargs)

    assert classify(raised.value)[0] == "SKETCH_NOT_FOUND"
    assert older.curve_calls == [] and newer.curve_calls == []


# ── mock parity ───────────────────────────────────────────────────────


@pytest.mark.parametrize(("method", "kwargs"), DRAW_CALLS)
def test_mock_mode_echoes_the_sketch_it_was_told_to_use(method, kwargs):
    """Mock mode has no sketch list, so the echo is the only signal.

    Reporting ``Sketch_mock_xy`` regardless taught an agent that its
    ``sketch_name`` had been ignored — the one thing mock mode must not do.
    """
    result = mock_command(method, {**kwargs, "sketch_name": "Sketch_plate"})

    reported = result.get("sketch_name", result.get("sketch"))
    assert reported == "Sketch_plate"


@pytest.mark.parametrize(("method", "kwargs"), DRAW_CALLS)
def test_mock_mode_keeps_its_default_without_a_name(method, kwargs):
    result = mock_command(method, kwargs)

    reported = result.get("sketch_name", result.get("sketch"))
    assert reported == "Sketch_mock_xy"
