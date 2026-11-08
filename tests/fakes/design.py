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

from typing import ClassVar

from .bodies import FakeBody, FakeFace
from .collection import FakeCollection, FakeDeletable
from .features import (
    FakeDraftFeatures,
    FakeFeature,
    FakeInterference,
)
from .runtime import DIRECT, PARAMETRIC, FakePoint3D


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

    def createInput(self, profile, operation) -> FakeExtrudeInput:
        inp = FakeExtrudeInput(profile, operation)
        self.inputs.append(inp)
        return inp

    def add(self, inp):
        self.added.append(inp)
        return FakeFeature("Extrude1")


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
        "Planar": ("primarySlideValue", "secondarySlideValue"),
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
        self.joints = FakeJoints()
        self.asBuiltJoints = FakeAsBuiltJoints()
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
        #: Fusion's design goes invalid when its document is closed, and its
        #: properties then raise "4 : An API Object refers to a deleted Object".
        self.isValid = True
        self.compute_all_calls = 0
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
