"""The fake ``adsk`` runtime the add-in is imported against.

``command_handler.py`` imports ``adsk.cam``, ``adsk.core`` and ``adsk.fusion``
at module level, so no test can import it without them.  This module supplies
those three, injects them into the add-in's adapter, and resets the adapter when
the test module finishes — a fake left behind would be handed to the next module
that imports adsk-dependent code instead of failing loudly.

Two rules keep the fakes honest (design §7):

* they model **state** — a test asserts on the geometry Fusion would build, not
  on which method was called;
* anything the handler uses but the fake does not implement raises
  ``AttributeError`` rather than returning ``None``, so a missing piece of the
  API fails loudly instead of being swallowed.

Geometry lives in ``tests.fakes.sketch`` and the design tree in
``tests.fakes.design``; this module also owns the loader that installs it.
"""

from __future__ import annotations

import importlib
import types
from collections.abc import Iterator
from contextlib import contextmanager

from .app import FakeApplication, FakeCustomEventHandler

# One source of truth for the design-type strings: ``undo`` compares against the
# copy the runtime hands the handler, so the fake design must use that same one.
PARAMETRIC = "ParametricDesignType"
DIRECT = "DirectDesignType"


class FakePoint3D:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    @classmethod
    def create(cls, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> FakePoint3D:
        return cls(x, y, z)

    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakePoint3D({self.x}, {self.y}, {self.z})"


class FakeVector3D(FakePoint3D):
    pass


class FakePlane:
    """``adsk.core.Plane``: a point on the plane and its normal, plus ``cast``.

    ``Face.geometry`` returns the face's *underlying surface*, so a plate's top
    face hands back a Plane and its side wall a Cylinder — which is why
    ``Plane.cast`` answering ``None`` is how ``create_hole`` skips a side wall.
    A fake that cast anything, or that had no geometry at all, would let a hole
    be drilled sideways and the test would still pass.
    """

    def __init__(
        self,
        origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
        normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
    ):
        self.origin = FakePoint3D(*origin)
        self.normal = FakeVector3D(*normal)

    @staticmethod
    def cast(geometry: object) -> FakePlane | None:
        """``Plane.cast``: a Plane for a plane, ``None`` for any other surface."""
        return geometry if isinstance(geometry, FakePlane) else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakePlane(origin={self.origin}, normal={self.normal})"


class FakeCylinderGeometry:
    """A non-planar ``Face.geometry``: enough for ``Plane.cast`` to refuse it.

    Nothing in the handler reads a cylinder's parameters — only that it is not a
    plane — so this deliberately carries no geometry rather than a fabricated
    one.
    """


class FakeObjectCollection:
    def __init__(self) -> None:
        self.items: list[object] = []

    @classmethod
    def create(cls) -> FakeObjectCollection:
        return cls()

    def add(self, item: object) -> None:
        self.items.append(item)

    @property
    def count(self) -> int:
        return len(self.items)

    def item(self, index: int) -> object:
        return self.items[index]

    def __iter__(self) -> Iterator[object]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


class FakeValueInput:
    """``adsk.core.ValueInput``: the two constructors, and which one was used.

    ``kind`` records the factory.  Fusion distinguishes them — ``createByReal``
    is read in internal units, ``createByString`` parses the unit — and that is
    the difference the parameter tests exist to pin, so the fake keeps it.
    """

    def __init__(self, value: object, kind: str = "real"):
        self.value = value
        self.kind = kind

    @classmethod
    def createByString(cls, value: object) -> FakeValueInput:
        return cls(value, "string")

    @classmethod
    def createByReal(cls, value: object) -> FakeValueInput:
        return cls(value, "real")


def module(name: str, **attrs: object) -> types.ModuleType:
    """A stub module carrying ``attrs`` (setattr keeps type checkers quiet)."""
    created = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(created, attr, value)
    return created


def _design_types() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        ParametricDesignType=PARAMETRIC,
        DirectDesignType=DIRECT,
    )


class FakeJointGeometry:
    """``JointGeometry``: an origin and a right-handed axis frame.

    ``createByCylinderOrConeFace`` is pinned to the live measurement. The origin
    lands on the FACE, never on the bore axis — all sixteen valid quadrant/height
    combinations were measured on Fusion 2706, and ``CenterKeyPoint`` is refused
    outright with "Invalid parameter height" — and the frame that comes back for
    a cylinder whose axis is world Z is primary=+Z, secondary=+X, third=+Y.

    The face supplies the numbers, so a test can move the frame without touching
    the handler: ``face.joint_geometry_for`` returns this object.
    """

    geometryType = 7  # Fusion's CylinderOrConeGeometryType

    def __init__(self, origin, primary, secondary, third):
        self._origin = FakePoint3D(*origin)
        self._primary = FakeVector3D(*primary)
        self._secondary = FakeVector3D(*secondary)
        self._third = FakeVector3D(*third)
        #: Set by ``Joints.add``. Fusion invalidates a JointGeometry once a joint
        #: is built from it: reading it afterwards fails live with
        #: "2 : InternalValidationError : face", which is how a handler that
        #: reported the origin after adding the joint would ship broken.
        self.consumed = False

    def _check(self) -> None:
        if self.consumed:
            raise RuntimeError("2 : InternalValidationError : face")

    @property
    def origin(self):
        self._check()
        return self._origin

    @property
    def primaryAxisVector(self):
        self._check()
        return self._primary

    @property
    def secondaryAxisVector(self):
        self._check()
        return self._secondary

    @property
    def thirdAxisVector(self):
        self._check()
        return self._third

    @staticmethod
    def createByCylinderOrConeFace(face, quadrant, key_point):
        return face.joint_geometry_for(quadrant, key_point)

    @staticmethod
    def createByPoint(point):
        """``JointGeometry.createByPoint(point)`` — Fusion's one-argument form.

        The occurrence-plus-point form this API used to take raises ``TypeError``
        on the current Fusion, which is why ``add_joint`` no longer calls it.  The
        arity is declared here so that a regression reintroducing the two-argument
        call fails the joint tests, instead of needing a source scan to notice.

        The frame is the identity: nothing measured what Fusion reports for a
        point geometry, and no handler reads it — a fabricated measurement would
        be worse than an obviously arbitrary one.
        """
        return FakeJointGeometry(
            origin=(point.x, point.y, point.z),
            primary=(1.0, 0.0, 0.0),
            secondary=(0.0, 1.0, 0.0),
            third=(0.0, 0.0, 1.0),
        )


