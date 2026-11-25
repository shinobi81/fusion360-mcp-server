"""Assembly commands: components, joints, and the frames a joint is built from.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

import math
from contextlib import suppress
from typing import TYPE_CHECKING, Any, ClassVar

from . import fusion_api as adsk
from . import hints as _hints
from . import rules as _rules


def _vector(v) -> list:
    """A Fusion vector as ``[x, y, z]``, which is what a response carries."""
    return [v.x, v.y, v.z]


#: A direction this close to the origin has no axis to normalise. Squared, so the
#: comparison needs no ``sqrt``; 1e-12 is a magnitude of 1e-6, far below any real
#: joint frame and far above floating-point noise on a unit vector.
_DEGENERATE_AXIS_SQUARED = 1e-12

#: How close to parallel counts as parallel for two unit vectors: ~0.08 degrees, so a
#: reference plane Fusion would refuse is caught and no buildable one is.  Both vectors
#: are unit by contract - ``Cylinder.axis`` and ``Plane.normal`` - which the live probe
#: corroborates: a non-unit axis would have refused the planes that do build.
_PARALLEL_TOLERANCE = 1e-6


def _is_zero(vector) -> bool:
    """Whether *vector* is too short to define a direction."""
    squared = sum(component * component for component in vector)
    return squared <= _DEGENERATE_AXIS_SQUARED


if TYPE_CHECKING:  # pragma: no cover - the mixin's contract, for type checkers only
    # Not inherited at runtime: ``CommandHandler`` supplies the base.  The reason this
    # exists at all is stated once, above ``class HandlerBase``.
    from .handler_base import HandlerBase as _Contract
else:  # pragma: no cover - unchanged runtime hierarchy: ``object``
    _Contract = object


class AssemblyCommands(_Contract):
    # joint_type -> (JointInput setter, number of direction arguments it takes).
    # The arities were verified against the running Fusion API: one direction for
    # revolute/slider/cylindrical/planar, two for pin_slot and ball, none for rigid.
    _JOINT_MOTION_SETTERS: ClassVar[dict[str, Any]] = {
        "rigid": ("setAsRigidJointMotion", 0),
        "revolute": ("setAsRevoluteJointMotion", 1),
        "slider": ("setAsSliderJointMotion", 1),
        "cylindrical": ("setAsCylindricalJointMotion", 1),
        "pin_slot": ("setAsPinSlotJointMotion", 2),
        "planar": ("setAsPlanarJointMotion", 1),
        "ball": ("setAsBallJointMotion", 2),
    }

    _JOINT_AXES: ClassVar[dict[str, Any]] = {
        "x": "XAxisJointDirection",
        "y": "YAxisJointDirection",
        "z": "ZAxisJointDirection",
    }

    #: The direction vectors a joint motion exposes, by Fusion's own names.
    #: Measured on 2706 per motion type: slider -> slideDirectionVector; revolute
    #: and cylindrical -> rotationAxisVector; planar -> normalDirectionVector plus a
    #: primary/secondary slide pair (so it DOES slide, and a single
    #: ``slideDirectionVector`` field would have reported null for it); pin_slot ->
    #: both; ball -> pitch/yaw/roll. Reporting whichever exist is the only honest
    #: shape across seven motion types.
    _MOTION_DIRECTIONS: ClassVar[tuple[str, ...]] = (
        "slideDirectionVector",
        "rotationAxisVector",
        "pitchDirectionVector",
        "yawDirectionVector",
        "rollDirectionVector",
        "normalDirectionVector",
        "primarySlideDirectionVector",
        "secondarySlideDirectionVector",
    )

    #: The model's axes, which is what the caller's ``axis`` means.
    _WORLD_AXES: ClassVar[dict[str, tuple[float, float, float]]] = {
        "x": (1.0, 0.0, 0.0),
        "y": (0.0, 1.0, 0.0),
        "z": (0.0, 0.0, 1.0),
    }

    _JOINT_QUADRANTS: ClassVar[dict[str, Any]] = {
        "start": "StartJointQuadrantAngleType",
        "quarter": "QuarterJointQuadrantAngleType",
        "middle": "MiddleJointQuadrantAngleType",
        "third_quarter": "ThirdQuarterJointQuadrantAngleType",
    }

    _JOINT_KEY_POINTS: ClassVar[dict[str, Any]] = {
        "start": "StartKeyPoint",
        "middle": "MiddleKeyPoint",
        "center": "CenterKeyPoint",
        "end": "EndKeyPoint",
    }

    # Joint types whose two direction arguments are (something, primary) rather
    # than (primary, something), so the caller's `axis` is passed second.
    #
    # ball takes (pitchDirection, yawDirection) and rejects a pitch parallel to the
    # joint axis with "Invalid parameter pitchDirection" (verified on 2705), so the
    # perpendicular one goes first.  Measured on 2706, `setAsPinSlotJointMotion(a, b)`
    # makes `a` the ROTATION axis and `b` the slide: passing the caller's axis first
    # makes `axis` the rotation and leaves the slide on the perpendicular default,
    # which the result's `directions` field exposes - `axis_world` said -X while
    # Fusion reported slideDirection [0,0,1].
    _JOINT_REVERSED_DIRECTION_ARGUMENTS = frozenset({"ball", "pin_slot"})

    # JointMotion attribute that carries the driveable value, by motion type,
    # with the value_kind names that select it. BallJointMotion exposes
    # pitchValue/yawValue/rollValue and no rotationValue; cylindrical, pin-slot
    # and planar joints carry both an angle and slide values.
    _JOINT_VALUE_ATTRIBUTES: ClassVar[dict[str, Any]] = {
        "RevoluteJointMotion": {"rotation": "rotationValue"},
        "SliderJointMotion": {"slide": "slideValue"},
        "CylindricalJointMotion": {
            "rotation": "rotationValue",
            "slide": "slideValue",
        },
        "PinSlotJointMotion": {
            "rotation": "rotationValue",
            "slide": "slideValue",
        },
        "PlanarJointMotion": {
            "rotation": "rotationValue",
            "slide": "primarySlideValue",
            "primary_slide": "primarySlideValue",
            "secondary_slide": "secondarySlideValue",
        },
        "BallJointMotion": {
            "rotation": "pitchValue",
            "pitch": "pitchValue",
            "yaw": "yawValue",
            "roll": "rollValue",
        },
    }

    # Attributes stored as an angle, so ``units`` applies to them. Everything
    # else is a length in Fusion's internal unit, cm, and passes through.
    _JOINT_ANGLE_ATTRIBUTES = frozenset(
        {"rotationValue", "pitchValue", "yawValue", "rollValue"}
    )

    def create_construction_plane(
        self,
        method: str,
        plane: str | None = None,
        offset: float | None = None,
        angle: float | None = None,
        edge_name: str | None = None,
        plane_one: str | None = None,
        plane_two: str | None = None,
        point_one: list | None = None,
        point_two: list | None = None,
        point_three: list | None = None,
        body_name: str | None = None,
        face_index: int | None = None,
    ):
        # Judged before a design is read, so a bad shape refuses without one and mock
        # mode answers the same sentence for the same call.
        if refusal := _rules.construction_plane_tangent_refusal(
            {
                "method": method,
                "body_name": body_name,
                "face_index": face_index,
                "point_one": point_one,
                "angle": angle,
                "plane": plane,
            }
        ):
            raise refusal

        root = self._root()
        planes = root.constructionPlanes
        inp = planes.createInput()

        if method == "offset":
            inp.setByOffset(
                self._construction_plane(plane),
                adsk.core.ValueInput.createByReal(offset),
            )
        elif method == "angle":
            inp.setByAngle(
                self._construction_axis(edge_name or "x"),
                adsk.core.ValueInput.createByString(f"{angle} deg"),
                self._construction_plane(plane),
            )
        elif method == "midplane":
            inp.setByTwoPlanes(
                self._construction_plane(plane_one), self._construction_plane(plane_two)
            )
        elif method == "three_points":
            p1 = self._point3d(point_one, "point_one")
            p2 = self._point3d(point_two, "point_two")
            p3 = self._point3d(point_three, "point_three")
            inp.setByThreePoints(p1, p2, p3)
        elif method == "tangent":
            # The rule has already decided which of Fusion's two definitions this call
            # describes: a point, or an angle measured from a reference plane.
            body = self._body_by_name(body_name)
            face = self._face_by_index(body, face_index)
            if point_one is not None:
                inp.setByTangentAtPoint(face, self._point3d(point_one, "point_one"))
            else:
                # Measured on 2706.1.17, against the binding's own docstring: it
                # says `setByTangent` takes a "cylindrical or conical" face, and a
                # cone is refused whichever reference plane the angle is measured
                # from. So the angle form is a cylinder's, and the documented route
                # for a cone is the at-a-point form. GEOMETRY_UNSUPPORTED because
                # every argument is usable - what is missing is a face of the kind
                # this form needs.
                surface = self._surface_type_name(face.geometry.surfaceType)
                if (
                    face.geometry.surfaceType
                    != adsk.core.SurfaceTypes.CylinderSurfaceType
                ):
                    raise _hints.Refusal(
                        "GEOMETRY_UNSUPPORTED",
                        f"A tangent plane at an angle needs a cylindrical face; this "
                        f"one is {surface}",
                        hints=(
                            "Pass point_one instead: the at-a-point form is measured "
                            "to work on a cone and on a planar face.",
                            "list_faces reports each face's surface_type.",
                        ),
                    )
                reference = self._construction_plane(plane)
                # Measured on 2706.1.17, not inferred: `setByTangent` answers True for
                # every reference and it is `constructionPlanes.add` that fails, with
                # `2 : InternalValidationError : data_->execute(&obj, apiName)` - a
                # sentence that names neither the argument nor the fix. The angle is
                # measured *around* the face's axis, so the reference has to contain
                # that axis; a reference plane whose normal is parallel to it is the
                # one Fusion refuses. On a Z cylinder `xy` fails and `yz`/`xz` build,
                # at 0 degrees and at 45.
                face_axis = face.geometry.axis
                normal = reference.geometry.normal
                alignment = abs(
                    face_axis.x * normal.x
                    + face_axis.y * normal.y
                    + face_axis.z * normal.z
                )
                if alignment > 1.0 - _PARALLEL_TOLERANCE:
                    raise _hints.Refusal(
                        "INVALID_INPUT",
                        f"plane '{plane}' is perpendicular to the face's axis: a "
                        "tangent plane's angle is measured around that axis",
                        hints=(
                            "Pass a reference plane that contains the axis: for a Z "
                            "cylinder that is yz or xz, not xy.",
                            "Or pass point_one: the at-a-point form takes any face "
                            "and no reference plane.",
                        ),
                    )
                inp.setByTangent(
                    face,
                    adsk.core.ValueInput.createByString(f"{angle or 0} deg"),
                    reference,
                )

        plane_obj = planes.add(inp)
        return {"created": True, "name": plane_obj.name, "method": method}

    def create_construction_axis(
        self,
        method: str,
        point_one: list | None = None,
        point_two: list | None = None,
        plane_one: str | None = None,
        plane_two: str | None = None,
        body_name: str | None = None,
        edge_index: int | None = None,
        face_index: int | None = None,
    ):
        root = self._root()
        axes = root.constructionAxes
        # Judged before anything is created, and from the parameters alone: the three
        # arguments this method needs are named in the refusal when one is missing.
        if refusal := _rules.perpendicular_axis_refusal(
            {
                "method": method,
                "body_name": body_name,
                "face_index": face_index,
                "point_one": point_one,
            }
        ):
            raise refusal
        inp = axes.createInput()

        if method == "two_points":
            p1 = self._point3d(point_one, "point_one")
            p2 = self._point3d(point_two, "point_two")
            inp.setByTwoPoints(p1, p2)
        elif method == "intersection":
            inp.setByTwoPlanes(
                self._construction_plane(plane_one), self._construction_plane(plane_two)
            )
        elif method == "edge":
            body = self._body_by_name(body_name)
            edge = body.edges.item(edge_index)
            inp.setByEdge(edge)
        elif method == "perpendicular_at_point":
            # The point is judged first: it is a pure parameter, mock mode can see it
            # without a design, and the two modes must answer the same fault for the
            # same call. The body and the face index follow.
            point = self._point3d(point_one, "point_one")
            body = self._body_by_name(body_name)
            inp.setByPerpendicularAtPoint(
                self._face_by_index(body, face_index), point
            )

        axis_obj = axes.add(inp)
        return {"created": True, "name": axis_obj.name, "method": method}

    def create_ucs(
        self,
        name: str | None = None,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        angle_x: float = 0,
        angle_y: float = 0,
        angle_z: float = 0,
    ):
        """Create a User Coordinate System at (x, y, z), angles in degrees.

        The UCS API (May 2026, preview) is entity-based: the anchor must be
        a sketch point / vertex / construction point.  This creates a hidden
        reference sketch (``UCS_<name>_ref``) holding the anchor point; the
        UCS stays parametrically linked to it, so don't delete that sketch.
        (ConstructionPoint anchors are rejected by current builds, hence the
        sketch-point route.)
        """
        root = self._root()

        if z:
            plane_in = root.constructionPlanes.createInput()
            plane_in.setByOffset(
                root.xYConstructionPlane, adsk.core.ValueInput.createByReal(z)
            )
            base_plane = root.constructionPlanes.add(plane_in)
        else:
            base_plane = root.xYConstructionPlane

        sk = root.sketches.add(base_plane)
        pt = sk.sketchPoints.add(adsk.core.Point3D.create(x, y, 0))
        ref_name = f"UCS_{name or 'unnamed'}_ref"
        sk.name = ref_name
        sk.isVisible = False

        geom = adsk.fusion.UserCoordinateSystemGeometry_createByPoint(pt)
        inp = root.userCoordinateSystems.createInput(geom)
        if angle_x:
            inp.angleX = adsk.core.ValueInput.createByReal(math.radians(angle_x))
        if angle_y:
            inp.angleY = adsk.core.ValueInput.createByReal(math.radians(angle_y))
        if angle_z:
            inp.angleZ = adsk.core.ValueInput.createByReal(math.radians(angle_z))

        ucs = root.userCoordinateSystems.add(inp)
        if name:
            # A rejected name must not cost us the UCS we just created.
            with suppress(Exception):
                ucs.name = name
        return {
            "name": ucs.name,
            "origin": [x, y, z],
            "angles_deg": [angle_x, angle_y, angle_z],
            "reference_sketch": ref_name,
        }

    def create_component(self, name: str, parent_name: str | None = None):
        root = self._root()
        parent = self._component_by_name(parent_name) if parent_name else root

        occ = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        occ.component.name = name
        return {"created": True, "name": name}

    def _occurrence_by_component(self, name: str):
        for occ in self._root().allOccurrences:
            if occ.component.name == name:
                return occ
        return None

    def _joint_face(
        self, occ, body_name: str | None, face_index: int | None, label: str
    ):
        """Resolve one cylindrical face used as joint geometry.

        ``face_index`` is optional in both joint commands, and the ``None`` case is
        refused below - the annotation says so rather than claiming a face is always
        named.
        """
        component = occ.component
        bodies = [b for b in component.bRepBodies]
        if body_name:
            bodies = [b for b in bodies if b.name == body_name]
            if not bodies:
                raise RuntimeError(
                    f"Body '{body_name}' not found in component '{component.name}'"
                )
        elif len(bodies) != 1:
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Component '{component.name}' has {len(bodies)} bodies; "
                f"pass '{label}' to choose which body carries the joint geometry",
                hints=(
                    "Pass body_name to say which body carries the joint geometry.",
                ),
            )

        body = bodies[0]
        return self._face_by_index(
            body,
            face_index,
            hints=(
                "Face indices run from 0; a joint needs a cylindrical one, and "
                "list_faces reports each face's surface_type.",
            ),
        )

    def add_joint(
        self,
        component_one: str,
        component_two: str,
        joint_type: str = "rigid",
        body_one: str | None = None,
        face_one: int | None = None,
        body_two: str | None = None,
        face_two: int | None = None,
        axis: str = "x",
        second_axis: str | None = None,
        quadrant: str = "middle",
        key_point: str = "end",
    ):
        """Create a joint between two components from a pair of faces.

        Geometry is mandatory. A joint cannot be built from the components'
        origin points: ``JointGeometry.createByPoint`` rejects them with
        ``Invalid parameter point`` because a bare point carries no component
        association, so ``joints.add`` has nothing to bind.
        """
        if selector_refusal := _rules.joint_selector_refusal(
            {"joint_type": joint_type, "quadrant": quadrant, "key_point": key_point}
        ):
            raise selector_refusal

        root = self._root()
        joints = root.joints

        occ1 = self._occurrence_by_component(component_one)
        occ2 = self._occurrence_by_component(component_two)
        if not occ1 or not occ2:
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                "One or both components not found",
                hints=("Call list_components to see the component names.",),
            )
        if component_refusal := _rules.components_differ_refusal(
            {"component_one": component_one, "component_two": component_two}
        ):
            raise component_refusal

        if geometry_refusal := _rules.joint_geometry_refusal(
            {"face_one": face_one, "face_two": face_two}
        ):
            raise geometry_refusal

        faces = (
            self._joint_face(occ1, body_one, face_one, "body_one"),
            self._joint_face(occ2, body_two, face_two, "body_two"),
        )

        # Indexed, not ``.get()``: ``joint_selector_refusal`` refused an unknown value
        # above, so the key is present for every caller - socket callers included, which
        # the schema gate never sees.
        quadrant_attr = self._JOINT_QUADRANTS[quadrant]
        key_point_attr = self._JOINT_KEY_POINTS[key_point]
        quadrant_value = getattr(adsk.fusion.JointQuadrantAngleTypes, quadrant_attr)
        key_point_value = getattr(adsk.fusion.JointKeyPointTypes, key_point_attr)

        geometries = [
            adsk.fusion.JointGeometry.createByCylinderOrConeFace(
                face, quadrant_value, key_point_value
            )
            for face in faces
        ]

        before = {
            occ.name: (
                occ.transform.translation.x,
                occ.transform.translation.y,
                occ.transform.translation.z,
            )
            for occ in (occ1, occ2)
        }

        inp = joints.createInput(geometries[0], geometries[1])

        # Set the requested motion explicitly: Fusion infers a rigid joint when no
        # motion is set and still reports success, so a type left unhandled silently
        # produces one.  The frame matters here: `axis` names a MODEL axis, and
        # Fusion's enum names a JOINT one.
        #
        # Only a motion that takes a direction needs the frame: a rigid joint
        # resolves no axis, so a degenerate frame it never reads must not refuse
        # it (rigid is the default joint_type).
        needs_frame = self._JOINT_MOTION_SETTERS[joint_type][1] > 0
        frame = self._joint_frame(geometries[0]) if needs_frame else None
        # Read the geometry's own measurements now: adding the joint invalidates
        # the JointGeometry object, and reading it afterwards fails live with
        # "2 : InternalValidationError : face".
        origin = geometries[0].origin
        primary = geometries[0].primaryAxisVector
        axis_world = self._apply_joint_motion(inp, joint_type, axis, second_axis, frame)

        joint = joints.add(inp)
        self._design().computeAll()

        # A Fusion joint *moves* components so the two joint origins become
        # coincident. That silently rearranges the design when the caller only
        # wanted a constraint, so report the displacement instead of hiding it.
        moved = {}
        for occ in (occ1, occ2):
            delta = [
                round(occ.transform.translation.x - before[occ.name][0], 6),
                round(occ.transform.translation.y - before[occ.name][1], 6),
                round(occ.transform.translation.z - before[occ.name][2], 6),
            ]
            if any(abs(v) > 1e-6 for v in delta):
                moved[occ.name] = delta

        motion = joint.jointMotion
        directions = {}
        for attr in self._MOTION_DIRECTIONS:
            vector = getattr(motion, attr, None)
            if vector is not None:
                key = attr.removesuffix("Vector")
                directions[key] = [vector.x, vector.y, vector.z]
        return {
            "created": True,
            "joint_name": joint.name,
            "joint_type": joint_type,
            "motion": motion.objectType.split("::")[-1],
            "snapped": bool(moved),
            "moved_components": moved,
            # Where the joint origin actually landed.  Fusion puts it on the FACE
            # for cylinder geometry — every valid quadrant/height combination was
            # measured at the bore's radius — so a revolute joint rotates about a
            # line offset from the bore.  Reported rather than assumed.
            "joint_origin": [origin.x, origin.y, origin.z],
            "primary_axis": [primary.x, primary.y, primary.z],
            # The model-space vector the motion was given, and every direction
            # vector Fusion then reports for the joint.  A model axis can be
            # unreachable exactly (see _joint_direction), so the sign in axis_world
            # is the answer rather than a guess, and `directions` is Fusion's own
            # account of the joint that came out - the two can differ when the two
            # faces' frames disagree.
            "axis_world": axis_world,
            "directions": directions,
        }

    def _apply_joint_motion(
        self, inp, joint_type: str, axis: str, second_axis: str | None, frame=None
    ):
        """Set the JointInput motion for *joint_type*.

        Arity and argument order were verified against Fusion 2705:

        * rigid                    -> no direction arguments
        * revolute/slider/cylindrical/planar -> one JointDirections
        * pin_slot                 -> (rotationDirection, slideDirection) — measured
        * ball                     -> (pitchDirection, yawDirection); Fusion
          rejects a pitch that is parallel to the joint axis
          (`Invalid parameter pitchDirection`), so the perpendicular axis is
          passed first regardless of which one the caller named as `axis`.
        """
        # `frame` is the joint's own axes in world terms; without it the caller's
        # axis is passed through literally (see _joint_direction).
        setter_name, direction_count = self._JOINT_MOTION_SETTERS[joint_type]
        setter = getattr(inp, setter_name)

        if not direction_count:
            setter()
            return None

        primary, chosen_world = self._joint_direction(axis, frame)
        if direction_count == 1:
            setter(primary)
            return chosen_world

        secondary, _ = self._joint_direction(
            second_axis or self._perpendicular(axis),
            frame,
            avoid=primary if second_axis is None else None,
        )
        if joint_type in self._JOINT_REVERSED_DIRECTION_ARGUMENTS:
            setter(secondary, primary)
        else:
            setter(primary, secondary)
        return chosen_world

    def _joint_frame(self, geometry) -> dict[str, list[float]]:
        """The joint's own axes, in world terms, from the geometry's frame.

        ``JointDirections`` selects a **joint** axis, not a model one. Measured on
        Fusion 2706 by reading ``slideDirectionVector`` back for each member:

            XAxisJointDirection == secondaryAxisVector
            YAxisJointDirection == thirdAxisVector
            ZAxisJointDirection == primaryAxisVector

        Across four quadrants (the slide rotated with the quadrant, and matched
        ``secondary`` in all four), a cylinder whose bore is world X, and a cone.
        The frame that matters is the one on the geometry passed to
        ``createInput``: a joint's own ``geometryOrOriginOne`` carries a permuted
        frame.

        Every direction the caller can ask for is therefore resolved against these
        three vectors.

        A zero-length axis is refused here rather than resolved: ``_joint_direction``
        ranks the members by ``|dot|`` with the wanted world axis, so a degenerate
        vector ties with everything and wins the ranking arbitrarily — the caller
        is then told ``axis_world`` is ``[0, 0, 0]`` and the joint is built around
        whichever ``JointDirections`` member the tie happened to produce.  Only the
        member reaches Fusion; the vector is what the response reports.
        Measured failure without this guard: a frame whose secondary axis was
        ``[0, 0, 0]`` answered ``axis_world`` ``[0, 0, 0]`` for ``axis="y"`` and
        picked an axis the geometry never had.
        """
        frame = {
            "x": _vector(geometry.secondaryAxisVector),
            "y": _vector(geometry.thirdAxisVector),
            "z": _vector(geometry.primaryAxisVector),
        }
        degenerate = [name for name, vector in frame.items() if _is_zero(vector)]
        if degenerate:
            raise RuntimeError(
                f"The joint geometry's {'/'.join(sorted(degenerate))} axis is "
                f"zero-length, so no direction can be resolved against it "
                f"(frame: {frame}). The geometry is unusable for axis selection — "
                "build the joint from another face."
            )
        return frame

    @staticmethod
    def _dot(a, b) -> float:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def _joint_direction(self, axis: str, frame=None, avoid=None):
        """The ``JointDirections`` member whose joint axis best matches *axis*.

        Returns ``(member, world_vector)``. Without a *frame* the caller's axis is
        passed through literally, which is only correct when the joint's frame
        happens to equal the model's.

        No member can point along a world axis the frame does not contain, so the
        closest one is chosen and the sign it actually gives is reported: on the
        measured cylinder geometry world +X is only reachable as joint Z, which
        slides along -X.
        """
        key = (axis or "").lower()
        attr = self._JOINT_AXES.get(key)
        if attr is None:
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Unknown axis: {axis}. Use one of {sorted(self._JOINT_AXES)}",
                hints=(
                    "Pass x, y or z; the axis is resolved against the joint's own "
                    "axes.",
                ),
            )
        if frame is None:
            # Only reachable for a joint whose motion takes no direction at all
            # (rigid), which returns before this is called; a frame is mandatory
            # for anything else, so ask for one rather than guessing.
            raise _hints.Refusal(
                "INTERNAL_ERROR",
                f"A joint frame is required to place axis '{axis}' — internal error",
                hints=("Report this with the traceback.",),
            )

        wanted = self._WORLD_AXES[key]
        ranked = sorted(
            ("x", "y", "z"),
            key=lambda name: abs(self._dot(frame[name], wanted)),
            reverse=True,
        )
        # Two different model axes can resolve to the same joint member when the
        # bore is not aligned with a model axis (a 45 degree bore sends both X and
        # Z to joint Y), and pin_slot/ball take two directions.  Repeating one
        # makes Fusion refuse the joint ("Invalid parameter pitchDirection"), so
        # the runner-up is used instead: one step less parallel, but perpendicular.
        if avoid is not None and self._JOINT_AXES[ranked[0]] == avoid:
            best = ranked[1]
        else:
            best = ranked[0]
        return getattr(adsk.fusion.JointDirections, self._JOINT_AXES[best]), frame[best]

    @staticmethod
    def _perpendicular(axis: str) -> str:
        return "z" if (axis or "x").lower() != "z" else "x"

    def create_as_built_joint(
        self,
        component_one: str,
        component_two: str,
        joint_type: str,
        body_one: str | None = None,
        face_one: int | None = None,
        body_two: str | None = None,
        face_two: int | None = None,
        axis: str = "x",
        second_axis: str | None = None,
        quadrant: str = "middle",
        key_point: str = "end",
    ):
        """Create a joint that keeps the components where they are.

        Unlike ``add_joint``, this does not move anything: an as-built joint
        records the current pose instead of enforcing a new one, which is what
        you want when the parts are already positioned correctly (for example
        the two halves of a hinge lined up in a design).

        Fusion refuses a non-rigid as-built joint without geometry
        (``Geometry should not be null if joint motion is not rigid``), so a
        face pair is required for every joint_type except ``rigid``.
        """
        if selector_refusal := _rules.joint_selector_refusal(
            {"joint_type": joint_type, "quadrant": quadrant, "key_point": key_point}
        ):
            raise selector_refusal

        root = self._root()

        occ1 = self._occurrence_by_component(component_one)
        occ2 = self._occurrence_by_component(component_two)
        if not occ1 or not occ2:
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                "One or both components not found",
                hints=("Call list_components to see the component names.",),
            )
        if component_refusal := _rules.components_differ_refusal(
            {"component_one": component_one, "component_two": component_two}
        ):
            raise component_refusal

        geometry = None
        if joint_type != "rigid":
            if geometry_refusal := _rules.as_built_geometry_refusal(
                {
                    "joint_type": joint_type,
                    "face_one": face_one,
                    "face_two": face_two,
                }
            ):
                raise geometry_refusal
            face = self._joint_face(occ1, body_one, face_one, "body_one")

            # ``asBuiltJoints.createInput`` takes a single geometry, so face_two
            # cannot be used to build the joint. It is still resolved, so an
            # unresolvable body_two/face_two is reported rather than ignored.
            self._joint_face(occ2, body_two, face_two, "body_two")
            # Indexed, not ``.get()``: same reason as in ``add_joint`` - the selector
            # refusal above is what keeps these keys present.
            quadrant_attr = self._JOINT_QUADRANTS[quadrant]
            key_point_attr = self._JOINT_KEY_POINTS[key_point]
            geometry = adsk.fusion.JointGeometry.createByCylinderOrConeFace(
                face,
                getattr(adsk.fusion.JointQuadrantAngleTypes, quadrant_attr),
                getattr(adsk.fusion.JointKeyPointTypes, key_point_attr),
            )

        as_built = root.asBuiltJoints
        inp = as_built.createInput(occ1, occ2, geometry)

        # Honour joint_type: with no motion set, every request produces a rigid
        # joint.  The frame comes from the geometry, and a rigid as-built joint has
        # none, which is why it is optional.
        frame = self._joint_frame(geometry) if geometry is not None else None
        self._apply_joint_motion(inp, joint_type, axis, second_axis, frame)

        joint = as_built.add(inp)
        return {
            "created": True,
            "joint_name": joint.name,
            "joint_type": joint_type,
            "motion": joint.jointMotion.objectType.split("::")[-1],
            "kept_current_positions": True,
        }

    def set_joint_value(
        self,
        value: float,
        joint_name: str | None = None,
        joint_index: int = 0,
        units: str = "deg",
        value_kind: str | None = None,
        as_built: bool = True,
    ):
        """Drive a joint to *value* and confirm Fusion kept it.

        Fusion resets a joint value to zero the next time ``design.computeAll()``
        runs, which makes a naive set-then-recompute look like the API silently
        ignored the assignment.  This method therefore never recomputes: it sets
        the value, refreshes the viewport, reads the value back and raises if it
        did not stick.

        ``units`` is ``deg`` (default) or ``rad`` and applies to angle values
        only; slide values are centimetres.  ``value_kind`` selects the
        attribute: ``rotation`` or ``slide`` on cylindrical and pin-slot,
        ``primary_slide``/``secondary_slide`` on planar, and
        ``pitch``/``yaw``/``roll`` on ball joints.
        """
        root = self._root()
        collection = root.asBuiltJoints if as_built else root.joints

        joint = None
        if joint_name:
            for i in range(collection.count):
                candidate = collection.item(i)
                if candidate.name == joint_name:
                    joint = candidate
                    break
            if joint is None:
                kind = "as-built " if as_built else ""
                raise _hints.Refusal(
                    "NAME_NOT_FOUND",
                    f"{kind}joint '{joint_name}' not found "
                    f"({collection.count} {kind}joints in the design)",
                    hints=("Call get_scene_info to list the joints in this design.",),
                )
        else:
            if collection.count == 0:
                raise _hints.Refusal(
                    "INVALID_INPUT",
                    "No as-built joints in the design; pass as_built=False for "
                    "regular joints or create one first",
                    hints=(
                        "Pass as_built=False for regular joints, or create an "
                        "as-built joint first.",
                    ),
                )
            joint = collection.item(joint_index)

        motion = joint.jointMotion
        motion_kind = motion.objectType.split("::")[-1]
        if motion_kind == "RigidJointMotion":
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"'{joint.name}' is a rigid joint; it has no value to drive",
                hints=(
                    "A rigid joint has no driven value; use a revolute or slider "
                    "joint.",
                ),
            )

        kinds = self._JOINT_VALUE_ATTRIBUTES.get(motion_kind)
        if kinds is None:
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"'{joint.name}' has motion {motion_kind}, which this command "
                f"cannot drive; known types: "
                f"{sorted(self._JOINT_VALUE_ATTRIBUTES)}",
                hints=("Drive only the value kinds the joint's motion has.",),
            )

        if value_kind:
            attribute = kinds.get(value_kind)
            if attribute is None:
                raise _hints.Refusal(
                    "INVALID_INPUT",
                    f"value_kind '{value_kind}' does not apply to {motion_kind}; "
                    f"use one of {sorted(kinds)}",
                    hints=(
                        "A value_kind valid for another joint's motion does not "
                        "apply here; use one this motion has.",
                    ),
                )
        else:
            attribute = kinds.get("rotation") or next(iter(kinds.values()))

        if attribute in self._JOINT_ANGLE_ATTRIBUTES:
            target = value if units == "rad" else math.radians(value)
            value_units = units
        else:
            target = value
            value_units = "cm"

        setattr(motion, attribute, target)
        self.app.activeViewport.refresh()

        read_back = getattr(joint.jointMotion, attribute)
        if abs(read_back - target) > 1e-6:
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Fusion did not keep the requested value on '{joint.name}' "
                f"(set {target:.6f} {value_units}, read back "
                f"{read_back:.6f}). A design.computeAll() after setting a joint "
                f"value resets it to zero.",
                hints=(
                    "Re-read the value with set_joint_value, and avoid computeAll "
                    "after setting it.",
                ),
            )

        return {
            "joint_name": joint.name,
            "motion": motion_kind,
            "value_kind": value_kind,
            "attribute": attribute,
            "value": round(value, 6),
            "units": value_units,
            "read_back": round(read_back, 9),
            "applied": True,
        }

    def create_rigid_group(self, component_names: list, include_children: bool = True):
        root = self._root()
        occs = adsk.core.ObjectCollection.create()
        resolved_names = []

        for name in component_names:
            for occ in root.allOccurrences:
                if occ.component.name == name:
                    occs.add(occ)
                    resolved_names.append(name)
                    break

        if refusal := _rules.rigid_group_size_refusal(
            {"component_names": resolved_names}
        ):
            raise refusal

        groups = root.rigidGroups
        groups.add(occs, include_children)
        return {"created": True, "component_count": occs.count}
