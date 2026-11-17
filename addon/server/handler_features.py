"""Feature commands: build, cut, pattern and edit bodies.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

import math
from contextlib import suppress
from typing import ClassVar

from . import fusion_api as adsk
from . import hints as _hints
from . import hole_geometry as _hole_geom
from . import parameter_units as _param_units
from . import rules as _rules


class FeatureCommands:
    # How far an edge's extent may sit from a plane and still count as lying in
    # it, and how much x/y extent still counts as no extent at all. 1e-3 cm is
    # 10 µm — the tolerance the coarse selectors already used as their threshold,
    # kept so that a near-coplanar top (four arcs meeting at z=1) still groups as
    # one plane.  Both comparisons are inclusive; an exclusive bound on one of
    # them would make "in the plane" and "vertical" disagree about the same gap.
    _EDGE_PLANE_EPSILON: ClassVar[float] = 1e-3

    def _resolve_target_body(self, target_body: str | None, operation: str):
        """The body an operation is restricted to, or None to let Fusion choose.

        The extrude, revolve, sweep and loft inputs all carry ``participantBodies``,
        and leaving it empty means "every body the profile reaches".  Measured on
        Fusion 2706: a loft whose sections spanned the seam between two touching
        blocks cut *both* of them, and a caller had no way to cut one.  Resolution
        happens before any geometry is created, so a refusal leaves nothing behind.

        The target-body refusal is ``rules``': mock mode answers a ``target_body``
        beside a new body with the same sentence and the same kind.
        """
        refusal = _rules.target_body_refusal({"target_body": target_body}, operation)
        if refusal is not None:
            raise refusal
        if target_body is None:
            return None
        return self._body_by_name(target_body)

    @staticmethod
    def _operation_type(name: str):
        m = {
            "new_body": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
            "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
            "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
            "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }
        t = m.get(name)
        if t is None:
            raise RuntimeError(
                f"Unknown operation '{name}' — use new_body/join/cut/intersect"
            )
        return t

    def _select_edges(
        self,
        body,
        selection: str,
        indices: list[int] | None = None,
        points: list | None = None,
        tolerance: float = 0.1,
    ):
        """Return an ObjectCollection of edges.

        One selector at a time.  ``indices`` names edges exactly (the indices
        ``list_edges`` reports), ``points`` chooses the nearest edge to each point,
        and ``selection`` is the coarse geometric filter that predates both.

        ``top`` and ``bottom`` take the edges lying in the highest / lowest plane
        that holds any edge — see ``_edges_in_extreme_plane``.

        Explicitness is the point: a caller that passes two selectors has not
        decided, and guessing would round whatever the other selector happened to
        match.  Only "all" is compatible with a silence, because "all" is the
        default and so means "unset".

        The parameters are judged from the parameters alone, by ``rules``; the body is
        resolved first, so a bad body still wins.
        """
        if refusal := _rules.edge_selector_refusal(
            {
                "edge_selection": selection,
                "edge_indices": indices,
                "edge_points": points,
            }
        ):
            raise refusal

        coll = adsk.core.ObjectCollection.create()

        if indices is not None:
            for edge in self._edges_by_index(body, indices):
                coll.add(edge)
            return coll

        if points is not None:
            for edge in self._edges_by_points(body, points, tolerance):
                coll.add(edge)
            return coll

        # A distinct message per cause: "nothing matched" is wrong for a body that
        # has nothing to match, and the hint that follows it would send the caller
        # to list_edges on a body with no edges to list.
        roundable = self._roundable_edges(body)
        if not body.edges.count:
            raise RuntimeError(f"Body '{body.name}' has no edges to select from")
        if not roundable:
            raise RuntimeError(
                f"Body '{body.name}' has no edges that can be rounded — every "
                "one is degenerate"
            )

        if selection == "all":
            for edge in roundable:
                coll.add(edge)
        elif selection in ("top", "bottom"):
            for edge in self._edges_in_extreme_plane(body, selection):
                coll.add(edge)
        else:
            # "vertical", the last of the four the validator accepts — so this is not
            # a guess.  The edge's own box, not its two ends: an end-to-end test calls
            # every closed edge vertical, because a Circle3D's two vertices are the
            # same point (measured on Fusion 2706).
            for edge in roundable:
                box = edge.boundingBox
                if (
                    abs(box.maxPoint.x - box.minPoint.x) <= self._EDGE_PLANE_EPSILON
                    and abs(box.maxPoint.y - box.minPoint.y) <= self._EDGE_PLANE_EPSILON
                ):
                    coll.add(edge)

        if coll.count == 0:
            raise RuntimeError(f"No edges matched selection '{selection}'")
        return coll

    @classmethod
    def _in_extreme_plane(cls, entities, selection: str) -> list:
        """The entities lying in the highest (``top``) or lowest (``bottom``) plane.

        Faces and edges are selected by the same rule, and it exists for a measured
        reason.  On Fusion 2706, ``shell(face_selection="top")`` on a plain
        10 x 10 x 2 box removed **five** faces - the top plus all four side walls,
        whose boxes reach z=2 - because the threshold came from the body's box and
        any face that merely *reaches* it matched.  "Top" now means the entities
        lying in the top plane, which is the one face of a box.

        The plane is measured from the entities, not from the body's box: a plate
        with a spheroid joined on top spans z -2..4 while every one of its fourteen
        edges lies at z=0 or z=1, so a body-extreme threshold matched nothing.

        An entity belongs to the plane only when its whole extent does.  An edge's
        ``pointOnEdge`` is one point on it and a closed edge's two vertices are the
        same point, so a sample cannot say where an edge *lies*; and taking the
        highest z anything reaches would let one raking edge invent a plane that
        holds nothing.

        Two planes closer together than ``_EDGE_PLANE_EPSILON`` are one plane, so a
        body thinner than 10 microns gets everything from both ``top`` and
        ``bottom``.  A body that thin has no top to tell from its bottom.
        """
        eps = cls._EDGE_PLANE_EPSILON
        boxes = [(entity, entity.boundingBox) for entity in entities]
        flat = [box for _, box in boxes if box.maxPoint.z - box.minPoint.z <= eps]
        if not flat:
            return []
        if selection == "top":
            plane = max(box.maxPoint.z for box in flat)
        else:
            plane = min(box.minPoint.z for box in flat)
        return [
            entity
            for entity, box in boxes
            if box.minPoint.z >= plane - eps and box.maxPoint.z <= plane + eps
        ]

    def _faces_in_extreme_plane(self, body, selection: str) -> list:
        """The faces in the top/bottom plane - see ``_in_extreme_plane``.

        Only a face that already lies in a plane can name one, so a body whose top
        is a curved surface (a dome on a plate) still resolves to its flat top ring
        rather than refusing.
        """
        return self._in_extreme_plane(body.faces, selection)

    def _roundable_edges(self, body) -> list:
        """The body's edges minus the degenerate ones, which cannot be rounded.

        A cone's apex produces edges with ``isDegenerate`` true and *no geometry*
        (measured on Fusion 2706: a revolved cone had two of them, both with
        ``geometry`` of type ``NoneType``).  Handing one to ``fillet`` fails
        inside Fusion with ``FILLET_NO_EDGE_FOUND``, so a selector that returns
        them is offering work that cannot be done — and the zero-extent box of a
        degenerate edge would otherwise satisfy "vertical" for the same reason
        it satisfies nothing else.

        ``list_edges`` still reports them: it is a listing, and a caller comparing
        ``count`` against a selection that skips them needs to see both numbers.
        """
        return [edge for edge in body.edges if not edge.isDegenerate]

    def _edges_in_extreme_plane(self, body, selection: str) -> list:
        """The edges in the top/bottom plane - see ``_in_extreme_plane``.

        Measured from the *roundable* edges: ``_roundable_edges`` drops degenerate
        ones upstream, and every edge that remains - curved and raking ones
        included - is judged by its whole box, which is exactly why one raking edge
        cannot invent a plane that holds nothing.
        """
        return self._in_extreme_plane(self._roundable_edges(body), selection)

    def _edges_by_index(self, body, indices) -> list:
        """The edges at *indices*, de-duplicated and range-checked.

        Fusion's edge indices are positional, so one goes stale as soon as the
        body changes.  A stale index that is merely in range would round the wrong
        edge and report success, which is why only the out-of-range case can be
        caught here — and why ``list_edges`` is the intended way to get them.

        ``rules.edge_selector_refusal`` has already refused a non-integer index and an
        empty list, so the range is what is left to check.
        """
        count = body.edges.count
        wanted: list[int] = []
        for index in indices:
            if not 0 <= index < count:
                valid = (
                    f"the valid indices run 0..{count - 1}"
                    if count
                    else "it has no edges to index"
                )
                raise RuntimeError(
                    f"Edge index {index} is out of range — body '{body.name}' has "
                    f"{count} edge(s), so {valid}"
                )
            if index not in wanted:
                wanted.append(index)
        return [body.edges.item(index) for index in wanted]

    def _edges_by_points(self, body, points, tolerance: float) -> list:
        """The edge nearest each point, in the order the points were given.

        Distance is the minimum over the sampled polyline rather than the
        distance to its midpoint: a point near the end of a long edge is still on
        that edge, and a midpoint-only measure would refuse it.
        Two edges equally close is ambiguous, and guessing there silently rounds
        the wrong one.
        """
        # NaN is deliverable over the socket, and ``NaN > tolerance`` is False, so
        # an unguarded tolerance would accept a point 9 cm from the body and round
        # whatever edge happened to be nearest.  One rule, in one place.
        tolerance = _param_units.require_finite(tolerance)
        chosen: list = []
        chosen_ids: set[int] = set()

        def segment_distance(samples, target) -> float:
            """Shortest distance from *target* to the sampled polyline.

            Point-to-*sample* distance is not point-to-*edge* distance: on a 10 cm
            edge sampled five times, a point lying exactly on the edge could sit
            0.5 cm from the nearest sample and be refused.  Measuring each segment
            instead is exact for a straight edge and chord-accurate for a curve.
            """

            def point_segment(a, b) -> float:
                ax, ay, az = a.x, a.y, a.z
                dx, dy, dz = b.x - ax, b.y - ay, b.z - az
                length_sq = dx * dx + dy * dy + dz * dz
                if length_sq == 0.0:
                    t = 0.0
                else:
                    t = (
                        (target.x - ax) * dx
                        + (target.y - ay) * dy
                        + (target.z - az) * dz
                    ) / length_sq
                    t = max(0.0, min(1.0, t))
                cx, cy, cz = ax + dx * t, ay + dy * t, az + dz * t
                return (
                    (target.x - cx) ** 2 + (target.y - cy) ** 2 + (target.z - cz) ** 2
                ) ** 0.5

            return min(
                point_segment(samples[i], samples[i + 1])
                for i in range(len(samples) - 1)
            )

        for point in points:
            x, y, z = (_param_units.require_finite(c) for c in point)
            target = adsk.core.Point3D.create(x, y, z)
            best = None
            ties = []
            for index in range(body.edges.count):
                edge = body.edges.item(index)
                # An edge's parameters are its own, not 0..1: Fusion reported
                # [-1.0, 0.0] for a straight edge, so sampling 0..1 asked for
                # points off the curve and raised "invalid argument parameter".
                # getPointAtParameter also answers (found, point), not a point.
                extent_ok, low, high = edge.evaluator.getParameterExtents()
                if not extent_ok or high <= low:
                    continue
                samples = []
                for step in range(17):
                    parameter = low + (high - low) * step / 16.0
                    found, position = edge.evaluator.getPointAtParameter(parameter)
                    if found:
                        samples.append(position)
                if len(samples) < 2:
                    continue
                distance = segment_distance(samples, target)
                if best is None or distance < best[0] - 1e-6:
                    best = (distance, edge, index)
                    ties = [(distance, index)]
                elif abs(distance - best[0]) <= 1e-6:
                    ties.append((distance, index))
            if best is None:
                # Two different failures, and they need different answers: a body
                # with no edges at all cannot be helped, while a body whose edges
                # reported no usable range is a Fusion surprise worth naming.
                reason = (
                    "has no edges"
                    if body.edges.count == 0
                    else f"reported no usable parameter range on any of its "
                    f"{body.edges.count} edge(s)"
                )
                raise _hints.Refusal(
                    "GEOMETRY_UNSUPPORTED",
                    f"Body '{body.name}' {reason}, so no point can select an edge",
                    hints=(
                        "Choose a body whose face has edges and reports a usable "
                        "parameter range.",
                    ),
                )
            distance, edge, index = best
            # Tolerance before ambiguity: a point far from everything that happens
            # to sit symmetrically between three edges is a *miss*, and telling
            # the caller it is ambiguous sends them to pick from a list instead of
            # moving the point.  Both within reach is what ambiguity means.
            if distance > tolerance:
                raise RuntimeError(
                    f"No edge within {tolerance} cm of ({x}, {y}, {z}) — the "
                    f"nearest is edge {index} at {distance:.3f} cm"
                )
            if len(ties) > 1:
                names = ", ".join(str(i) for _, i in ties)
                raise RuntimeError(
                    f"Point ({x}, {y}, {z}) is equally close to edges {names} — "
                    "pick one with edge_indices from list_edges"
                )
            if id(edge) not in chosen_ids:
                chosen_ids.add(id(edge))
                chosen.append(edge)
        return chosen

    def _select_faces(self, body, selection: str):
        """Return an ObjectCollection of faces based on *selection*."""
        coll = adsk.core.ObjectCollection.create()

        if selection == "all":
            for face in body.faces:
                coll.add(face)
        elif selection in ("top", "bottom"):
            for face in self._faces_in_extreme_plane(body, selection):
                coll.add(face)
        elif selection == "vertical":
            for face in body.faces:
                # Check if face normal is roughly horizontal (vertical face)
                with suppress(Exception):
                    _, normal_vec = face.evaluator.getNormalAtPoint(face.pointOnFace)
                    if abs(normal_vec.z) < 0.1:
                        coll.add(face)
        else:
            raise RuntimeError(
                f"Unknown face_selection '{selection}' — use all/top/bottom/vertical"
            )

        if coll.count == 0:
            raise RuntimeError(f"No faces matched selection '{selection}'")
        return coll

    def extrude(
        self,
        height: float,
        profile_index: int = 0,
        operation: str = "new_body",
        direction: str = "positive",
        sketch_name: str | None = None,
        target_body: str | None = None,
    ):
        """Extrude a sketch profile.

        ``target_body`` names the body a cut/join/intersect applies to; without
        it Fusion applies the operation to every body the profile reaches.
        """
        root = self._root()
        # The operation first: a mistyped one invalidates everything after it,
        # and a caller sent looking for a body or a sketch would fix that and be
        # refused again.
        feature_operation = self._operation_type(operation)
        sketch = self._sketch(sketch_name)
        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)
        target = self._resolve_target_body(target_body, operation)

        ext_feats = root.features.extrudeFeatures
        ext_input = ext_feats.createInput(profile, feature_operation)
        dist = adsk.core.ValueInput.createByReal(height)
        if direction == "symmetric":
            ext_input.setSymmetricExtent(dist, True)
        else:
            ext_input.setDistanceExtent(direction == "negative", dist)
        if target is not None:
            ext_input.participantBodies = [target]

        feat = ext_feats.add(ext_input)
        return {
            "feature_name": feat.name,
            "sketch": sketch.name,
            "height": height,
            "operation": operation,
            "direction": direction,
            "target_body": target_body,
        }

    def revolve(
        self,
        angle: float,
        profile_index: int = 0,
        axis_origin_x: float = 0,
        axis_origin_y: float = 0,
        axis_origin_z: float = 0,
        axis_direction_x: float = 1,
        axis_direction_y: float = 0,
        axis_direction_z: float = 0,
        operation: str = "new_body",
        sketch_name: str | None = None,
        target_body: str | None = None,
    ):
        """Revolve the profile about ``axis_origin`` + ``axis_direction``.

        Both are **model space** (cm).  The axis is one of Fusion's own
        construction axes when it is world-aligned and passes through the model
        origin; otherwise it is a construction line in the profile's sketch, so
        it must be coplanar with the profile — an axis leaving the sketch plane
        is refused rather than silently projected onto it.

        ``target_body`` names the body a cut/join/intersect applies to; without
        it Fusion applies the operation to every body the profile reaches.
        """
        root = self._root()
        # The operation first: a mistyped one invalidates everything after it.
        feature_operation = self._operation_type(operation)
        sketch = self._sketch(sketch_name)
        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        # Read the frame before anything is created, so a failure here cannot
        # report an error for geometry that was already built.
        frame = self._sketch_frame(sketch)
        # Before the axis line exists: a refused target must leave no geometry.
        target = self._resolve_target_body(target_body, operation)

        axis_entity, axis_report = self._revolve_axis(
            root,
            sketch,
            frame,
            (axis_origin_x, axis_origin_y, axis_origin_z),
            (axis_direction_x, axis_direction_y, axis_direction_z),
        )

        # After the axis line, never before: adding geometry to the sketch
        # invalidates the profile proxy, and Fusion then rejects the revolve
        # with "invalid profile(s) for Revolve Feature".
        profile = sketch.profiles.item(profile_index)

        rev_feats = root.features.revolveFeatures
        rev_input = rev_feats.createInput(profile, axis_entity, feature_operation)

        angle_val = adsk.core.ValueInput.createByString(f"{angle} deg")
        rev_input.setAngleExtent(False, angle_val)
        if target is not None:
            rev_input.participantBodies = [target]

        feat = rev_feats.add(rev_input)
        return {
            "feature_name": feat.name,
            "sketch": sketch.name,
            "angle": angle,
            "operation": operation,
            "target_body": target_body,
            **axis_report,
        }

    @staticmethod
    def _world_axis(root, direction):
        """Fusion's own construction axis for a world-aligned direction, if any."""
        dx, dy, dz = direction
        scale = max(abs(dx), abs(dy), abs(dz))
        if scale == 0:
            return None
        ux, uy, uz = dx / scale, dy / scale, dz / scale
        if abs(ux) > 0.99 and abs(uy) < 0.01 and abs(uz) < 0.01:
            return root.xConstructionAxis
        if abs(uy) > 0.99 and abs(ux) < 0.01 and abs(uz) < 0.01:
            return root.yConstructionAxis
        if abs(uz) > 0.99 and abs(ux) < 0.01 and abs(uy) < 0.01:
            return root.zConstructionAxis
        return None

    @classmethod
    def _revolve_axis(cls, root, sketch, frame, origin, direction):
        """The revolve axis as an entity, plus where it landed in model space.

        ``origin`` and ``direction`` are model space.  A sketch line can only
        live in the sketch's own plane, so the axis line is built from points
        converted with ``modelToSketchSpace`` — passing model coordinates
        straight through displaced the axis by the plane's offset (0.4.0) and
        left it unrotated on a yz/xz sketch.
        """
        dx, dy, dz = direction
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length == 0:
            raise RuntimeError(
                "Invalid input: revolve axis direction is zero-length — pass "
                "axis_direction_x/y/z"
            )
        # A 10 cm probe along the unit direction: long enough to be visible in
        # the sketch, and independent of the magnitude the caller passed.
        ux, uy, uz = dx / length, dy / length, dz / length

        world = cls._world_axis(root, direction)
        if world is not None and max(abs(v) for v in origin) <= 1e-9:
            return world, {
                "axis_model_start": [0.0, 0.0, 0.0],
                "axis_model_end": [ux * 10, uy * 10, uz * 10],
            }

        start = sketch.modelToSketchSpace(adsk.core.Point3D.create(*origin))
        end = sketch.modelToSketchSpace(
            adsk.core.Point3D.create(
                origin[0] + ux * 10, origin[1] + uy * 10, origin[2] + uz * 10
            )
        )
        # The direction, in the sketch's frame: a nonzero normal component means
        # the axis cannot be a construction line, and projecting it would turn
        # the profile about an axis the caller never asked for.
        sdx, sdy, sdz = end.x - start.x, end.y - start.y, end.z - start.z
        span = math.sqrt(sdx * sdx + sdy * sdy + sdz * sdz)
        if abs(sdz) > 1e-6 * span:
            off_plane = math.degrees(math.asin(min(1.0, abs(sdz) / span)))
            raise RuntimeError(
                "Invalid input: the revolve axis does not lie in the sketch "
                f"plane — axis_direction is {off_plane:.3g}\u00b0 out of it. A "
                "revolve axis built from axis_origin/axis_direction is a "
                "construction line in the profile's sketch, so it must be "
                "coplanar with the profile; sketch the profile on a plane that "
                "contains the axis, or pass a world-aligned direction."
            )

        snapped = abs(start.z) > 1e-6
        start_pt = adsk.core.Point3D.create(start.x, start.y, 0)
        end_pt = adsk.core.Point3D.create(start.x + sdx, start.y + sdy, 0)
        line = sketch.sketchCurves.sketchLines.addByTwoPoints(start_pt, end_pt)
        line.isConstruction = True

        # Annotated because the values are three different types - two lists, a
        # bool and a string - and an inferred dict[str, list] makes the later
        # writes look wrong to a type checker (they are not; it is a report).
        report: dict[str, object] = {
            "axis_model_start": cls._model_point(frame, start_pt.x, start_pt.y),
            "axis_model_end": cls._model_point(frame, end_pt.x, end_pt.y),
        }
        if snapped:
            report["axis_snapped_to_sketch_plane"] = True
            report["note"] = (
                "The requested axis origin is not on the profile's sketch "
                "plane. A construction line cannot leave it, so the offset "
                "along the plane normal was dropped and the axis lies in the "
                "sketch plane — see axis_model_start/axis_model_end for where "
                "it actually runs."
            )
        return line, report

    def sweep(
        self,
        profile_index: int,
        path_sketch_name: str,
        path_curve_index: int = 0,
        operation: str = "new_body",
        sketch_name: str | None = None,
        target_body: str | None = None,
    ):
        """Sweep a profile along a path curve.

        ``target_body`` names the body a cut/join/intersect applies to; without
        it Fusion applies the operation to every body the sweep reaches.
        """
        root = self._root()
        # The operation first: a mistyped one invalidates everything after it.
        feature_operation = self._operation_type(operation)
        sketch = self._sketch(sketch_name)
        path_sketch = self._sketch_by_name(path_sketch_name)

        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)
        target = self._resolve_target_body(target_body, operation)

        path_curves = list(path_sketch.sketchCurves)
        path_curve = self._curve_by_index(
            path_sketch, path_curves, path_curve_index, "path_curve_index"
        )

        path = root.features.createPath(path_curve)

        sweep_feats = root.features.sweepFeatures
        sweep_input = sweep_feats.createInput(profile, path, feature_operation)
        if target is not None:
            sweep_input.participantBodies = [target]
        feat = sweep_feats.add(sweep_input)
        return {
            "feature_name": feat.name,
            "sketch": sketch.name,
            "operation": operation,
            "target_body": target_body,
        }

    def loft(
        self,
        profile_sketch_names: list,
        operation: str = "new_body",
        target_body: str | None = None,
    ):
        """Loft through the first profile of each named sketch.

        ``target_body`` names the body a cut/join/intersect applies to; without
        it Fusion applies the operation to every body the loft reaches.
        """
        root = self._root()
        # The operation first: a mistyped one invalidates everything after it.
        feature_operation = self._operation_type(operation)
        if len(profile_sketch_names) < 2:
            raise RuntimeError(
                "Invalid input: a loft needs at least two profiles — got "
                f"{len(profile_sketch_names)}"
            )
        target = self._resolve_target_body(target_body, operation)
        loft_feats = root.features.loftFeatures
        loft_input = loft_feats.createInput(feature_operation)

        for sketch_name in profile_sketch_names:
            sketch = self._sketch_by_name(sketch_name)
            if sketch.profiles.count == 0:
                raise RuntimeError(f"No profiles in sketch '{sketch_name}'")
            loft_input.loftSections.add(sketch.profiles.item(0))

        if target is not None:
            loft_input.participantBodies = [target]
        feat = loft_feats.add(loft_input)
        return {
            "feature_name": feat.name,
            "operation": operation,
            "profile_count": len(profile_sketch_names),
            "target_body": target_body,
        }

    def fillet(
        self,
        radius: float,
        body_name: str | None = None,
        body_index: int = 0,
        edge_selection: str = "all",
        edge_indices: list[int] | None = None,
        edge_points: list | None = None,
        edge_tolerance: float = 0.1,
    ):
        root = self._root()
        body = self._body_or_index(body_name, body_index)
        edges = self._select_edges(
            body,
            edge_selection,
            indices=edge_indices,
            points=edge_points,
            tolerance=edge_tolerance,
        )

        fillets = root.features.filletFeatures
        inp = fillets.createInput()
        inp.addConstantRadiusEdgeSet(
            edges, adsk.core.ValueInput.createByReal(radius), True
        )
        feat = fillets.add(inp)
        return {"feature_name": feat.name, "radius": radius, "edges_count": edges.count}

    def chamfer(
        self,
        distance: float,
        body_name: str | None = None,
        body_index: int = 0,
        edge_selection: str = "all",
        edge_indices: list[int] | None = None,
        edge_points: list | None = None,
        edge_tolerance: float = 0.1,
    ):
        root = self._root()
        body = self._body_or_index(body_name, body_index)
        edges = self._select_edges(
            body,
            edge_selection,
            indices=edge_indices,
            points=edge_points,
            tolerance=edge_tolerance,
        )

        chamfers = root.features.chamferFeatures
        inp = chamfers.createInput(edges, True)
        inp.setToEqualDistance(adsk.core.ValueInput.createByReal(distance))
        feat = chamfers.add(inp)
        return {
            "feature_name": feat.name,
            "distance": distance,
            "edges_count": edges.count,
        }

    def shell(
        self,
        thickness: float,
        body_name: str | None = None,
        body_index: int = 0,
        face_selection: str = "top",
    ):
        # Judged before the body is looked up: a wall Fusion cannot honour is the
        # caller's value, not the design's problem.  NaN and infinity are deliverable
        # over the socket (json.loads accepts both), and Fusion answers a wall of
        # zero or less with "3 : Some input argument is invalid." (measured on 2706).
        # The neighbouring "2 : InternalValidationError" comes from *reading*
        # insideThickness before it is set, not from a bad wall.
        try:
            thickness = _param_units.require_finite(thickness)
        except ValueError as exc:
            # require_finite's message is shaped to classify as INVALID_INPUT; the
            # field is prepended here because it is the caller's only clue.
            raise ValueError(f"thickness must be finite, in cm: {exc}") from exc
        # ``require_finite`` passes a non-number through on purpose, and comparing
        # one raises TypeError, which classifies as UNKNOWN with no hints - so the
        # type is judged here.  A bool is not a distance, whatever ``True == 1`` says.
        if isinstance(thickness, bool) or not isinstance(thickness, (int, float)):
            raise RuntimeError(
                f"thickness must be a positive number in cm, got {thickness!r}"
            )
        if thickness <= 0:
            raise RuntimeError(
                f"thickness must be a positive number in cm, got {thickness!r} - a "
                "shell removes material, so the wall has to be a real distance"
            )

        root = self._root()
        body = self._body_or_index(body_name, body_index)

        if face_selection not in ("top", "bottom"):
            raise RuntimeError(
                f"Unknown face_selection '{face_selection}' — use top/bottom"
            )
        faces = adsk.core.ObjectCollection.create()
        for face in self._faces_in_extreme_plane(body, face_selection):
            faces.add(face)

        if faces.count == 0:
            raise RuntimeError(f"No faces matched '{face_selection}'")

        shells = root.features.shellFeatures
        # The faces to remove go IN the input collection, and the body does not:
        # Fusion derives the body from the faces and refuses a face alongside the
        # body that owns it ("Fails if any faces are input, and the owning bodies
        # of the faces are also input").  There is no `facesToRemove` property on
        # ShellFeatureInput - assigning one attaches a plain attribute to the SWIG
        # wrapper, which reads back as if stored and never reaches Fusion, so the
        # feature closed the cavity and this handler reported a face removed.
        # Measured on 2706: a body plus that phantom attribute gave 200 -> 52.544
        # cm3 with the top intact; the faces alone give 200 -> 34.112, top open.
        # isTangentChain stays False because the selector has already chosen the
        # faces, and tangent propagation would open more than `faces_removed` says.
        inp = shells.createInput(faces, False)
        inp.insideThickness = adsk.core.ValueInput.createByReal(thickness)
        feat = shells.add(inp)
        return {
            "feature_name": feat.name,
            "thickness": thickness,
            "faces_removed": faces.count,
        }

    def mirror(
        self, mirror_plane: str, body_name: str | None = None, body_index: int = 0
    ):
        root = self._root()
        body = self._body_or_index(body_name, body_index)

        entities = adsk.core.ObjectCollection.create()
        entities.add(body)

        mirrors = root.features.mirrorFeatures
        inp = mirrors.createInput(entities, self._construction_plane(mirror_plane))
        feat = mirrors.add(inp)
        return {"feature_name": feat.name, "mirror_plane": mirror_plane}

    def create_hole(
        self,
        diameter: float,
        depth: float,
        body_name: str | None = None,
        body_index: int = 0,
        face_selection: str = "top",
        center_x: float = 0,
        center_y: float = 0,
    ):
        root = self._root()
        body = self._body_or_index(body_name, body_index)

        # Find the target face.
        # Comparing bounding boxes is not enough: the side faces of a box reach
        # the body's max Z too, so the first "hit" is usually a vertical face.
        # Require a near-horizontal planar face that points up (or down).
        if face_selection not in ("top", "bottom"):
            raise RuntimeError(f"Unknown face_selection '{face_selection}'")
        want_up = face_selection == "top"

        target_face = None
        best_key = None
        for face in body.faces:
            if adsk.core.Plane.cast(face.geometry) is None:
                continue
            # Use the evaluator: it reports the face's outward normal, whereas
            # the underlying plane's normal ignores the face's orientation.
            ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if not ok or not _hole_geom.is_horizontal_face(normal.z, want_up):
                continue
            # Rank on the face's own extreme Z, not on an arbitrary point on
            # it: within the tilt tolerance the two are not the same.
            fbox = face.boundingBox
            edge_z = fbox.maxPoint.z if want_up else fbox.minPoint.z
            key = _hole_geom.face_rank_key(edge_z, face.area, want_up)
            if best_key is None or key > best_key:
                best_key, target_face = key, face

        if target_face is None:
            raise _hints.Refusal(
                "GEOMETRY_UNSUPPORTED",
                f"No near-horizontal {face_selection}-facing planar face on "
                f"'{body.name}'",
                hints=(
                    "Pick a body whose faces include a near-horizontal plane (top "
                    "or bottom).",
                ),
            )

        # Place the hole centre. center_x / center_y are model-space XY, so the
        # caller does not have to know the sketch's own coordinate system. Solve
        # the face's plane for Z rather than reusing an arbitrary point on it.
        plane = adsk.core.Plane.cast(target_face.geometry)
        n, o = plane.normal, plane.origin
        center_z = _hole_geom.plane_z_at(
            (n.x, n.y, n.z), (o.x, o.y, o.z), center_x, center_y
        )
        sketch = root.sketches.add(target_face)
        sketch_pt = sketch.sketchPoints.add(
            sketch.modelToSketchSpace(
                adsk.core.Point3D.create(center_x, center_y, center_z)
            )
        )

        # createSimpleInput() takes the DIAMETER -- "A ValueInput object that
        # defines the diameter of the hole" -- not the radius.
        holes = root.features.holeFeatures
        hole_input = holes.createSimpleInput(
            adsk.core.ValueInput.createByReal(diameter)
        )
        hole_input.setPositionBySketchPoint(sketch_pt)
        hole_input.setDistanceExtent(adsk.core.ValueInput.createByReal(depth))
        # Without this the hole cuts every body it happens to intersect.
        # The property takes a plain list, not an ObjectCollection.
        hole_input.participantBodies = [body]

        feat = holes.add(hole_input)
        # No "cut_bodies" here: Feature.bodies reports the participants this call
        # set above, not what was actually cut (measured on 2706 - a cut naming a
        # body it never reaches still reports that body), so the field echoed the
        # input dressed as a result. The measured answer to "did it cut?" is the
        # envelope's own deltas.
        return {
            "feature_name": feat.name,
            "diameter": diameter,
            "depth": depth,
            "actual_diameter": feat.holeDiameter.value,
            # Where the request resolved to, not a measurement of the feature.
            "resolved_center": [center_x, center_y, center_z],
        }

    def rectangular_pattern(
        self,
        body_name: str,
        x_count: int = 1,
        x_spacing: float = 1.0,
        y_count: int = 1,
        y_spacing: float = 1.0,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        patterns = root.features.rectangularPatternFeatures
        inp = patterns.createInput(
            bodies,
            root.xConstructionAxis,
            adsk.core.ValueInput.createByReal(x_count),
            adsk.core.ValueInput.createByReal(x_spacing),
            adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
        )
        inp.setDirectionTwo(
            root.yConstructionAxis,
            adsk.core.ValueInput.createByReal(y_count),
            adsk.core.ValueInput.createByReal(y_spacing),
        )
        feat = patterns.add(inp)
        return {"feature_name": feat.name, "x_count": x_count, "y_count": y_count}

    def circular_pattern(
        self, body_name: str, count: int, axis: str = "z", total_angle: float = 360
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        patterns = root.features.circularPatternFeatures
        inp = patterns.createInput(bodies, self._construction_axis(axis))
        inp.quantity = adsk.core.ValueInput.createByReal(count)
        inp.totalAngle = adsk.core.ValueInput.createByString(f"{total_angle} deg")
        feat = patterns.add(inp)
        return {"feature_name": feat.name, "count": count, "total_angle": total_angle}

    def create_thread(
        self,
        body_name: str,
        face_index: int,
        is_internal: bool = False,
        thread_type: str = "ISO Metric profile",
        thread_designation: str = "M10x1.5",
        thread_class: str | None = None,
        is_modeled: bool = False,
        is_full_length: bool = True,
        thread_length: float | None = None,
        allow_resize: bool = False,
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        face = body.faces.item(face_index)
        face_diameter = self._cylindrical_diameter(face)

        threads = root.features.threadFeatures
        # A ThreadInfo, not the ThreadDataQuery: createInput takes the former and
        # raises "argument 3 of type ThreadInfo" for the latter (measured on 2706).
        # The query carries no designation or class at all - assigning them to it
        # writes plain Python attributes Fusion never reads.
        # ISO 965 assigns 6g to external threads and 6H to internal ones, so the
        # default follows is_internal rather than naming one class for both. An
        # explicit thread_class always wins.
        if thread_class is None:
            thread_class = "6H" if is_internal else "6g"
        info = adsk.fusion.ThreadInfo.create(
            False, is_internal, thread_type, thread_designation, thread_class, True
        )
        thread_diameter = self._named_thread_diameter(info, is_internal)
        if (
            not allow_resize
            and thread_diameter > 0
            and not self._thread_fits(face_diameter, thread_diameter)
        ):
            raise RuntimeError(
                self._mismatch_message(
                    face_diameter,
                    thread_diameter,
                    thread_designation,
                    is_internal,
                    thread_type,
                )
            )

        inp = threads.createInput(face, info)
        inp.isModeled = is_modeled
        inp.isFullLength = is_full_length
        if not is_full_length and thread_length:
            inp.threadLength = adsk.core.ValueInput.createByReal(thread_length)

        feat = threads.add(inp)
        return {
            "feature_name": feat.name,
            "thread_type": thread_type,
            "thread_designation": thread_designation,
            "thread_class": thread_class,
            "is_internal": is_internal,
            "face_diameter_cm": face_diameter,
            "thread_diameter_cm": thread_diameter,
        }

    @staticmethod
    def _cylindrical_diameter(face) -> float:
        """The diameter a thread could be cut on this face, in centimetres.

        ``Cylinder.cast`` answers None for anything else, which is Fusion's own test
        for "can this face be threaded" - a thread needs a cylindrical face, and the
        diameter is what its designation has to match.
        """
        cylinder = adsk.core.Cylinder.cast(face.geometry)
        if cylinder is None:
            raise RuntimeError(
                "That face is not cylindrical, so no thread can be cut on it."
            )
        return float(cylinder.radius) * 2.0

    @staticmethod
    def _named_thread_diameter(info, is_internal: bool) -> float:
        """What the designation says the body's diameter should be, in centimetres.

        External threads are cut on the major diameter; an internal thread's hole is
        tapped to the minor one.  Read from the ``ThreadInfo`` Fusion built from the
        designation, so no table of thread sizes lives here.
        """
        return float(info.minorDiameter if is_internal else info.majorDiameter)

    @staticmethod
    def _thread_fits(face_diameter: float, thread_diameter: float) -> bool:
        """Whether the face is the size the designation describes, near enough.

        A *relative* band alone is wrong: callers model the nominal diameter while
        Fusion reports the middle of the tolerance band, and the gap between the two
        is roughly constant in absolute terms - 0.073 mm on an M3, 0.116 mm on an M6,
        0.209 mm on an M20 - so a percentage gate tightens as the thread shrinks and
        would refuse Ø3.00 mm stock against M3x0.5, the canonical small-thread call.
        The floor keeps that accepted; Ø20 against M6 is 14.1 cm apart and still
        refused.
        """
        return abs(face_diameter - thread_diameter) <= max(
            0.02 * thread_diameter, 0.012
        )

    @staticmethod
    def _recommended_thread(
        face_diameter: float, is_internal: bool, thread_type: str
    ) -> tuple[bool, str, str]:
        """Fusion's own answer to "what thread belongs on this diameter?".

        ``ThreadDataQuery.create`` is the current accessor - ``threadFeatures.
        threadDataQuery`` is retired - and ``recommendThreadData`` returns
        ``(ok, designation, class)`` with the out-parameters folded into the tuple.
        The callers compare the designation as a *string*, which is why this returns
        the pieces rather than a sentence.
        """
        query = adsk.fusion.ThreadDataQuery.create(False)
        ok, designation, thread_class = query.recommendThreadData(
            face_diameter, is_internal, thread_type
        )
        return bool(ok), str(designation), str(thread_class)

    def _mismatch_message(
        self,
        face_diameter: float,
        thread_diameter: float,
        designation: str,
        is_internal: bool,
        thread_type: str,
    ) -> str:
        """What to tell a caller whose face and designation disagree.

        The message names the diameter it measured, so the answer says what was seen
        rather than only what was expected.  It does not recommend the designation it
        has just refused: the recommendation is the nearest standard thread, which on
        nominal-sized stock *is* the one asked for.  And ``is_internal`` may be the
        wrong flag rather than the designation, which is a different repair.
        """
        parts = [
            f"The face is {face_diameter * 10:.2f} mm across but {designation} is "
            f"{thread_diameter * 10:.2f} mm: Fusion would resize the body to match "
            "the thread."
        ]
        ok, recommended, recommended_class = self._recommended_thread(
            face_diameter, is_internal, thread_type
        )
        if ok and recommended != designation:
            parts.append(f"{recommended} ({recommended_class}) matches that diameter.")

        # A wrong flag is diagnosed without building a second ThreadInfo: if asking
        # the *other* polarity for this diameter returns the designation the caller
        # already asked for, the flag is the mistake, not the thread.
        ok_other, recommended_other, _ = self._recommended_thread(
            face_diameter, not is_internal, thread_type
        )
        if ok_other and recommended_other == designation:
            kind = "internal" if not is_internal else "external"
            parts.append(
                f"This face sizes up as {kind} ({designation}) - check "
                f"is_internal={str(not is_internal).lower()}."
            )

        parts.append("Pass allow_resize=true to accept the resize.")
        return " ".join(parts)

    def draft_faces(
        self,
        body_name: str,
        angle: float,
        face_selection: str = "vertical",
        pull_direction_plane: str = "xy",
        is_tangent_chain: bool = True,
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        faces = self._select_faces(body, face_selection)

        drafts = root.features.draftFeatures
        # createInput wants a BRepFace array and three arguments; the angle is
        # set on the input object afterwards, not passed in.
        inp = drafts.createInput(
            [faces.item(i) for i in range(faces.count)],
            self._construction_plane(pull_direction_plane),
            is_tangent_chain,
        )
        inp.setSingleAngle(False, adsk.core.ValueInput.createByString(f"{angle} deg"))
        feat = drafts.add(inp)
        return {"feature_name": feat.name, "angle": angle, "face_count": faces.count}

    def split_body(
        self,
        body_name: str,
        splitting_plane: str = "xy",
        splitting_body: str | None = None,
        extend_tool: bool = True,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        splits = root.features.splitBodyFeatures
        if splitting_body:
            tool = self._body_by_name(splitting_body)
            inp = splits.createInput(body, tool, extend_tool)
        else:
            inp = splits.createInput(
                body, self._construction_plane(splitting_plane), extend_tool
            )
        feat = splits.add(inp)
        if splitting_body:
            return {"feature_name": feat.name, "splitting_body": splitting_body}
        return {"feature_name": feat.name, "splitting_plane": splitting_plane}

    def split_face(
        self,
        body_name: str,
        face_indices: list | None = None,
        splitting_plane: str = "xy",
        extend_tool: bool = True,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        faces = adsk.core.ObjectCollection.create()
        if face_indices:
            for idx in face_indices:
                faces.add(body.faces.item(idx))
        else:
            for face in body.faces:
                faces.add(face)

        splits = root.features.splitFaceFeatures
        inp = splits.createInput(
            faces, self._construction_plane(splitting_plane), extend_tool
        )
        feat = splits.add(inp)
        return {"feature_name": feat.name}

    def offset_faces(
        self,
        body_name: str,
        distance: float,
        face_selection: str = "top",
        face_indices: list | None = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        if face_indices:
            faces = adsk.core.ObjectCollection.create()
            for idx in face_indices:
                faces.add(body.faces.item(idx))
        else:
            faces = self._select_faces(body, face_selection)

        offsets = root.features.offsetFeatures
        inp = offsets.createInput(
            faces,
            adsk.core.ValueInput.createByReal(distance),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        )
        feat = offsets.add(inp)
        return {"feature_name": feat.name, "distance": distance}

    def scale_body(
        self,
        body_name: str,
        scale: float,
        scale_x: float | None = None,
        scale_y: float | None = None,
        scale_z: float | None = None,
        anchor_x: float = 0,
        anchor_y: float = 0,
        anchor_z: float = 0,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        anchor = adsk.core.Point3D.create(anchor_x, anchor_y, anchor_z)

        scales = root.features.scaleFeatures
        # Shipped: createInput(inputEntities, point, scaleFactor) - three
        # arguments, the third the uniform factor.  A per-axis scale is that
        # same input with setToNonUniform() called on it afterwards.
        inp = scales.createInput(
            bodies, anchor, adsk.core.ValueInput.createByReal(scale)
        )
        non_uniform = (
            scale_x is not None and scale_y is not None and scale_z is not None
        )
        if non_uniform:
            inp.setToNonUniform(
                adsk.core.ValueInput.createByReal(scale_x),
                adsk.core.ValueInput.createByReal(scale_y),
                adsk.core.ValueInput.createByReal(scale_z),
            )
        feat = scales.add(inp)
        if non_uniform:
            return {
                "feature_name": feat.name,
                "scale_x": scale_x,
                "scale_y": scale_y,
                "scale_z": scale_z,
            }
        return {"feature_name": feat.name, "scale": scale}

    def suppress_feature(self, feature_name: str):
        return self._set_suppressed(feature_name, True)

    def unsuppress_feature(self, feature_name: str):
        return self._set_suppressed(feature_name, False)

    def rename_body(self, body_name: str, new_name: str):
        body = self._body_by_name(body_name)
        old_name = body.name
        body.name = new_name
        return {"renamed": True, "old_name": old_name, "new_name": new_name}

    def move_body(self, body_name: str, x: float = 0, y: float = 0, z: float = 0):
        root = self._root()
        body = self._body_by_name(body_name)

        move_feats = root.features.moveFeatures
        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(x, y, z)

        inp = move_feats.createInput(bodies, transform)
        feat = move_feats.add(inp)
        return {"feature_name": feat.name, "body": body_name, "translation": [x, y, z]}

    def boolean_operation(
        self,
        target_body: str,
        tool_body: str,
        operation: str = "join",
        keep_tool: bool = False,
    ):
        root = self._root()
        target = self._body_by_name(target_body)
        tool = self._body_by_name(tool_body)

        combine_feats = root.features.combineFeatures
        tool_coll = adsk.core.ObjectCollection.create()
        tool_coll.add(tool)

        op_map = {
            "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
            "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
            "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }
        op = op_map.get(operation)
        if op is None:
            raise RuntimeError(
                f"Unknown boolean op '{operation}' — use join/cut/intersect"
            )

        inp = combine_feats.createInput(target, tool_coll)
        inp.operation = op
        # Fusion consumes the tool body unless told otherwise.  The property is
        # the whole implementation: nothing is copied or recreated here, so a
        # caller that wants the cutter back gets Fusion's own behaviour.
        inp.isKeepToolBodies = keep_tool
        feat = combine_feats.add(inp)
        return {
            "feature_name": feat.name,
            "operation": operation,
            "target": target_body,
            "tool": tool_body,
            "keep_tool": keep_tool,
        }
