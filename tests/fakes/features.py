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
    """``app.measureManager``: the two queries the measure commands use.

    ``measureAngle`` answers in **radians**, as Fusion does, so a reply that
    skipped ``math.degrees`` reads 1.5708 where the caller asked for 90.  Both
    queries record into ``measured``, because the command's job is to resolve the
    names to the entities it measures - a face pair, for the angle.
    """

    def __init__(
        self,
        value: float = 5.0,
        point_one: tuple[float, float, float] = (0.0, 0.0, 0.0),
        point_two: tuple[float, float, float] = (5.0, 0.0, 0.0),
        angle: float = 0.0,
    ):
        self._result = FakeMeasureResult(value, point_one, point_two)
        self._angle = angle
        self.measured: list[tuple] = []

    def measureMinimumDistance(self, entity_one, entity_two) -> FakeMeasureResult:
        self.measured.append((entity_one, entity_two))
        return self._result

    def measureAngle(self, entity_one, entity_two) -> FakeMeasureResult:
        self.measured.append((entity_one, entity_two))
        return FakeMeasureResult(self._angle, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


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


#: ``(designation, is_internal) -> (major, minor)``, measured on Fusion 2706.
#:
#: Measured, not derived: an ISO formula gives the nominal profile, while Fusion
#: reports the tolerance-band extremes, and they differ by *class* - 6g external and 6H
#: internal are different numbers for the same designation (``M3x0.5`` is 2.927 mm
#: major externally and 3.086 mm internally).  A single value per designation is wrong
#: for half the calls, which is how the first version of this table shipped a 2.459 mm
#: minor for M3x0.5 when Fusion says 2.529 mm.
_THREAD_SIZES: dict[tuple[str, bool], tuple[float, float]] = {
    ("M3x0.5", False): (0.2927, 0.2356),
    ("M3x0.5", True): (0.3086, 0.2529),
    ("M6x1", False): (0.5884, 0.4744),
    ("M6x1", True): (0.6147, 0.5035),
    ("M10x1.5", False): (0.985, 0.8141),
    ("M10x1.5", True): (1.0198, 0.8526),
    ("M20x2.5", False): (1.9791, 1.6938),
    ("M20x2.5", True): (2.0293, 1.7519),
}


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
        if (designation, bool(is_internal)) not in _THREAD_SIZES:
            # Fusion builds a ThreadInfo from its thread XML, so an unknown
            # designation fails there; a fake that invented a diameter would let the
            # size check pass for a thread that does not exist.
            raise RuntimeError(f"{designation!r} is not a thread this fake models")
        if thread_class is None:
            # The real call refuses a null class ("invalid null reference in method
            # ThreadInfo_create, argument 5"), so the fake does too rather than
            # flattering a caller Fusion would reject.
            raise RuntimeError("ThreadInfo.create needs a thread class, not None")
        self.isTapered = is_tapered
        self.isInternal = is_internal
        self.threadType = thread_type
        self.threadDesignation = designation
        self.threadClass = thread_class
        self.isRightHanded = is_right_handed
        self.majorDiameter, self.minorDiameter = _THREAD_SIZES[
            (designation, bool(is_internal))
        ]

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

    @staticmethod
    def create(is_tapered: bool = False) -> "FakeThreadDataQuery":
        """``ThreadDataQuery.create(isTapered)`` - the current accessor.

        ``threadFeatures.threadDataQuery`` is the retired one; Fusion's own docstring
        says so, and the handler uses this.
        """
        return FakeThreadDataQuery()

    def recommendThreadData(self, model_diameter, is_internal, thread_type):
        """``(ok, designation, class)`` for the nearest standard thread.

        Fusion returns the three through out-parameters, which SWIG folds into a
        tuple - measured on 2706: ``(True, 'M20x2.5', '6g')`` for a 2 cm shaft.
        """
        candidates = {
            name: size
            for (name, internal), size in _THREAD_SIZES.items()
            if internal == bool(is_internal)
        }
        # The diameter a thread must match is the major one externally and the minor
        # one in a tapped hole, the same rule the handler applies.
        index = 1 if is_internal else 0
        nearest = min(
            candidates, key=lambda name: abs(candidates[name][index] - model_diameter)
        )
        return True, nearest, "6H" if is_internal else "6g"


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

    # Declared for the type checker: the ``__setattr__`` below writes through
    # ``object.__setattr__``, which pyright cannot see as initialisation.
    kind: str
    entity: object
    path: str
    meshRefinement: object | None

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
