"""Fake sketch geometry: transforms, curves, lines and profile proxies.

The add-in reads sketch geometry through a handful of collections, and two
Fusion behaviours have caused real bugs here, so both are modelled rather than
stubbed:

* **Sketch curves are in the sketch's own frame.** ``modelToSketchSpace`` and
  ``sketchToModelSpace`` apply the sketch transform, so a test can tell a
  converted point from a passed-through one — the 0.4.0 ``revolve`` axis bug
  and the 0.3.1 ``draw_*`` z bug both came from that confusion.
* **A profile proxy goes stale when its sketch changes.** ``profiles.item()``
  stamps the sketch's version, and ``FakeRevolveFeatures.add`` rejects a stale
  proxy the way Fusion 2706 does — which is why the profile must be read after
  the axis line is added to the same sketch.
"""

from __future__ import annotations

from .runtime import FakePoint3D, FakeVector3D


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class FakeTransform:
    """A sketch transform: an origin plus an orthonormal basis.

    Defaults are the world identity, so an "offset" sketch is the XY plane
    lifted along Z.  A ``yz`` or ``xz`` sketch passes rotated axes, which is what
    distinguishes a frame-converted direction from one passed through unchanged.
    """

    def __init__(
        self,
        origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
        x_axis: tuple[float, float, float] = (1.0, 0.0, 0.0),
        y_axis: tuple[float, float, float] = (0.0, 1.0, 0.0),
        z_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    ):
        self.origin = (float(origin[0]), float(origin[1]), float(origin[2]))
        self.x_axis = (float(x_axis[0]), float(x_axis[1]), float(x_axis[2]))
        self.y_axis = (float(y_axis[0]), float(y_axis[1]), float(y_axis[2]))
        self.z_axis = (float(z_axis[0]), float(z_axis[1]), float(z_axis[2]))

    def getAsCoordinateSystem(self):
        return (
            FakePoint3D(*self.origin),
            FakeVector3D(*self.x_axis),
            FakeVector3D(*self.y_axis),
            FakeVector3D(*self.z_axis),
        )


def xy_sketch_at(z: float) -> FakeTransform:
    """The XY plane lifted to model ``z``."""
    return FakeTransform(origin=(0.0, 0.0, z))


def yz_sketch() -> FakeTransform:
    """Sketch x is model y, sketch y is model z, normal is model x."""
    return FakeTransform(
        origin=(0.0, 0.0, 0.0),
        x_axis=(0.0, 1.0, 0.0),
        y_axis=(0.0, 0.0, 1.0),
        z_axis=(1.0, 0.0, 0.0),
    )


class FakeLine:
    """A sketch line.  ``isConstruction`` is the only attribute the add-in sets."""

    def __init__(self, start: FakePoint3D, end: FakePoint3D):
        self.start = start
        self.end = end
        self.isConstruction = False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakeLine({self.start} -> {self.end})"


class _CurveRecorder:
    """Shared base: records a call as ``(kind, payload)`` on the sketch."""

    def __init__(self, sketch: FakeSketch, kind: str):
        self._sketch = sketch
        self._kind = kind

    def _record(self, **payload: object) -> None:
        self._sketch.curve_calls.append((self._kind, payload))


class _CircleRecorder(_CurveRecorder):
    """``sketchCircles``: Fusion's only constructor takes centre and radius."""

    def addByCenterRadius(self, center, radius) -> None:
        self._record(center=center, radius=radius)


class _ArcRecorder(_CurveRecorder):
    """``sketchArcs``: centre, start and sweep angle."""

    def addByCenterStartSweep(self, center, start, sweep) -> None:
        self._record(center=center, start=start, sweep=sweep)


class _PointRecorder(_CurveRecorder):
    """``sketchFittedSplines``: points only — a second argument is a bug."""

    def add(self, points) -> None:
        self._record(points=list(points))


class _PointDegreeRecorder(_CurveRecorder):
    """``sketchControlPointSplines``: points and a degree."""

    def add(self, points, degree) -> None:
        self._record(points=list(points), degree=degree)


