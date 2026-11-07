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

from .bodies import FakeBody
from .collection import FakeCollection, FakeDeletable
from .features import (
    FakeDraftFeatures,
    FakeFeature,
    FakeInterference,
)
from .runtime import DIRECT, PARAMETRIC


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
        """A simplification: Fusion reads centimetres, so "1000 mm" is 100.0.

        Nothing reads this today; the tests assert on ``expression``, which is
        what the handler must write, so the scale is not modelled.
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
        self._parameters[name] = created
        return created

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
        self.bRepBodies = FakeCollection(list(bodies))


class FakeOccurrence:
    def __init__(self, component: FakeComponent):
        self.component = component

    @property
    def bRepBodies(self) -> FakeCollection:
        """An occurrence reaches its component's bodies, as Fusion does."""
        return self.component.bRepBodies


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


class FakeFeatures:
    """``root.features``: a count, the revolve collection and the draft one."""

    def __init__(self, design: FakeDesign | None = None):
        self._design = design
        self.revolveFeatures = FakeRevolveFeatures()
        self.draftFeatures = FakeDraftFeatures()
        self.filletFeatures = FakeFilletFeatures()
        self.chamferFeatures = FakeChamferFeatures()

    @property
    def count(self) -> int:
        return 0 if self._design is None else self._design.features


class FakeRoot:
    """``design.rootComponent``: everything ``delete_all`` sweeps, plus planes."""

    def __init__(
        self,
        design: FakeDesign | None = None,
        sketches=(),
        bodies=None,
    ):
        self.bRepBodies = FakeCollection(
            list(bodies) if bodies is not None else _default_bodies(design)
        )
        self.sketches = FakeCollection(list(sketches))
        self.features = FakeFeatures(design)
        self.joints = FakeCollection()
        self.asBuiltJoints = FakeCollection()
        self.rigidGroups = FakeCollection()
        self.occurrences = FakeCollection()
        self.constructionPlanes = FakeCollection()
        self.constructionAxes = FakeCollection()
        self.constructionPoints = FakeCollection()
        axes = FakeAxes()
        self.xConstructionAxis = axes.xConstructionAxis
        self.yConstructionAxis = axes.yConstructionAxis
        self.zConstructionAxis = axes.zConstructionAxis
        planes = FakePlanes()
        self.xYConstructionPlane = planes.xYConstructionPlane
        self.yZConstructionPlane = planes.yZConstructionPlane
        self.xZConstructionPlane = planes.xZConstructionPlane

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
        self.interference = FakeInterference(list(interferences))
        self._timeline = FakeTimeline(self)
        self.rootComponent = FakeRoot(self, sketches, bodies)
        self.undo_commands_executed = 0
        self.marker_writes: list[int] = []
        self.parentDocument = type("FakeDocument", (), {"name": "fake-design"})()

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
