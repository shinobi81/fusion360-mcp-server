"""Fake design tree: document, timeline, root component, features and UI.

Two Fusion behaviours are modelled rather than stubbed, because both are the
reason the tests in ``test_addon_undo.py`` and ``test_addon_revolve_axis.py``
exist:

* ``design.timeline`` **raises** on a direct design (Fusion: "3 : this is not a
  parametric design"), so a caller that reads it behind ``hasattr`` breaks —
  ``hasattr`` only swallows ``AttributeError``.
* a revolve about a **stale profile proxy** is rejected, so reading the profile
  before adding the axis line to the same sketch fails instead of passing.

``delete_all`` additionally needs deletions to be real: the timeline object
wraps an entity, and only the *entity* has ``deleteMe()``.  Both are modelled
here, so a sweep that calls the wrong one leaves the design populated and the
test fails.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

from .appearance import FakeAppearances
from .bodies import FakeBody, FakeFace
from .collection import FakeCollection, FakeDeletable, FakeItemCollection
from .features import (
    FakeAnalyses,
    FakeCircularPatternFeatures,
    FakeDraftFeatures,
    FakeExportManager,
    FakeFeature,
    FakeInterference,
    FakeMirrorFeatures,
    FakeMoveFeatures,
    FakeOffsetFacesFeatures,
    FakePatchFeatures,
    FakeProfile,
    FakeRectangularPatternFeatures,
    FakeRuledSurfaceFeatures,
    FakeScaleFeatures,
    FakeSplitBodyFeatures,
    FakeSplitFaceFeatures,
    FakeStitchFeatures,
    FakeThickenFeatures,
    FakeThreadFeatures,
    FakeUnfoldFeatures,
)
from .mesh import FakeMeshBodies
from .runtime import (
    DIRECT,
    PARAMETRIC,
    FakeMatrix3D,
    FakePoint3D,
    FakeUserCoordinateSystemGeometry,
    FakeValueInput,
)
from .sketch import FakeSketches, FakeSketchPoint


class FakeTimelineEntity:
    """The feature a timeline object wraps.  This is where ``deleteMe()`` lives."""

    def __init__(self, name: str, remove):
        self.name = name
        self._remove = remove

    def deleteMe(self) -> None:
        self._remove()


class FakeTimelineObject:
    """``design.timeline.item(i)``: a name and an entity — and no ``deleteMe()``."""

    def __init__(self, name: str, remove):
        self.name = name
        self.entity = FakeTimelineEntity(name, remove)
        # A real property: ``_set_suppressed`` writes it for both
        # ``suppress_feature`` and ``unsuppress_feature``, and the test reads it
        # back to prove the flip landed on the named entry.
        self.isSuppressed = False


class FakeTimeline:
    """``design.timeline``: entries, a count and a movable marker."""

    def __init__(self, design: FakeDesign):
        self._design = design

    @property
    def count(self) -> int:
        return self._design.timeline_count

    def item(self, index: int) -> FakeTimelineObject:
        return self._design.timeline_entries[index]

    @property
    def markerPosition(self) -> int:
        return self._design.marker

    @markerPosition.setter
    def markerPosition(self, value: int) -> None:
        self._design.set_marker(value)


class FakeParameter(FakeDeletable):
    """A user parameter.  Assigning ``value`` is refused on purpose.

    Fusion reads ``Parameter.value`` in internal units, so a handler that
    assigns it silently rescales anything measured in another unit; the fixed
    handler writes ``expression`` instead.  Making the setter raise turns that
    regression into a failure here.
    """

    def __init__(
        self,
        name: str,
        expression: str,
        unit: str = "",
        comment: str = "",
        source: str = "string",
    ):
        super().__init__(name)
        self.expression = expression
        self.unit = unit
        self.comment = comment
        # Which ValueInput factory produced it: "string" or "real".
        self.source = source

    @property
    def value(self) -> float:
        """The expression's leading number - **not** Fusion's centimetres.

        Fusion answers ``Parameter.value`` in internal units, so ``"100 mm"`` is
        ``10.0``; this fake splits the expression and returns the number verbatim,
        so the same parameter reads back as ``100.0``.  The tests that assert on
        ``value`` pin the field's wiring, not the conversion, and say so where they
        assert it; ``expression`` is what the handler must write.
        """
        first = self.expression.split()[0] if self.expression else "0"
        return float(first)

    @value.setter
    def value(self, _new: float) -> None:
        raise RuntimeError(
            "Parameter.value is read in internal units; write the expression"
        )


class FakeUserParameters:
    """``design.userParameters``: add, look up by name, count, iterate."""

    def __init__(self):
        self._parameters: dict[str, FakeParameter] = {}

    def add(self, name, value_input, unit, comment) -> FakeParameter:
        expression = (
            value_input.value
            if isinstance(value_input.value, str)
            else str(value_input.value)
        )
        created = FakeParameter(name, expression, unit, comment, value_input.kind)
        # ``Parameter.deleteMe()`` removes it from this collection, so the
        # collection has to be the one that knows how: ``delete_parameter`` reads
        # back through ``get_parameters``, where a parameter that only looked
        # deleted is still there.
        created._collection = self
        self._parameters[name] = created
        return created

    def remove(self, parameter: FakeParameter) -> None:
        """What ``FakeDeletable.deleteMe()`` calls; Fusion's deletion is per item."""
        self._parameters.pop(parameter.name, None)

    def itemByName(self, name: str) -> FakeParameter | None:
        return self._parameters.get(name)

    @property
    def count(self) -> int:
        return len(self._parameters)

    def __iter__(self):
        """Fusion's collection is iterable; ``get_parameters`` walks it."""
        return iter(self._parameters.values())


class FakeComponent:
    def __init__(self, name: str, bodies=()):
        self.name = name
        self.bRepBodies = FakeBRepBodies(list(bodies))
        #: A Fusion component holds its own sketches and features - the root
        #: component is one, not a separate kind of thing - so a command that
        #: builds into a named component (``create_box_parametric``'s
        #: ``component_name``) reaches these on the component it resolved.
        self.sketches = FakeSketches()
        self.features = FakeFeatures()
        #: A component holds the occurrences placed in it, and ``get_bounding_box``
        #: unions their bodies as well as its own; ``create_component`` places the
        #: new one through this collection.
        self.occurrences = FakeOccurrences()
        #: Fusion assigns an appearance to a component as well as to a body and a
        #: face; ``None`` until something assigns one.
        self.appearance = None

    @property
    def allOccurrences(self) -> FakeCollection:
        """Fusion's flat list of every occurrence below this component.

        Only the immediate children are modelled: no fixture here nests an
        assembly inside an assembly, and a recursive walk would be fiction about
        a depth nothing has measured.
        """
        return self.occurrences