class FakeSketchLines:
    """``sketchCurves.sketchLines``: records calls *and* builds line objects.

    Lines are appended with a version bump, because adding a line to a sketch
    invalidates every profile proxy taken from it — the behaviour that made
    ``revolve`` fail after the axis line was created.
    """

    def __init__(self, sketch: FakeSketch):
        self._sketch = sketch

    def addByTwoPoints(self, p1, p2) -> FakeLine:
        line = FakeLine(p1, p2)
        self._sketch.lines.append(line)
        self._sketch.curve_calls.append(("line", {"points": [p1, p2]}))
        self._sketch.bump()  # Fusion invalidates existing proxies
        return line

    def addTwoPointRectangle(self, p1, p2) -> None:
        # Fusion builds four edges; the revolve tests probe ``lines`` for
        # "no geometry was created", so a rectangle has to appear there.
        corners = [
            FakePoint3D(p1.x, p1.y, 0.0),
            FakePoint3D(p2.x, p1.y, 0.0),
            FakePoint3D(p2.x, p2.y, 0.0),
            FakePoint3D(p1.x, p2.y, 0.0),
        ]
        for index, start in enumerate(corners):
            self._sketch.lines.append(FakeLine(start, corners[(index + 1) % 4]))
        self._sketch.curve_calls.append(("line", {"points": [p1, p2]}))
        self._sketch.bump()

    @property
    def count(self) -> int:
        return len(self._sketch.lines)

    def item(self, index: int) -> FakeLine:
        return self._sketch.lines[index]


class FakeSketchCurves:
    """Each collection offers only the constructors Fusion has on it."""

    def __init__(self, sketch: FakeSketch):
        self.sketchLines = FakeSketchLines(sketch)
        self.sketchCircles = _CircleRecorder(sketch, "circle")
        self.sketchArcs = _ArcRecorder(sketch, "arc")
        self.sketchFittedSplines = _PointRecorder(sketch, "fit_spline")
        self.sketchControlPointSplines = _PointDegreeRecorder(sketch, "control_spline")


class FakeProfile:
    """A profile proxy: tied to the sketch state it was read from."""

    def __init__(self, sketch: FakeSketch):
        self.sketch = sketch
        self.version = sketch.version


class FakeProfiles:
    def __init__(self, sketch: FakeSketch, count: int):
        self._sketch = sketch
        self.count = count

    def item(self, index: int) -> FakeProfile:
        return FakeProfile(self._sketch)


class FakeSketch:
    """A sketch: transform, recorded curve calls, line objects, profiles."""

    def __init__(
        self,
        transform: FakeTransform | None = None,
        name: str = "Sketch1",
        profile_count: int = 1,
    ):
        self.name = name
        self.isVisible = True
        self.isComputeDeferred = False
        self.transform = transform if transform is not None else FakeTransform()
        self.version = 0
        self.lines: list[FakeLine] = []
        self.curve_calls: list[tuple[str, dict]] = []
        self.sketchCurves = FakeSketchCurves(self)
        self.profiles = FakeProfiles(self, profile_count)

    def bump(self) -> None:
        self.version += 1

    def last_call(self, kind: str | None = None) -> dict:
        """The single curve call recorded, asserting exactly one happened."""
        assert len(self.curve_calls) == 1, (
            f"expected one curve call, got {self.curve_calls}"
        )
        recorded_kind, payload = self.curve_calls[0]
        if kind is not None:
            assert recorded_kind == kind, f"expected a {kind}, got {recorded_kind}"
        return payload

    def modelToSketchSpace(self, point: FakePoint3D) -> FakePoint3D:
        t = self.transform
        delta = (
            point.x - t.origin[0],
            point.y - t.origin[1],
            point.z - t.origin[2],
        )
        return FakePoint3D(
            _dot(delta, t.x_axis),
            _dot(delta, t.y_axis),
            _dot(delta, t.z_axis),
        )

    def sketchToModelSpace(self, point: FakePoint3D) -> FakePoint3D:
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
