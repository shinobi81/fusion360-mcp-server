"""Which body a ``extrude``, ``revolve``, ``sweep`` or ``loft`` cut may touch.

All four leave ``participantBodies`` unset, and Fusion then applies the operation
to **every** body the profile reaches.  Measured live on 2706: a loft whose
sections spanned the seam between two touching blocks cut *both* of them.  Naming
the target restricts the operation to the body the caller meant.

Fusion exposes the choice on the feature input (``participantBodies``), so the
add-in sets a property and recreates nothing.  These tests record what the input
was told, because what matters is the value that reached Fusion.

``loft`` had no fake at all before this file, so the two characterisation tests
below (sections, and the empty-sketch refusal) are the first that ever run it.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from fusion360_mcp.mock import mock_command
from tests.fakes.bodies import FakeBody
from tests.fakes.design import FakeDesign
from tests.fakes.sketch import FakeSketch


@pytest.fixture
def two_bodies(bound_handler):
    """A handler whose design holds a ``Block`` and an unrelated ``Other``."""
    handler = bound_handler(
        FakeDesign(
            bodies=[FakeBody("Block"), FakeBody("Other")],
            sketches=[FakeSketch(name="Sketch_profile", profile_count=1)],
        )
    )
    return handler


@pytest.fixture
def loft_design(bound_handler):
    """Two profiled sketches, which is the minimum a loft needs."""
    handler = bound_handler(
        FakeDesign(
            bodies=[FakeBody("Block"), FakeBody("Other")],
            sketches=[
                FakeSketch(name="Sketch_bottom", profile_count=1),
                FakeSketch(name="Sketch_top", profile_count=1),
            ],
        )
    )
    return handler


def _participants(handler, collection):
    built = getattr(handler._root().features, collection).added[-1]
    return [body.name for body in built.participantBodies]


# ── extrude ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("operation", ["cut", "join", "intersect"])
def test_extrude_targets_only_the_named_body(two_bodies, operation):
    result = two_bodies.extrude(height=2.0, operation=operation, target_body="Block")

    assert result["target_body"] == "Block"
    assert _participants(two_bodies, "extrudeFeatures") == ["Block"]


def test_extrude_without_a_target_leaves_the_bodies_to_fusion(two_bodies):
    result = two_bodies.extrude(height=2.0, operation="cut")

    assert result["target_body"] is None
    assert _participants(two_bodies, "extrudeFeatures") == []


def test_extrude_refuses_a_target_body_that_does_not_exist(two_bodies):
    with pytest.raises(RuntimeError) as raised:
        two_bodies.extrude(height=2.0, operation="cut", target_body="Blok")

    assert classify(raised.value)[0] == "BODY_NOT_FOUND"
    assert two_bodies._root().features.extrudeFeatures.added == []
    assert two_bodies._root().features.extrudeFeatures.inputs == []


def test_extrude_refuses_a_target_body_on_a_new_body(two_bodies):
    with pytest.raises(RuntimeError) as raised:
        two_bodies.extrude(height=2.0, operation="new_body", target_body="Block")

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("nothing to target" in hint for hint in hints)
    assert two_bodies._root().features.extrudeFeatures.added == []
    assert two_bodies._root().features.extrudeFeatures.inputs == []


# ── sweep ────────────────────────────────────────────────────────────


@pytest.fixture
def sweep_design(bound_handler):
    """A profile sketch and a path sketch with a curve to sweep along."""
    profile = FakeSketch(name="Sketch_profile", profile_count=1)
    path = FakeSketch(name="Sketch_path", profile_count=0)
    path.sketchCurves.sketchLines.addByTwoPoints((0, 0, 0), (5, 0, 0))
    handler = bound_handler(
        FakeDesign(
            bodies=[FakeBody("Block"), FakeBody("Other")],
            sketches=[profile, path],
        )
    )
    return handler


@pytest.mark.parametrize("operation", ["cut", "join", "intersect"])
def test_sweep_targets_only_the_named_body(sweep_design, operation):
    result = sweep_design.sweep(
        profile_index=0,
        path_sketch_name="Sketch_path",
        operation=operation,
        target_body="Block",
        sketch_name="Sketch_profile",
    )

    assert result["target_body"] == "Block"
    assert _participants(sweep_design, "sweepFeatures") == ["Block"]


def test_sweep_without_a_target_leaves_the_bodies_to_fusion(sweep_design):
    result = sweep_design.sweep(
        profile_index=0,
        path_sketch_name="Sketch_path",
        operation="cut",
        sketch_name="Sketch_profile",
    )

    assert result["target_body"] is None
    assert _participants(sweep_design, "sweepFeatures") == []


def test_sweep_refuses_a_target_body_that_does_not_exist(sweep_design):
    with pytest.raises(RuntimeError) as raised:
        sweep_design.sweep(
            profile_index=0,
            path_sketch_name="Sketch_path",
            operation="cut",
            target_body="Blok",
            sketch_name="Sketch_profile",
        )

    assert classify(raised.value)[0] == "BODY_NOT_FOUND"
    assert sweep_design._root().features.sweepFeatures.added == []
    assert sweep_design._root().features.sweepFeatures.inputs == []


def test_sweep_refuses_a_target_body_on_a_new_body(sweep_design):
    with pytest.raises(RuntimeError) as raised:
        sweep_design.sweep(
            profile_index=0,
            path_sketch_name="Sketch_path",
            operation="new_body",
            target_body="Block",
            sketch_name="Sketch_profile",
        )

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("nothing to target" in hint for hint in hints)
    assert sweep_design._root().features.sweepFeatures.added == []
    assert sweep_design._root().features.sweepFeatures.inputs == []


# ── revolve ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("operation", ["cut", "join", "intersect"])
def test_revolve_targets_only_the_named_body(two_bodies, operation):
    """Without the property, Fusion decides — and it picks every body it reaches."""
    result = two_bodies.revolve(angle=360, operation=operation, target_body="Block")

    assert result["target_body"] == "Block"
    assert _participants(two_bodies, "revolveFeatures") == ["Block"]


def test_revolve_without_a_target_leaves_the_bodies_to_fusion(two_bodies):
    """The shipped behaviour stays the default: no name, no restriction."""
    result = two_bodies.revolve(angle=360, operation="cut")

    assert result["target_body"] is None
    assert _participants(two_bodies, "revolveFeatures") == []


def test_revolve_refuses_a_target_body_that_does_not_exist(two_bodies):
    """A typo must not silently become "every body" — the cut would be wider."""
    with pytest.raises(RuntimeError) as raised:
        two_bodies.revolve(angle=360, operation="cut", target_body="Blok")

    assert classify(raised.value)[0] == "BODY_NOT_FOUND"
    assert two_bodies._root().features.revolveFeatures.added == []


def test_revolve_refuses_a_target_body_on_a_new_body(two_bodies):
    """A new body has no target; accepting the name would report work it ignored."""
    with pytest.raises(RuntimeError) as raised:
        two_bodies.revolve(angle=360, operation="new_body", target_body="Block")

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    # The specific rule, not the generic "invalid input" one: that one talks
    # about units and enums, which is the wrong thing to go and check.
    assert any("nothing to target" in hint for hint in hints)
    assert two_bodies._root().features.revolveFeatures.added == []


# ── loft ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("operation", ["cut", "join", "intersect"])
def test_loft_targets_only_the_named_body(loft_design, operation):
    result = loft_design.loft(
        profile_sketch_names=["Sketch_bottom", "Sketch_top"],
        operation=operation,
        target_body="Block",
    )

    assert result["target_body"] == "Block"
    assert _participants(loft_design, "loftFeatures") == ["Block"]


def test_loft_without_a_target_leaves_the_bodies_to_fusion(loft_design):
    result = loft_design.loft(profile_sketch_names=["Sketch_bottom", "Sketch_top"])

    assert result["target_body"] is None
    assert _participants(loft_design, "loftFeatures") == []


def test_loft_refuses_a_target_body_that_does_not_exist(loft_design):
    with pytest.raises(RuntimeError) as raised:
        loft_design.loft(
            profile_sketch_names=["Sketch_bottom", "Sketch_top"],
            operation="cut",
            target_body="Blok",
        )

    assert classify(raised.value)[0] == "BODY_NOT_FOUND"
    assert loft_design._root().features.loftFeatures.added == []


def test_loft_refuses_a_target_body_on_a_new_body(loft_design):
    with pytest.raises(RuntimeError) as raised:
        loft_design.loft(
            profile_sketch_names=["Sketch_bottom", "Sketch_top"],
            operation="new_body",
            target_body="Block",
        )

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("nothing to target" in hint for hint in hints)
    assert loft_design._root().features.loftFeatures.added == []


def test_a_bad_operation_is_reported_before_a_bad_target_body(
    two_bodies, loft_design, sweep_design
):
    """With two mistakes in one call, name the one that invalidates the other.

    ``union`` is not an operation, so nothing else about the call matters — and a
    caller told to fix a body name would fix it and be refused again.
    """
    with pytest.raises(RuntimeError) as revolve_error:
        two_bodies.revolve(angle=360, operation="union", target_body="Blok")

    with pytest.raises(RuntimeError) as loft_error:
        loft_design.loft(
            profile_sketch_names=["Sketch_bottom", "Sketch_top"],
            operation="union",
            target_body="Blok",
        )

    with pytest.raises(RuntimeError) as extrude_error:
        two_bodies.extrude(height=2.0, operation="union", target_body="Blok")

    with pytest.raises(RuntimeError) as sweep_error:
        sweep_design.sweep(
            profile_index=0,
            path_sketch_name="Sketch_path",
            operation="union",
            target_body="Blok",
        )

    for raised in (revolve_error, loft_error, extrude_error, sweep_error):
        assert "Unknown operation" in str(raised.value)


def test_a_refused_target_body_leaves_no_sketch_geometry_behind(bound_handler):
    """A non-world axis becomes a construction line in the profile's sketch.

    The refusal has to precede that line, or a call the caller was told did
    nothing leaves geometry in their sketch.
    """
    sketch = FakeSketch(name="Sketch_profile", profile_count=1)
    handler = bound_handler(FakeDesign(bodies=[FakeBody("Block")], sketches=[sketch]))

    with pytest.raises(RuntimeError) as raised:
        handler.revolve(
            angle=360,
            operation="cut",
            target_body="Blok",
            axis_direction_x=1,
            axis_direction_y=1,
        )

    assert classify(raised.value)[0] == "BODY_NOT_FOUND"
    assert sketch.curve_calls == []


def test_a_refused_loft_target_body_never_creates_a_feature_input(loft_design):
    """No input, so no loft object exists to be half-built."""
    with pytest.raises(RuntimeError):
        loft_design.loft(
            profile_sketch_names=["Sketch_bottom", "Sketch_top"],
            operation="cut",
            target_body="Blok",
        )

    assert loft_design._root().features.loftFeatures.inputs == []


def test_loft_refuses_a_single_profile(loft_design):
    """One profile is a zero-length loft.

    Fusion's own "needs at least two sections" message classified as UNKNOWN with
    no hints, so the add-in refuses the call before asking Fusion.
    """
    with pytest.raises(RuntimeError) as raised:
        loft_design.loft(profile_sketch_names=["Sketch_bottom"])

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("two or more" in hint for hint in hints)
    assert loft_design._root().features.loftFeatures.inputs == []


def test_the_fake_loft_still_refuses_one_section_on_its_own():
    """Fusion refuses a one-section loft; the fake models Fusion, not our guard."""
    from tests.fakes.design import FakeLoftFeatures

    features = FakeLoftFeatures()
    with pytest.raises(RuntimeError):
        features.add(features.createInput(object()))


def test_loft_adds_one_section_per_named_sketch_in_order(loft_design):
    """The sections are what the loft follows; reordering them twists the solid."""
    loft_design.loft(profile_sketch_names=["Sketch_top", "Sketch_bottom"])

    built = loft_design._root().features.loftFeatures.added[-1]
    assert [section.sketch.name for section in built.loftSections] == [
        "Sketch_top",
        "Sketch_bottom",
    ]


def test_loft_refuses_a_named_sketch_with_no_profile(loft_design):
    """Fusion cannot loft an empty sketch, and the message must name it."""
    empty = FakeSketch(name="Sketch_empty", profile_count=0)
    loft_design._root().sketches.add(empty)

    with pytest.raises(RuntimeError) as raised:
        loft_design.loft(profile_sketch_names=["Sketch_bottom", "Sketch_empty"])

    assert "Sketch_empty" in str(raised.value)
    assert classify(raised.value)[0] == "PROFILE_NOT_CLOSED"
    assert loft_design._root().features.loftFeatures.added == []


def test_an_unknown_operation_is_the_error_a_target_body_call_reports(
    two_bodies, loft_design
):
    """A mistyped operation is the root cause, so its message must win.

    Validating ``target_body`` first would report the wrong cause and send the
    caller looking for a body when the operation name is what is wrong.
    """
    with pytest.raises(RuntimeError) as revolve_error:
        two_bodies.revolve(angle=360, operation="union", target_body="Block")

    with pytest.raises(RuntimeError) as loft_error:
        loft_design.loft(
            profile_sketch_names=["Sketch_bottom", "Sketch_top"],
            operation="union",
            target_body="Block",
        )

    for raised in (revolve_error, loft_error):
        assert "Unknown operation" in str(raised.value)
        assert classify(raised.value)[0] == "INVALID_INPUT"


# ── mock parity ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mock_name", "params"),
    [
        ("revolve", {"angle": 360, "operation": "cut"}),
        (
            "loft",
            {
                "profile_sketch_names": ["Sketch_bottom", "Sketch_top"],
                "operation": "cut",
            },
        ),
        ("extrude", {"height": 2.0, "operation": "cut"}),
        (
            "sweep",
            {
                "profile_index": 0,
                "path_sketch_name": "Sketch_path",
                "operation": "cut",
            },
        ),
    ],
)
def test_mock_mode_echoes_the_target_body(mock_name, params):
    result = mock_command(mock_name, {**params, "target_body": "Block"})

    assert result["target_body"] == "Block"


def test_mock_mode_refuses_a_single_loft_profile():
    """The schema already requires two; a raw socket caller is not the schema."""
    result = mock_command("loft", {"profile_sketch_names": ["Sketch_bottom"]})

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert any("two or more" in hint for hint in result["hints"])
    assert "deltas" not in result


@pytest.mark.parametrize(
    ("mock_name", "params"),
    [
        ("revolve", {"angle": 360}),
        ("loft", {"profile_sketch_names": ["Sketch_bottom", "Sketch_top"]}),
        ("extrude", {"height": 2.0}),
        ("sweep", {"profile_index": 0, "path_sketch_name": "Sketch_path"}),
    ],
)
def test_mock_mode_refuses_a_target_body_on_a_new_body(mock_name, params):
    """Mock mode is the development surface; it must refuse what Fusion refuses."""
    result = mock_command(
        mock_name, {**params, "operation": "new_body", "target_body": "Block"}
    )

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert any("nothing to target" in hint for hint in result["hints"])
    assert "deltas" not in result
