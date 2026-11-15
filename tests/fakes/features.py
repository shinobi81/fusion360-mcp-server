"""Fake feature builders and the measurement API.

These are the calls the ``ast`` guards in ``test_addon_api_usage.py`` used to
police by reading the source.  Modelling them lets the same claims be checked by
running the handler instead: an API that does not exist raises ``AttributeError``,
and a wrongly-shaped argument raises ``TypeError``, the way Fusion does.
"""

from __future__ import annotations

from typing import ClassVar

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
        self.added: list[FakeDraftInput] = []

    def createInput(self, input_faces, plane, is_tangent_chain) -> FakeDraftInput:
        if not isinstance(input_faces, (list, tuple)):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'DraftFeatures_createInput'"
            )
        return FakeDraftInput(input_faces, plane, is_tangent_chain)

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


class FakeThreadInfo:
    """``adsk.fusion.ThreadInfo``: what a thread feature is actually built from.

    The class is the reason ``create_thread`` was rebuilt: Fusion's
    ``ThreadFeatures.createInput`` takes a **ThreadInfo**, not the
    ``ThreadDataQuery`` the handler used to pass, and it raises
    ``TypeError: argument 3 of type ThreadInfo`` when handed the query.  Measured
    on Fusion 2706 through ``execute_code``.  So the fake takes ThreadInfo and
    refuses anything else, and the query object below is deliberately not one.
    """

    def __init__(
        self,
        is_tapered,
        is_internal,
        thread_type,
        designation,
        thread_class,
        is_right_handed,
    ):
        self.isTapered = is_tapered
        self.isInternal = is_internal
        self.threadType = thread_type
        self.threadDesignation = designation
        self.threadClass = thread_class
        self.isRightHanded = is_right_handed

    @staticmethod
    def create(
        is_tapered,
        is_internal,
        thread_type,
        thread_designation,
        thread_class,
        is_right_handed,
    ) -> "FakeThreadInfo":
        """Six arguments, in Fusion's order - ``ThreadInfo.create`` from the SDK."""
        return FakeThreadInfo(
            is_tapered,
            is_internal,
            thread_type,
            thread_designation,
            thread_class,
            is_right_handed,
        )


class FakeThreadDataQuery:
    """``threadFeatures.threadDataQuery``: a query, and *not* a ThreadInfo.

    Fusion's query has no ``threadDesignation``/``threadClass`` properties; a
    handler that assigned them would be writing plain Python attributes that
    Fusion never reads.  Keeping the class free of them makes that mistake fail
    here instead of shipping.
    """

    allThreadTypes: ClassVar[list[str]] = [
        "ISO Metric profile",
        "ANSI Unified Screw Threads",
    ]
    defaultMetricThreadType = "ISO Metric profile"
    defaultInchThreadType = "ANSI Unified Screw Threads"


class FakeThreadFeatureInput:
    def __init__(self, faces, thread_info: FakeThreadInfo):
        self.inputCylindricalFace = faces
        self.threadInfo = thread_info
        self.isModeled: bool | None = None
        self.isFullLength: bool | None = None
        self.isRightHanded: bool | None = None
        self.threadLength: FakeValueInput | None = None


class FakeThreadFeatures:
    """``root.features.threadFeatures``: strict where Fusion is strict."""

    def __init__(self):
        self.threadDataQuery = FakeThreadDataQuery()
        self.inputs: list[FakeThreadFeatureInput] = []

    def createInput(self, faces, thread_info) -> FakeThreadFeatureInput:
        if not isinstance(thread_info, FakeThreadInfo):
            raise TypeError(
                "in method 'ThreadFeatures_createInput', argument 3 of type "
                "'adsk::core::Ptr< adsk::fusion::ThreadInfo > const &'"
            )
        created = FakeThreadFeatureInput(faces, thread_info)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeThreadFeatureInput) -> FakeFeature:
        return FakeFeature(f"Thread{len(self.inputs)}")


class FakeRuledSurfaceInput:
    def __init__(self, profile, distance, angle, ruled_type):
        self.profile = profile
        self.distance = distance
        self.angle = angle
        self.ruleType = ruled_type


class FakeProfile:
    """What ``Component.createBRepEdgeProfile`` returns, and the only legal first
    argument to ``RuledSurfaceFeatures.createInput``.

    Fusion's signature is ``createInput(profile, distance, angle, type)``; the
    handler used to pass a raw edge and two arguments, which is the bug these
    fakes exist to keep buried.  Arity alone would not have caught a two-argument
    call that passed an edge - the type check does.
    """

    def __init__(self, edges, chain_edges: bool):
        self.edges = edges
        self.chainEdges = chain_edges


