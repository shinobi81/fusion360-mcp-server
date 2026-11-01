"""``revolve`` must turn the profile about the axis the caller asked for.

Measured against Fusion 2706.1.17 (``command_handler.revolve`` in 0.4.0), with a
profile on a sketch offset to model ``z=-2`` and ``axis_origin=(0, 0, 0)``:

* the axis line was built at sketch-space ``(0, 0, 0)``, which the sketch
  transform places at model ``(0, 0, -2)`` — displaced by exactly the plane
  offset, because ``SketchCurves`` read points in the sketch's own frame. The
  same defect the 0.3.1 sketch-plane fix removed from the ``draw_*`` tools.
* the revolve did not even get that far: it failed with ``3 : invalid
  profile(s) for Revolve Feature``. The profile proxy was fetched **before**
  the axis line was added to the same sketch, and Fusion invalidates the proxy
  when the sketch changes. Proven by holding geometry and the axis line fixed
  and varying only that order: fetched-before-line fails, fetched-after-line
  builds ``Revolve4``.

So these tests assert on the geometry handed to Fusion, not just on the return
value: the axis line's endpoints in the sketch's frame, and where they land in
model space. The add-in cannot be imported under pytest (it needs Fusion's
``adsk``), so it is loaded against a fake whose ``profiles`` collection carries
a version stamp, reproducing the staleness rule above.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types
from pathlib import Path

import pytest

from fusion360_mcp.hints import classify

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "addon" / "server"
FAKE_PACKAGE = "addon_revolve_under_test"


# ----------------------------------------------------------------------
# Fake adsk
# ----------------------------------------------------------------------


class FakePoint3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    @classmethod
    def create(cls, x=0.0, y=0.0, z=0.0):
        return cls(x, y, z)

    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakePoint3D({self.x}, {self.y}, {self.z})"


class FakeVector3D(FakePoint3D):
    pass


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def xy_sketch_at(z: float) -> FakeTransform:
    """The XY plane lifted to model ``z``."""
    return FakeTransform(origin=(0.0, 0.0, z))


def yz_sketch() -> FakeTransform:
    """The YZ plane: sketch x is model y, sketch y is model z, normal is model x."""
    return FakeTransform(
        origin=(0.0, 0.0, 0.0),
        x_axis=(0.0, 1.0, 0.0),
        y_axis=(0.0, 0.0, 1.0),
        z_axis=(1.0, 0.0, 0.0),
    )


class FakeTransform:
    """A sketch transform: origin plus an orthonormal basis, as Fusion reports.

    Default axes are the world identity, so an "offset" sketch is the XY plane
    lifted along Z. A ``yz`` / ``xz`` sketch passes rotated axes, which is what
    distinguishes a frame-converted direction from a passed-through one.
    """

    def __init__(
        self,
        origin=(0.0, 0.0, 0.0),
        x_axis=(1.0, 0.0, 0.0),
        y_axis=(0.0, 1.0, 0.0),
        z_axis=(0.0, 0.0, 1.0),
    ):
        self.origin = tuple(float(v) for v in origin)
        self.x_axis = tuple(float(v) for v in x_axis)
        self.y_axis = tuple(float(v) for v in y_axis)
        self.z_axis = tuple(float(v) for v in z_axis)

    def getAsCoordinateSystem(self):
        return (
            FakePoint3D(*self.origin),
            FakeVector3D(*self.x_axis),
            FakeVector3D(*self.y_axis),
            FakeVector3D(*self.z_axis),
        )


class FakeValueInput:
    def __init__(self, value):
        self.value = value

    @classmethod
    def createByString(cls, value):
        return cls(value)

    @classmethod
    def createByReal(cls, value):
        return cls(value)


class FakeLine:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.isConstruction = False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakeLine({self.start} -> {self.end})"


class FakeSketchLines:
    def __init__(self, sketch):
        self._sketch = sketch

    def addByTwoPoints(self, p1, p2):
        line = FakeLine(p1, p2)
        self._sketch.calls.append(line)
        self._sketch.bump()  # Fusion invalidates existing proxies
        return line

    @property
    def count(self) -> int:
        return len(self._sketch.calls)

    def item(self, index):
        return self._sketch.calls[index]


class FakeSketchCurves:
    def __init__(self, sketch):
        self.sketchLines = FakeSketchLines(sketch)


class FakeProfile:
    """A profile stamp: Fusion hands back a proxy tied to the sketch state."""

    def __init__(self, version):
        self.version = version


class FakeProfiles:
    def __init__(self, sketch, count):
        self._sketch = sketch
        self.count = count

    def item(self, index):
        return FakeProfile(self._sketch.version)


class FakeSketch:
    def __init__(self, transform=None, name="Sketch1", profile_count=1):
        self.name = name
        self.transform = transform if transform is not None else FakeTransform()
        self.version = 0
        self.calls: list[FakeLine] = []
        self.sketchCurves = FakeSketchCurves(self)
        self.profiles = FakeProfiles(self, profile_count)

    def bump(self):
        self.version += 1

    def modelToSketchSpace(self, point):
        d = (
            point.x - self.transform.origin[0],
            point.y - self.transform.origin[1],
            point.z - self.transform.origin[2],
        )
        return FakePoint3D(
            _dot(d, self.transform.x_axis),
            _dot(d, self.transform.y_axis),
            _dot(d, self.transform.z_axis),
        )

    def sketchToModelSpace(self, point):
        t = self.transform
        return FakePoint3D(
            t.origin[0]
            + point.x * t.x_axis[0]
            + point.y * t.y_axis[0]
            + point.z * t.z_axis[0],
            t.origin[1]
            + point.x * t.x_axis[1]
            + point.y * t.y_axis[1]
            + point.z * t.z_axis[1],
            t.origin[2]
            + point.x * t.x_axis[2]
            + point.y * t.y_axis[2]
            + point.z * t.z_axis[2],
        )


class FakeRevolveInput:
    def __init__(self, profile, axis, operation):
        self.profile = profile
        self.axis = axis
        self.operation = operation
        self.angle = None
        self.symmetric = None

    def setAngleExtent(self, symmetric, angle):
        self.symmetric = symmetric
        self.angle = angle


class FakeFeature:
    def __init__(self, name):
        self.name = name


class FakeRevolveFeatures:
    def __init__(self, sketch):
        self._sketch = sketch
        self.inputs: list[FakeRevolveInput] = []
        self.added: list[FakeRevolveInput] = []

    def createInput(self, profile, axis, operation):
        inp = FakeRevolveInput(profile, axis, operation)
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        # What Fusion 2706 does: a profile proxy captured before the sketch was
        # modified is stale, and a revolve about it is rejected outright.
        if inp.profile.version != self._sketch.version:
            raise RuntimeError("3 : invalid profile(s) for Revolve Feature")
        self.added.append(inp)
        return FakeFeature("Revolve1")


class FakeAxes:
    def __init__(self):
        self.xConstructionAxis = types.SimpleNamespace(name="X")
        self.yConstructionAxis = types.SimpleNamespace(name="Y")
        self.zConstructionAxis = types.SimpleNamespace(name="Z")


class FakeSketches:
    def __init__(self, sketch):
        self._items = [sketch]
        self.count = 1

    def item(self, index):
        return self._items[index]


class FakeFeatures:
    def __init__(self, sketch):
        self.revolveFeatures = FakeRevolveFeatures(sketch)


class FakeRoot:
    def __init__(self, sketch):
        self.sketches = FakeSketches(sketch)
        self.features = FakeFeatures(sketch)
        axes = FakeAxes()
        self.xConstructionAxis = axes.xConstructionAxis
        self.yConstructionAxis = axes.yConstructionAxis
        self.zConstructionAxis = axes.zConstructionAxis


class Rig:
    """A bound handler plus the fake design it drives."""

    def __init__(self, handler, sketch, root):
        self.handler = handler
        self.sketch = sketch
        self.root = root

    @property
    def axis_line(self) -> FakeLine:
        calls = self.sketch.calls
        assert len(calls) == 1, f"expected one axis line, got {calls}"
        return calls[0]

    @property
    def last_input(self) -> FakeRevolveInput:
        return self.root.features.revolveFeatures.inputs[-1]

    def model_points(self) -> list[tuple[float, float, float]]:
        """The axis line's endpoints in model space, via the sketch transform."""
        line = self.axis_line
        return [
            self.sketch.sketchToModelSpace(line.start).coords(),
            self.sketch.sketchToModelSpace(line.end).coords(),
        ]


