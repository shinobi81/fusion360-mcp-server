"""Fake feature builders and the measurement API.

These are the calls the ``ast`` guards in ``test_addon_api_usage.py`` used to
police by reading the source.  Modelling them lets the same claims be checked by
running the handler instead: an API that does not exist raises ``AttributeError``,
and a wrongly-shaped argument raises ``TypeError``, the way Fusion does.
"""

from __future__ import annotations

from .collection import FakeCollection
from .runtime import FakePoint3D, FakeValueInput


class FakeFeature:
    def __init__(self, name: str):
        self.name = name


class FakeDraftInput:
    def __init__(self, faces, plane, is_tangent_chain):
        self.faces = faces
        self.plane = plane
        self.isTangentChain = is_tangent_chain
        self.angle: FakeValueInput | None = None
        self.symmetric: bool | None = None

    def setSingleAngle(self, is_symmetric, angle) -> None:
        self.symmetric = is_symmetric
        self.angle = angle


class FakeDraftFeatures:
    """``root.features.draftFeatures``.

    ``createInput`` demands a *sequence* of faces.  Fusion rejects an
    ObjectCollection with "Wrong number or type of arguments for overloaded
    function", which is exactly the bug the old source guard covered, so the
    fake rejects it too rather than accepting anything iterable.
    """

    def __init__(self):
        self.inputs: list[FakeDraftInput] = []
        self.added: list[FakeDraftInput] = []

    def createInput(self, input_faces, plane, is_tangent_chain) -> FakeDraftInput:
        if not isinstance(input_faces, (list, tuple)):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'DraftFeatures_createInput'"
            )
        created = FakeDraftInput(input_faces, plane, is_tangent_chain)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeDraftInput) -> FakeFeature:
        self.added.append(inp)
        return FakeFeature("Draft1")


class FakeInterferenceInput:
    def __init__(self, entities):
        self.entities = entities
        self.areCoincidentFacesIncluded = False


class FakeInterferenceBody:
    def __init__(self, volume: float):
        self.volume = volume


class FakeInterferenceResult:
    def __init__(self, entity_one, entity_two, volume: float = 0.5):
        self.entityOne = entity_one
        self.entityTwo = entity_two
        self.interferenceBody = FakeInterferenceBody(volume)


class FakeMeasureResult:
    """``MeasureResults``: ``positionOne`` / ``positionTwo`` and nothing else.

    ``pointOnEntityOne`` does not exist in the Fusion API; the bug was reading
    it, and a fake that quietly provided it would hide that.
    """

    def __init__(
        self,
        value: float,
        point_one: tuple[float, float, float],
        point_two: tuple[float, float, float],
    ):
        self.value = value
        self.positionOne = FakePoint3D(*point_one)
        self.positionTwo = FakePoint3D(*point_two)


class FakeMeasureManager:
    """``app.measureManager``: the minimum-distance query ``measure_distance`` uses."""

    def __init__(
        self,
        value: float = 5.0,
        point_one: tuple[float, float, float] = (0.0, 0.0, 0.0),
        point_two: tuple[float, float, float] = (5.0, 0.0, 0.0),
    ):
        self._result = FakeMeasureResult(value, point_one, point_two)
        self.measured: list[tuple] = []

    def measureMinimumDistance(self, entity_one, entity_two) -> FakeMeasureResult:
        self.measured.append((entity_one, entity_two))
        return self._result


class FakeInterference:
    """The design-level interference API: ``createInterferenceInput`` + analyse."""

    def __init__(self, results: list[FakeInterferenceResult] | None = None):
        self.results = FakeCollection(results or [])
        self.inputs: list[FakeInterferenceInput] = []

    def createInterferenceInput(self, entities) -> FakeInterferenceInput:
        created = FakeInterferenceInput(entities)
        self.inputs.append(created)
        return created

    def analyzeInterference(self, inp: FakeInterferenceInput) -> FakeCollection:
        return self.results