class FakeRuledSurfaceFeatures:
    """``root.features.ruledSurfaceFeatures``: four positional arguments, as in the SDK.

    ``createInput(profile, distance, angle, ruledSurfaceType)`` is the shipped
    signature - the handler used to call it with two arguments and a raw edge,
    which raised ``TypeError: Wrong number or type of arguments`` every time the
    tool was invoked.  The arity is declared so that regression cannot come back.
    """

    def __init__(self):
        self.inputs: list[FakeRuledSurfaceInput] = []

    def createInput(
        self, profile, distance, angle, ruled_type
    ) -> FakeRuledSurfaceInput:
        if not isinstance(profile, FakeProfile):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'RuledSurfaceFeatures_createInput'"
            )
        created = FakeRuledSurfaceInput(profile, distance, angle, ruled_type)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeRuledSurfaceInput) -> FakeFeature:
        return FakeFeature(f"Ruled Surface{len(self.inputs)}")


class FakeSectionAnalysisInput:
    def __init__(self):
        self.plane = None
        self.distance = None


class FakeSectionAnalysis:
    """A created analysis: Fusion's ``Analysis`` carries the name the UI shows."""

    def __init__(self, name: str):
        self.name = name
        self.isLightBulbOn = True
        #: The input it was built from, so a test can read the plane handed over.
        self.input: FakeSectionAnalysisInput | None = None


class FakeAnalyses:
    """``root.analyses``: ``createInput()`` then ``add()`` returns the analysis."""

    def __init__(self):
        self.added: list[FakeSectionAnalysis] = []

    def createInput(self) -> FakeSectionAnalysisInput:
        return FakeSectionAnalysisInput()

    def add(self, inp: FakeSectionAnalysisInput) -> FakeSectionAnalysis:
        analysis = FakeSectionAnalysis(f"Section Analysis{len(self.added) + 1}")
        analysis.input = inp
        self.added.append(analysis)
        return analysis


class FakeExportOptions:
    """One export's options: the entity, the path, and the flags set on it.

    ``meshRefinement`` exists on STL options only - Fusion's STEP options have no
    such property and SWIG raises ``AttributeError`` when one is assigned.  The
    write is refused here for the same reason, so "set the refinement for both
    kinds" fails with the error Fusion gives rather than a value mismatch.
    """

    def __init__(self, kind: str, entity, path: str):
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "entity", entity)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "meshRefinement", None)

    def __setattr__(self, name, value):
        if name == "meshRefinement" and self.kind != "stl":
            raise AttributeError(f"'{self.kind}' export options have no meshRefinement")
        object.__setattr__(self, name, value)


class FakeExportManager:
    """``design.exportManager``.

    The two creation methods keep Fusion's own argument order, which is the whole
    reason the STL and STEP call sites could not simply be merged by name:
    ``createSTLExportOptions(entity, path)`` against
    ``createSTEPExportOptions(path, entity)``.  A fake that took them in one order
    would let a wrong call pass.
    """

    def __init__(self, fail: bool = False):
        self.executed: list[FakeExportOptions] = []
        #: ``isVisible`` of every body in the exported occurrence, sampled inside
        #: ``execute``.  Asserting after the handler returns can only see the state
        #: after the ``finally`` restored it, which is how a sibling sweep that
        #: never ran would still pass.
        self.visible_at_execute: list[bool] | None = None
        self.fail = fail

    # The ``isinstance(path, str)`` guards below exist for one mistake: calling a
    # factory with the arguments swapped.  The tests also assert on ``entity`` and
    # ``path`` directly, so the guard is belt-and-braces - and it is the only way
    # the fake fails with Fusion's own TypeError rather than a shape mismatch.
    def createSTLExportOptions(self, entity, path: str) -> FakeExportOptions:
        if not isinstance(path, str):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'ExportManager_createSTLExportOptions'"
            )
        return FakeExportOptions("stl", entity, path)

    def createSTEPExportOptions(self, path: str, entity) -> FakeExportOptions:
        if not isinstance(path, str):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'ExportManager_createSTEPExportOptions'"
            )
        return FakeExportOptions("step", entity, path)

    def createFusionArchiveExportOptions(self, path: str) -> FakeExportOptions:
        return FakeExportOptions("f3d", None, path)

    def execute(self, options: FakeExportOptions) -> None:
        self.executed.append(options)
        # Cleared first: a second export must not read the previous sample.
        self.visible_at_execute = None
        bodies = getattr(options.entity, "bRepBodies", None)
        if bodies is not None:
            self.visible_at_execute = [
                bodies.item(i).isVisible for i in range(bodies.count)
            ]
        if self.fail:
            raise RuntimeError("3 : Some input argument is invalid.")
