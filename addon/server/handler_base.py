"""The command handler's shared half: dispatch, the attribute tables, the helpers.

``__init__`` builds the dispatch table and ``execute_command`` runs it.  A helper
lives here when two or more domains call it, or when dispatch calls it directly:
one domain owning it would make that domain's module the dependency of another.
``command_handler.CommandHandler`` is this class plus one class per domain, so a
helper here cannot be unreachable, only under-sorted.
"""

import inspect
import time
import traceback
from contextlib import suppress
from typing import Any, Callable, ClassVar

from . import fusion_api as adsk
from . import get_logger
from . import hints as _hints
from . import rules as _rules
from .mutation_commands import MUTATION_COMMANDS

log = get_logger("handler")


class HandlerBase:
    def __init__(self):
        self.app = adsk.core.Application.get()
        self.ui = self.app.userInterface
        self._commands: dict[str, Callable[..., Any]] = {
            name: getattr(self, name) for name in self._COMMAND_NAMES
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    # Canonical camera presets, (eye_dir, up_vec) in Fusion's Z-up world.
    # Shared by render_view and export_view_sheet.
    _VIEW_DIRS: ClassVar[dict[str, Any]] = {
        "iso": ((1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
        "iso_ne": ((1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
        "iso_nw": ((-1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
        "iso_sw": ((-1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
        "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
        "back": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
        "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
        "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    }

    # Commands that can change body mass / bbox / body count.  Only these
    # get before/after snapshots so agents can sanity-check without a render.
    # The set itself is canonical in `mutation_commands.py`, which the server
    # package mirrors and mock mode imports.
    _MUTATION_COMMANDS = MUTATION_COMMANDS

    # The dispatch table: command name -> method of this class.  A class
    # attribute rather than a literal, so a name that has no method cannot be
    # listed (`__init__` resolves it) and a reloaded handler cannot inherit a
    # table built by another instance.
    _COMMAND_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "new_document",
            "get_scene_info",
            "get_object_info",
            "list_edges",
            "get_bounding_box",
            "list_components",
            # sketch
            "create_sketch",
            "draw_rectangle",
            "draw_circle",
            "draw_line",
            "draw_arc",
            "draw_spline",
            "create_polygon",
            "draw_circles",
            "add_constraint",
            "auto_constrain",
            "add_dimension",
            "offset_curve",
            "trim_curve",
            "extend_curve",
            "project_geometry",
            # features
            "extrude",
            "revolve",
            "sweep",
            "loft",
            "fillet",
            "chamfer",
            "shell",
            "mirror",
            "create_hole",
            "rectangular_pattern",
            "circular_pattern",
            "create_thread",
            "draft_faces",
            "split_body",
            "split_face",
            "offset_faces",
            "scale_body",
            "suppress_feature",
            "unsuppress_feature",
            # body operations
            "move_body",
            "rename_body",
            "export_stl",
            "export_step",
            "export_f3d",
            "export_view_sheet",
            "export",
            "import_mesh",
            "create_box_parametric",
            "boolean_operation",
            "delete_all",
            "undo",
            # direct primitives
            "create_box",
            "create_cylinder",
            "create_sphere",
            "create_torus",
            # construction geometry
            "create_construction_plane",
            "create_construction_axis",
            "create_ucs",
            # assembly
            "create_component",
            "add_joint",
            "set_joint_value",
            "create_as_built_joint",
            "create_rigid_group",
            # inspection / analysis
            "measure_distance",
            "measure_angle",
            "get_physical_properties",
            "create_section_analysis",
            "check_interference",
            "compare_meshes",
            # appearance
            "set_appearance",
            "set_color",
            # parameters
            "get_parameters",
            "create_parameter",
            "set_parameter",
            "delete_parameter",
            # surface operations
            "patch_surface",
            "stitch_surfaces",
            "thicken_surface",
            "ruled_surface",
            "trim_surface",
            # sheet metal
            "create_flange",
            "create_bend",
            "flat_pattern",
            "unfold",
            # code execution
            "execute_code",
            # CAM
            "cam_list_setups",
            "cam_list_operations",
            "cam_get_operation_info",
            "cam_create_setup",
            "cam_create_operation",
            "cam_generate_toolpath",
            "cam_post_process",
            # health
            "ping",
            # design type safety
            "get_design_type",
            "set_design_type",
            # perception
            "render_view",
        }
    )

    def execute_command(self, command: dict) -> dict:
        """Route *command* to the correct handler; return a response dict."""
        cmd_type = command.get("type")
        params = command.get("params", {})

        commands = self._commands
        handler = commands.get(cmd_type or "")
        if handler is None:
            # Infrastructure-level failure (not an application error) —
            # keep the legacy error envelope so the client raises.
            return {
                "status": "error",
                "error_kind": "UNKNOWN_COMMAND",
                "message": f"Unknown command: {cmd_type}",
            }

        is_mutation = cmd_type in self._MUTATION_COMMANDS
        snap_before = self._snapshot() if is_mutation else None

        try:
            # A client can reach :9876 directly and skip the server's schema gate
            # (spec D12), so the handler's own signature is the last check: an
            # argument the tool does not declare - or a missing one - must arrive
            # as a typed refusal, not a bare TypeError that classifies as UNKNOWN.
            try:
                inspect.signature(handler).bind(**params)
            except TypeError as exc:
                raise _hints.Refusal(
                    "INVALID_INPUT",
                    f"{cmd_type}: {exc}",
                    hints=(
                        "An argument is missing, or is not one this tool declares.",
                        "docs/TOOLS.md and get_object_info name each tool's arguments.",
                    ),
                ) from None
            t0 = time.monotonic()
            result = handler(**params)
            elapsed = time.monotonic() - t0
            log.debug("%s completed in %.3fs", cmd_type, elapsed)
        except Exception as exc:
            log.error("%s raised: %s", cmd_type, exc)
            error_kind, hint_list = _hints.classify(exc)
            return {
                "status": "success",
                "result": {
                    "ok": False,
                    "error_kind": error_kind,
                    "error_message": str(exc) or exc.__class__.__name__,
                    "hints": hint_list,
                    "traceback": traceback.format_exc(),
                },
            }

        if not isinstance(result, dict):
            result = {"value": result}
        result.setdefault("ok", True)

        if is_mutation and snap_before is not None:
            snap_after = self._snapshot()
            if snap_after is not None:
                result["deltas"] = self._compute_deltas(snap_before, snap_after)

        return {"status": "success", "result": result}

    def _design(self):
        """The active document's Design product.

        Prefer the explicit DesignProductType lookup: when the Manufacture
        (or another) workspace is active, ``app.activeProduct`` returns the
        CAM product instead of the design, which breaks every handler that
        assumes a fusion.Design.
        """
        doc = self.app.activeDocument
        if doc is not None:
            with suppress(Exception):
                design = doc.products.itemByProductType("DesignProductType")
                if design is not None:
                    return design
        d = self.app.activeProduct
        if d is None or not hasattr(d, "rootComponent"):
            raise RuntimeError(
                "No active design — call new_document to create one "
                "(Fusion has no document open)"
            )
        return d

    def _root(self):
        return self._design().rootComponent

    def _last_sketch(self):
        root = self._root()
        if root.sketches.count == 0:
            raise RuntimeError("No sketch available — create one first")
        return root.sketches.item(root.sketches.count - 1)

    def _sketch(self, name: str | None = None):
        """The sketch called ``name``, or the most recent one when it is falsy.

        Seventeen handlers resolve the same way; the truthiness test is load-bearing
        (an empty string means "the last one", not a sketch called "").
        """
        return self._sketch_by_name(name) if name else self._last_sketch()

    def _sketch_by_name(self, name: str):
        root = self._root()
        for i in range(root.sketches.count):
            s = root.sketches.item(i)
            if s.name == name:
                return s
        raise RuntimeError(f"Sketch '{name}' not found")

    @staticmethod
    def _point3d(values, label: str):
        """``Point3D.create(*values)``, naming the parameter when it is unset.

        The construction tools take optional point lists; unpacking None raised
        TypeError from inside Fusion's binding, which said nothing a caller could
        act on.  The check is judged from the parameter alone, so it lives in
        ``rules`` and mock mode answers it identically.
        """
        if refusal := _rules.point3d_refusal({label: values}):
            raise refusal
        return adsk.core.Point3D.create(*values)

    def _body_by_name(self, name: str | None):
        if refusal := _rules.body_name_required_refusal({"body_name": name}):
            raise refusal
        root = self._root()
        # Search root bodies first
        for i in range(root.bRepBodies.count):
            b = root.bRepBodies.item(i)
            if b.name == name:
                return b
        # Search bodies inside components via occurrence proxies (assembly design)
        # Returns proxy body in root coordinate space for correct boolean ops
        for occ in root.allOccurrences:
            for i in range(occ.bRepBodies.count):
                b = occ.bRepBodies.item(i)
                if b.name == name:
                    return b
        raise RuntimeError(f"Body '{name}' not found")

    def _body_or_index(self, body_name: str | None, body_index: int):
        """The body named, or the one at ``body_index`` when no name was given.

        Six selectors take ``body_name``/``body_index`` in preference order; the
        truthiness test keeps "" meaning "use the index".
        """
        if body_name:
            return self._body_by_name(body_name)
        return self._root().bRepBodies.item(body_index)

    def _component_by_name(self, name: str):
        root = self._root()
        if root.name == name:
            return root
        for occ in root.allOccurrences:
            if occ.component.name == name:
                return occ.component
        raise _hints.Refusal(
            "NAME_NOT_FOUND",
            f"Component '{name}' not found",
            hints=("Call list_components for the component names.",),
        )

    def _construction_plane(self, plane: str | None):
        root = self._root()
        m = {
            "xy": root.xYConstructionPlane,
            "yz": root.yZConstructionPlane,
            "xz": root.xZConstructionPlane,
        }
        # Still a refusal: an unset plane is a caller mistake, and defaulting to
        # xy would build geometry nobody asked for.
        p = m.get((plane or "").lower())
        if p is None:
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Unknown plane {plane!r} — use xy, yz, or xz",
                hints=("Pass xy, yz or xz; the plane is lowercased, so XZ works.",),
            )
        return p

    def _construction_axis(self, axis: str):
        root = self._root()
        m = {
            "x": root.xConstructionAxis,
            "y": root.yConstructionAxis,
            "z": root.zConstructionAxis,
        }
        # Lowercased like _construction_plane, so "X" and "x" name the same axis.
        a = m.get((axis or "").lower())
        if a is None:
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Unknown axis '{axis}' — use x, y, or z",
                hints=("Pass x, y or z; the axis is lowercased, so Y works.",),
            )
        return a

    @staticmethod
    def _timeline_count(design) -> int:
        """Timeline length, or 0 — ``design.timeline`` raises in direct mode.

        ``hasattr`` only swallows AttributeError, and Fusion raises RuntimeError
        ("3 : this is not a parametric design"), so the property has to be
        guarded rather than probed.
        """
        try:
            timeline = design.timeline
        except RuntimeError:
            return 0
        return timeline.count if timeline is not None else 0

    @staticmethod
    def _sketch_frame(sketch):
        """Origin and in-plane axes of the sketch.

        Read before any curve is added: if reading the transform failed after
        the mutation landed, the caller would see ``ok: false`` for geometry
        that was already created.
        """
        origin, x_axis, y_axis, _z_axis = sketch.transform.getAsCoordinateSystem()
        return origin, x_axis, y_axis

    @staticmethod
    def _model_point(frame, x: float, y: float):
        """Where a local ``(x, y)`` point on the sketch plane lands in model space."""
        origin, x_axis, y_axis = frame
        return [
            origin.x + x * x_axis.x + y * y_axis.x,
            origin.y + x * x_axis.y + y * y_axis.y,
            origin.z + x * x_axis.z + y * y_axis.z,
        ]

    @staticmethod
    def _report_dropped_z(result: dict, *z_values: float) -> dict:
        """Surface any z that was dropped, so the projection is never silent."""
        dropped = [z for z in z_values if z]
        if dropped:
            result["ignored_z"] = dropped[0] if len(dropped) == 1 else dropped
            result["note"] = _rules.sketch_plane_z_note()
        return result

    def _curve_by_index(self, sketch, curves, index, field: str):
        """The sketch curve *index* names, or a refusal that says which one missed.

        Every curve-taking tool used ``curves[index]`` with no guard, and three
        of Python's behaviours then decide what a caller sees - none of them an
        answer to the question asked: an index past the end raises ``IndexError``
        (``UNKNOWN``, no hints), a **negative** index silently wraps so
        ``curves[-1]`` constrains a curve nobody named (measured live:
        ``add_dimension(entity_one=-1, entity_two=-2)`` returned ``ok: true``),
        and ``True`` is an ``int`` in Python, so ``curves[True]`` is ``curves[1]``.
        """
        if isinstance(index, bool) or not isinstance(index, int):
            raise RuntimeError(
                f"{field} must be a whole-number curve index, got {index!r} - "
                f"sketch '{sketch.name}' has {len(curves)} curve(s)"
            )
        if not curves:
            raise RuntimeError(
                f"sketch '{sketch.name}' has no curves, so {field} {index} names "
                "nothing - draw the geometry first"
            )
        if index < 0 or index >= len(curves):
            raise RuntimeError(
                f"{field} {index} is outside sketch '{sketch.name}': it has "
                f"{len(curves)} curve(s), indexed 0..{len(curves) - 1}"
            )
        return curves[index]

    def _point_by_index(self, sketch, points, index, field: str):
        """The sketch point *index* names, or a refusal that says which one missed.

        ``midpoint``'s first entity is a POINT, so it is read against the point
        collection: validated against the curve list, a point index that is also
        inside that list names the wrong item, and one past it is refused with advice
        about curves - a different collection.

        ``points`` is Fusion's collection (``count``/``item``), not a list: that is
        the surface it offers, and it is what the fake models.
        """
        count = points.count
        if isinstance(index, bool) or not isinstance(index, int):
            raise RuntimeError(
                f"{field} must be a whole-number point index, got {index!r} - "
                f"sketch '{sketch.name}' has {count} point(s)"
            )
        if count == 0:
            raise RuntimeError(
                f"sketch '{sketch.name}' has no points, so {field} {index} names "
                "nothing - draw the geometry first"
            )
        if index < 0 or index >= count:
            raise RuntimeError(
                f"{field} {index} is outside sketch '{sketch.name}': it has "
                f"{count} point(s), indexed 0..{count - 1}"
            )
        return points.item(index)

    def _set_suppressed(self, feature_name: str, suppressed: bool) -> dict:
        """Flip one timeline entry's ``isSuppressed``, by feature name.

        The entity check is the only guard here: an item can wrap no entity, and
        ``item.entity.name`` would raise.  A direct design has no timeline at all,
        and Fusion's own "this is not a parametric design" refusal is surfaced
        from ``design.timeline`` rather than swallowed - the caller needs to see
        that a suppress on a direct design is meaningless, not a silent no-op.
        """
        design = self._design()
        for i in range(design.timeline.count):
            item = design.timeline.item(i)
            has_entity = hasattr(item, "entity") and item.entity
            if has_entity and item.entity.name == feature_name:
                item.isSuppressed = suppressed
                key = "suppressed" if suppressed else "unsuppressed"
                return {key: True, "feature": feature_name}
        raise _hints.Refusal(
            "NAME_NOT_FOUND",
            f"Feature '{feature_name}' not found in timeline",
            hints=("Call get_scene_info for the timeline feature names.",),
        )

    @staticmethod
    def _wait_future(future, timeout: float = 25.0):
        """Wait for a CAM generation future, bounded so a runaway
        generation fails as a structured error instead of freezing the
        main thread past the bridge timeout."""
        is_completed = getattr(future, "isCompleted", None)
        if is_completed is None:
            future.wait()
            return
        deadline = time.monotonic() + timeout
        while not future.isCompleted:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Toolpath generation did not finish within {timeout}s. "
                    "The operation may still complete in the background — "
                    "check with cam_list_operations before regenerating."
                )
            time.sleep(0.1)

    @staticmethod
    def _bbox_dict(bbox):
        return {
            "min": [bbox.minPoint.x, bbox.minPoint.y, bbox.minPoint.z],
            "max": [bbox.maxPoint.x, bbox.maxPoint.y, bbox.maxPoint.z],
        }

    def _snapshot(self) -> dict | None:
        """Capture body_count, overall bbox, and total mass of the design.

        Best-effort — returns None if the design isn't readable yet.  Mass
        is reported in grams; bbox in cm (Fusion's internal unit).
        """
        try:
            # The Design product, through _design()'s own preference: activeProduct
            # is the CAM product while the Manufacture workspace is active, and it
            # has no rootComponent - which silently cost every mutation its deltas.
            design = self._design()
            root = design.rootComponent

            # Count bodies recursively (root + occurrences).
            body_count = root.bRepBodies.count
            try:
                for occ in design.rootComponent.allOccurrences:
                    body_count += occ.bRepBodies.count
            except Exception:
                pass  # allOccurrences can fail on empty designs

            bbox_dict = None
            if body_count > 0:
                try:
                    bbox = root.boundingBox
                    if bbox is not None:
                        bbox_dict = self._bbox_dict(bbox)
                except Exception:
                    bbox_dict = None

            mass_g = 0.0
            if body_count > 0:
                try:
                    # physicalProperties.mass is in kg.  Sum occurrence
                    # bodies explicitly so mass_g stays consistent with
                    # body_count (which includes occurrence bodies).
                    mass_kg = float(root.physicalProperties.mass)
                    for occ in root.allOccurrences:
                        with suppress(Exception):
                            mass_kg += float(occ.physicalProperties.mass)
                    mass_g = mass_kg * 1000.0
                except Exception:
                    mass_g = 0.0

            return {
                "body_count": body_count,
                "bbox": bbox_dict,
                "mass_g": mass_g,
            }
        except Exception as exc:
            log.debug("snapshot failed: %s", exc)
            return None

    @staticmethod
    def _compute_deltas(before: dict, after: dict) -> dict:
        """Return a diff suitable for an agent: counts + masses + bboxes."""
        return {
            "body_count_before": before.get("body_count", 0),
            "body_count_after": after.get("body_count", 0),
            "body_count_delta": after.get("body_count", 0)
            - before.get("body_count", 0),
            "mass_g_before": before.get("mass_g", 0.0),
            "mass_g_after": after.get("mass_g", 0.0),
            "mass_g_delta": after.get("mass_g", 0.0) - before.get("mass_g", 0.0),
            "bbox_before": before.get("bbox"),
            "bbox_after": after.get("bbox"),
        }
