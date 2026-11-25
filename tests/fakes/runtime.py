"""The fake ``adsk`` runtime the add-in is imported against.

Nothing under ``addon/`` imports ``adsk`` at module level any more: it resolves the
API through ``addon/server/fusion_api.py``.  This module builds the fake surface and
injects it into that adapter, and ``fake_runtime`` restores the adapter when the test
module finishes - a fake left behind would be handed to the next module that imports
adsk-dependent code instead of failing loudly.

Two rules keep the fakes honest:

* they model **state** — a test asserts on the geometry Fusion would build, not
  on which method was called;
* anything the handler uses but the fake does not implement raises
  ``AttributeError`` rather than returning ``None``, so a missing piece of the
  API fails loudly instead of being swallowed.

Geometry lives in ``tests.fakes.sketch``, the design tree in ``tests.fakes.design``, and
the application in ``tests.fakes.app``.
"""

from __future__ import annotations

import importlib
import types
from collections.abc import Iterator
from contextlib import contextmanager

from .app import FakeApplication, FakeCustomEventHandler

#: The names the adapter serves; ``fake_runtime`` restores exactly these.
_ADAPTER_NAMES = ("cam", "core", "fusion", "doEvents")

# One source of truth for the design-type strings: ``undo`` compares against the
# copy the runtime hands the handler, so the fake design must use that same one.
PARAMETRIC = "ParametricDesignType"
DIRECT = "DirectDesignType"

# ``adsk.core.SurfaceTypes``, as the shipped stub numbers it (``adsk/core.py``:
# ``PlaneSurfaceType = 0``, ``CylinderSurfaceType = 1``).  ``unfold`` scans a body's
# faces for the first planar one, so a geometry that answered the wrong member
# would pick a bend's side wall as the stationary face.
PLANE_SURFACE_TYPE = 0
CYLINDER_SURFACE_TYPE = 1
CONE_SURFACE_TYPE = 2


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
        #: ``Surface.surfaceType`` - the property ``unfold`` reads to find a
        #: planar face, rather than the ``Plane.cast`` the hole tools use.
        self.surfaceType = PLANE_SURFACE_TYPE

    @staticmethod
    def cast(geometry: object) -> FakePlane | None:
        """``Plane.cast``: a Plane for a plane, ``None`` for any other surface."""
        return geometry if isinstance(geometry, FakePlane) else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakePlane(origin={self.origin}, normal={self.normal})"


class FakeCylinderGeometry:
    """A non-planar ``Face.geometry``: enough for ``Plane.cast`` to refuse it.

    It carries a **radius** because ``create_thread`` now reads one: the diameter a
    thread must match is ``2 * geometry.radius``, and a thread face without a
    diameter would make the size check untestable.  Measured on 2706 - a Ø20 shaft's
    side face reports ``radius = 1.0``.
    """

    def __init__(self, radius: float = 1.0, axis=(0.0, 0.0, 1.0)):
        self.radius = float(radius)
        #: Not ``PlaneSurfaceType``: a bend's cylindrical wall must never be
        #: mistaken for the stationary face.
        self.surfaceType = CYLINDER_SURFACE_TYPE
        #: ``Cylinder.axis`` / ``Cone.axis``: a tangent plane's angle is measured
        #: *around* it, which is what makes a perpendicular reference plane a
        #: measured refusal rather than a guess.  Z is the fakes' default body axis.
        self.axis = FakeVector3D(*axis)

    @staticmethod
    def cast(geometry):
        """``Cylinder.cast``: the geometry for a cylinder, ``None`` otherwise."""
        return geometry if isinstance(geometry, FakeCylinderGeometry) else None


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


class FakeMatrix3D:
    """``adsk.core.Matrix3D.create()``: the identity placement.

    ``translation`` is the one member modelled, because ``move_body`` writes it
    before handing the matrix to ``moveFeatures``: Fusion's is a settable
    ``Vector3D``, and a test reads back the one the handler built.  It stays
    ``None`` until something writes one, so a call site that never sets a
    placement cannot pass by inheriting a default.  ``create_component`` passes
    a matrix to ``occurrences.addNewComponent`` and reads nothing back from it - a
    matrix that carried numbers nothing measured would be fiction there.
    """

    def __init__(self):
        self.translation: FakeVector3D | None = None

    @classmethod
    def create(cls) -> "FakeMatrix3D":
        return cls()