class FakeBaseFeature(FakeDeletable):
    """``features.baseFeatures.add()``: a feature a body is added *inside*.

    Fusion's ``BRepBodies.add`` docstring is explicit - "you must first call the
    edit method of the base feature, then use the add method to create the body,
    and finally call the finishEdit method ... The base feature must be in an
    'edit' state to be able to add any additional items to it" - so the state is
    tracked and an add outside it is refused.

    What is **not** modelled: Fusion documents no refusal for creating a second
    base feature while one is in edit (``BaseFeatures.add`` says only "Creates a
    new empty base feature"), and ``finishEdit`` is documented as "if this base
    feature is not in edit mode, then nothing happens" - so neither is invented
    here.  A handler that never finishes the edit is caught by asserting
    ``editing`` is false afterwards, not by a fake refusal.
    """

    def __init__(self, name: str = "Base Feature1"):
        super().__init__(name)
        self.editing = False
        self.bodies: list = []

    def startEdit(self) -> bool:
        self.editing = True
        return True

    def finishEdit(self) -> bool:
        self.editing = False
        return True


class FakeBaseFeatures:
    """``features.baseFeatures``: numbered the way Fusion numbers them.

    Not a ``FakeCollection``: Fusion's ``BaseFeatures.add`` takes no argument, so
    it cannot share that collection's ``add(item)`` shape.  A base feature is a
    timeline entry in Fusion; this collection does not grow ``design.features``,
    because no handler test reads the timeline after a primitive.
    """

    def __init__(self):
        self.added: list[FakeBaseFeature] = []

    def add(self) -> FakeBaseFeature:
        feature = FakeBaseFeature(f"Base Feature{len(self.added) + 1}")
        self.added.append(feature)
        return feature

    @property
    def count(self) -> int:
        return len(self.added)

    def item(self, index: int) -> FakeBaseFeature:
        return self.added[index]

    def __iter__(self):
        return iter(self.added)


class FakeBRepBodies(FakeCollection):
    """``component.bRepBodies``: ``add`` persists a body, into a base feature.

    Fusion's ``BRepBodies.add`` docstring: the base feature "is an optional
    requirement. It is required in a parametric modeling design but is ignored in
    a direct modeling design."  So when the owning design is parametric - which is
    ``FakeDesign``'s default - a body with no base feature, or a base feature that
    is not in edit, is refused here exactly as Fusion refuses it.  A fake that
    accepted it could not tell ``create_box`` from one that drops the feature.

    ``add_existing`` is the escape hatch for a fixture that models a body the
    *user* already has: such a body was created by some earlier feature, and
    wrapping it in a base feature now would be inventing history.

    A body added this way does **not** grow ``design.features`` or
    ``design.bodies``: those are the timeline's count and a fixed number set at
    construction, and no handler test reads either after a primitive.
    """

    def __init__(self, items=None, design: "FakeDesign | None" = None):
        super().__init__(items)
        self._design = design

    def __iter__(self) -> Iterator[FakeBody]:
        return iter(self._items)

    def add(self, body, targetBaseFeature: FakeBaseFeature | None = None):
        """Persist a new body, refusing what a parametric design refuses."""
        parametric = self._design is not None and self._design.designType == PARAMETRIC
        if parametric:
            if targetBaseFeature is None:
                raise RuntimeError(
                    "3 : a base feature is required to add a body to a parametric "
                    "design"
                )
            if not targetBaseFeature.editing:
                raise RuntimeError("3 : the base feature is not in an edit state")
        if targetBaseFeature is not None:
            targetBaseFeature.bodies.append(body)
        return super().add(body)

    def add_existing(self, body):
        """A body that is already in this component, as a test fixture."""
        return super().add(body)


class FakeTransform:
    """An occurrence's placement: ``joint`` reads ``transform.translation``."""

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.translation = FakePoint3D(x, y, z)


class FakeOccurrence:
    def __init__(self, component: FakeComponent, x: float = 0.0):
        self.component = component
        #: Fusion names an occurrence after its component; ``add_joint`` keys its
        #: before/after displacement map on this.
        self.name = component.name
        self.transform = FakeTransform(x)
        #: Visible until a test hides it: ``list_components`` reports the flag.
        self.isVisible = True

    @property
    def bRepBodies(self) -> FakeCollection:
        """An occurrence reaches its component's bodies, as Fusion does."""
        return self.component.bRepBodies


class FakeOccurrences(FakeCollection):
    """``root.occurrences``: ``addNewComponent(matrix)`` is the one creator used.

    Fusion takes a ``Matrix3D`` and returns the occurrence it placed.  The fake
    keeps the component it made, so the occurrence reads back as an ordinary one
    - which is what ``create_component`` renames and what ``allOccurrences``
    reports afterwards.
    """

    def addNewComponent(self, matrix) -> FakeOccurrence:
        if not isinstance(matrix, FakeMatrix3D):
            raise TypeError(
                f"addNewComponent takes a Matrix3D, not {type(matrix).__name__}"
            )
        occurrence = FakeOccurrence(FakeComponent(f"Component{self.count + 1}"))
        return super().add(occurrence)


class FakeAxes:
    """The three world construction axes, one distinct object each.

    Distinct objects are what make ``axis is root.xConstructionAxis`` meaningful.
    """

    def __init__(self):
        self.xConstructionAxis = FakeDeletable("X")
        self.yConstructionAxis = FakeDeletable("Y")
        self.zConstructionAxis = FakeDeletable("Z")


class FakePlanes:
    """The three base construction planes, as ``_construction_plane`` expects."""

    def __init__(self):
        self.xYConstructionPlane = FakeDeletable("XY")
        self.yZConstructionPlane = FakeDeletable("YZ")
        self.xZConstructionPlane = FakeDeletable("XZ")


class FakeRevolveInput:
    def __init__(self, profile, axis, operation):
        self.profile = profile
        self.axis = axis
        self.operation = operation
        self.angle = None
        self.symmetric = None
        # Empty means "let Fusion pick the bodies this operation touches" —
        # and Fusion picks every body the profile reaches, which is how a cut
        # land on a body the caller never named.  See FakeLoftInput too.
        self.participantBodies: list = []

    def setAngleExtent(self, symmetric, angle) -> None:
        self.symmetric = symmetric
        self.angle = angle


class FakeRevolveFeatures:
    """``features.revolveFeatures``: records inputs, rejects stale profiles."""

    def __init__(self):
        self.inputs: list[FakeRevolveInput] = []
        self.added: list[FakeRevolveInput] = []

    def createInput(self, profile, axis, operation) -> FakeRevolveInput:
        created = FakeRevolveInput(profile, axis, operation)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeRevolveInput) -> FakeFeature:
        # What Fusion 2706 does: a profile proxy captured before its sketch was
        # modified is stale, and the revolve is rejected outright.  The check
        # goes through the profile's own sketch, so it holds for any sketch in
        # the design, not just the first.
        if inp.profile.version != inp.profile.sketch.version:
            raise RuntimeError("3 : invalid profile(s) for Revolve Feature")
        self.added.append(inp)
        return FakeFeature("Revolve1")