# ----------------------------------------------------------------------
# Module loading with a fake adsk
# ----------------------------------------------------------------------


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    return module


def _install_fake_adsk():
    core = _module(
        "adsk.core",
        Point3D=FakePoint3D,
        Vector3D=FakeVector3D,
        ValueInput=FakeValueInput,
    )
    operations = types.SimpleNamespace(
        NewBodyFeatureOperation="new_body",
        JoinFeatureOperation="join",
        CutFeatureOperation="cut",
        IntersectFeatureOperation="intersect",
    )
    fusion = _module("adsk.fusion", FeatureOperations=operations)
    cam = _module("adsk.cam")
    adsk = _module("adsk", core=core, fusion=fusion, cam=cam)
    sys.modules.update(
        {
            "adsk": adsk,
            "adsk.core": core,
            "adsk.fusion": fusion,
            "adsk.cam": cam,
        }
    )


@pytest.fixture(scope="module")
def handler_module():
    """command_handler.py, imported against the fake runtime."""
    if FAKE_PACKAGE in sys.modules:
        return sys.modules[f"{FAKE_PACKAGE}.server.command_handler"]

    _install_fake_adsk()
    package = types.ModuleType(FAKE_PACKAGE)
    package.__path__ = [str(SERVER_DIR.parent)]
    server = types.ModuleType(f"{FAKE_PACKAGE}.server")
    server.__path__ = [str(SERVER_DIR)]
    setattr(server, "get_logger", lambda name=None: logging.getLogger("addon-test"))
    sys.modules[FAKE_PACKAGE] = package
    sys.modules[f"{FAKE_PACKAGE}.server"] = server
    yield importlib.import_module(f"{FAKE_PACKAGE}.server.command_handler")
    for name in ("adsk", "adsk.core", "adsk.fusion", "adsk.cam"):
        sys.modules.pop(name, None)


