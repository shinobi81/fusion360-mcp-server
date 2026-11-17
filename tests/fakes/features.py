"""Fake feature builders and the measurement API.

These are the calls the ``ast`` guards in ``test_addon_api_usage.py`` used to
police by reading the source.  Modelling them lets the same claims be checked by
running the handler instead: an API that does not exist raises ``AttributeError``,
and a wrongly-shaped argument raises ``TypeError``, the way Fusion does.
"""

from __future__ import annotations

from typing import ClassVar

from .bodies import FakeBody
from .collection import FakeCollection, FakeItemCollection
from .runtime import FakeMatrix3D, FakePoint3D, FakeValueInput


class FakeFeature:
    def __init__(self, name: str, bodies=()):
        self.name = name
        #: Fusion's ``Feature.bodies`` - the bodies the feature created or
        #: modified.  Empty unless a fake models a body, and only
        #: ``FakeExtrudeFeatures`` does: ``create_box_parametric`` renames the body
        #: it built and has nothing else to read it from.  A ``FakeItemCollection``
        #: because Fusion's is a derived view over bodies that live in the
        #: component - it owns none of them and must not reparent one.
        self.bodies = FakeItemCollection(bodies)


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


class FakePatchInput:
    """``PatchFeatureInput``: the two ``createInput`` arguments, under Fusion's names.

    The shipped signature is ``createInput(boundaryCurve, operation)`` - the
    boundary may be a sketch profile, an edge, an ObjectCollection or a Path, and
    only ``NewBodyFeatureOperation``/``NewComponentFeatureOperation`` are accepted
    for the operation (``adsk.fusion.PatchFeatures.createInput``'s own docstring).

    ``continuity`` and ``groupContinuity`` are the names the stub lists.  The
    retired ``continuity`` stays ``None``; ``groupContinuity`` is the one
    ``patch_surface`` writes, and Fusion's own instances also accept arbitrary
    attribute names, so a call site that writes a name the SDK does not ship
    (``boundaryContinuity``) leaves it ``None`` - a silent no-op, which is what
    makes the real name worth declaring.
    """

    def __init__(self, boundary_curve, operation):
        self.boundaryCurve = boundary_curve
        self.operation = operation
        self.continuity = None
        self.groupContinuity = None