class FakeLoftInput:
    """``loftFeatures.createInput(operation)``: sections, then participants."""

    def __init__(self, operation):
        self.operation = operation
        self.loftSections = FakeCollection()
        self.participantBodies: list = []


class FakeLoftFeatures:
    """``features.loftFeatures``: what each loft was built from.

    Fusion needs two sections at minimum; a loft with fewer is refused there,
    so the fake refuses it too rather than recording a loft that cannot exist.
    """

    def __init__(self):
        self.inputs: list[FakeLoftInput] = []
        self.added: list[FakeLoftInput] = []

    def createInput(self, operation) -> FakeLoftInput:
        created = FakeLoftInput(operation)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeLoftInput) -> FakeFeature:
        if inp.loftSections.count < 2:
            raise RuntimeError("2 : A loft needs at least two sections")
        self.added.append(inp)
        return FakeFeature(f"Loft{len(self.inputs)}")


class FakeCombineInput:
    """``combineFeatures.createInput(target, tools)``: records what it was told."""

    def __init__(self, target, tools):
        self.targetBody = target
        self.toolBodies = list(tools)
        self.operation = None
        self.isKeepToolBodies = False


class FakeCombineFeatures:
    """``features.combineFeatures``: the bool a boolean was built with."""

    def __init__(self):
        self.inputs: list[FakeCombineInput] = []
        self.added: list[FakeCombineInput] = []

    def createInput(self, target, tools) -> FakeCombineInput:
        inp = FakeCombineInput(target, tools)
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        self.added.append(inp)
        return type("FakeFeature", (), {"name": f"Combine{len(self.inputs)}"})()


class FakeExtrudeInput:
    """``extrudeFeatures.createInput(profile, operation)`` and its two extents."""

    def __init__(self, profile, operation):
        self.profile = profile
        self.operation = operation
        self.symmetric = None
        self.distance = None
        # Empty means "let Fusion pick the bodies this operation touches".
        self.participantBodies: list = []

    def setSymmetricExtent(self, distance, is_full_width) -> None:
        self.symmetric = (distance, is_full_width)

    def setDistanceExtent(self, is_symmetric, distance) -> None:
        self.distance = (is_symmetric, distance)


class FakeExtrudeFeatures:
    """``features.extrudeFeatures``: records which profile each extrude used."""

    def __init__(self):
        self.inputs: list[FakeExtrudeInput] = []
        self.added: list[FakeExtrudeInput] = []
        self.created: list[FakeFeature] = []

    def createInput(self, profile, operation) -> FakeExtrudeInput:
        inp = FakeExtrudeInput(profile, operation)
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        self.added.append(inp)
        # One body, the fake's model of ``NewBodyFeatureOperation`` - the only
        # operation this fake builds a body for.  ``create_box_parametric``
        # renames that body through ``Feature.bodies`` (the SDK's own property,
        # not measured here); a cut or a join would produce none, which is not
        # modelled and nothing here reads.
        feature = FakeFeature("Extrude1", bodies=[FakeBody("Extrude1")])
        self.created.append(feature)
        return feature


class FakeSweepInput:
    def __init__(self, profile, path, operation):
        self.profile = profile
        self.path = path
        self.operation = operation
        # Empty means "let Fusion pick the bodies this operation touches".
        self.participantBodies: list = []


class FakeSweepFeatures:
    def __init__(self):
        self.inputs: list[FakeSweepInput] = []
        self.added: list[FakeSweepInput] = []

    def createInput(self, profile, path, operation) -> FakeSweepInput:
        inp = FakeSweepInput(profile, path, operation)
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        self.added.append(inp)
        return FakeFeature("Sweep1")


class FakeFilletInput:
    """``filletFeatures.createInput()``: records each edge set it is given."""

    def __init__(self):
        self.edge_sets: list[list] = []
        self.radius = None

    def addConstantRadiusEdgeSet(self, edges, radius, is_chain) -> None:
        self.edge_sets.append(list(edges))
        self.radius = radius


class FakeFilletFeatures:
    """``features.filletFeatures``: what the fillet was actually built from."""

    def __init__(self):
        self.inputs: list[FakeFilletInput] = []
        self.last_edge_indices: list[int] = []

    def createInput(self) -> FakeFilletInput:
        inp = FakeFilletInput()
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        self.last_edge_indices = [edge.index for edge in inp.edge_sets[-1]]
        name = f"Fillet{len(self.inputs)}"
        return type("FakeFeature", (), {"name": name, "radius": inp.radius})()


class FakeChamferInput:
    """``chamferFeatures.createInput(edges, is_chain)``: takes edges up front."""

    def __init__(self, edges):
        self.edges = list(edges)
        self.distance = None

    def setToEqualDistance(self, distance) -> None:
        self.distance = distance


class FakeChamferFeatures:
    """``features.chamferFeatures``: same idea, one edge list per input."""

    def __init__(self):
        self.inputs: list[FakeChamferInput] = []
        self.last_edge_indices: list[int] = []

    def createInput(self, edges, is_chain) -> FakeChamferInput:
        inp = FakeChamferInput(edges)
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        self.last_edge_indices = [edge.index for edge in inp.edges]
        name = f"Chamfer{len(self.inputs)}"
        return type("FakeFeature", (), {"name": name, "distance": inp.distance})()


class FakeShellInput:
    """``shellFeatures.createInput``: the faces to remove and the bodies to shell.

    Fusion takes the two in ONE collection and exposes no ``facesToRemove``
    property at all - which is why a handler that assigned one built a closed
    cavity for months: the assignment attaches a plain Python attribute to the
    SWIG wrapper and Fusion never sees it.  Measured on Fusion 2706 by reading
    ``dir()`` on the input and grepping the shipped ``adsk/fusion.py``, where the
    name appears nowhere.
    """

    def __init__(self, input_entities, is_tangent_chain: bool = True):
        self.inputEntities = input_entities
        self.isTangentChain = is_tangent_chain
        self.insideThickness = None