@pytest.fixture
def revolve(handler_module):
    """Return ``(handler, sketch, root)`` for a design holding one sketch."""

    def factory(transform=None, profile_count=1):
        sketch = FakeSketch(transform=transform, profile_count=profile_count)
        root = FakeRoot(sketch)
        handler = handler_module.CommandHandler.__new__(handler_module.CommandHandler)
        handler._root = lambda: root
        handler._last_sketch = lambda: sketch
        return Rig(handler, sketch, root)

    return factory


# ----------------------------------------------------------------------
# The frame bug: sketch coordinates were used where model coordinates belong
# ----------------------------------------------------------------------


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

        assert rig.sketch.calls == []
        assert rig.last_input.axis is rig.root.xConstructionAxis


# ----------------------------------------------------------------------
# The profile proxy must be read after the axis line exists
# ----------------------------------------------------------------------


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

        assert rig.sketch.calls == []


# ----------------------------------------------------------------------
# World axes: built in when they pass through the model origin, honoured when not
# ----------------------------------------------------------------------


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
        assert rig.sketch.calls == []

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


# ----------------------------------------------------------------------
# Refusals: an axis a sketch line cannot represent must not revolve silently
# ----------------------------------------------------------------------


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
        assert rig.sketch.calls == []

    def test_a_zero_length_direction_is_refused(self, revolve):
        rig = revolve()

        with pytest.raises(RuntimeError, match="zero-length"):
            rig.handler.revolve(
                angle=360, axis_direction_x=0, axis_direction_y=0, axis_direction_z=0
            )

        assert rig.sketch.calls == []


def test_helper_math_is_sound():
    """Guard the harness itself: the fake transform must round-trip."""
    sketch = FakeSketch(transform=xy_sketch_at(-2.0))

    model = FakePoint3D(3.0, 4.0, -2.0)
    back = sketch.sketchToModelSpace(sketch.modelToSketchSpace(model))

    assert back.coords() == pytest.approx(model.coords())
