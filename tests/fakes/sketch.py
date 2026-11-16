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

import math

from .bodies import FakeBoundingBox
from .collection import FakeCollection
from .runtime import FakeObjectCollection, FakePlane, FakePoint3D, FakeVector3D


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
    """A sketch line.  ``isConstruction`` is the only attribute the add-in sets.

    ``startSketchPoint``/``endSketchPoint`` exist because ``add_dimension``
    dimensions a *point* pair, not a curve pair: without them the handler could
    not run against the fake at all, which is why it had no test.
    """

    def __init__(self, start: FakePoint3D, end: FakePoint3D):
        self.start = start
        self.end = end
        self.isConstruction = False
        self.startSketchPoint = FakeSketchPoint(start)
        self.endSketchPoint = FakeSketchPoint(end)

    @property
    def boundingBox(self) -> FakeBoundingBox:
        """The line's own box.  ``add_dimension`` places a one-entity label here.

        Fusion refuses a radial/diameter label at the curve's centre (measured on
        2706: "3 : Some input argument is invalid" for the world origin over a
        circle centred there) and accepts the box corner, so the handler reads this.
        """
        return FakeBoundingBox(
            (
                min(self.start.x, self.end.x),
                min(self.start.y, self.end.y),
                min(self.start.z, self.end.z),
            ),
            (
                max(self.start.x, self.end.x),
                max(self.start.y, self.end.y),
                max(self.start.z, self.end.z),
            ),
        )

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


class FakeSketchLineList:
    """What ``addTwoPointRectangle`` returns: the four lines it built, in order.

    Fusion's ``SketchLines.addTwoPointRectangle`` returns a ``SketchLineList``
    rather than nothing, and ``create_box_parametric`` dimensions two of the four
    (``item(0)`` horizontally, ``item(1)`` vertically) - so the return value has
    to be a collection or the command cannot run at all.  The **order** is this
    fake's: the lines are built counter-clockwise from the first corner, which makes
    ``item(0)`` the edge along sketch x and ``item(1)`` the one along sketch y.
    No test asserts Fusion's own ordering, only which orientation and value each
    index was dimensioned with.
    """

    def __init__(self, lines: list[FakeLine]):
        self._lines = list(lines)

    @property
    def count(self) -> int:
        return len(self._lines)

    def item(self, index: int) -> FakeLine:
        return self._lines[index]

    def __iter__(self):
        return iter(self._lines)


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

    def addTwoPointRectangle(self, p1, p2) -> FakeSketchLineList:
        # Fusion builds four edges; the revolve tests probe ``lines`` for
        # "no geometry was created", so a rectangle has to appear there.
        corners = [
            FakePoint3D(p1.x, p1.y, 0.0),
            FakePoint3D(p2.x, p1.y, 0.0),
            FakePoint3D(p2.x, p2.y, 0.0),
            FakePoint3D(p1.x, p2.y, 0.0),
        ]
        built = []
        for index, start in enumerate(corners):
            line = FakeLine(start, corners[(index + 1) % 4])
            self._sketch.lines.append(line)
            built.append(line)
        self._sketch.curve_calls.append(("line", {"points": [p1, p2]}))
        self._sketch.bump()
        return FakeSketchLineList(built)

    @property
    def count(self) -> int:
        return len(self._sketch.lines)

    def item(self, index: int) -> FakeLine:
        return self._sketch.lines[index]


class FakeSketchCurves:
    """Each collection offers only the constructors Fusion has on it."""

    def __init__(self, sketch: FakeSketch):
        self._sketch = sketch
        self.sketchLines = FakeSketchLines(sketch)
        self.sketchCircles = _CircleRecorder(sketch, "circle")
        self.sketchArcs = _ArcRecorder(sketch, "arc")
        self.sketchFittedSplines = _PointRecorder(sketch, "fit_spline")
        self.sketchControlPointSplines = _PointDegreeRecorder(sketch, "control_spline")

    @property
    def count(self) -> int:
        """Curves in the sketch, which ``draw_circles`` reports back.

        Lines are counted from the objects ``sketchLines`` builds — a rectangle
        is four lines from one call — and the other curve types from their
        recorded calls, because nothing here models them as objects.
        """
        other_curves = sum(1 for kind, _ in self._sketch.curve_calls if kind != "line")
        return len(self._sketch.lines) + other_curves

    def __iter__(self):
        """One entry per curve, matching ``count``.

        Lines are the objects ``sketchLines`` builds — a rectangle is *four*
        lines from one call, and ``add_constraint`` indexes this collection by
        curve — and the other types are proxies standing for their recorded
        calls.  Keeping ``len(list(...)) == count`` matters: a caller that takes
        ``curves[index]`` must not see a different number than the one it read.
        """
        curves: list = list(self._sketch.lines)
        curves.extend(
            type("FakeCurve", (), {"kind": kind, "payload": payload})()
            for kind, payload in self._sketch.curve_calls
            if kind != "line"
        )
        return iter(curves)


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


