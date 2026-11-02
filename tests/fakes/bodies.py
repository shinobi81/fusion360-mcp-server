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
        """Fusion returns ``(point, normal)``; callers usually keep the normal."""
        return point, FakeVector3D(*self._normal)


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
    ):
        super().__init__(name)
        self.volume = 1.0
        self.area = 6.0
        self.material = None
        self.isVisible = True
        self.boundingBox = bounding_box or FakeBoundingBox()
        self.faces = faces if faces is not None else FakeCollection([FakeFace()])


def body_with_faces(name: str, normals: list[tuple[float, float, float]]) -> FakeBody:
    """A body whose faces have the given normals, for ``_select_faces``."""
    faces = FakeCollection([FakeFace(normal) for normal in normals])
    return FakeBody(name, faces=faces)