class FakeColor:
    """``adsk.core.Color``: four 0-255 channels, including ``opacity``.

    Fusion's opacity is an integer 0-255, not a 0..1 float, so ``set_color``'s own
    conversion of its 0..1 argument is visible here.  The fake stores what it was
    given and neither clamps nor rounds it - that is the handler's job, and a fake
    that did it too would hide a caller that forgot.
    """

    def __init__(self, red: int, green: int, blue: int, opacity: int):
        self.red = red
        self.green = green
        self.blue = blue
        self.opacity = opacity

    @staticmethod
    def create(red: int, green: int, blue: int, opacity: int) -> "FakeColor":
        return FakeColor(red, green, blue, opacity)

    def channels(self) -> tuple[int, int, int, int]:
        return (self.red, self.green, self.blue, self.opacity)


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


def _document_types() -> types.SimpleNamespace:
    """``DocumentTypes``: the one member ``new_document`` asks ``documents.add`` for.

    Fusion also has a drawing document type; nothing here calls it, and a member
    nobody calls would be a guess about Fusion's naming rather than a measurement.
    """
    return types.SimpleNamespace(FusionDesignDocumentType="FusionDesignDocumentType")


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


class FakeUserCoordinateSystemGeometry:
    """What ``UserCoordinateSystemGeometry_createByPoint(point)`` returns.

    The factory is a module-level function in Fusion's binding, spelled with the
    constructor in the name.  The handler never reads the geometry - it hands it
    straight to ``userCoordinateSystems.createInput`` - so the fake keeps the
    anchor point and nothing else, which is what lets a test assert where the UCS
    was placed.
    """

    def __init__(self, point):
        self.point = point

    @staticmethod
    def createByPoint(point) -> "FakeUserCoordinateSystemGeometry":
        return FakeUserCoordinateSystemGeometry(point)


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


def _surface_types() -> types.SimpleNamespace:
    """``adsk.core.SurfaceTypes``: the two members the add-in asks for.

    Read from the shipped stub (``adsk/core.py``, ``SurfaceTypes``): it numbers all
    eight surface kinds, and only a planar face and a cylindrical one are modelled
    here - the two a sheet-metal body's scan meets.
    """
    return types.SimpleNamespace(
        PlaneSurfaceType=PLANE_SURFACE_TYPE,
        CylinderSurfaceType=CYLINDER_SURFACE_TYPE,
        # A cone is the surface a tangent plane's at-a-point form is measured on,
        # and the one the angle form must refuse, so the fake declares it rather
        # than letting `getattr` hide its absence.
        ConeSurfaceType=CONE_SURFACE_TYPE,
    )


def _feature_operations() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        NewBodyFeatureOperation="new_body",
        JoinFeatureOperation="join",
        CutFeatureOperation="cut",
        IntersectFeatureOperation="intersect",
    )


def _calculation_accuracy() -> types.SimpleNamespace:
    """``CalculationAccuracy``: the four levels ``get_physical_properties`` maps to.

    Fusion's member names are the handler's own; their values here are those names
    so a test can assert which accuracy reached the body without a lookup table.
    """
    return types.SimpleNamespace(
        LowCalculationAccuracy="LowCalculationAccuracy",
        MediumCalculationAccuracy="MediumCalculationAccuracy",
        HighCalculationAccuracy="HighCalculationAccuracy",
        VeryHighCalculationAccuracy="VeryHighCalculationAccuracy",
    )


def _mesh_refinement_settings() -> types.SimpleNamespace:
    """``MeshRefinementSettings``: the one member ``export_stl`` asks for.

    Fusion offers five levels; only ``MeshRefinementMedium`` is reachable from the
    handler, so only it is modelled - a member nobody calls would be a guess about
    Fusion's naming rather than a measurement.
    """
    return types.SimpleNamespace(MeshRefinementMedium="medium")


