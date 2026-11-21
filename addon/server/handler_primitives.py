"""Direct primitives, and the two operations that empty or unwind a design.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

from typing import TYPE_CHECKING

from . import fusion_api as adsk
from . import get_logger
from . import hints as _hints
from . import parameter_units as _param_units

log = get_logger("handler")


if TYPE_CHECKING:  # pragma: no cover - the mixin's contract, for type checkers only
    # Not inherited at runtime: ``CommandHandler`` supplies the base.  The reason this
    # exists at all is stated once, above ``class HandlerBase``.
    from .handler_base import HandlerBase as _Contract
else:  # pragma: no cover - unchanged runtime hierarchy: ``object``
    _Contract = object


class PrimitiveCommands(_Contract):
    def delete_all(self):
        """Clear the active design: unwind the timeline, then sweep leftovers.

        Returns counts of what was removed plus any per-item failures.  Raises
        if the design is *not* empty afterwards — a caller that believes this
        succeeded will happily build on a dirty document.
        """
        design = self._design()
        root = design.rootComponent
        deleted = {
            "timeline": 0,
            "joints": 0,
            "occurrences": 0,
            "construction": 0,
            "bodies": 0,
            "sketches": 0,
        }
        errors = []

        def _sweep(collection, stage, counter):
            """Delete every item of *collection*, newest-first."""
            for i in range(collection.count - 1, -1, -1):
                name = "?"
                try:
                    item = collection.item(i)
                    name = getattr(item, "name", "?")
                    item.deleteMe()
                    deleted[counter] += 1
                except Exception as exc:
                    errors.append(
                        {
                            "stage": stage,
                            "index": i,
                            "name": name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        # Parametric: unwind newest-first.  NOTE: TimelineObject has no
        # deleteMe() — that method lives on the *entity* it wraps.  Calling it
        # on the TimelineObject raises AttributeError on every item.
        tl = getattr(design, "timeline", None)
        if tl is not None and tl.count > 0:
            for i in range(tl.count - 1, -1, -1):
                name = "?"
                try:
                    item = tl.item(i)
                    name = item.name
                    entity = item.entity
                    if entity is None:
                        errors.append(
                            {
                                "stage": "timeline",
                                "index": i,
                                "name": name,
                                "error": "timeline item exposes no entity",
                            }
                        )
                        continue
                    entity.deleteMe()
                    deleted["timeline"] += 1
                except Exception as exc:
                    errors.append(
                        {
                            "stage": "timeline",
                            "index": i,
                            "name": name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        # Direct mode has no timeline; the sweeps below also catch anything
        # the timeline pass could not remove.  Joints go before occurrences
        # because they reference them.
        _sweep(root.rigidGroups, "rigid_group", "joints")
        _sweep(root.asBuiltJoints, "as_built_joint", "joints")
        _sweep(root.joints, "joint", "joints")
        # Deleting an occurrence removes the component it references,
        # including its bodies and sketches.
        _sweep(root.occurrences, "occurrence", "occurrences")
        _sweep(root.constructionPlanes, "construction_plane", "construction")
        _sweep(root.constructionAxes, "construction_axis", "construction")
        _sweep(root.constructionPoints, "construction_point", "construction")

        _sweep(root.bRepBodies, "body", "bodies")
        _sweep(root.sketches, "sketch", "sketches")

        remaining = {
            "bodies": root.bRepBodies.count,
            "sketches": root.sketches.count,
            "occurrences": root.occurrences.count,
            "joints": (
                root.joints.count + root.asBuiltJoints.count + root.rigidGroups.count
            ),
            "construction": (
                root.constructionPlanes.count
                + root.constructionAxes.count
                + root.constructionPoints.count
            ),
            "timeline": tl.count if tl is not None else 0,
        }

        if any(v for k, v in remaining.items() if k != "timeline"):
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"delete_all did not clear the design — remaining: {remaining}. "
                f"Deleted: {deleted}. Failures: {errors}",
                hints=(
                    "Re-run delete_all; if bodies remain, delete them one at a time.",
                ),
            )

        return {"deleted": deleted, "remaining": remaining, "errors": errors}

    def undo(self):
        """Step the design back one operation.

        Fusion's ``UndoCommand`` is asynchronous: it applies only after this
        handler returns, so the tool can neither rely on it nor verify it.
        Measured on 2706 — four of five consecutive calls changed nothing while
        reporting success, and 57 event pumps inside one handler did not make a
        queued undo land. Parametric designs therefore step the timeline marker
        back, which the API performs synchronously; direct designs have no
        timeline and keep the UI command, reported as issued-but-unverified.
        """
        design = self._design()
        parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType

        # ``design.timeline`` raises "this is not a parametric design" in direct
        # mode, so it must only be touched once the type is known.
        if parametric:
            timeline = design.timeline
            if timeline is None or not timeline.count:
                return self._undo_nothing(timeline)
            return self._undo_by_marker(design, timeline)

        return self._undo_by_command(design)

    @staticmethod
    def _undo_nothing(timeline) -> dict:
        """Nothing to step back — say so instead of issuing an unverifiable undo."""
        return {
            "undone": False,
            "verified": True,
            "timeline_count": timeline.count if timeline is not None else 0,
            "marker_position": (timeline.markerPosition if timeline is not None else 0),
            "reason": "No timeline feature to step back — the marker is at the "
            "start of history, or the timeline is empty.",
            "hints": [
                "Undo only reverts timeline features. Edits that create no "
                "timeline item (parameter values, appearances, body renames, "
                "joint values) are not undone by this tool.",
            ],
        }

    def _undo_by_marker(self, design, timeline):
        """Step the timeline marker back one feature — verifiable in this call."""
        marker_before = timeline.markerPosition
        type_before = design.designType

        if marker_before <= 0:
            return self._undo_nothing(timeline)

        timeline.markerPosition = marker_before - 1
        adsk.doEvents()
        marker_after = timeline.markerPosition

        if design.designType != type_before:
            # Rollback must never change the design type; if it ever does, put
            # both the marker and the type back rather than leave direct mode.
            try:
                timeline.markerPosition = marker_before
            except Exception as exc:
                log.error("Could not restore the timeline marker: %s", exc)
            try:
                design.designType = type_before
            except Exception as exc:
                log.error("Could not restore design type after aborted undo: %s", exc)
            adsk.doEvents()
            parametric = adsk.fusion.DesignTypes.ParametricDesignType
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Undo aborted: stepping the timeline back to "
                f"{marker_before - 1} changed the design type from "
                f"{'Parametric' if type_before == parametric else 'Direct'} to "
                f"{'Parametric' if design.designType == parametric else 'Direct'}. "
                f"The marker was restored. If the design is stuck in direct "
                f"mode, call set_design_type('parametric') to capture history "
                f"again, then delete the failed feature explicitly.",
                hints=(
                    "If the design is stuck in direct mode, call "
                    "set_design_type('parametric'), then delete the failed "
                    "feature explicitly.",
                ),
            )

        if marker_after == marker_before:
            # The write did not take — do not report a success nobody can see.
            return {
                "undone": False,
                "verified": True,
                "marker_before": marker_before,
                "marker_position": marker_after,
                "timeline_count": timeline.count,
                "reason": "Fusion did not move the timeline marker, so nothing "
                "was undone.",
                "hints": [
                    "Retry once; if the marker still does not move, undo in the "
                    "Fusion UI.",
                ],
            }

        return {
            "undone": True,
            "verified": True,
            "marker_before": marker_before,
            "marker_position": marker_after,
            "timeline_count": timeline.count,
            "note": (
                "Timeline stepped back one feature; it stays in the timeline "
                "suppressed rather than being deleted. Rolling the marker "
                "forward restores it (execute_code: "
                "design.timeline.markerPosition = N) — but creating a new "
                "feature while rolled back discards the suppressed ones."
            ),
        }

    def _undo_by_command(self, design):
        """Direct designs have no timeline; undo is issued, unverified."""
        cmd_def = self.ui.commandDefinitions.itemById("UndoCommand")
        if cmd_def is None:
            raise _hints.Refusal(
                "WORKSPACE_UNAVAILABLE",
                "Undo command is not available in the current workspace. "
                "The design was NOT modified — delete the failed feature "
                "explicitly instead.",
                hints=("Undo needs a Parametric workspace; open one and retry.",),
            )
        cmd_def.execute()
        adsk.doEvents()
        return {
            "undone": "issued",
            "verified": False,
            "design_type": design.designType,
            "note": (
                "This design has no timeline to step back, so Fusion's undo "
                "command was issued. Fusion applies it on a later event-loop "
                "turn, so this call cannot confirm it."
            ),
            "hints": [
                "Fusion's undo is asynchronous; call get_scene_info to confirm "
                "before issuing another undo.",
            ],
        }

    @staticmethod
    def _add_base_body(root, body) -> None:
        """Persist a temporary BRep body as a base feature's body.

        Fusion's documented sequence is add() the feature, startEdit(), add the
        body to it, finishEdit() - a body added outside the edit state is refused.
        The four primitives all came from ``TemporaryBRepManager`` and all need
        exactly this.
        """
        base_feat = root.features.baseFeatures.add()
        base_feat.startEdit()
        root.bRepBodies.add(body, base_feat)
        base_feat.finishEdit()

    def create_box(
        self,
        length: float,
        width: float,
        height: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        # The oriented box's point is its CENTRE (adsk.core.OrientedBoundingBox3D),
        # so the caller's centre goes in unchanged.  Adding ``height / 2`` would base
        # Z while centring X and Y: a box asked for at centre 1 would span 1..3 while
        # its name said centre.
        orient = adsk.core.OrientedBoundingBox3D.create(
            adsk.core.Point3D.create(center_x, center_y, center_z),
            adsk.core.Vector3D.create(1, 0, 0),
            adsk.core.Vector3D.create(0, 1, 0),
            length,
            width,
            height,
        )

        box_body = temp_brep.createBox(orient)
        self._add_base_body(root, box_body)

        return {"created": True, "length": length, "width": width, "height": height}

    def create_box_parametric(
        self,
        length,
        width,
        height,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
        origin_z: float = 0.0,
        plane: str = "xy",
        component_name: str | None = None,
        body_name: str | None = None,
    ):
        """Parametric box: sketch rectangle + dimensions + extrude.

        length/width/height may be numeric (cm) or string expressions
        (e.g. 'boxL', '56 mm'). Expressions are applied via Fusion's
        parameter system so later changes to User Parameters propagate.
        """
        # Every numeric argument that reaches Fusion is judged here: a string
        # expression passes through untouched, and inf/nan is refused rather than
        # written into a dimension or an extrude extent.
        length = _param_units.require_finite(length)
        width = _param_units.require_finite(width)
        height = _param_units.require_finite(height)
        origin_x = _param_units.require_finite(origin_x)
        origin_y = _param_units.require_finite(origin_y)
        origin_z = _param_units.require_finite(origin_z)

        comp = (
            self._component_by_name(component_name) if component_name else self._root()
        )

        base_plane = self._construction_plane(plane)
        if origin_z != 0:
            plane_input = comp.constructionPlanes.createInput()
            offset_val = adsk.core.ValueInput.createByReal(origin_z)
            plane_input.setByOffset(base_plane, offset_val)
            sketch_plane = comp.constructionPlanes.add(plane_input)
        else:
            sketch_plane = base_plane
        sketch = comp.sketches.add(sketch_plane)

        def _initial(val):
            # A placeholder only: the dimensions below carry the real value. An int
            # too large for float must not fail here, or the dimension's expression
            # fallback would be unreachable code.
            try:
                return float(val) if isinstance(val, (int, float)) else 1.0
            except OverflowError:
                return 1.0

        p1 = adsk.core.Point3D.create(origin_x, origin_y, 0)
        p2 = adsk.core.Point3D.create(
            origin_x + _initial(length), origin_y + _initial(width), 0
        )
        rect = sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)

        dims = sketch.sketchDimensions
        text_pt = adsk.core.Point3D.create(0, 0, 0)

        def _set_dim(dim, value):
            kind, payload = _param_units.value_input_for(value)
            if kind == "real":
                dim.parameter.value = payload
            else:
                dim.parameter.expression = payload

        bottom = rect.item(0)
        length_dim = dims.addDistanceDimension(
            bottom.startSketchPoint,
            bottom.endSketchPoint,
            adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
            text_pt,
        )
        _set_dim(length_dim, length)

        right = rect.item(1)
        width_dim = dims.addDistanceDimension(
            right.startSketchPoint,
            right.endSketchPoint,
            adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
            text_pt,
        )
        _set_dim(width_dim, width)

        if sketch.profiles.count == 0:
            raise RuntimeError("Rectangle sketch produced no profile")
        profile = sketch.profiles.item(0)

        ext_feats = comp.features.extrudeFeatures
        ext_input = ext_feats.createInput(
            profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        kind, payload = _param_units.value_input_for(height)
        if kind == "real":
            h_vi = adsk.core.ValueInput.createByReal(payload)
        else:
            h_vi = adsk.core.ValueInput.createByString(payload)
        ext_input.setDistanceExtent(False, h_vi)
        feat = ext_feats.add(ext_input)

        body = feat.bodies.item(0)
        if body_name:
            body.name = body_name

        return {
            "created": True,
            "body_name": body.name,
            "feature_name": feat.name,
            "sketch_name": sketch.name,
            "length": length,
            "width": width,
            "height": height,
            "origin": [origin_x, origin_y, origin_z],
            "plane": plane,
            "component": comp.name,
        }

    def create_cylinder(
        self,
        radius: float,
        height: float,
        base_x: float = 0,
        base_y: float = 0,
        base_z: float = 0,
        axis: str = "z",
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        base_pt = adsk.core.Point3D.create(base_x, base_y, base_z)
        axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
        top_pt = adsk.core.Point3D.create(
            base_x + axis_vec[0] * height,
            base_y + axis_vec[1] * height,
            base_z + axis_vec[2] * height,
        )

        cyl_body = temp_brep.createCylinderOrCone(base_pt, radius, top_pt, radius)

        self._add_base_body(root, cyl_body)

        return {"created": True, "radius": radius, "height": height}

    def create_sphere(
        self,
        radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        center = adsk.core.Point3D.create(center_x, center_y, center_z)
        sphere_body = temp_brep.createSphere(center, radius)

        self._add_base_body(root, sphere_body)

        return {"created": True, "radius": radius}

    def create_torus(
        self,
        major_radius: float,
        minor_radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
        axis: str = "z",
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        center = adsk.core.Point3D.create(center_x, center_y, center_z)
        axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
        axis_vector = adsk.core.Vector3D.create(*axis_vec)

        torus_body = temp_brep.createTorus(
            center, axis_vector, major_radius, minor_radius
        )

        self._add_base_body(root, torus_body)

        return {
            "created": True,
            "major_radius": major_radius,
            "minor_radius": minor_radius,
        }
