"""``revolve`` must turn the profile about the axis the caller asked for.

Measured against Fusion 2706.1.17 (``command_handler.revolve`` in 0.4.0), with a
profile on a sketch offset to model ``z=-2`` and ``axis_origin=(0, 0, 0)``:

* the axis line was built at sketch-space ``(0, 0, 0)``, which the sketch
  transform places at model ``(0, 0, -2)`` — displaced by exactly the plane
  offset, because ``SketchCurves`` read points in the sketch's own frame. The
  same defect the 0.3.1 sketch-plane fix removed from the ``draw_*`` tools.
* the revolve did not even get that far: it failed with ``3 : invalid
  profile(s) for Revolve Feature``. The profile proxy was fetched **before** the
  axis line was added to the same sketch, and Fusion invalidates the proxy
  when the sketch changes. Proven by holding geometry and the axis line fixed
  and varying only that order: fetched-before-line fails, fetched-after-line
  builds ``Revolve4``.

So these tests assert on the geometry handed to Fusion, not just on the return
value: the axis line's endpoints in the sketch's frame, and where they land in
model space. The fake in ``tests.fakes`` reproduces the staleness rule above,
so reading the profile too early fails here rather than passing silently.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from tests.fakes.design import FakeDesign
from tests.fakes.sketch import FakePoint3D, FakeSketch, xy_sketch_at, yz_sketch


class Rig:
    """A bound handler plus the fake design it drives."""

    def __init__(self, handler, sketch: FakeSketch, root):
        self.handler = handler
        self.sketch = sketch
        self.root = root

    @property
    def axis_line(self):
        lines = self.sketch.lines
        assert len(lines) == 1, f"expected one axis line, got {lines}"
        return lines[0]

    @property
    def last_input(self):
        return self.root.features.revolveFeatures.inputs[-1]

    def model_points(self) -> list[tuple[float, float, float]]:
        """The axis line's endpoints in model space, via the sketch transform."""
        line = self.axis_line
        return [
            self.sketch.sketchToModelSpace(line.start).coords(),
            self.sketch.sketchToModelSpace(line.end).coords(),
        ]


@pytest.fixture
def revolve(handler_module):
    """Return a rig for a design holding one sketch."""

    def factory(transform=None, profile_count=1):
        sketch = FakeSketch(transform=transform, profile_count=profile_count)
        design = FakeDesign(features=2, sketches=(sketch,))
        root = design.rootComponent
        handler = handler_module.CommandHandler.__new__(handler_module.CommandHandler)
        handler._root = lambda: root
        handler._last_sketch = lambda: sketch
        return Rig(handler, sketch, root)

    return factory


class TestAxisIsModelSpace:
    def test_a_coplanar_axis_origin_is_used_as_given(self, revolve):
        """Offset sketch, origin already on the plane: exact pass-through."""
        rig = revolve(transform=xy_sketch_at(-2.0))

        result = rig.handler.revolve(
            angle=360,
            axis_origin_x=1,
            axis_origin_y=2,
            axis_origin_z=-2,
            axis_direction_x=1,
            axis_direction_y=1,
        )

        assert rig.axis_line.start.coords() == (1.0, 2.0, 0.0)
        assert rig.axis_line.end.coords() == pytest.approx(
            (1.0 + 10 / 2**0.5, 2.0 + 10 / 2**0.5, 0.0)
        )
        assert rig.axis_line.isConstruction is True
        assert rig.model_points()[0] == pytest.approx((1.0, 2.0, -2.0))
        assert rig.model_points()[1] == pytest.approx(
            (1.0 + 10 / 2**0.5, 2.0 + 10 / 2**0.5, -2.0)
        )
        assert result["axis_model_start"] == pytest.approx([1.0, 2.0, -2.0])
        assert result["axis_model_end"] == pytest.approx(
            [1.0 + 10 / 2**0.5, 2.0 + 10 / 2**0.5, -2.0]
        )
        assert "note" not in result

    def test_the_axis_is_not_displaced_by_the_plane_offset(self, revolve):
        """The 0.4.0 bug: origin (0,0,0) landed at model z=-2, not z=0.

        A construction line cannot leave the sketch plane, so the requested
        normal offset is dropped — the axis ends up in the profile's plane —
        but the drop is reported rather than silent.
        """
        rig = revolve(transform=xy_sketch_at(-2.0))

        result = rig.handler.revolve(angle=360, axis_direction_x=1, axis_direction_y=1)

        assert rig.axis_line.start.coords() == (0.0, 0.0, 0.0)
        assert rig.model_points()[0] == pytest.approx((0.0, 0.0, -2.0))
        assert result["axis_snapped_to_sketch_plane"] is True
        assert "sketch plane" in result["note"]

    def test_the_direction_is_rotated_into_the_sketch_frame(self, revolve):
        """On a YZ sketch, model +Y is the sketch's own +x.

        Passing the model direction through unchanged would build a line along
        the wrong axis — the same transposition the draw tools had.
        """
        rig = revolve(transform=yz_sketch())

        result = rig.handler.revolve(
            angle=90, axis_direction_x=0, axis_direction_y=1, axis_direction_z=1
        )

        assert rig.axis_line.start.coords() == (0.0, 0.0, 0.0)
        assert rig.axis_line.end.coords() == pytest.approx(
            (10 / 2**0.5, 10 / 2**0.5, 0.0)
        )
        assert rig.model_points()[1] == pytest.approx((0.0, 10 / 2**0.5, 10 / 2**0.5))
        assert result["axis_model_end"] == pytest.approx(
            [0.0, 10 / 2**0.5, 10 / 2**0.5]
        )

    def test_a_yz_normal_direction_still_uses_the_world_axis(self, revolve):
        """Model X is the YZ plane's normal — the built-in axis covers it."""
        rig = revolve(transform=yz_sketch())

        rig.handler.revolve(angle=90, axis_direction_x=1)

        assert rig.sketch.lines == []
        assert rig.last_input.axis is rig.root.xConstructionAxis


