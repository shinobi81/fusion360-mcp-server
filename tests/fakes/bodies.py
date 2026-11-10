"""Fake bodies, faces and bounding boxes.

``draft_faces`` selects faces by normal and ``delete_all`` deletes bodies, so a
body has to be more than a name: it carries faces with evaluators and boxes,
and its ``deleteMe()`` really removes it from the root's collection.
"""

from __future__ import annotations

import math

from .collection import FakeCollection, FakeDeletable
from .runtime import (
    FakeCylinderGeometry,
    FakeJointGeometry,
    FakePlane,
    FakePoint3D,
    FakeVector3D,
)


class FakeBoundingBox:
    def __init__(
        self,
        min_point: tuple[float, float, float] = (0.0, 0.0, 0.0),
        max_point: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ):
        self.minPoint = FakePoint3D(*min_point)
        self.maxPoint = FakePoint3D(*max_point)


class FakeOrientedBoundingBox3D:
    """``adsk.core.OrientedBoundingBox3D``: a centre, two directions, three sizes.

    Read from the shipped stub (``adsk/core.py``, ``OrientedBoundingBox3D.create``):
    ``centerPoint`` is the box's **centre**, the length and width directions carry
    only a direction ("the magnitude of the vector is ignored"), the width
    direction "must be perpendicular to the length direction", and the height runs
    along length x width by the right-hand rule.

    The perpendicularity and the size checks are the fake's **own** stricter
    rules, not quoted refusals: the stub says the width direction "must be
    perpendicular to the length direction" and gives no error, and says nothing at
    all about a zero or negative size.  Being stricter than Fusion is safe here -
    it can only fail a call Fusion would reject or mishandle - but neither is
    evidence of what Fusion does.
    """

    def __init__(
        self,
        center_point: FakePoint3D,
        length_direction: FakePoint3D,
        width_direction: FakePoint3D,
        length: float,
        width: float,
        height: float,
    ):
        self.centerPoint = center_point
        self.lengthDirection = FakeVector3D(*_as_unit(length_direction, "length"))
        self.widthDirection = FakeVector3D(*_as_unit(width_direction, "width"))
        if abs(_dot(self.lengthDirection, self.widthDirection)) > 1e-9:
            raise ValueError("widthDirection must be perpendicular to lengthDirection")
        self.heightDirection = FakeVector3D(
            *_cross(self.lengthDirection, self.widthDirection)
        )
        for name, value in (
            ("length", length),
            ("width", width),
            ("height", height),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite size: {value!r}")
        self.length = float(length)
        self.width = float(width)
        self.height = float(height)

    @staticmethod
    def create(
        centerPoint: FakePoint3D,
        lengthDirection: FakePoint3D,
        widthDirection: FakePoint3D,
        length: float,
        width: float,
        height: float,
    ) -> "FakeOrientedBoundingBox3D":
        return FakeOrientedBoundingBox3D(
            centerPoint, lengthDirection, widthDirection, length, width, height
        )

    def world_half_extents(self) -> tuple[float, float, float]:
        """Half the box's size along each **world** axis, after orientation.

        An oriented box's axis-aligned box is the projection of its three edge
        vectors, which for a box built on the world axes is simply half its size
        on that axis.
        """
        directions = (
            self.lengthDirection,
            self.widthDirection,
            self.heightDirection,
        )
        halves = (self.length / 2, self.width / 2, self.height / 2)
        # Materialised so ``strict`` is checked once, and so each sum below reads
        # the same three (direction, half-extent) pairs.
        edges = tuple(zip(directions, halves, strict=True))
        return (
            sum(abs(d.coords()[0]) * h for d, h in edges),
            sum(abs(d.coords()[1]) * h for d, h in edges),
            sum(abs(d.coords()[2]) * h for d, h in edges),
        )


class FakeTemporaryBRepManager:
    """``adsk.fusion.TemporaryBRepManager``: ``get()`` and ``createBox``.

    ``createBox`` is the only primitive modelled, because it is the only one a
    test drives: ``createCylinderOrCone``, ``createSphere`` and ``createTorus``
    are absent, so those three handlers still cannot run under the fake.  The body
    returned is transient and face-less - not null - whose box is the oriented box
    projected onto the world axes, so a test reads where the solid actually landed
    rather than trusting the arguments it was asked for.  Its ``volume`` and
    ``area`` are the box's real ones; its face count is not modelled, because
    nothing reads a primitive's faces.
    """

    @staticmethod
    def get() -> "FakeTemporaryBRepManager":
        return FakeTemporaryBRepManager()

    def createBox(self, box: object) -> "FakeBody":
        if not isinstance(box, FakeOrientedBoundingBox3D):
            raise TypeError(
                f"createBox takes an OrientedBoundingBox3D, not {type(box).__name__}"
            )
        centre = box.centerPoint.coords()
        half = box.world_half_extents()
        body = FakeBody(
            "Box",
            faces=FakeCollection(),
            bounding_box=FakeBoundingBox(
                (centre[0] - half[0], centre[1] - half[1], centre[2] - half[2]),
                (centre[0] + half[0], centre[1] + half[1], centre[2] + half[2]),
            ),
        )
        length, width, height = box.length, box.width, box.height
        body.volume = length * width * height
        body.area = 2 * (length * width + length * height + width * height)
        return body


def _as_unit(vector: FakePoint3D, name: str) -> tuple[float, float, float]:
    """A direction vector, normalised - Fusion ignores the magnitude."""
    x, y, z = vector.coords()
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0:
        raise ValueError(f"{name}Direction has no direction: {vector!r}")
    return (x / length, y / length, z / length)


def _dot(a: FakePoint3D, b: FakePoint3D) -> float:
    ax, ay, az = a.coords()
    bx, by, bz = b.coords()
    return ax * bx + ay * by + az * bz


def _cross(a: FakePoint3D, b: FakePoint3D) -> tuple[float, float, float]:
    ax, ay, az = a.coords()
    bx, by, bz = b.coords()
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


class FakeEvaluator:
    def __init__(self, normal: tuple[float, float, float]):
        self._normal = normal

    def getNormalAtPoint(self, point):
        """Fusion returns ``(result_flag, normal)``, not the point."""
        return True, FakeVector3D(*self._normal)


class FakeVertex:
    """A vertex: the handler reads ``.geometry`` off it."""

    def __init__(self, point: tuple[float, float, float]):
        self.geometry = FakePoint3D(*point)


class FakeEdgeEvaluator:
    """Enough of Fusion's evaluator to place a point anywhere along the edge."""

    def __init__(self, edge: FakeEdge):
        self._edge = edge

    #: Fusion's edge parameters are the edge's own, not 0..1 — measured on a
    #: straight edge in Fusion 2706, which reported exactly this range.
    ranges = (-1.0, 0.0)

    #: Fusion's first answer is a flag: False means "could not measure".
    found = True

    def getParameterExtents(self):
        """``(found, low, high)`` — Fusion's three-part answer."""
        return self.found, self.ranges[0], self.ranges[1]

    def getPointAtParameter(self, parameter):
        """``(found, point)`` for a parameter inside the edge's own range.

        Fusion refuses a parameter outside that range with ``3 : invalid
        argument parameter``, and returns a two-part answer rather than a point;
        the fake does both, so a handler that samples 0..1 or unpacks wrongly
        fails here.  It did not, once: a live run found this, not the suite.
        """
        low, high = self.ranges
        if not low - 1e-9 <= parameter <= high + 1e-9:
            raise RuntimeError("3 : invalid argument parameter")
        t = 0.0 if high == low else (parameter - low) / (high - low)
        start = self._edge.startVertex.geometry
        end = self._edge.endVertex.geometry
        return True, FakePoint3D(
            start.x + (end.x - start.x) * t,
            start.y + (end.y - start.y) * t,
            start.z + (end.z - start.z) * t,
        )


class FakeEdge:
    """A straight edge with the attributes ``_select_edges`` reads.

    ``pointOnEdge`` is Fusion's point at the *parameter* midpoint, so it differs
    from the average of the vertices on a curved edge, and a closed edge's two
    vertices coincide so its midpoint *is* its seam point (measured in Fusion
    2706). ``boundingBox`` is Fusion's box for the edge itself, which is how the
    planes the top/bottom selectors use are measured; on a straight edge it is
    just the two endpoint extremes.
    """

    def __init__(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        curve_type: str = "Line3D",
        index: int = 0,
        bounding_box: FakeBoundingBox | None = None,
    ):
        self.startVertex = FakeVertex(start)
        self.endVertex = FakeVertex(end)
        self.index = index
        self.evaluator = FakeEdgeEvaluator(self)
        self.geometry = type(curve_type, (), {"__module__": "adsk.core"})()
        self._bounding_box = bounding_box
        #: Fusion's own flag. A degenerate edge has no geometry at all — a cone's
        #: apex produces them (measured on 2706) — and no fillet can round one.
        self.isDegenerate = False
        middle = sum(self.evaluator.ranges) / 2
        self.pointOnEdge = self.evaluator.getPointAtParameter(middle)[1]

    @property
    def boundingBox(self) -> FakeBoundingBox:
        """The edge's own box — not the body's, which is what went wrong.

        A closed or curved edge must be given a box of its own. Measured live on
        Fusion 2706, a ``Circle3D``'s two vertices are the *same point* and its
        box spans the whole circle, so deriving a box from the vertices would
        hide exactly the case that made the old end-to-end ``vertical`` test call
        every circle vertical. Deriving one silently for a curve would let a test
        pass on a lie, so it raises instead.
        """
        if self._bounding_box is not None:
            return self._bounding_box
        if type(self.geometry).__name__ != "Line3D":
            raise RuntimeError(
                f"FakeEdge of type {type(self.geometry).__name__} needs an explicit "
                "bounding_box: an endpoint box is only true for a straight edge."
            )
        start = self.startVertex.geometry
        end = self.endVertex.geometry
        return FakeBoundingBox(
            (min(start.x, end.x), min(start.y, end.y), min(start.z, end.z)),
            (max(start.x, end.x), max(start.y, end.y), max(start.z, end.z)),
        )

    @property
    def length(self) -> float:
        start = self.startVertex.geometry
        end = self.endVertex.geometry
        return (
            (end.x - start.x) ** 2 + (end.y - start.y) ** 2 + (end.z - start.z) ** 2
        ) ** 0.5

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakeEdge({self.startVertex.geometry} -> {self.endVertex.geometry})"


class FakeEdges(FakeCollection):
    """``body.edges``: indexed, iterable, and countable like Fusion's."""


class FakeFace:
    """A face: a normal, a surface, a bounding box, a point on it, joint geometry.

    ``geometry`` is the face's underlying *surface* as Fusion reports it, so
    ``adsk.core.Plane.cast(face.geometry)`` is the same test the handler makes:
    a Plate's top face is a plane, a bore wall is not.  ``pointOnFace`` is *some*
    point on the face - Fusion does not promise the centroid - and the fake uses
    the box centre, which is on the face.  It has to be: it also fixes the face's
    own plane, and a point off the face would put that plane where it never is.

    ``joint_geometry_for`` is what ``JointGeometry.createByCylinderOrConeFace``
    asks the face for.  The defaults are the live measurement for a cylinder
    whose bore is world Z with ``quadrant="middle"``: origin on the SURFACE at
    radius 2, frame primary=-X, secondary=-Y, third=+Z.  That frame matters —
    under the measured mapping (joint X = secondary, Y = third, Z = primary) it
    makes joint X world -Y, so a handler that passed the caller's axis straight
    through is caught.  An identity frame would not: it would make the mapping
    and the old passthrough indistinguishable.
    """

    def __init__(
        self,
        normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
        bounding_box: FakeBoundingBox | None = None,
        joint_frame: dict | None = None,
        area: float = 1.0,
        point_on_face: tuple[float, float, float] | None = None,
        planar: bool = True,
    ):
        self.boundingBox = bounding_box or FakeBoundingBox()
        box = self.boundingBox
        centre = (
            (box.minPoint.x + box.maxPoint.x) / 2,
            (box.minPoint.y + box.maxPoint.y) / 2,
            (box.minPoint.z + box.maxPoint.z) / 2,
        )
        self.pointOnFace = FakePoint3D(
            *(point_on_face if point_on_face is not None else centre)
        )
        self.evaluator = FakeEvaluator(normal)
        self.area = area
        self.geometry = (
            FakePlane(self.pointOnFace.coords(), normal)
            if planar
            else FakeCylinderGeometry()
        )
        self.joint_frame = joint_frame or {
            "origin": (-2.0, 0.0, 5.0),
            "primary": (-1.0, 0.0, 0.0),
            "secondary": (0.0, -1.0, 0.0),
            "third": (0.0, 0.0, 1.0),
        }

    def joint_geometry_for(self, quadrant, key_point):
        """The ``JointGeometry`` Fusion builds for this face and these enums.

        Live, the quadrant picks the angle around the bore and the key point picks
        the height along it; every combination lands on the surface.  The mapping
        is not modelled here because the handler never reads it — it reads the
        frame — so this returns the frame the test asked for.
        """
        return FakeJointGeometry(**self.joint_frame)


class FakeBody(FakeDeletable):
    """A body with the attributes the handlers read, and real deletion."""

    def __init__(
        self,
        name: str = "Body1",
        faces: FakeCollection | None = None,
        bounding_box: FakeBoundingBox | None = None,
        edges: FakeCollection | None = None,
    ):
        super().__init__(name)
        self.volume = 1.0
        self.area = 6.0
        self.material = None
        self.isVisible = True
        self.boundingBox = bounding_box or FakeBoundingBox()
        self.faces = faces if faces is not None else FakeCollection([FakeFace()])
        self.edges = edges if edges is not None else FakeEdges([])


def body_with_faces(name: str, normals: list[tuple[float, float, float]]) -> FakeBody:
    """A body whose faces have the given normals, for ``_select_faces``."""
    faces = FakeCollection([FakeFace(normal) for normal in normals])
    return FakeBody(name, faces=faces)


def body_with_edges(
    name: str,
    pairs: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    curve_type: str = "Line3D",
    bounding_box: FakeBoundingBox | None = None,
) -> FakeBody:
    """A body whose edges run between the given start/end pairs, in order.

    The body's box is derived from the edges unless one is passed: a body whose
    top is a curved surface spans past every one of its edges, and the top/bottom
    selectors must not read that span as "where the edges are".
    """
    edges = FakeEdges(
        [
            FakeEdge(start, end, curve_type=curve_type, index=index)
            for index, (start, end) in enumerate(pairs)
        ]
    )
    box = FakeBoundingBox()
    if pairs:
        xs = [c for pair in pairs for c in (pair[0][0], pair[1][0])]
        ys = [c for pair in pairs for c in (pair[0][1], pair[1][1])]
        zs = [c for pair in pairs for c in (pair[0][2], pair[1][2])]
        box = FakeBoundingBox((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return FakeBody(
        name,
        faces=FakeCollection([FakeFace()]),
        bounding_box=bounding_box or box,
        edges=edges,
    )