def _mesh_units() -> types.SimpleNamespace:
    """``MeshUnits``: the five members ``import_mesh``'s unit map names.

    All five are reachable - the map is the tool's whole ``units`` enum - so all five
    are modelled; their values are the member names so a test can assert which unit
    reached ``MeshBodies.add``.
    """
    return types.SimpleNamespace(
        MillimeterMeshUnit="MillimeterMeshUnit",
        CentimeterMeshUnit="CentimeterMeshUnit",
        MeterMeshUnit="MeterMeshUnit",
        InchMeshUnit="InchMeshUnit",
        FootMeshUnit="FootMeshUnit",
    )


def _auto_constrain_result_types() -> types.SimpleNamespace:
    """``AutoConstrainResultTypes``: the three options ``auto_constrain`` maps to.

    The members are the ones the add-in asks for - 1 thorough, 2 fast, 3 may move
    geometry within tolerance - and their values are the attribute names, so a test
    reads which one reached the input without a lookup table.
    """
    return types.SimpleNamespace(
        Option1AutoConstrainResultType="Option1AutoConstrainResultType",
        Option2AutoConstrainResultType="Option2AutoConstrainResultType",
        Option3AutoConstrainResultType="Option3AutoConstrainResultType",
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


def _ruled_surface_types() -> types.SimpleNamespace:
    """``RuledSurfaceTypes``: the members ``RuledSurfaceFeatures.createInput`` takes.

    Measured on 2706 - the enum is ``RuledSurfaceTypes``, not ``RuledSurfaceRuleType``,
    and the third member is ``DirectionRuledSurfaceType``, which needs a direction
    entity the tool does not take.  Their values are the attribute names so a test
    can assert which one was passed.
    """
    return types.SimpleNamespace(
        TangentRuledSurfaceType="TangentRuledSurfaceType",
        NormalRuledSurfaceType="NormalRuledSurfaceType",
        DirectionRuledSurfaceType="DirectionRuledSurfaceType",
    )


def _surface_continuity_types() -> types.SimpleNamespace:
    """``SurfaceContinuityTypes``: the three the patch input's continuity takes.

    Read from the shipped stub (``adsk/fusion.py``, ``SurfaceContinuityTypes``):
    Connected, Tangent, Curvature, and nothing else.  Their values are the
    attribute names so a test can assert which one reached the input.
    """
    return types.SimpleNamespace(
        ConnectedSurfaceContinuityType="ConnectedSurfaceContinuityType",
        TangentSurfaceContinuityType="TangentSurfaceContinuityType",
        CurvatureSurfaceContinuityType="CurvatureSurfaceContinuityType",
    )


def _fold_bend_line_positions() -> types.SimpleNamespace:
    """``FoldBendLinePositionTypes``: where the bend line sits in the flat state.

    Read from the shipped stub (``adsk/fusion.py``,
    ``FoldBendLinePositionTypes``): start, center and end, spelled with the
    ``FoldBendLinePositionType`` suffix.
    """
    return types.SimpleNamespace(
        StartFoldBendLinePositionType="Start",
        CenterFoldBendLinePositionType="Center",
        EndFoldBendLinePositionType="End",
    )


def _pattern_distance_types() -> types.SimpleNamespace:
    """``PatternDistanceType``: the member ``rectangular_pattern`` asks for.

    Fusion offers a spacing and an extent form; only
    ``SpacingPatternDistanceType`` is reachable from the handler, so only it is
    modelled - a member nobody calls would be a guess about Fusion's naming
    rather than a measurement.  The value is the attribute name so a test can
    assert which one reached the input without a lookup table.
    """
    return types.SimpleNamespace(
        SpacingPatternDistanceType="SpacingPatternDistanceType",
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
        Cylinder=FakeCylinderGeometry,
        ObjectCollection=FakeObjectCollection,
        ValueInput=FakeValueInput,
        Color=FakeColor,
        Matrix3D=FakeMatrix3D,
        DocumentTypes=_document_types(),
        SurfaceTypes=_surface_types(),
        OrientedBoundingBox3D=_primitives().FakeOrientedBoundingBox3D,
        Application=FakeApplication,
        CustomEventHandler=FakeCustomEventHandler,
    )
    fusion = module(
        "adsk.fusion",
        DesignTypes=_design_types(),
        CalculationAccuracy=_calculation_accuracy(),
        FeatureOperations=_feature_operations(),
        AutoConstrainResultTypes=_auto_constrain_result_types(),
        UserCoordinateSystemGeometry_createByPoint=(
            FakeUserCoordinateSystemGeometry.createByPoint
        ),
        JointDirections=_joint_directions(),
        JointQuadrantAngleTypes=_joint_quadrants(),
        JointKeyPointTypes=_joint_key_points(),
        JointGeometry=FakeJointGeometry,
        DimensionOrientations=_dimension_orientations(),
        RuledSurfaceTypes=_ruled_surface_types(),
        SurfaceContinuityTypes=_surface_continuity_types(),
        FoldBendLinePositionTypes=_fold_bend_line_positions(),
        PatternDistanceType=_pattern_distance_types(),
        ThreadInfo=importlib.import_module("tests.fakes.features").FakeThreadInfo,
        ThreadDataQuery=importlib.import_module(
            "tests.fakes.features"
        ).FakeThreadDataQuery,
        MeshRefinementSettings=_mesh_refinement_settings(),
        MeshUnits=_mesh_units(),
        TemporaryBRepManager=_primitives().FakeTemporaryBRepManager,
    )
    cam_fakes = importlib.import_module("tests.fakes.cam")
    cam = module(
        "adsk.cam",
        PostProcessInput=cam_fakes.FakePostProcessInput,
        # ``Tool``: built from JSON only, so the handler's one seam into a tool is
        # the measured ``createFromJson`` and nothing else.
        Tool=cam_fakes.FakeTool,
        # ``OperationTypes``: the four members the shipped stub declares, as distinct
        # sentinels. The handler indexes a map by identity, so sharing one value would
        # let a swapped branch pass.
        OperationTypes=types.SimpleNamespace(
            MillingOperation=object(),
            TurningOperation=object(),
            JetOperation=object(),
            AdditiveOperation=object(),
        ),
        # ``PostOutputUnitOptions``: the three members are 0/1/2, read from Fusion
        # 2706.1.17 rather than guessed - the handler picks one by identity, so a
        # wrong number would pass and say nothing.
        PostOutputUnitOptions=types.SimpleNamespace(
            DocumentUnitsOutput=0,
            InchesOutput=1,
            MillimetersOutput=2,
        ),
    )

    from addon.server import fusion_api

    # A fresh session per install: ``get()`` memoises like Fusion's, and state (events,
    # unregistrations) must not leak from one fixture use into the next.
    FakeApplication.reset()

    fusion_api.core = core
    fusion_api.fusion = fusion
    fusion_api.cam = cam
    fusion_api.doEvents = lambda: None


@contextmanager
def fake_runtime() -> Iterator[types.ModuleType]:
    """Inject the fakes, import the handler, and restore the adapter afterwards.

    Scoped to the caller: a module that inherited a previous test module's injected
    adapter would pass for the wrong reason, so the restore is in a ``finally``.

    **Restores rather than resets**, so nesting works: an inner ``with fake_runtime()``
    inside a module-scoped ``handler_module`` puts the outer fakes back instead of
    wiping them for the rest of the module.
    """
    from addon.server import fusion_api

    absent = object()
    saved = {n: fusion_api.__dict__.get(n, absent) for n in _ADAPTER_NAMES}
    install()
    try:
        yield importlib.import_module("addon.server.command_handler")
    finally:
        for name, value in saved.items():
            if value is absent:
                fusion_api.__dict__.pop(name, None)
            else:
                setattr(fusion_api, name, value)
