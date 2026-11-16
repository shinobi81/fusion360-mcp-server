"""Mesh bodies: the collection ``compare_meshes`` searches, and the meshes it compares.

``compare_meshes`` walks ``rootComponent.meshBodies`` by name, takes
``body.mesh or body.displayMesh`` from each, and turns ``mesh_a.compareWith(mesh_b)``
into min / max / mean-absolute / RMS.  No fixture had ``meshBodies`` at all, so the
command was executed by no test.

What is **not** modelled: the deviations themselves.  Fusion computes one signed
distance per node of mesh A against the surface of mesh B; doing that would mean
modelling both tessellations, and a fake that did would report its own arithmetic
instead of the handler's.  So a ``FakePolygonMesh`` is *told* the list
``compareWith`` answers - that list is the test's, not a measurement - and the one
value geometry supplies is a mesh compared with **itself**: all zeros, because every
node lies on its own surface.

``MeshBodies.add(filePath, units)`` and ``addByFile`` are not here: they belong to
``import_mesh``, whose ``add`` takes a path rather than an item, so a stub with that
name and a different signature would be an invented API.  A component's
``meshBodies`` starts empty, which is a design with no mesh in it.
"""

from __future__ import annotations

from .collection import FakeDeletable


class FakePolygonMesh:
    """``adsk.fusion.PolygonMesh``: ``nodeCount`` and ``compareWith``.

    ``deviations`` is the list ``compareWith`` answers when it is compared with
    another mesh - one signed distance per node, in centimetres, as Fusion reports
    them.  Leave it out for a mesh that is only ever compared with itself.
    """

    def __init__(self, node_count: int, deviations: list[float] | None = None):
        self.nodeCount = node_count
        self._deviations = None if deviations is None else list(deviations)
        if self._deviations is not None and len(self._deviations) != node_count:
            raise ValueError(
                "compareWith answers one distance per node: "
                f"{node_count} nodes, {len(self._deviations)} distances"
            )

    def compareWith(self, other: "FakePolygonMesh") -> list[float]:
        if other is self:
            return [0.0] * self.nodeCount
        if self._deviations is None:
            raise AttributeError(
                "FakePolygonMesh.compareWith: this mesh was not told its deviations. "
                "Two distinct meshes have a distance Fusion computes from their "
                "surfaces, which this fake does not model - pass ``deviations``."
            )
        return list(self._deviations)


class FakeMeshBody(FakeDeletable):
    """``adsk.fusion.MeshBody``: a name and its polygon mesh.

    Only ``mesh`` is populated.  Fusion exposes ``displayMesh`` as well and the
    handler falls back to it when ``mesh`` is empty, but nothing here measured which
    of the two a mesh body carries, so the fake leaves the second one empty rather
    than claiming they are the same object.
    """

    def __init__(self, name: str, mesh: FakePolygonMesh):
        super().__init__(name)
        self.mesh = mesh
        self.displayMesh = None


class FakeMeshBodies:
    """``component.meshBodies``: ``count`` / ``item(i)``.

    Not a ``FakeCollection``: Fusion's ``MeshBodies.add`` takes a file path and a
    unit, so inheriting that collection's one-item ``add`` would put the wrong
    signature under Fusion's name — the same reason ``FakeRigidGroups`` carries its
    own members.
    """

    def __init__(self, items: list[FakeMeshBody] | None = None):
        self._items: list[FakeMeshBody] = list(items or [])

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> FakeMeshBody:
        return self._items[index]