class FakeShellFeatures(FakeCollection):
    """``root.features.shellFeatures``: records what a shell was told to open."""

    def __init__(self):
        super().__init__()
        self.inputs: list[FakeShellInput] = []

    @property
    def last_input(self) -> FakeShellInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, input_entities, is_tangent_chain: bool = True):
        """``createInput(inputEntities, isTangentChain=True)``, as Fusion declares it.

        Fusion fails when a face and the body that owns it are both in the call
        ("Fails if any faces are input, and the owning bodies of the faces are
        also input"), so the fake refuses it too rather than letting a caller
        believe both were honoured.  Ownership, not mere presence: a body and a
        *different* body's face is a call Fusion accepts.
        """
        items = list(input_entities)
        bodies = [item for item in items if isinstance(item, FakeBody)]
        faces = [item for item in items if isinstance(item, FakeFace)]
        owning_bodies = [
            body
            for face in faces
            for body in bodies
            if getattr(face, "_collection", None) is body.faces
        ]
        if owning_bodies:
            raise TypeError(
                "shellFeatures.createInput refuses a face together with the body "
                f"that owns it (got {len(faces)} face(s), one belonging to "
                f"'{owning_bodies[0].name}') - pass the faces to remove OR the "
                "bodies to shell"
            )
        inp = FakeShellInput(input_entities, is_tangent_chain)
        self.inputs.append(inp)
        return inp

    def add(self, item) -> FakeDeletable:
        if not isinstance(item, FakeShellInput):
            raise TypeError("shellFeatures.add takes the input createInput returned")
        joint = FakeDeletable("Shell1")
        super().add(joint)
        return joint


class FakeHoleFeatureInput:
    """``holeFeatures.createSimpleInput``: a diameter, a position and an extent.

    ``participantBodies`` starts **empty**, which is Fusion's default and means
    "every body the hole reaches" — the reason ``create_hole`` sets it at all.
    It takes a plain list: Fusion refuses an ``ObjectCollection`` here, while
    other feature inputs demand one, so the fake refuses it too.  The diameter is
    kept as the ``ValueInput`` Fusion was handed rather than a number, so a test
    reads exactly what the call site passed.
    """

    def __init__(self, diameter):
        self.diameter = diameter
        self.position = None
        self.distance = None
        self.participantBodies = []

    @property
    def participantBodies(self) -> list:
        return self._participant_bodies

    @participantBodies.setter
    def participantBodies(self, bodies) -> None:
        if not isinstance(bodies, list):
            raise TypeError(
                "participantBodies takes a plain list of bodies, not "
                f"{type(bodies).__name__}"
            )
        self._participant_bodies = bodies

    def setPositionBySketchPoint(self, sketch_point) -> None:
        if not isinstance(sketch_point, FakeSketchPoint):
            raise TypeError(
                "setPositionBySketchPoint takes a SketchPoint, not "
                f"{type(sketch_point).__name__}"
            )
        self.position = sketch_point

    def setDistanceExtent(self, distance) -> None:
        if not isinstance(distance, FakeValueInput):
            raise TypeError(
                f"setDistanceExtent takes a ValueInput, not {type(distance).__name__}"
            )
        self.distance = distance


class FakeHoleFeature(FakeDeletable):
    """The feature ``holeFeatures.add`` returns: name, diameter, and bodies.

    ``bodies`` is a ``FakeItemCollection`` over the participants the *input*
    named, because that is what Fusion reports: measured on 2706, a cut naming a
    body it never reaches still lists that body.  It is not a ``FakeCollection``
    on purpose - that would reparent bodies that already live in ``bRepBodies`` -
    and it is not evidence of what was cut, so no response field is built on it.
    A handler that reports from it is reporting its own input back.

    ``cut_body_names`` is the fake's own record of which bodies the feature was
    left to reach.  With participants named it repeats them (there is nothing
    else to model, and the test that reads it is asserting the participants);
    with none named it is the whole root component, which is Fusion's rule and an
    over-approximation of "every body the hole intersects".
    """

    def __init__(self, hole_input: FakeHoleFeatureInput, participants, cut):
        super().__init__("Hole1")
        self.holeDiameter = hole_input.diameter
        self.bodies = FakeItemCollection(participants)
        self.cut_body_names = [body.name for body in cut]


class FakeHoleFeatures(FakeCollection):
    """``root.features.holeFeatures``: what each hole was built from.

    ``add`` refuses an input that never got a position or an extent, the way
    Fusion does, and settles the one thing the input leaves open: with
    ``participantBodies`` empty the feature reaches *every* body in the design.
    """

    def __init__(self, design=None):
        super().__init__()
        self._design = design
        self.inputs: list[FakeHoleFeatureInput] = []

    @property
    def last_input(self) -> FakeHoleFeatureInput | None:
        return self.inputs[-1] if self.inputs else None

    def createSimpleInput(self, diameter) -> FakeHoleFeatureInput:
        if not isinstance(diameter, FakeValueInput):
            raise TypeError(
                f"createSimpleInput takes a ValueInput, not {type(diameter).__name__}"
            )
        created = FakeHoleFeatureInput(diameter)
        self.inputs.append(created)
        return created

    def add(self, hole_input: FakeHoleFeatureInput) -> FakeHoleFeature:
        if not isinstance(hole_input, FakeHoleFeatureInput):
            raise TypeError("holeFeatures.add takes the input createSimpleInput made")
        if hole_input.position is None:
            raise RuntimeError("3 : a hole needs a position")
        if hole_input.distance is None:
            raise RuntimeError("3 : a hole needs an extent")
        participants = list(hole_input.participantBodies)
        cut = participants or self._every_body()
        feature = FakeHoleFeature(hole_input, participants, cut)
        super().add(feature)
        return feature

    def _every_body(self) -> list:
        """No participant named: every body in the root is left to be cut.

        Fusion's words are "all bodies that are intersected by the hole"; which
        ones a hole reaches needs real geometry, so this over-approximates.  The
        approximation can only fail a wrong handler, never pass one.
        """
        root = None if self._design is None else self._design.rootComponent
        return [] if root is None else list(root.bRepBodies)


class FakeFeatures:
    """``root.features``: a count, the revolve collection and the draft one."""

    def __init__(self, design: FakeDesign | None = None):
        self._design = design
        self.revolveFeatures = FakeRevolveFeatures()
        self.draftFeatures = FakeDraftFeatures()
        self.filletFeatures = FakeFilletFeatures()
        self.chamferFeatures = FakeChamferFeatures()
        self.extrudeFeatures = FakeExtrudeFeatures()
        self.sweepFeatures = FakeSweepFeatures()
        self.loftFeatures = FakeLoftFeatures()
        self.combineFeatures = FakeCombineFeatures()
        self.shellFeatures = FakeShellFeatures()
        self.holeFeatures = FakeHoleFeatures(design)
        self.baseFeatures = FakeBaseFeatures()
        self.threadFeatures = FakeThreadFeatures()
        self.ruledSurfaceFeatures = FakeRuledSurfaceFeatures()
        self.patchFeatures = FakePatchFeatures()
        self.stitchFeatures = FakeStitchFeatures()
        self.mirrorFeatures = FakeMirrorFeatures(design)
        self.rectangularPatternFeatures = FakeRectangularPatternFeatures()
        self.circularPatternFeatures = FakeCircularPatternFeatures()
        self.splitBodyFeatures = FakeSplitBodyFeatures()
        self.splitFaceFeatures = FakeSplitFaceFeatures()
        self.thickenFeatures = FakeThickenFeatures()
        self.unfoldFeatures = FakeUnfoldFeatures()
        self.offsetFeatures = FakeOffsetFacesFeatures()
        self.scaleFeatures = FakeScaleFeatures()
        self.moveFeatures = FakeMoveFeatures()

    def createPath(self, curve):
        """``features.createPath``: a sweep needs a Path around the curve."""
        return type("FakePath", (), {"curve": curve})()

    @property
    def count(self) -> int:
        return 0 if self._design is None else self._design.features


