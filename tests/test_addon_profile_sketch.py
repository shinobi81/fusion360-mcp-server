"""Which sketch the *profile* comes from, for the three feature tools.

``extrude``, ``revolve`` and ``sweep`` all took the profile from *the most recent
sketch*, so a part whose profiles live in two sketches had to be built in
creation order — the same defect #35 fixed for the ``draw_*`` tools.  ``sweep``
was the oddest case: it names its *path* sketch by name while leaving the
*profile* implicit, so a sweep across two sketches was half explicit.

These run the handler against the shared fake runtime: a design holding two named
sketches, extruding/revolving/sweeping the **older** one's profile while the newer
one is the most recent.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from fusion360_mcp.mock import mock_command
from tests.fakes.design import FakeDesign
from tests.fakes.sketch import FakeSketch


@pytest.fixture
def two_profiles(bound_handler):
    """``(handler, older, newer)`` — older is the sketch that must be used."""
    older = FakeSketch(name="Sketch_plate", profile_count=1)
    newer = FakeSketch(name="Sketch_slot", profile_count=1)
    handler = bound_handler(FakeDesign(sketches=[older, newer]))
    return handler, older, newer


def test_extrude_uses_the_named_sketch_profile(two_profiles):
    handler, older, _ = two_profiles

    result = handler.extrude(height=2.0, sketch_name="Sketch_plate")

    assert result["sketch"] == "Sketch_plate"
    used = handler._root().features.extrudeFeatures.added[0].profile
    assert used.sketch is older


def test_extrude_still_defaults_to_the_most_recent_sketch(two_profiles):
    handler, _, newer = two_profiles

    result = handler.extrude(height=2.0)

    assert result["sketch"] == "Sketch_slot"
    assert handler._root().features.extrudeFeatures.added[0].profile.sketch is newer


def test_revolve_uses_the_named_sketch_profile(two_profiles):
    handler, older, _ = two_profiles

    result = handler.revolve(angle=90.0, sketch_name="Sketch_plate")

    assert result["sketch"] == "Sketch_plate"
    assert handler._root().features.revolveFeatures.added[0].profile.sketch is older


def test_sweep_can_name_the_profile_sketch_and_the_path_sketch(
    bound_handler,
):
    """The point of the fix: path *and* profile named, not one of each."""
    profile_sketch = FakeSketch(name="Sketch_profile", profile_count=1)
    path_sketch = FakeSketch(name="Sketch_path", profile_count=0)
    # sweep takes a path curve by index, so the path sketch needs one.
    path_sketch.sketchCurves.sketchLines.addByTwoPoints((0, 0, 0), (1, 0, 0))
    newest = FakeSketch(name="Sketch_newest", profile_count=1)
    handler = bound_handler(FakeDesign(sketches=[profile_sketch, path_sketch, newest]))

    result = handler.sweep(
        profile_index=0,
        path_sketch_name="Sketch_path",
        sketch_name="Sketch_profile",
    )

    assert result["sketch"] == "Sketch_profile"
    used = handler._root().features.sweepFeatures.added[0].profile
    assert used.sketch is profile_sketch


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("extrude", {"height": 2.0}),
        ("revolve", {"angle": 90.0}),
        (
            "sweep",
            {"profile_index": 0, "path_sketch_name": "Sketch_slot"},
        ),
    ],
)
def test_an_unknown_profile_sketch_is_refused(two_profiles, method, kwargs):
    handler, _, _ = two_profiles

    with pytest.raises(RuntimeError) as raised:
        getattr(handler, method)(sketch_name="Sketch_typo", **kwargs)

    assert classify(raised.value)[0] == "SKETCH_NOT_FOUND"


@pytest.mark.parametrize(
    ("mock_name", "params"),
    [
        ("extrude", {"height": 2.0}),
        ("revolve", {"angle": 90.0}),
        ("sweep", {"profile_index": 0, "path_sketch_name": "Sketch_path"}),
    ],
)
def test_mock_mode_echoes_the_profile_sketch(mock_name, params):
    """Mock mode reports which sketch held the profile, as the handler does."""
    result = mock_command(mock_name, {**params, "sketch_name": "Sketch_plate"})
    assert result["sketch"] == "Sketch_plate"