class FakeSketchPoint:
    """A sketch point: ``geometry`` is the point in the SKETCH's own frame.

    Fusion keeps them apart (``SketchPoint.geometry``), and ``add_dimension``
    hands these - not Point3Ds - to ``addDistanceDimension``.  Measured live on
    2706: after ``create_hole`` put a centre at model (3, 4, 3) on a face at
    z = 3, the sketch point read ``(3.0, 4.0, 0.0)`` and ``sketchToModelSpace``
    was what turned it back into ``(3, 4, 3)``.  On an unoffset XY sketch the two
    frames coincide, which is why "model point" read as true for so long.
    """

    def __init__(self, geometry: FakePoint3D | None = None):
        self.geometry = geometry if geometry is not None else FakePoint3D()


class FakeSketchPoints:
    """``sketch.sketchPoints``: ``count``, a 0-based ``item``, and ``add``.

    ``midpoint`` resolves its first entity through this collection rather than
    through the curves, so it has to be indexable for the constraint handler to
    run at all - hence the sketch's own origin point, which Fusion gives every
    sketch and which ``add`` appends after.  ``add`` is where ``create_hole``
    parks its centre.
    """

    def __init__(self, points: list | None = None):
        self._points = list(points) if points is not None else [FakeSketchPoint()]

    @property
    def count(self) -> int:
        return len(self._points)

    def item(self, index: int) -> FakeSketchPoint:
        return self._points[index]

    def add(self, point: FakePoint3D) -> FakeSketchPoint:
        """``add(point, isReference=False)``: the point, in SKETCH space.

        Fusion takes sketch coordinates here and projects whatever it is given
        onto the sketch plane, so a model-space point does not raise — it lands
        somewhere else.  That is how the unconverted hole centre shipped, so the
        fake stays permissive too and the tests assert the round trip through
        ``sketchToModelSpace`` instead of expecting an error.
        """
        created = FakeSketchPoint(point)
        self._points.append(created)
        return created


class FakeConstraint:
    def __init__(self, method: str):
        self.name = method
        self.method = method


class FakeGeometricConstraints:
    """``sketch.geometricConstraints``: which constraint was added, with what.

    Every ``add*`` Fusion exposes to this handler is present, so a misspelt one
    raises ``AttributeError`` instead of being swallowed.
    """

    METHODS = (
        "addCoincident",
        "addParallel",
        "addPerpendicular",
        "addTangent",
        "addEqual",
        "addFix",
        "addHorizontal",
        "addVertical",
        "addConcentric",
        "addCollinear",
        "addSmooth",
        "addMidPoint",
        "addSymmetry",
    )

    def __init__(self):
        self.added: list[tuple[str, tuple]] = []

    def _record(self, method: str, args: tuple) -> FakeConstraint:
        self.added.append((method, args))
        return FakeConstraint(method)


def _constraint_method(method: str):
    def add(self, *args):
        return self._record(method, args)

    return add


for _name in FakeGeometricConstraints.METHODS:
    setattr(FakeGeometricConstraints, _name, _constraint_method(_name))


class FakeModelParameter:
    """``dim.parameter``: the value ``add_dimension`` writes.

    Fusion's ``ModelParameter`` carries the number in ``value`` (internal units)
    and the unit-carrying text in ``expression``, and assigning one does not
    assign the other.  So both are properties that **record** which one was
    written, in ``writes`` - with two plain attributes a ``createByReal`` payload
    and a ``createByString`` one would be indistinguishable, and the choice
    between them is the whole point of ``value_input_for``.
    """

    def __init__(self):
        self.written: list[tuple[str, object]] = []
        self._value = 0.0
        self._expression: str | None = None

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, new: float) -> None:
        self.written.append(("value", new))
        self._value = new

    @property
    def expression(self) -> str | None:
        """``None`` until written: a sketch dimension always has an expression
        in Fusion, but which text it starts with is the handler's business and
        nothing reads it before a write."""
        return self._expression

    @expression.setter
    def expression(self, new: str) -> None:
        self.written.append(("expression", new))
        self._expression = new