class FakeJointMotion:
    """What Fusion reports back for a created joint, per motion type.

    Which attributes exist is a measurement, not a guess: on 2706 a slider
    exposes ``slideDirectionVector``, revolute and cylindrical expose
    ``rotationAxisVector`` only, planar exposes ``normalDirectionVector`` plus a
    primary/secondary slide pair (planar DOES slide, which a single
    ``slideDirectionVector`` probe would have got wrong), pin_slot exposes both,
    and ball exposes pitch/yaw/roll.

    The **driveable values** are here too, and they are per-motion on purpose: a
    handler that wrote ``rotationValue`` to a ball joint would be caught, because
    Fusion's ball motion has pitch/yaw/roll and nothing else.  Unknown attributes
    raise instead of being conjured by ``setattr`` — a fake that accepts any name
    cannot tell a working ``set_joint_value`` from one writing a typo.

    Each vector follows the measured JointDirections -> world mapping: X is the
    geometry's secondary axis, Y its third, Z its primary.
    """

    #: Driveable values per motion, in Fusion's units: angles in radians, slides
    #: in centimetres. All start at zero, as a new joint's do.
    _VALUES: ClassVar[dict[str, tuple[str, ...]]] = {
        "Revolute": ("rotationValue",),
        "Slider": ("slideValue",),
        "Cylindrical": ("rotationValue", "slideValue"),
        "PinSlot": ("rotationValue", "slideValue"),
        # Fusion's PlanarJointMotion exposes rotationValue *and* both slides
        # (read from the shipped adsk/fusion.py: rotationValue + rotationLimits
        # alongside primary/secondarySlideValue). Omitting the rotation here would
        # refuse a write Fusion accepts.
        "Planar": ("rotationValue", "primarySlideValue", "secondarySlideValue"),
        "Ball": ("pitchValue", "yawValue", "rollValue"),
    }

    #: The two descriptive strings and the direction vectors, i.e. everything
    #: Fusion keeps on a motion object that is not a driveable value.
    _FIXED: ClassVar[frozenset[str]] = frozenset(
        {
            "objectType",
            "jointType",
            "slideDirectionVector",
            "rotationAxisVector",
            "normalDirectionVector",
            "primarySlideDirectionVector",
            "secondarySlideDirectionVector",
            "pitchDirectionVector",
            "yawDirectionVector",
            "rollDirectionVector",
        }
    )

    def __init__(self, setter: str, frame: dict, directions: tuple):
        self.jointType = setter
        self._frame = frame
        self._directions = directions
        name = setter.removeprefix("setAs").removesuffix("JointMotion")
        self.objectType = f"adsk::fusion::{name}JointMotion"
        for attribute in self._VALUES.get(name, ()):
            object.__setattr__(self, attribute, 0.0)
        first = frame.get(directions[0]) if directions else None
        second = frame.get(directions[1]) if len(directions) > 1 else None
        # Keyed by JointDirections member, so pick "the others" by key.
        others = [frame[key] for key in frame if key not in directions[:2]]
        if name == "Slider":
            self.slideDirectionVector = first
        elif name in ("Revolute", "Cylindrical"):
            self.rotationAxisVector = first
        elif name == "PinSlot":
            # Measured on 2706: the FIRST argument becomes the rotation axis and
            # the second the slide - the opposite of what the add-in's own
            # docstring claimed for years.
            self.rotationAxisVector = first
            self.slideDirectionVector = second
        elif name == "Planar":
            self.normalDirectionVector = first
            self.primarySlideDirectionVector = others[0]
            self.secondarySlideDirectionVector = others[1]
        elif name == "Ball":
            self.pitchDirectionVector = first
            self.yawDirectionVector = second
            self.rollDirectionVector = others[0] if others else None

    def __setattr__(self, name, value):
        """Accept only attributes the modelled motion really has.

        Fusion's motion objects expose a fixed set, so a table entry naming an
        attribute the motion does not have is a bug the read-back would otherwise
        confirm: ``setattr`` creates any name, and ``getattr`` then returns it.
        Raising here is what makes ``set_joint_value``'s table falsifiable.
        """
        if name.startswith("_") or name in self._FIXED:
            object.__setattr__(self, name, value)
            return
        motion = getattr(self, "jointType", "")
        kind = motion.removeprefix("setAs").removesuffix("JointMotion")
        if name in self._VALUES.get(kind, ()):
            object.__setattr__(self, name, value)
            return
        raise AttributeError(
            f"{kind or 'this'}JointMotion has no attribute '{name}' - Fusion "
            f"exposes {sorted(self._VALUES.get(kind, ()))}"
        )


class FakeJoint(FakeDeletable):
    """A created joint: name, motion, and the geometry it was built from.

    The geometry is the same object the input was given. Fusion's own
    ``geometryOrOriginOne`` was measured to report a *different* frame than the
    geometry passed to ``createInput``, which is what made an early reading of
    this look inconsistent — but no measurement pinned the permutation, so the
    fake does not invent one. What it can still catch is a handler that stopped
    reading the geometry it built: the reported vectors in these tests are the
    input's.
    """

    def __init__(self, name, geometry_one, geometry_two, motion, is_flipped):
        super().__init__(name)
        self.geometryOrOriginOne = geometry_one
        self.geometryOrOriginTwo = geometry_two
        self.jointMotion = motion
        self.isFlipped = is_flipped


class FakeJointInput:
    """``Joints.createInput``: records which motion setter was called, with what.

    ``isFlipped`` is accepted and stored because Fusion accepts it, but it is
    recorded rather than honoured: measured on 2706, setting it did NOT reverse a
    slider's ``slideDirectionVector``.  A test can therefore assert the handler
    never relies on it.
    """

    def __init__(self, geometry_one, geometry_two):
        self.geometryOrOriginOne = geometry_one
        self.geometryOrOriginTwo = geometry_two
        self.isFlipped = False
        self.motion_setter = None
        self.motion_directions = ()
        self.motion_calls = 0

    def _record(self, setter: str, directions: tuple) -> None:
        self.motion_setter = setter
        self.motion_directions = directions
        self.motion_calls += 1

    def setAsRigidJointMotion(self) -> None:
        self._record("setAsRigidJointMotion", ())

    def setAsRevoluteJointMotion(self, direction) -> None:
        self._record("setAsRevoluteJointMotion", (direction,))

    def setAsSliderJointMotion(self, direction) -> None:
        self._record("setAsSliderJointMotion", (direction,))

    def setAsCylindricalJointMotion(self, direction) -> None:
        self._record("setAsCylindricalJointMotion", (direction,))

    def setAsPlanarJointMotion(self, direction) -> None:
        self._record("setAsPlanarJointMotion", (direction,))

    def setAsPinSlotJointMotion(self, slide, rotation) -> None:
        self._record("setAsPinSlotJointMotion", (slide, rotation))

    def setAsBallJointMotion(self, pitch, yaw) -> None:
        self._record("setAsBallJointMotion", (pitch, yaw))