def _joint_directions() -> types.SimpleNamespace:
    """The three members of ``JointDirections`` a joint motion can be given.

    Their *values* are the attribute names, so a test can assert which one the
    handler passed without a lookup table.  They are joint-frame axes, not world
    ones — measured on Fusion 2706, ``XAxisJointDirection`` on a cylinder-face
    joint slid along world -Y.
    """
    return types.SimpleNamespace(
        XAxisJointDirection="XAxisJointDirection",
        YAxisJointDirection="YAxisJointDirection",
        ZAxisJointDirection="ZAxisJointDirection",
    )


def _joint_quadrants() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        StartJointQuadrantAngleType="StartJointQuadrantAngleType",
        QuarterJointQuadrantAngleType="QuarterJointQuadrantAngleType",
        MiddleJointQuadrantAngleType="MiddleJointQuadrantAngleType",
        ThirdQuarterJointQuadrantAngleType="ThirdQuarterJointQuadrantAngleType",
    )


def _joint_key_points() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        StartKeyPoint="StartKeyPoint",
        MiddleKeyPoint="MiddleKeyPoint",
        CenterKeyPoint="CenterKeyPoint",
        EndKeyPoint="EndKeyPoint",
    )


def _feature_operations() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        NewBodyFeatureOperation="new_body",
        JoinFeatureOperation="join",
        CutFeatureOperation="cut",
        IntersectFeatureOperation="intersect",
    )


def _dimension_orientations() -> types.SimpleNamespace:
    """``DimensionOrientations``: the three ``addDistanceDimension`` orientations.

    Only the distance, horizontal and vertical branches of ``add_dimension``
    read these; angular, radial and diameter never touch the enum.  It has to
    exist for the handler to run at all, which is why it was missing.
    """
    return types.SimpleNamespace(
        AlignedDimensionOrientation="aligned",
        HorizontalDimensionOrientation="horizontal",
        VerticalDimensionOrientation="vertical",
    )


def _primitives() -> types.ModuleType:
    """``tests.fakes.bodies``, imported here rather than at module scope.

    ``bodies`` imports this module for ``FakePoint3D`` and friends, so importing it
    at the top of this file would be circular.  By the time ``install()`` runs both
    modules are loaded.
    """
    return importlib.import_module("tests.fakes.bodies")



def install() -> None:
    """Point the add-in's one import site at the fake API.

    The surface is the union of what the add-in test modules need: a small, fixed
    set of constructors and enums.  Adding a name here is the only way to widen it,
    so it stays reviewable.

    Nothing goes into ``sys.modules``: the add-in resolves ``adsk`` through
    ``fusion_api``, so injecting attributes *is* the production path - the same code
    Fusion runs, with different values.
    """
    core = module(
        "adsk.core",
        Point3D=FakePoint3D,
        Vector3D=FakeVector3D,
        Plane=FakePlane,
        ObjectCollection=FakeObjectCollection,
        ValueInput=FakeValueInput,
        OrientedBoundingBox3D=_primitives().FakeOrientedBoundingBox3D,
        Application=FakeApplication,
        CustomEventHandler=FakeCustomEventHandler,
    )
    fusion = module(
        "adsk.fusion",
        DesignTypes=_design_types(),
        FeatureOperations=_feature_operations(),
        JointDirections=_joint_directions(),
        JointQuadrantAngleTypes=_joint_quadrants(),
        JointKeyPointTypes=_joint_key_points(),
        JointGeometry=FakeJointGeometry,
        DimensionOrientations=_dimension_orientations(),
        TemporaryBRepManager=_primitives().FakeTemporaryBRepManager,
    )
    cam = module("adsk.cam")

    from addon.server import fusion_api

    fusion_api.core = core
    fusion_api.fusion = fusion
    fusion_api.cam = cam
    fusion_api.doEvents = lambda: None


@contextmanager
def fake_runtime() -> Iterator[types.ModuleType]:
    """Inject the fakes, import the handler, and reset the adapter afterwards.

    Scoped to the caller: a module that inherited a previous test module's injected
    adapter would pass for the wrong reason, so the reset is in a ``finally``.
    """
    from addon.server import fusion_api

    install()
    try:
        yield importlib.import_module("addon.server.command_handler")
    finally:
        fusion_api.reset()