class FakeDimension:
    """A dimension: ``parameter.value`` is what ``add_dimension`` writes."""

    def __init__(self, method: str):
        self.method = method
        self.parameter = FakeModelParameter()


class FakeSketchDimensions:
    """``sketch.sketchDimensions``: records which ``add*Dimension`` ran."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.last_dimension: FakeDimension | None = None
        #: Every dimension ``add*Dimension`` returned, in order - a command that
        #: adds two (``create_box_parametric`` adds one per side) needs both, and
        #: ``last_dimension`` would only keep the second.
        self.dimensions: list[FakeDimension] = []

    def _record(self, method: str, args: tuple) -> FakeDimension:
        self.calls.append((method, args))
        self.last_dimension = FakeDimension(method)
        self.dimensions.append(self.last_dimension)
        return self.last_dimension

    def addDistanceDimension(self, p1, p2, orientation, text_point) -> FakeDimension:
        return self._record("addDistanceDimension", (p1, p2, orientation, text_point))

    def addAngularDimension(self, e1, e2, text_point) -> FakeDimension:
        return self._record("addAngularDimension", (e1, e2, text_point))

    def addRadialDimension(self, e1, text_point) -> FakeDimension:
        return self._record("addRadialDimension", (e1, text_point))

    def addDiameterDimension(self, e1, text_point) -> FakeDimension:
        return self._record("addDiameterDimension", (e1, text_point))


class FakeProjectedCurves:
    """What the retired ``Sketch.project`` returns: an ObjectCollection with a count."""

    def __init__(self, count: int):
        self.count = count


class FakeAutoConstrainInput:
    """``Sketch.createAutoConstrainInput()``: an input whose option is settable.

    Fusion's input carries ``resultOption``, and the handler writes one of the
    three ``AutoConstrainResultTypes`` members to it before calling
    ``autoConstrain``.  The fake records whatever it was handed rather than
    refusing an unknown member: what Fusion does with one has not been measured.
    """

    def __init__(self):
        self.resultOption = None


class FakeAutoConstrainResult:
    """What ``Sketch.autoConstrain`` returns: the four counts the reply is built from.

    The three collections are only ever measured with ``len()``, so each count
    builds its own list: a separate number that disagreed with the collection it
    described would be a fake reporting a count Fusion never reported.
    """

    def __init__(
        self,
        is_fully_constrained: bool = False,
        constraints: int = 0,
        dimensions: int = 0,
        moved: int = 0,
    ):
        self.isFullyConstrained = is_fully_constrained
        self.addedConstraints = list(range(constraints))
        self.addedDimensions = list(range(dimensions))
        self.movedGeometry = list(range(moved))


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
        #: What the sketch was built on — Fusion's ``Sketch.supportingPlane``.
        self.supportingPlane = None
        self.version = 0
        self.lines: list[FakeLine] = []
        self.curve_calls: list[tuple[str, dict]] = []
        #: ``(entities, is_linked)`` per projection, so a test reads what it asked for.
        self.projected: list[tuple[list, bool | None]] = []
        self.sketchCurves = FakeSketchCurves(self)
        self.sketchPoints = FakeSketchPoints()
        self.geometricConstraints = FakeGeometricConstraints()
        self.sketchDimensions = FakeSketchDimensions()
        self.profiles = FakeProfiles(self, profile_count)
        #: ``(entities, direction, distance)`` per ``offset()``, which is the arity
        #: the handler calls and Fusion ships.
        self.offset_calls: list[tuple] = []
        #: The input each ``autoConstrain()`` was called with, so a test reads the
        #: option that was asked for.
        self.auto_constrain_inputs: list[FakeAutoConstrainInput] = []
        #: ``resultOption -> answer``; a missing key gives ``auto_constrain_result``,
        #: and ``None`` models Fusion's answer for a sketch it will not adjust.
        self.auto_constrain_results: dict = {}
        self.auto_constrain_result = FakeAutoConstrainResult()

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

    def project2(self, entities, is_linked: bool) -> list:
        """``Sketch.project2(entities, isLinked)``: replaces the retired ``project``.

        The retired one-argument form cannot express linkage, which is why
        ``project_geometry``'s ``is_linked`` argument did nothing.  Both the
        two-argument arity and the list-of-entities input are Fusion's, so a
        handler that calls the retired method or passes a bare edge fails here.
        """
        if not isinstance(entities, (list, tuple)):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'Sketch_project2'"
            )
        self.projected.append((list(entities), is_linked))
        return [FakeSketchPoint(FakePoint3D()) for _ in entities]

    def project(self, entity) -> FakeProjectedCurves:
        """The retired form, kept so a regression shows up as linkage=None."""
        self.projected.append(([entity], None))
        return FakeProjectedCurves(1)

    def offset(self, entities, direction, distance) -> None:
        """``Sketch.offset(entities, direction, distance)`` — three arguments.

        Fusion takes an ``ObjectCollection`` of sketch entities, a point that says
        which side to offset towards, and the distance; the handler passes exactly
        those three, so the two-argument shape this fake was first planned with is
        a ``TypeError`` here.  The offset geometry is not modelled — Fusion derives
        it from the curve and no handler reads it back — so only the call is kept.
        """
        if not isinstance(entities, FakeObjectCollection):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'Sketch_offset'"
            )
        self.offset_calls.append((entities, direction, distance))

    def createAutoConstrainInput(self) -> FakeAutoConstrainInput:
        """``Sketch.createAutoConstrainInput()``: the input, before any option."""
        return FakeAutoConstrainInput()

    def autoConstrain(self, ac_input: FakeAutoConstrainInput):
        """``Sketch.autoConstrain(input)``: one result — or ``None``.

        Fusion's Option 3 answers ``None`` for a sketch it will not adjust, which
        the handler turns into a refusal; ``auto_constrain_results`` overrides the
        answer per option so that branch is expressible.  A permissive fake that
        always returned a result would hide it, and nothing would notice.
        """
        self.auto_constrain_inputs.append(ac_input)
        return self.auto_constrain_results.get(
            ac_input.resultOption, self.auto_constrain_result
        )


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def transform_from_plane(plane: FakePlane) -> FakeTransform:
    """The sketch frame Fusion puts on a planar face: the plane's own.

    Right-handed, with sketch z along the face normal — so ``modelToSketchSpace``
    gives a point in that frame and ``sketchToModelSpace`` undoes it exactly.
    """
    n = (plane.normal.x, plane.normal.y, plane.normal.z)
    # Any vector the normal is not parallel to, to start the basis from.
    helper = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    raw_x = _cross(helper, n)
    length = math.sqrt(sum(component * component for component in raw_x))
    scaled = [component / length for component in raw_x]
    x = (scaled[0], scaled[1], scaled[2])
    y = _cross(n, x)
    return FakeTransform(origin=plane.origin.coords(), x_axis=x, y_axis=y, z_axis=n)


class FakeSketches(FakeCollection):
    """``root.sketches``: ``add`` builds the sketch Fusion would build there.

    A sketch on a face carries that face's own coordinate system, which is what
    makes ``modelToSketchSpace`` a real conversion rather than a rename — and the
    hole centre that skipped it landed somewhere else entirely.  An object that
    is not a face (a construction plane) gets the world frame whatever plane it
    is - ``create_sketch(plane="yz")`` is modelled wrongly by that - so a test
    that needs a real frame builds ``FakeSketch(transform=yz_sketch())`` instead.
    A *non-planar* face is refused, because Fusion cannot sketch on one.
    """

    def add(self, geometry) -> FakeSketch:
        if isinstance(geometry, FakeSketch):
            super().add(geometry)
            return geometry

        surface = getattr(geometry, "geometry", None)
        if isinstance(surface, FakePlane):
            transform = transform_from_plane(surface)
        elif surface is not None:
            raise TypeError(
                "cannot create a sketch on a non-planar face: "
                f"{type(surface).__name__} is not a plane"
            )
        else:
            transform = None  # a construction plane: the world frame

        sketch = FakeSketch(transform=transform)
        sketch.supportingPlane = geometry
        super().add(sketch)
        return sketch