class FakeJoints(FakeCollection):
    """``root.joints``: inputs to record against, and the joints that come out."""

    def __init__(self):
        super().__init__()
        self.inputs: list[FakeJointInput] = []

    @property
    def last_input(self) -> FakeJointInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, geometry_one, geometry_two) -> FakeJointInput:
        inp = FakeJointInput(geometry_one, geometry_two)
        self.inputs.append(inp)
        return inp

    def add(self, item) -> FakeJoint:
        """Create the joint an input describes, as Fusion's ``add`` does."""
        if not isinstance(item, FakeJointInput):
            raise TypeError("joints.add takes the input createInput returned")
        inp = item
        frame = _joint_frame(inp.geometryOrOriginOne)
        motion = FakeJointMotion(
            inp.motion_setter or "setAsRigidJointMotion", frame, inp.motion_directions
        )
        joint = FakeJoint(
            f"Joint{self.count + 1}",
            inp.geometryOrOriginOne,
            inp.geometryOrOriginTwo,
            motion,
            inp.isFlipped,
        )
        super().add(joint)
        # Fusion invalidates both geometries once the joint exists (measured);
        # anything the handler wants from them has to be read before this point.
        for geometry in (inp.geometryOrOriginOne, inp.geometryOrOriginTwo):
            if hasattr(geometry, "consumed"):
                geometry.consumed = True
        return joint


def _joint_frame(geometry) -> dict:
    """``{JointDirections member: joint-frame vector}`` - the measured mapping.

    X is the geometry's secondary axis, Y its third and Z its primary: read back
    from ``slideDirectionVector`` on Fusion 2706 across four quadrants, a
    cylinder-X body and a cone.
    """
    return {
        "XAxisJointDirection": geometry.secondaryAxisVector,
        "YAxisJointDirection": geometry.thirdAxisVector,
        "ZAxisJointDirection": geometry.primaryAxisVector,
    }


class FakeAsBuiltJointInput(FakeJointInput):
    """``AsBuiltJoints.createInput``: two occurrences and one optional geometry.

    Fusion's signature is ``createInput(occurrenceOne, occurrenceTwo, geometry)``
    — a **single** geometry, which is why ``create_as_built_joint`` cannot build
    from ``face_two`` and only validates it.  Motion setters are inherited: an
    as-built input takes the same seven ``setAs*JointMotion`` calls.

    ``geometry`` is ``None`` for a rigid joint, which Fusion accepts without it.
    """

    def __init__(self, occurrence_one, occurrence_two, geometry=None):
        super().__init__(geometry, None)
        self.occurrenceOne = occurrence_one
        self.occurrenceTwo = occurrence_two
        self.geometry = geometry


class FakeAsBuiltJoints(FakeCollection):
    """``root.asBuiltJoints``: the sibling of ``FakeJoints`` for kept poses.

    It was a bare ``FakeCollection``, so ``create_as_built_joint`` could not run
    under a test at all and its two claims — that ``joint_type`` is honoured, and
    that ``face_two`` is validated even though it cannot be built from — were
    guarded by source scans instead.

    One thing is deliberately *not* modelled: ``Joints.add`` was measured to
    invalidate the geometry it was given, but nothing pinned whether
    ``asBuiltJoints.add`` does the same, so the fake does not invent it.
    """

    def __init__(self):
        super().__init__()
        self.inputs: list[FakeAsBuiltJointInput] = []

    @property
    def last_input(self) -> FakeAsBuiltJointInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(
        self, occurrence_one, occurrence_two, geometry=None
    ) -> FakeAsBuiltJointInput:
        inp = FakeAsBuiltJointInput(occurrence_one, occurrence_two, geometry)
        self.inputs.append(inp)
        return inp

    def add(self, item) -> FakeJoint:
        if not isinstance(item, FakeAsBuiltJointInput):
            raise TypeError("asBuiltJoints.add takes the input createInput returned")
        if item.geometry is None and item.motion_setter not in (
            None,
            "setAsRigidJointMotion",
        ):
            # Fusion's own refusal, and the reason create_as_built_joint requires a
            # face pair for every motion but rigid.  Without it the fake would
            # build the joint a handler's missing guard failed to prevent.
            raise RuntimeError(
                "Geometry should not be null if joint motion is not rigid"
            )
        frame = _joint_frame(item.geometry) if item.geometry is not None else {}
        motion = FakeJointMotion(
            item.motion_setter or "setAsRigidJointMotion", frame, item.motion_directions
        )
        joint = FakeJoint(
            f"AsBuiltJoint{self.count + 1}", item.geometry, None, motion, False
        )
        super().add(joint)
        return joint


class FakeConstructionInput:
    """``constructionPlanes.createInput()`` / ``constructionAxes.createInput()``.

    Each setter declares the arity of the handler's call site, which is Fusion's,
    so a wrong one is a ``TypeError`` here instead of a recorded call nobody could
    tell from a correct one.  Which setters exist is per collection - a plane input
    has no ``setByEdge``, an axis input no ``setByOffset`` - so the wrong call is an
    ``AttributeError``, as it is in Fusion.
    """

    def __init__(self):
        #: The one setter that was called, and the arguments it was given.
        self.setter: str | None = None
        self.args: tuple = ()

    def _record(self, setter: str, args: tuple) -> None:
        self.setter = setter
        self.args = args


class FakeConstructionPlaneInput(FakeConstructionInput):
    """The four plane definitions ``create_construction_plane`` builds."""

    def setByOffset(self, plane, offset) -> None:
        self._record("setByOffset", (plane, offset))

    def setByAngle(self, axis, angle, plane) -> None:
        self._record("setByAngle", (axis, angle, plane))

    def setByTwoPlanes(self, plane_one, plane_two) -> None:
        self._record("setByTwoPlanes", (plane_one, plane_two))

    def setByThreePoints(self, point_one, point_two, point_three) -> None:
        self._record("setByThreePoints", (point_one, point_two, point_three))