class FakePatchFeatures:
    """``root.features.patchFeatures``: two positional arguments, as in the SDK.

    A one- or three-argument call is a ``TypeError`` here as it is in the binding.
    The patched surface itself is not modelled - that needs the boundary's
    geometry - so the reply can only be built from what the call passed.
    """

    def __init__(self):
        self.inputs: list[FakePatchInput] = []
        self.added: list[FakePatchInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakePatchInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, boundary_curve, operation) -> FakePatchInput:
        created = FakePatchInput(boundary_curve, operation)
        self.inputs.append(created)
        return created

    def add(self, inp: FakePatchInput) -> FakeFeature:
        if not isinstance(inp, FakePatchInput):
            raise TypeError("patchFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Patch{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeStitchInput:
    """``stitchFeatures.createInput(stitchSurfaces, tolerance, operation)``.

    ``stitchSurfaces`` is the ``ObjectCollection`` of open bodies the handler
    assembled by name; ``tolerance`` is the ``ValueInput``.  Nothing is set on the
    input afterwards, so the three attributes are the ``createInput`` arguments.
    """

    def __init__(self, stitch_surfaces, tolerance, operation):
        self.stitchSurfaces = stitch_surfaces
        self.tolerance = tolerance
        self.operation = operation


class FakeStitchFeatures:
    """``root.features.stitchFeatures``: three arguments, the last optional.

    The shipped signature is ``createInput(stitchSurfaces, tolerance,
    operation=NewBodyFeatureOperation)``, so the operation may be left out; the
    fake then records the fake runtime's spelling of that default (``new_body``).
    Whether the surfaces actually touch - and therefore whether they stitch at
    all - is Fusion's judgement about geometry this fake does not carry, so it
    records the request and refuses nothing beyond a wrong arity or a wrong
    ``add`` argument.
    """

    def __init__(self):
        self.inputs: list[FakeStitchInput] = []
        self.added: list[FakeStitchInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakeStitchInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(
        self, stitch_surfaces, tolerance, operation="new_body"
    ) -> FakeStitchInput:
        created = FakeStitchInput(stitch_surfaces, tolerance, operation)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeStitchInput) -> FakeFeature:
        if not isinstance(inp, FakeStitchInput):
            raise TypeError("stitchFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Stitch{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeThickenInput:
    """``ThickenFeatureInput``: the four required ``createInput`` arguments.

    ``thickness`` stays the ``ValueInput`` Fusion was handed, so a test reads
    whether the call site passed a real; ``operation`` is the enum member.
    ``isChainSelection`` carries Fusion's shipped default of ``True`` when the
    call site omits the fifth argument.

    There is no direction or flip member: the shipped properties are
    ``inputFaces``, ``thickness``, ``isSymmetric``, ``operation``,
    ``isChainSelection``, ``targetBaseFeature``, ``creationOccurrence`` and
    ``thickenType``.  So ``positive`` and ``negative`` cannot be modelled as
    different calls, which is the API's limit rather than the fake's.
    """

    def __init__(
        self,
        input_faces,
        thickness,
        is_symmetric,
        operation,
        is_chain_selection,
    ):
        self.inputFaces = input_faces
        self.thickness = thickness
        self.isSymmetric = is_symmetric
        self.operation = operation
        self.isChainSelection = is_chain_selection


class FakeThickenFeatures:
    """``root.features.thickenFeatures``: Fusion's five-argument ``createInput``.

    ``createInput(inputFaces, thickness, isSymmetric, operation,
    isChainSelection=True)`` is the shipped signature, so a missing required
    argument or a sixth one is a ``TypeError``.  The thickened solid is not
    modelled: where it lands depends on the faces' normals and the thickness,
    which this fake does not carry.
    """

    def __init__(self):
        self.inputs: list[FakeThickenInput] = []
        self.added: list[FakeThickenInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakeThickenInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(
        self,
        input_faces,
        thickness,
        is_symmetric,
        operation,
        is_chain_selection=True,
    ) -> FakeThickenInput:
        created = FakeThickenInput(
            input_faces, thickness, is_symmetric, operation, is_chain_selection
        )
        self.inputs.append(created)
        return created

    def add(self, inp: FakeThickenInput) -> FakeFeature:
        if not isinstance(inp, FakeThickenInput):
            raise TypeError("thickenFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Thicken{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeMirrorInput:
    """``mirrorFeatures.createInput(objects, mirrorPlane)``: two arguments, no setters.

    ``mirror`` sets no property on this input - it hands over one body and one
    construction plane and calls ``add`` - so nothing here has to match a call
    site's attribute name.  The two attributes are named after Fusion's own
    arguments; that ``createInput`` keeps them is the fake's arrangement, kept so
    a test can read back what the call site passed.  Fusion's ``MirrorFeatureInput``
    also has ``isCombine``, which the handler never touches and the fake does not
    model.
    """

    def __init__(self, objects, mirror_plane):
        self.objects = objects
        self.mirrorPlane = mirror_plane


class FakeMirrorFeatures:
    """``root.features.mirrorFeatures``: the input, and the copy a mirror makes.

    Two things are modelled and one refused:

    * ``createInput`` takes exactly two arguments, Fusion's arity, so a one- or
      three-argument call is a ``TypeError`` rather than a recorded call.
    * ``add`` appends one **new** body per input body to the root component.
      That count is the **fake's model**, not a measurement: it is what a mirror
      produces while ``isCombine`` sits at Fusion's default of false, and the
      handler never sets that property.  The copy's geometry and *name* are the
      fake's too - no test reads either, and none may.
    """

    def __init__(self, design=None):
        self._design = design
        self.inputs: list[FakeMirrorInput] = []
        self.added: list[FakeMirrorInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakeMirrorInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, objects, mirror_plane) -> FakeMirrorInput:
        created = FakeMirrorInput(objects, mirror_plane)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeMirrorInput) -> FakeFeature:
        if not isinstance(inp, FakeMirrorInput):
            raise TypeError("mirrorFeatures.add takes the input createInput returned")
        self.added.append(inp)
        self._copy_each(list(inp.objects))
        feature = FakeFeature(f"Mirror{len(self.added)}")
        self.created.append(feature)
        return feature

    def _copy_each(self, bodies: list) -> None:
        """One copy per body, appended to the root - the fake's only geometry.

        ``add_existing``, not ``add``: a parametric design's ``BRepBodies.add``
        demands a base feature in edit, while a mirror is a timeline feature and
        opens none.  Wrapping the copy in a base feature would invent history.
        """
        root = None if self._design is None else self._design.rootComponent
        if root is None:
            return
        for body in bodies:
            root.bRepBodies.add_existing(FakeBody(f"{body.name} (mirrored)"))


class FakeRectangularPatternInput:
    """``rectangularPatternFeatures``: the first direction up front, the second later.

    Fusion splits the two: ``createInput(inputEntities, directionOne, quantityOne,
    distanceOne, patternDistanceType)`` and then ``setDirectionTwo(direction,
    quantity, distance)``.  The fake declares both halves at that arity, so a
    handler that passes all five to ``createInput`` - or never sets the second
    direction - fails here instead of building a single-direction pattern.

    The attributes are named after Fusion's arguments; that ``createInput`` keeps
    them, and that ``setDirectionTwo`` fills the second triple, is the fake's
    arrangement.  No handler reads any of them back from Fusion.
    """

    def __init__(
        self,
        input_entities,
        direction_one,
        quantity_one,
        distance_one,
        pattern_distance_type,
    ):
        self.inputEntities = input_entities
        self.directionOne = direction_one
        self.quantityOne: FakeValueInput = quantity_one
        self.distanceOne: FakeValueInput = distance_one
        self.patternDistanceType = pattern_distance_type
        # ``None`` until ``setDirectionTwo`` runs, so a call site that skips it is
        # visible rather than defaulted to a second direction nobody asked for.
        self.directionTwo = None
        self.quantityTwo: FakeValueInput | None = None
        self.distanceTwo: FakeValueInput | None = None

    def setDirectionTwo(self, direction, quantity, distance) -> None:
        self.directionTwo = direction
        self.quantityTwo = quantity
        self.distanceTwo = distance


class FakeRectangularPatternFeatures:
    """``root.features.rectangularPatternFeatures``: five arguments, then a setter.

    ``add`` refuses nothing beyond a wrong type: Fusion's second direction is
    optional, and no measurement says what it does with an input that never got
    one, so the fake records the absence (``quantityTwo`` stays ``None``) and
    lets a test assert on it rather than inventing a refusal.
    """

    def __init__(self):
        self.inputs: list[FakeRectangularPatternInput] = []
        self.added: list[FakeRectangularPatternInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakeRectangularPatternInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(
        self,
        input_entities,
        direction_one,
        quantity_one,
        distance_one,
        pattern_distance_type,
    ) -> FakeRectangularPatternInput:
        created = FakeRectangularPatternInput(
            input_entities,
            direction_one,
            quantity_one,
            distance_one,
            pattern_distance_type,
        )
        self.inputs.append(created)
        return created

    def add(self, inp: FakeRectangularPatternInput) -> FakeFeature:
        if not isinstance(inp, FakeRectangularPatternInput):
            raise TypeError(
                "rectangularPatternFeatures.add takes the input createInput returned"
            )
        self.added.append(inp)
        feature = FakeFeature(f"Rectangular Pattern{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeCircularPatternInput:
    """``circularPatternFeatures.createInput(inputEntities, axis)``.

    Two properties follow it, both ``ValueInput``s: ``quantity`` and
    ``totalAngle``.  Both start ``None`` so a call site that sets neither is
    visible.  Fusion's input also has ``isSymmetric``, which the handler never
    touches and the fake therefore does not model.
    """

    def __init__(self, input_entities, axis):
        self.inputEntities = input_entities
        self.axis = axis
        self.quantity: FakeValueInput | None = None
        self.totalAngle: FakeValueInput | None = None


class FakeCircularPatternFeatures:
    """``root.features.circularPatternFeatures``: an entity set and an axis.

    The axis is positional and the fake does not check its type: no measurement
    says what Fusion does with something that is not a construction axis, so the
    fake records what it was handed and leaves the judgement to the test.
    """

    def __init__(self):
        self.inputs: list[FakeCircularPatternInput] = []
        self.added: list[FakeCircularPatternInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakeCircularPatternInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, input_entities, axis) -> FakeCircularPatternInput:
        created = FakeCircularPatternInput(input_entities, axis)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeCircularPatternInput) -> FakeFeature:
        if not isinstance(inp, FakeCircularPatternInput):
            raise TypeError(
                "circularPatternFeatures.add takes the input createInput returned"
            )
        self.added.append(inp)
        feature = FakeFeature(f"Circular Pattern{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeSplitBodyInput:
    """``splitBodyFeatures.createInput(body, splitTool, isSplittingToolExtended)``.

    One call, two shapes: the split tool is a construction plane or another
    BRepBody, and the handler chooses between them on whether a body was named.
    The fake keeps the tool exactly as it was handed over rather than demanding
    one type - which of the two Fusion accepts depends on the same branch, so a
    fake that took only a plane would refuse the body form.  The attribute names
    are Fusion's ``createInput`` arguments; the handler sets no property here.
    """

    def __init__(self, body, split_tool, is_extended):
        self.body = body
        self.splitTool = split_tool
        self.isSplittingToolExtended = is_extended


class FakeSplitBodyFeatures:
    """``root.features.splitBodyFeatures``: what a split was told to cut.

    Three arguments, Fusion's arity, so a two- or four-argument call is a
    ``TypeError``.  What is **not** modelled is the split itself: where a plane
    cuts a solid - and therefore how many bodies come out - needs the geometry,
    so a count here would be the fake's invention, and no handler reports one.
    """

    def __init__(self):
        self.inputs: list[FakeSplitBodyInput] = []
        self.added: list[FakeSplitBodyInput] = []
        self.created: list[FakeFeature] = []

    def createInput(self, body, split_tool, is_extended) -> FakeSplitBodyInput:
        created = FakeSplitBodyInput(body, split_tool, is_extended)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeSplitBodyInput) -> FakeFeature:
        if not isinstance(inp, FakeSplitBodyInput):
            raise TypeError("splitBodyFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Split Body{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeSplitFaceInput:
    """``splitFaceFeatures.createInput(faces, splittingPlane, isExtended)``.

    ``faces`` is the ``ObjectCollection`` of the faces to split, not a body: the
    handler assembles it from indices or from every face the body has.  Nothing
    is set on the input afterwards, so the three attributes are named after
    Fusion's arguments.
    """

    def __init__(self, faces, splitting_plane, is_extended):
        self.faces = faces
        self.splittingPlane = splitting_plane
        self.isSplittingToolExtended = is_extended


class FakeSplitFaceFeatures:
    """``root.features.splitFaceFeatures``: which faces, on which plane.

    Three arguments, Fusion's arity.  The split - a face becoming two - is not
    modelled for the same reason as ``FakeSplitBodyFeatures``: it needs the
    geometry, and no reply field is built on it.
    """

    def __init__(self):
        self.inputs: list[FakeSplitFaceInput] = []
        self.added: list[FakeSplitFaceInput] = []
        self.created: list[FakeFeature] = []

    def createInput(self, faces, splitting_plane, is_extended) -> FakeSplitFaceInput:
        created = FakeSplitFaceInput(faces, splitting_plane, is_extended)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeSplitFaceInput) -> FakeFeature:
        if not isinstance(inp, FakeSplitFaceInput):
            raise TypeError("splitFaceFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Split Face{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeOffsetFacesInput:
    """``offsetFeatures.createInput(faces, distance, operation)``.

    ``distance`` stays the ``ValueInput`` Fusion was handed, so a test reads
    whether the call site passed a real or an expression; ``operation`` is the
    ``FeatureOperations`` member.  The handler sets no property afterwards, so
    the names are the ``createInput`` arguments.
    """

    def __init__(self, faces, distance, operation):
        self.faces = faces
        self.distance = distance
        self.operation = operation


class FakeOffsetFacesFeatures:
    """``root.features.offsetFeatures``: which faces, by how much.

    Three arguments, Fusion's arity.  The offset surface is not modelled - how
    far a face moves depends on its geometry, which this fake does not carry -
    so only the request is recorded, and a test asserts on that.
    """

    def __init__(self):
        self.inputs: list[FakeOffsetFacesInput] = []
        self.added: list[FakeOffsetFacesInput] = []
        self.created: list[FakeFeature] = []

    def createInput(self, faces, distance, operation) -> FakeOffsetFacesInput:
        created = FakeOffsetFacesInput(faces, distance, operation)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeOffsetFacesInput) -> FakeFeature:
        if not isinstance(inp, FakeOffsetFacesInput):
            raise TypeError("offsetFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Offset{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeScaleInput:
    """``ScaleFeatureInput``: one uniform factor, or three after ``setToNonUniform``.

    Fusion's ``createInput`` takes the bodies, the point and one uniform factor;
    a per-axis scale is that same input with ``setToNonUniform(x, y, z)`` called
    on it, which fills ``xScale``/``yScale``/``zScale`` and flips ``isUniform``
    to ``False``.  ``point`` is whatever the handler built from ``anchor_x``/
    ``anchor_y``/``anchor_z``.
    """

    def __init__(self, input_entities, point, scale_factor):
        self.inputEntities = input_entities
        self.point = point
        self.scaleFactor = scale_factor
        self.isUniform = True
        self.xScale = None
        self.yScale = None
        self.zScale = None

    def setToNonUniform(self, x_scale, y_scale, z_scale) -> bool:
        self.xScale = x_scale
        self.yScale = y_scale
        self.zScale = z_scale
        self.isUniform = False
        return True


class FakeScaleFeatures:
    """``root.features.scaleFeatures``: three arguments, as the binding declares.

    ``ScaleFeatures.createInput(inputEntities, point, scaleFactor)`` is not
    overloaded - a four- or five-argument call is a ``TypeError`` here as it is
    in Fusion - and the three factors go on the returned input through
    ``setToNonUniform``.  The scaled geometry is not modelled: a body's points
    move by an amount that depends on the anchor and every vertex, and no reply
    field is built on it.
    """

    def __init__(self):
        self.inputs: list[FakeScaleInput] = []
        self.added: list[FakeScaleInput] = []
        self.created: list[FakeFeature] = []

    def createInput(self, input_entities, point, scale_factor) -> FakeScaleInput:
        created = FakeScaleInput(input_entities, point, scale_factor)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeScaleInput) -> FakeFeature:
        if not isinstance(inp, FakeScaleInput):
            raise TypeError("scaleFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Scale{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeMoveInput:
    """``moveFeatures.createInput(inputEntities, transform)``.

    The transform is the ``Matrix3D`` the handler built, so a test can read the
    ``translation`` it set on it.  Nothing is set on the input afterwards.
    """

    def __init__(self, input_entities, transform):
        self.inputEntities = input_entities
        self.transform = transform


class FakeMoveFeatures:
    """``root.features.moveFeatures``: two arguments, as the binding declares.

    The type check is not decoration: the handler's mistake would be to hand
    over a ``Vector3D`` - the translation it just built - where the placement
    belongs, and Fusion answers that with "Wrong number or type of arguments".
    The move itself is not modelled; nothing reads where the body went.
    """

    def __init__(self):
        self.inputs: list[FakeMoveInput] = []
        self.added: list[FakeMoveInput] = []
        self.created: list[FakeFeature] = []

    def createInput(self, input_entities, transform) -> FakeMoveInput:
        if not isinstance(transform, FakeMatrix3D):
            raise TypeError(
                "Wrong number or type of arguments for overloaded function "
                "'MoveFeatures_createInput': expected a Matrix3D, got "
                f"{type(transform).__name__}"
            )
        created = FakeMoveInput(input_entities, transform)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeMoveInput) -> FakeFeature:
        if not isinstance(inp, FakeMoveInput):
            raise TypeError("moveFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Move{len(self.added)}")
        self.created.append(feature)
        return feature


class FakeUnfoldFeatureInput:
    """``UnfoldFeatureInput``: the stationary face up front, the bends afterwards.

    Read from ``Fusion/SheetMetal/UnfoldFeatureInput.h``: ``stationaryFace``
    (``:46-47``, "The stationary face is set when createInput is called but can be
    changed before calling add"), ``bendFaces`` (``:54-55``, a
    ``std::vector<core::Ptr<BRepFace>>`` - the inner or outer cylindrical face of
    each bend), and ``isUnfoldAllBends`` (``:61-62``), which ``:58-59`` says unfolds
    every bend and **ignores** ``bendFaces`` when true, defaulting to false.

    The two later properties start at Fusion's defaults - no bend faces and the flag
    off - so a call site that sets neither is visible rather than defaulted, and a
    call site that sets both is visible too, since Fusion would read only the flag.
    """

    def __init__(self, stationary_face):
        self.stationaryFace = stationary_face
        self.bendFaces: list = []
        self.isUnfoldAllBends: bool = False


class FakeUnfoldFeatures:
    """``root.features.unfoldFeatures``: ``createInput`` takes the stationary face
    alone.

    ``UnfoldFeatures.h:63`` ships ``createInput(const core::Ptr<BRepFace>&
    stationaryFace)`` - **one** argument, the face that stays fixed.  The handler
    used to pass ``(bends, stationary)``, a collection first, which Fusion answers
    with ``TypeError: Wrong number or type of arguments`` on every call; declaring
    the arity here is what keeps that call from coming back, so a two- or
    three-argument call is a ``TypeError`` in the fake too.

    The face is not type-checked and the unfold itself is not modelled: whether a
    face is a bend's wall, and what the flattened body looks like, is Fusion's
    judgement about geometry this fake does not carry.
    """

    def __init__(self):
        self.inputs: list[FakeUnfoldFeatureInput] = []
        self.added: list[FakeUnfoldFeatureInput] = []
        self.created: list[FakeFeature] = []

    @property
    def last_input(self) -> FakeUnfoldFeatureInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, stationary_face) -> FakeUnfoldFeatureInput:
        created = FakeUnfoldFeatureInput(stationary_face)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeUnfoldFeatureInput) -> FakeFeature:
        if not isinstance(inp, FakeUnfoldFeatureInput):
            raise TypeError("unfoldFeatures.add takes the input createInput made")
        self.added.append(inp)
        feature = FakeFeature(f"Unfold{len(self.added)}")
        self.created.append(feature)
        return feature


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
