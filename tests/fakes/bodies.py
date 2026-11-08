"""Fake bodies, faces and bounding boxes.

``draft_faces`` selects faces by normal and ``delete_all`` deletes bodies, so a
body has to be more than a name: it carries faces with evaluators and boxes,
and its ``deleteMe()`` really removes it from the root's collection.
"""

from __future__ import annotations

from .collection import FakeCollection, FakeDeletable
from .runtime import FakePoint3D, FakeVector3D


class FakeBoundingBox:
    def __init__(
        self,
        min_point: tuple[float, float, float] = (0.0, 0.0, 0.0),
        max_point: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ):
        self.minPoint = FakePoint3D(*min_point)
        self.maxPoint = FakePoint3D(*max_point)


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
    """A planar face: a normal, a bounding box and a point on it."""

    def __init__(
        self,
        normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
        bounding_box: FakeBoundingBox | None = None,
    ):
        self.pointOnFace = FakePoint3D()
        self.evaluator = FakeEvaluator(normal)
        self.boundingBox = bounding_box or FakeBoundingBox()


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