class FakeConstructionAxisInput(FakeConstructionInput):
    """The three axis definitions ``create_construction_axis`` builds.

    ``setByPerpendicularAtPoint(face, point)`` is not here: Fusion's first
    argument is a B-Rep face, the tool has no parameter that can supply one, and
    the handler refuses the method before any setter runs.
    """

    def setByTwoPoints(self, point_one, point_two) -> None:
        self._record("setByTwoPoints", (point_one, point_two))

    def setByTwoPlanes(self, plane_one, plane_two) -> None:
        self._record("setByTwoPlanes", (plane_one, plane_two))

    def setByEdge(self, edge) -> None:
        self._record("setByEdge", (edge,))


class _FakeConstructionCollection(FakeCollection):
    """Shared half of the two construction collections: inputs, then a named item.

    ``add`` takes the input ``createInput`` returned and does not check that a
    setter ran: no measurement says what Fusion does with an input whose geometry
    was never set, so the fake does not refuse one.  The default names -
    "Construction Plane1", "Construction Axis1" - are the *fake's*: the replies only
    have to name the object ``add`` returned, and no test pins Fusion's own default.
    """

    _INPUT: type
    _NAME: str

    def __init__(self):
        super().__init__()
        self.inputs: list[FakeConstructionInput] = []

    @property
    def last_input(self) -> FakeConstructionInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self) -> FakeConstructionInput:
        created = self._INPUT()
        self.inputs.append(created)
        return created

    def add(self, item) -> FakeDeletable:
        if not isinstance(item, self._INPUT):
            raise TypeError(f"add takes the input createInput returned, got {item!r}")
        return super().add(FakeDeletable(f"{self._NAME}{self.count + 1}"))


class FakeConstructionPlanes(_FakeConstructionCollection):
    """``root.constructionPlanes``: the definition each plane was built from."""

    _INPUT = FakeConstructionPlaneInput
    _NAME = "Construction Plane"


class FakeConstructionAxes(_FakeConstructionCollection):
    """``root.constructionAxes``: the same shape, for the axis definitions."""

    _INPUT = FakeConstructionAxisInput
    _NAME = "Construction Axis"


class FakeUserCoordinateSystemInput:
    """``userCoordinateSystems.createInput(geometry)``: three optional angles.

    Fusion exposes ``angleX``/``angleY``/``angleZ`` as ``ValueInput`` properties
    and only the ones set take effect, so an unset one stays ``None`` and a test
    can tell which angles the handler wrote.
    """

    def __init__(self, geometry):
        self.geometry = geometry
        self.angleX = None
        self.angleY = None
        self.angleZ = None


class FakeUserCoordinateSystems(FakeCollection):
    """``root.userCoordinateSystems``: anchored on a geometry, then named.

    The default name "UCS1" is the *fake's* - ``create_ucs`` renames the UCS when
    the caller named it, and the reply only reads ``name`` back.
    """

    def __init__(self):
        super().__init__()
        self.inputs: list[FakeUserCoordinateSystemInput] = []

    @property
    def last_input(self) -> FakeUserCoordinateSystemInput | None:
        return self.inputs[-1] if self.inputs else None

    def createInput(self, geometry) -> FakeUserCoordinateSystemInput:
        if not isinstance(geometry, FakeUserCoordinateSystemGeometry):
            raise TypeError(
                "userCoordinateSystems.createInput takes the geometry "
                "UserCoordinateSystemGeometry_createByPoint made, not "
                f"{type(geometry).__name__}"
            )
        created = FakeUserCoordinateSystemInput(geometry)
        self.inputs.append(created)
        return created

    def add(self, item) -> FakeDeletable:
        if not isinstance(item, FakeUserCoordinateSystemInput):
            raise TypeError("add takes the input createInput returned")
        return super().add(FakeDeletable(f"UCS{self.count + 1}"))


class FakeRigidGroup(FakeDeletable):
    """A created rigid group: the occurrences in it and whether children came too."""

    def __init__(self, name: str, occurrences: list, include_children: bool):
        super().__init__(name)
        self.occurrences = occurrences
        self.includeChildren = include_children


class FakeRigidGroups:
    """``root.rigidGroups``: ``add(occurrences, includeChildren)`` - two arguments.

    A rigid group is one call in Fusion, not an input/feature pair, and its second
    argument is the flag ``create_rigid_group``'s ``include_children`` becomes.
    That two-argument ``add`` is why this is not a ``FakeCollection``: inheriting a
    base whose ``add`` takes one item would leave this class overriding it with a
    different signature - ``py/overridden-method-signature``, the sibling of the
    ``py/init-calls-subclass`` lesson ``FakeCollection`` records.  So the three
    members the add-in uses are carried here instead: ``add`` for
    ``create_rigid_group``, and ``count``/``item(i)`` for ``delete_all``'s sweep.
    """

    def __init__(self):
        self._items: list[FakeRigidGroup] = []
        self.added: list[FakeRigidGroup] = []

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> FakeRigidGroup:
        return self._items[index]

    def add(self, occurrences, include_children) -> FakeRigidGroup:
        group = FakeRigidGroup(
            f"Rigid Group{self.count + 1}", list(occurrences), include_children
        )
        # ``FakeDeletable.deleteMe()`` removes the group from the collection it
        # lives in, which is how ``delete_all`` proves the design is empty.
        group._collection = self
        self._items.append(group)
        self.added.append(group)
        return group

    def remove(self, group: FakeRigidGroup) -> None:
        """What ``FakeDeletable.deleteMe()`` calls."""
        if group in self._items:
            self._items.remove(group)


