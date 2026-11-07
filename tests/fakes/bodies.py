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

    def getPointAtParameter(self, t: float):
        """Straight-line interpolation between the vertices.

        Fusion returns a Point3D for a curve that has one; a fake edge is always
        straight, and the handler only samples a handful of parameters.
        """
        start = self._edge.startVertex.geometry
        end = self._edge.endVertex.geometry
        t = max(0.0, min(1.0, float(t)))
        return FakePoint3D(
            start.x + (end.x - start.x) * t,
            start.y + (end.y - start.y) * t,
            start.z + (end.z - start.z) * t,
        )


class FakeEdge:
    """A straight edge with the four attributes ``_select_edges`` reads.

    ``pointOnEdge`` is Fusion's point at the *parameter* midpoint, so it differs
    from the average of the vertices on a curved edge; here every edge is a
    straight line and the two coincide, which is stated rather than hidden.
    """

    def __init__(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        curve_type: str = "Line3D",
        index: int = 0,
    ):
        self.startVertex = FakeVertex(start)
        self.endVertex = FakeVertex(end)
        self.index = index
        self.evaluator = FakeEdgeEvaluator(self)
        self.geometry = type(curve_type, (), {"__module__": "adsk.core"})()
        self.pointOnEdge = self.evaluator.getPointAtParameter(0.5)

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
) -> FakeBody:
    """A body whose edges run between the given start/end pairs, in order."""
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
        bounding_box=box,
        edges=edges,
    )