class TestProfileIsReadAfterTheAxisLine:
    def test_revolve_succeeds_with_a_non_world_axis(self, revolve):
        """0.4.0 raised ``3 : invalid profile(s) for Revolve Feature`` here.

        The fake enforces Fusion's invalidation rule, so reading the profile
        before adding the axis line fails this test rather than passing
        silently.
        """
        rig = revolve(transform=xy_sketch_at(-2.0))

        result = rig.handler.revolve(angle=360, axis_direction_x=1, axis_direction_y=1)

        assert result["feature_name"] == "Revolve1"
        assert result["operation"] == "new_body"
        assert rig.root.features.revolveFeatures.added == [rig.last_input]
        assert rig.last_input.axis is rig.axis_line

    def test_revolve_succeeds_on_a_sketch_with_no_offset(self, revolve):
        rig = revolve()

        result = rig.handler.revolve(angle=180, axis_direction_x=1, axis_direction_y=1)

        assert result["feature_name"] == "Revolve1"

    def test_an_empty_sketch_still_reports_no_profile(self, revolve):
        """Fail before creating axis geometry, not after."""
        rig = revolve(profile_count=0)

        with pytest.raises(RuntimeError, match="No profiles in sketch"):
            rig.handler.revolve(angle=360, axis_direction_x=1, axis_direction_y=1)

        assert rig.sketch.lines == []


class TestWorldAxis:
    def test_the_axis_length_does_not_depend_on_the_direction_magnitude(self, revolve):
        """A direction is a direction: (2, 0, 0) and (1, 0, 0) must agree."""
        rig = revolve()

        rig.handler.revolve(angle=360, axis_origin_y=5, axis_direction_x=2)

        assert rig.axis_line.start.coords() == (0.0, 5.0, 0.0)
        assert rig.axis_line.end.coords() == (10.0, 5.0, 0.0)

    @pytest.mark.parametrize(
        "direction, axis_name",
        [
            ((1, 0, 0), "X"),
            ((0, 1, 0), "Y"),
            ((0, 0, 1), "Z"),
            ((2, 0, 0), "X"),  # magnitude must not change the axis
        ],
    )
    def test_a_world_axis_through_the_origin_adds_no_geometry(
        self, revolve, direction, axis_name
    ):
        rig = revolve()

        rig.handler.revolve(
            angle=360,
            axis_direction_x=direction[0],
            axis_direction_y=direction[1],
            axis_direction_z=direction[2],
        )

        expected = getattr(rig.root, f"{axis_name.lower()}ConstructionAxis")
        assert rig.last_input.axis is expected
        assert rig.sketch.lines == []

    def test_an_offset_world_axis_is_honoured_not_ignored(self, revolve):
        """``axis_origin`` used to be dropped whenever the direction was world.

        A caller asking for a line parallel to model X through (0, 5, 0) got
        the X axis through the model origin instead.
        """
        rig = revolve()

        result = rig.handler.revolve(angle=360, axis_origin_y=5, axis_direction_x=1)

        assert rig.axis_line.start.coords() == (0.0, 5.0, 0.0)
        assert rig.axis_line.end.coords() == (10.0, 5.0, 0.0)
        assert rig.last_input.axis is rig.axis_line
        assert result["axis_model_start"] == pytest.approx([0.0, 5.0, 0.0])


class TestUnrepresentableAxis:
    def test_an_axis_leaving_the_sketch_plane_is_refused(self, revolve):
        """A diagonal out of the sketch plane cannot be a construction line.

        0.4.0 let Fusion project it, revolving about a different axis than the
        caller asked for.
        """
        rig = revolve()

        with pytest.raises(RuntimeError) as excinfo:
            rig.handler.revolve(
                angle=360, axis_direction_x=1, axis_direction_y=1, axis_direction_z=1
            )

        assert "sketch plane" in str(excinfo.value)
        assert classify(excinfo.value)[0] == "AXIS_OUT_OF_PLANE"
        assert rig.sketch.lines == []

    def test_a_zero_length_direction_is_refused(self, revolve):
        rig = revolve()

        with pytest.raises(RuntimeError, match="zero-length"):
            rig.handler.revolve(
                angle=360, axis_direction_x=0, axis_direction_y=0, axis_direction_z=0
            )

        assert rig.sketch.lines == []


def test_helper_math_is_sound():
    """Guard the harness itself: the fake transform must round-trip."""
    sketch = FakeSketch(transform=xy_sketch_at(-2.0))

    model = FakePoint3D(3.0, 4.0, -2.0)
    back = sketch.sketchToModelSpace(sketch.modelToSketchSpace(model))

    assert back.coords() == pytest.approx(model.coords())