class FakeRoot:
    """``design.rootComponent``: everything ``delete_all`` sweeps, plus planes."""

    def __init__(
        self,
        design: FakeDesign | None = None,
        sketches=(),
        bodies=None,
        mesh_bodies=(),
    ):
        #: The *fake's* root name - no measurement pinned what Fusion calls the root
        #: component of a new design - and ``list_components`` reports it as the
        #: first row.
        self.name = "Component1"
        self.bRepBodies = FakeBRepBodies(
            list(bodies) if bodies is not None else _default_bodies(design),
            design=design,
        )
        self.sketches = FakeSketches(list(sketches))
        #: Fusion keeps mesh bodies apart from B-rep bodies; ``compare_meshes`` walks
        #: this collection by name. Empty until a fixture supplies one.
        self.meshBodies = FakeMeshBodies(list(mesh_bodies))
        self.features = FakeFeatures(design)
        self.joints = FakeJoints()
        self.asBuiltJoints = FakeAsBuiltJoints()
        self.rigidGroups = FakeRigidGroups()
        self.occurrences = FakeOccurrences()
        #: Fusion assigns an appearance to a component as well as to a body and a
        #: face; ``None`` until something assigns one.
        self.appearance = None
        self.constructionPlanes = FakeConstructionPlanes()
        self.constructionAxes = FakeConstructionAxes()
        self.constructionPoints = FakeCollection()
        self.userCoordinateSystems = FakeUserCoordinateSystems()
        axes = FakeAxes()
        self.xConstructionAxis = axes.xConstructionAxis
        self.yConstructionAxis = axes.yConstructionAxis
        self.zConstructionAxis = axes.zConstructionAxis
        planes = FakePlanes()
        self.xYConstructionPlane = planes.xYConstructionPlane
        self.yZConstructionPlane = planes.yZConstructionPlane
        self.xZConstructionPlane = planes.xZConstructionPlane
        self.analyses = FakeAnalyses()
        #: The ``FlatPattern`` objects ``createFlatPattern`` returned, in order.
        self.flat_patterns: list[FakeFeature] = []
        #: The stationary face of each of those calls, in the same order.  Fusion's
        #: ``FlatPattern`` does not keep the face it was built from, so this is the
        #: fake's own record of the call - not a Fusion property.
        self.flat_pattern_faces: list = []

    def createFlatPattern(self, stationary_face):
        """``Component.createFlatPattern(stationaryFace)``: **one** argument.

        ``Fusion/Components/Component.h:355`` ships ``core::Ptr<FlatPattern>
        createFlatPattern(const core::Ptr<BRepFace>& stationaryFace)`` - Fusion's
        root component is a ``Component`` and this fake is where the handler's
        ``root`` lands.  There is no ``features.flatPatternFeatures`` in the API,
        which is what the handler used to read.  The returned ``FlatPattern``
        derives from ``Feature`` (``Fusion/SheetMetal/FlatPattern.h``, ``class
        FlatPattern : public Feature``), so it carries the name the reply is built
        from.

        Declaring the arity is what keeps that call from coming back: a no-argument
        or two-argument call is a ``TypeError``, as in the binding.  What the flat
        body looks like is not modelled - that is geometry this fake does not carry -
        and the face is not type-checked, because the handler's own planar scan is
        what picks it.
        """
        flat_pattern = FakeFeature(f"Flat Pattern{len(self.flat_patterns) + 1}")
        self.flat_patterns.append(flat_pattern)
        self.flat_pattern_faces.append(stationary_face)
        return flat_pattern

    def createBRepEdgeProfile(self, edges, chain_edges: bool = True):
        """``Component.createBRepEdgeProfile``: a ruled surface is built from a profile.

        The handler's mistake was one level up - ``RuledSurfaceFeatures.createInput``
        takes the *profile* this returns, not the edge - so the fake's job is to
        return the one type that call accepts.

        The first argument is deliberately permissive, because Fusion's is: the SDK
        says "edges : A single BRepEdge object or an ObjectCollection containing
        multiple BRepEdge objects, or a BRepLoop object", so a bare edge is a
        documented call shape, not a bug.
        """
        return FakeProfile(edges, chain_edges)

    @property
    def allOccurrences(self) -> FakeCollection:
        """``check_interference`` walks every occurrence in the design."""
        return self.occurrences


def _default_bodies(design: FakeDesign | None) -> list[FakeBody]:
    count = design.bodies if design else 0
    return [FakeBody(f"Body{i + 1}") for i in range(count)]


class FakeDesign:
    """A design: timeline, type, root component, parameters and interference.

    ``features=0`` means empty: no bodies, no timeline entries.  A direct design
    raises on ``design.timeline`` unless a test says otherwise — a more
    permissive fake would hide exactly the bug ``undo`` was fixed for.
    """

    def __init__(
        self,
        features: int = 2,
        marker: int | None = None,
        design_type: str = PARAMETRIC,
        marker_switches_type: bool = False,
        timeline_raises: bool | None = None,
        sketches=(),
        bodies=None,
        interferences=(),
        mesh_bodies=(),
    ):
        self.marker = features if marker is None else marker
        self.features = features
        self.designType = design_type
        self.productType = "DesignProductType"
        self.marker_switches_type = marker_switches_type
        self.timeline_raises = (
            design_type == DIRECT if timeline_raises is None else timeline_raises
        )
        self.timeline_entries: list[FakeTimelineObject] = [
            self._new_entry(index) for index in range(features)
        ]
        self.bodies = len(bodies) if bodies is not None else (1 if features else 0)
        self.userParameters = FakeUserParameters()
        #: The design's own appearances: ``set_color`` adds one, ``set_appearance``
        #: copies a library appearance in. Empty until a command creates one, which
        #: is a new design's state as far as anything here reads it.
        self.appearances = FakeAppearances()
        self.interference = FakeInterference(list(interferences))
        self._timeline = FakeTimeline(self)
        self.rootComponent = FakeRoot(self, sketches, bodies, mesh_bodies)
        self.undo_commands_executed = 0
        #: Fusion's design goes invalid when its document is closed, and its
        #: properties then raise "4 : An API Object refers to a deleted Object".
        self.isValid = True
        self.compute_all_calls = 0
        self.marker_writes: list[int] = []
        self.parentDocument = type("FakeDocument", (), {"name": "fake-design"})()
        self.exportManager = FakeExportManager()

    @property
    def timeline_count(self) -> int:
        """Derived, so a deletion is visible to anything that reads it."""
        return len(self.timeline_entries)

    def _new_entry(self, index: int) -> FakeTimelineObject:
        holder: dict[str, FakeTimelineObject] = {}

        def remove() -> None:
            entry = holder["entry"]
            if entry in self.timeline_entries:
                self.timeline_entries.remove(entry)

        entry = FakeTimelineObject(f"Feature{index + 1}", remove)
        holder["entry"] = entry
        return entry

    @property
    def timeline(self) -> FakeTimeline:
        if self.timeline_raises:
            raise RuntimeError("3 : this is not a parametric design")
        return self._timeline

    def computeAll(self) -> None:
        """Counted rather than simulated: a re-compute is observable, its effect not.

        ``add_joint`` must call it (Fusion needs it after a joint moves components)
        and ``set_joint_value`` must not (it would reset the value being driven).
        """
        self.compute_all_calls += 1

    def set_marker(self, value: int) -> None:
        self.marker_writes.append(value)
        self.marker = value
        if self.marker_switches_type:
            self.designType = DIRECT

    # The interference API lives on Design, not on Component.
    def createInterferenceInput(self, entities):
        return self.interference.createInterferenceInput(entities)

    def analyzeInterference(self, inp):
        return self.interference.analyzeInterference(inp)


class FakeCommandDefinition:
    def __init__(self, name: str, on_execute):
        self.name = name
        self._on_execute = on_execute

    def execute(self) -> None:
        self._on_execute()


class FakeCommandDefinitions:
    def __init__(self, definitions: dict):
        self._definitions = definitions

    def itemById(self, command_id: str):
        return self._definitions.get(command_id)


class FakeUI:
    def __init__(self, definitions: dict):
        self.commandDefinitions = FakeCommandDefinitions(definitions)
