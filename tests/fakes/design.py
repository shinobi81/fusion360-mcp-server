"""Fake design tree: the document, its timeline, features and UI commands.

Two Fusion behaviours are modelled rather than stubbed, because both are the
reason the tests in ``test_addon_undo.py`` and ``test_addon_revolve_axis.py``
exist:

* ``design.timeline`` **raises** on a direct design (Fusion: "3 : this is not a
  parametric design"), so a caller that reads it behind ``hasattr`` breaks —
  ``hasattr`` only swallows ``AttributeError``.
* a revolve about a **stale profile proxy** is rejected, so reading the profile
  before adding the axis line to the same sketch fails instead of passing.
"""

from __future__ import annotations

from .sketch import FakeSketch

PARAMETRIC = "ParametricDesignType"
DIRECT = "DirectDesignType"


class FakeTimeline:
    """``design.timeline``: a count and a movable marker."""

    def __init__(self, design: FakeDesign):
        self._design = design

    @property
    def count(self) -> int:
        return self._design.timeline_count

    @property
    def markerPosition(self) -> int:
        return self._design.marker

    @markerPosition.setter
    def markerPosition(self, value: int) -> None:
        self._design.set_marker(value)


class FakeCollection:
    """``.count`` / ``.item(i)`` over a list, the shape Fusion collections have."""

    def __init__(self, items: list | None = None):
        self._items = list(items or [])

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int):
        return self._items[index]

    def __iter__(self):
        return iter(self._items)


class FakeAxes:
    """The three world axes; a revolve about one must not build geometry."""

    def __init__(self):
        self.xConstructionAxis = type("Axis", (), {"name": "X"})()
        self.yConstructionAxis = type("Axis", (), {"name": "Y"})()
        self.zConstructionAxis = type("Axis", (), {"name": "Z"})()


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


class FakeFeature:
    def __init__(self, name: str):
        self.name = name


class FakeRevolveFeatures:
    """``features.revolveFeatures``: records inputs, rejects stale profiles."""

    def __init__(self, sketch: FakeSketch | None):
        self._sketch = sketch
        self.inputs: list[FakeRevolveInput] = []
        self.added: list[FakeRevolveInput] = []

    def createInput(self, profile, axis, operation) -> FakeRevolveInput:
        created = FakeRevolveInput(profile, axis, operation)
        self.inputs.append(created)
        return created

    def add(self, inp: FakeRevolveInput) -> FakeFeature:
        # What Fusion 2706 does: a profile proxy captured before the sketch was
        # modified is stale, and the revolve is rejected outright.
        if self._sketch is not None and inp.profile.version != self._sketch.version:
            raise RuntimeError("3 : invalid profile(s) for Revolve Feature")
        self.added.append(inp)
        return FakeFeature("Revolve1")


class FakeFeatures:
    """``root.features``: a count plus the revolve collection."""

    def __init__(
        self,
        design: FakeDesign | None = None,
        sketch: FakeSketch | None = None,
    ):
        self._design = design
        self.revolveFeatures = FakeRevolveFeatures(sketch)

    @property
    def count(self) -> int:
        return 0 if self._design is None else self._design.features


class FakeRoot:
    """``design.rootComponent``: bodies, sketches, features and world axes."""

    def __init__(self, design: FakeDesign | None = None, sketches=()):
        body_count = design.bodies if design else 0
        self.bRepBodies = FakeCollection([object() for _ in range(body_count)])
        self.sketches = FakeCollection(list(sketches))
        self.features = FakeFeatures(design, sketches[0] if sketches else None)
        axes = FakeAxes()
        self.xConstructionAxis = axes.xConstructionAxis
        self.yConstructionAxis = axes.yConstructionAxis
        self.zConstructionAxis = axes.zConstructionAxis


class FakeDesign:
    """A design: timeline, type, root component, and a document behind it.

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
    ):
        self.timeline_count = features
        self.marker = features if marker is None else marker
        self.bodies = 1 if features else 0
        self.features = features
        self.designType = design_type
        self.marker_switches_type = marker_switches_type
        self.timeline_raises = (
            design_type == DIRECT if timeline_raises is None else timeline_raises
        )
        self._timeline = FakeTimeline(self)
        self.rootComponent = FakeRoot(self, sketches)
        self.undo_commands_executed = 0
        self.marker_writes: list[int] = []
        self.parentDocument = type("FakeDocument", (), {"name": "fake-design"})()

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


class UndoRig:
    """A handler wired to a fake design, with the UI undo/redo commands stubbed."""

    def __init__(self, handler_module, design: FakeDesign, defs: dict):
        self.design = design
        self.handler = handler_module.CommandHandler.__new__(
            handler_module.CommandHandler
        )
        self.handler.ui = FakeUI(defs)
        self.handler._design = lambda: design


def undo_rig(handler_module, design=None, with_undo=True, with_redo=True) -> UndoRig:
    """Build an :class:`UndoRig`; ``with_undo=False`` models the missing command."""
    design = design or FakeDesign()
    defs = {}
    if with_undo:

        def undo_execute():
            design.undo_commands_executed += 1

        defs["UndoCommand"] = FakeCommandDefinition("UndoCommand", undo_execute)
    if with_redo:
        defs["RedoCommand"] = FakeCommandDefinition("RedoCommand", lambda: None)
    return UndoRig(handler_module, design, defs)
