"""Sketch commands: create a sketch, then draw into it.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

import math
from typing import ClassVar

from . import fusion_api as adsk
from . import hints as _hints
from . import rules as _rules


class SketchCommands:
    @staticmethod
    def _plane_point(x: float, y: float):
        """A sketch-space point lying **on** the sketch plane.

        ``SketchCurves`` interpret points in the sketch's own coordinate
        system, so a z supplied by a caller is added to whatever offset the
        plane already carries: on a sketch created with ``z_offset=-0.65``,
        drawing with ``center_z=-0.65`` puts the curve at model z=-1.30. Sketch
        curves are planar, so the normal component is dropped rather than being
        applied twice.
        """
        return adsk.core.Point3D.create(x, y, 0)

    def create_sketch(self, plane: str = "xy", z_offset: float | None = None):
        root = self._root()

        if z_offset is not None and z_offset != 0:
            # Create an offset construction plane
            planes = root.constructionPlanes
            plane_input = planes.createInput()
            offset_val = adsk.core.ValueInput.createByReal(z_offset)
            plane_input.setByOffset(self._construction_plane(plane), offset_val)
            cp = planes.add(plane_input)
            sketch = root.sketches.add(cp)
        else:
            sketch = root.sketches.add(self._construction_plane(plane))

        return {"sketch_name": sketch.name, "plane": plane, "z_offset": z_offset}

    def draw_rectangle(
        self,
        width: float,
        height: float,
        origin_x: float = 0,
        origin_y: float = 0,
        origin_z: float = 0,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        frame = self._sketch_frame(sketch)
        p1 = self._plane_point(origin_x, origin_y)
        p2 = self._plane_point(origin_x + width, origin_y + height)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
        return self._report_dropped_z(
            {
                "sketch": sketch.name,
                "width": width,
                "height": height,
                "model_origin": self._model_point(frame, origin_x, origin_y),
            },
            origin_z,
        )

    def draw_circle(
        self,
        radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        frame = self._sketch_frame(sketch)
        c = self._plane_point(center_x, center_y)
        sketch.sketchCurves.sketchCircles.addByCenterRadius(c, radius)
        return self._report_dropped_z(
            {
                "sketch": sketch.name,
                "radius": radius,
                "center": [center_x, center_y, center_z],
                "model_center": self._model_point(frame, center_x, center_y),
            },
            center_z,
        )

    def draw_line(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        start_z: float = 0,
        end_z: float = 0,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        frame = self._sketch_frame(sketch)
        sp = self._plane_point(start_x, start_y)
        ep = self._plane_point(end_x, end_y)
        sketch.sketchCurves.sketchLines.addByTwoPoints(sp, ep)
        return self._report_dropped_z(
            {
                "sketch": sketch.name,
                "start": [start_x, start_y, start_z],
                "end": [end_x, end_y, end_z],
                "model_start": self._model_point(frame, start_x, start_y),
                "model_end": self._model_point(frame, end_x, end_y),
            },
            start_z,
            end_z,
        )

    def draw_arc(
        self,
        center_x: float,
        center_y: float,
        start_x: float,
        start_y: float,
        sweep_angle: float,
        center_z: float = 0,
        start_z: float = 0,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        frame = self._sketch_frame(sketch)
        center = self._plane_point(center_x, center_y)
        start = self._plane_point(start_x, start_y)
        sweep_rad = math.radians(sweep_angle)
        sketch.sketchCurves.sketchArcs.addByCenterStartSweep(center, start, sweep_rad)
        return self._report_dropped_z(
            {
                "sketch": sketch.name,
                "sweep_angle": sweep_angle,
                "model_center": self._model_point(frame, center_x, center_y),
            },
            center_z,
            start_z,
        )

    def draw_spline(
        self,
        spline_type: str,
        points: list,
        degree: int = 3,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        frame = self._sketch_frame(sketch)
        pts = adsk.core.ObjectCollection.create()
        for p in points:
            pts.add(self._plane_point(p[0], p[1]))

        if spline_type == "fit_points":
            sketch.sketchCurves.sketchFittedSplines.add(pts)
        else:  # control_points
            sketch.sketchCurves.sketchControlPointSplines.add(pts, degree)
        dropped = [p[2] for p in points if len(p) > 2 and p[2]]
        return self._report_dropped_z(
            {
                "sketch": sketch.name,
                "spline_type": spline_type,
                "points_count": len(points),
                "model_points": [self._model_point(frame, p[0], p[1]) for p in points],
            },
            *dropped,
        )

    def create_polygon(
        self,
        sides: int,
        radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        frame = self._sketch_frame(sketch)
        # Draw inscribed polygon. Deferring the solve matters here because Fusion
        # re-solves the whole sketch after every entity insert.
        previous_deferred = sketch.isComputeDeferred
        sketch.isComputeDeferred = True
        try:
            for i in range(sides):
                angle1 = 2 * math.pi * i / sides
                angle2 = 2 * math.pi * (i + 1) / sides
                p1 = self._plane_point(
                    center_x + radius * math.cos(angle1),
                    center_y + radius * math.sin(angle1),
                )
                p2 = self._plane_point(
                    center_x + radius * math.cos(angle2),
                    center_y + radius * math.sin(angle2),
                )
                sketch.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
        finally:
            sketch.isComputeDeferred = previous_deferred

        return self._report_dropped_z(
            {
                "sketch": sketch.name,
                "sides": sides,
                "radius": radius,
                "model_center": self._model_point(frame, center_x, center_y),
            },
            center_z,
        )

    def draw_circles(
        self,
        count: int,
        radius: float,
        spacing: float,
        axis: str = "x",
        center_x: float = 0,
        center_y: float = 0,
        sketch_name: str | None = None,
    ):
        """Add *count* evenly spaced circles to one sketch in a single solve.

        The default is the last sketch; *sketch_name* targets an older one.
        Fusion re-solves the sketch after every entity insert, so adding N
        circles one command at a time is superlinear in N. Deferring the solve
        across the inserts and restoring the previous value afterwards removes
        that: measured at 100 circles, 68 ms against 912 ms. The restore is in a
        ``finally`` so a bad parameter cannot leave the sketch unsolved.

        ``count`` and ``axis`` are judged by the schema too: the gate refuses a
        value it forbids first for MCP callers, and the checks below are the
        direct-wire defence D12 requires.
        """
        # The gate refuses these first for MCP callers, and a client on :9876 can
        # reach this method without it: count=-5 would report added: -5, and
        # axis="q" would put every circle on one point.
        if count < 1:
            raise _hints.Refusal(
                "INVALID_INPUT",
                "count must be at least 1",
                hints=("Pass count as a whole number of circles, at least 1.",),
            )
        if axis not in ("x", "y"):
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Unknown axis: {axis} - use x or y",
                hints=("Pass axis='x' or axis='y'.",),
            )

        sketch = self._sketch(sketch_name)
        previous_deferred = sketch.isComputeDeferred
        sketch.isComputeDeferred = True
        try:
            for i in range(count):
                cx = center_x + (i * spacing if axis == "x" else 0.0)
                cy = center_y + (i * spacing if axis == "y" else 0.0)
                sketch.sketchCurves.sketchCircles.addByCenterRadius(
                    self._plane_point(cx, cy), radius
                )
        finally:
            sketch.isComputeDeferred = previous_deferred

        return {
            "sketch": sketch.name,
            "added": count,
            "total_curves": sketch.sketchCurves.count,
            "radius": radius,
            "spacing": spacing,
            "axis": axis,
        }

    #: What each constraint resolves: the kind of ``entity_one`` (a curve for every
    #: type except ``midpoint``, whose first entity is a sketch point), and whether
    #: a second entity is needed.  A table because Fusion accepts a missing second
    #: entity: ``addParallel(e1, None)`` reaches the API and reports ``ok: true``.
    _CONSTRAINT_ENTITIES: ClassVar[dict[str, tuple[str, bool]]] = {
        "coincident": ("curve", True),
        "parallel": ("curve", True),
        "perpendicular": ("curve", True),
        "tangent": ("curve", True),
        "equal": ("curve", True),
        "fix": ("curve", False),
        "horizontal": ("curve", False),
        "vertical": ("curve", False),
        "concentric": ("curve", True),
        "collinear": ("curve", True),
        "smooth": ("curve", True),
        "midpoint": ("point", True),
        "symmetry": ("curve", True),
    }

    def add_constraint(
        self,
        constraint_type: str,
        entity_one: int | None = None,
        entity_two: int | None = None,
        symmetry_line: int | None = None,
        sketch_name: str | None = None,
    ):
        # symmetry is the one type that needs a third entity, and its mirror line is a
        # parameter of its own: judged here, before the sketch is read, so mock mode
        # answers the same sentence instead of rehearsing a call Fusion refuses.
        if refusal := _rules.symmetry_line_refusal(
            {"constraint_type": constraint_type, "symmetry_line": symmetry_line}
        ):
            raise refusal

        sketch = self._sketch(sketch_name)
        constraints = sketch.geometricConstraints
        curves = list(sketch.sketchCurves)

        needs = self._CONSTRAINT_ENTITIES.get(constraint_type)
        if needs is None:
            raise RuntimeError(
                f"Unknown constraint type: {constraint_type} (expected one of "
                + ", ".join(sorted(self._CONSTRAINT_ENTITIES))
                + ")"
            )
        first_kind, needs_two = needs

        # entity_one is a curve for every type except midpoint, whose first entity
        # is a sketch POINT - resolving it against the curves named the wrong item.
        point = None
        e1 = None
        if entity_one is not None:
            if first_kind == "point":
                point = self._point_by_index(
                    sketch, sketch.sketchPoints, entity_one, "entity_one"
                )
            else:
                e1 = self._curve_by_index(sketch, curves, entity_one, "entity_one")
        e2 = (
            self._curve_by_index(sketch, curves, entity_two, "entity_two")
            if entity_two is not None
            else None
        )

        # Refuse before the call, not inside Fusion: addParallel(e1, None) reaches
        # the API and reports success.
        if (point if first_kind == "point" else e1) is None:
            raise RuntimeError(
                f"a {constraint_type} constraint needs entity_one "
                f"(a {'point' if first_kind == 'point' else 'curve'} index) - "
                f"sketch '{sketch.name}' has {len(curves)} curve(s)"
            )
        if needs_two and e2 is None:
            raise RuntimeError(
                f"a {constraint_type} constraint needs entity_two (a curve index) "
                f"- sketch '{sketch.name}' has {len(curves)} curve(s)"
            )

        # symmetry's mirror line is resolved here so the map below just names it; a
        # call that omitted it was refused above, from the parameters alone.
        mirror_line = None
        if symmetry_line is not None:
            mirror_line = self._curve_by_index(
                sketch, curves, symmetry_line, "symmetry_line"
            )

        constraint_map = {
            "coincident": lambda: constraints.addCoincident(e1, e2),
            "parallel": lambda: constraints.addParallel(e1, e2),
            "perpendicular": lambda: constraints.addPerpendicular(e1, e2),
            "tangent": lambda: constraints.addTangent(e1, e2),
            "equal": lambda: constraints.addEqual(e1, e2),
            "fix": lambda: constraints.addFix(e1),
            "horizontal": lambda: constraints.addHorizontal(e1),
            "vertical": lambda: constraints.addVertical(e1),
            "concentric": lambda: constraints.addConcentric(e1, e2),
            "collinear": lambda: constraints.addCollinear(e1, e2),
            "smooth": lambda: constraints.addSmooth(e1, e2),
            "midpoint": lambda: constraints.addMidPoint(point, e2),
            "symmetry": lambda: constraints.addSymmetry(e1, e2, mirror_line),
        }

        constraint_map[constraint_type]()
        return {"sketch": sketch.name, "constraint_type": constraint_type}

    def auto_constrain(
        self,
        sketch_name: str | None = None,
        result_option: int = 1,
    ):
        """Auto-constrain a sketch using Fusion's AutoConstrain (Jan 2026+).

        result_option: 1 = thorough (default), 2 = fast,
        3 = may move geometry within tolerance.
        """
        sketch = self._sketch(sketch_name)

        option_map = {
            1: adsk.fusion.AutoConstrainResultTypes.Option1AutoConstrainResultType,
            2: adsk.fusion.AutoConstrainResultTypes.Option2AutoConstrainResultType,
            3: adsk.fusion.AutoConstrainResultTypes.Option3AutoConstrainResultType,
        }
        # The schema's enum is what refuses a value outside the three, so the key is
        # present here; indexing rather than ``.get`` keeps a caller that reached the
        # add-in around the gate from handing Fusion a ``None`` option.
        option = option_map[result_option]

        ac_input = sketch.createAutoConstrainInput()
        ac_input.resultOption = option
        result = sketch.autoConstrain(ac_input)
        if result is None:
            # Option 3 returns null when the sketch is not eligible for
            # geometry adjustment.  Fusion declined to run, so this is not our bug.
            raise _hints.Refusal(
                "FUSION_REFUSED",
                "autoConstrain returned no result — the sketch is not "
                "eligible for geometry adjustment. Retry with "
                "result_option 1 or 2.",
                hints=("Retry auto_constrain with result_option 1 or 2.",),
            )

        return {
            "sketch": sketch.name,
            "is_fully_constrained": result.isFullyConstrained,
            "constraints_added": len(result.addedConstraints),
            "dimensions_added": len(result.addedDimensions),
            "entities_moved": len(result.movedGeometry),
            "result_option": result_option,
        }

    #: Which entities each dimension type resolves.  ``radial`` and ``diameter``
    #: measure ONE curve; the rest need two.  A guard demanding both for every type
    #: refused a schema-legal radial dimension outright.
    _DIMENSION_ENTITIES: ClassVar[dict[str, tuple[str, ...]]] = {
        "distance": ("entity_one", "entity_two"),
        "horizontal": ("entity_one", "entity_two"),
        "vertical": ("entity_one", "entity_two"),
        "angular": ("entity_one", "entity_two"),
        "radial": ("entity_one",),
        "diameter": ("entity_one",),
    }

    def add_dimension(
        self,
        dimension_type: str,
        value: float,
        entity_one: int | None = None,
        entity_two: int | None = None,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        dims = sketch.sketchDimensions
        curves = list(sketch.sketchCurves)

        needed = self._DIMENSION_ENTITIES.get(dimension_type)
        if needed is None:
            raise RuntimeError(
                f"Unknown dimension type: {dimension_type} (expected one of "
                + ", ".join(sorted(self._DIMENSION_ENTITIES))
                + ")"
            )

        e1 = (
            self._curve_by_index(sketch, curves, entity_one, "entity_one")
            if "entity_one" in needed and entity_one is not None
            else None
        )
        e2 = (
            self._curve_by_index(sketch, curves, entity_two, "entity_two")
            if "entity_two" in needed and entity_two is not None
            else None
        )
        missing = [
            field
            for field, value in (("entity_one", e1), ("entity_two", e2))
            if field in needed and value is None
        ]
        if missing:
            raise RuntimeError(
                f"a {dimension_type} dimension needs {' and '.join(missing)} (a "
                f"curve index) - sketch '{sketch.name}' has {len(curves)} curve(s)"
            )
        # Narrowed AFTER the refusal, never before it: an assert ahead of the guard
        # turns a missing index into an AssertionError instead of the message the
        # caller can act on.  These tell the type checker what the guard guarantees.
        #
        # ``first``/``second`` rather than ``e1``/``e2`` because the narrowing has to
        # survive into the lambda table below, where the merged type after this
        # if/else is otherwise ``Any | None`` for both.  For a one-entity type
        # ``second`` aliases the same curve and no entry reads it; nothing is touched
        # eagerly, so an attribute Fusion may not expose is still only read when its
        # own lambda runs.
        if "entity_two" in needed:
            assert e1 is not None and e2 is not None
            first, second = e1, e2
            # The two-entity label takes the origin, measured on 2706.
            text_pt = adsk.core.Point3D.create(0, 0, 0)
        else:
            assert e1 is not None
            first, second = e1, e1
            # The one-entity label needs a point away from the curve's centre: measured
            # on 2706, a radial label at the world origin over a circle centred there
            # raises "3 : Some input argument is invalid", while the curve's
            # bounding-box corner is accepted.
            box = first.boundingBox
            text_pt = adsk.core.Point3D.create(
                box.maxPoint.x, box.maxPoint.y, box.maxPoint.z
            )

        # One dict, not an if/elif chain with an unreachable else: membership is
        # the table's job (it raised above), and a type added to the table without a
        # call here fails the parity test rather than at a caller's expense.
        calls = {
            "distance": lambda: dims.addDistanceDimension(
                first.startSketchPoint,
                second.startSketchPoint,
                adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
                text_pt,
            ),
            "horizontal": lambda: dims.addDistanceDimension(
                first.startSketchPoint,
                second.startSketchPoint,
                adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
                text_pt,
            ),
            "vertical": lambda: dims.addDistanceDimension(
                first.startSketchPoint,
                second.startSketchPoint,
                adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
                text_pt,
            ),
            "angular": lambda: dims.addAngularDimension(first, second, text_pt),
            "radial": lambda: dims.addRadialDimension(first, text_pt),
            "diameter": lambda: dims.addDiameterDimension(first, text_pt),
        }
        dim = calls[dimension_type]()

        dim.parameter.value = value
        return {"sketch": sketch.name, "dimension_type": dimension_type, "value": value}

    def offset_curve(
        self,
        curve_index: int,
        offset_distance: float,
        direction_x: float = 1,
        direction_y: float = 0,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        curves = list(sketch.sketchCurves)
        curve = self._curve_by_index(sketch, curves, curve_index, "curve_index")
        direction_pt = adsk.core.Point3D.create(direction_x, direction_y, 0)

        coll = adsk.core.ObjectCollection.create()
        coll.add(curve)
        sketch.offset(coll, direction_pt, offset_distance)
        return {"sketch": sketch.name, "offset_distance": offset_distance}

    def trim_curve(
        self,
        curve_index: int,
        point_x: float,
        point_y: float,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        curves = list(sketch.sketchCurves)
        curve = self._curve_by_index(sketch, curves, curve_index, "curve_index")
        point = adsk.core.Point3D.create(point_x, point_y, 0)
        curve.trim(point)
        return {"sketch": sketch.name, "trimmed": True}

    def extend_curve(
        self,
        curve_index: int,
        point_x: float,
        point_y: float,
        sketch_name: str | None = None,
    ):
        sketch = self._sketch(sketch_name)
        curves = list(sketch.sketchCurves)
        curve = self._curve_by_index(sketch, curves, curve_index, "curve_index")
        point = adsk.core.Point3D.create(point_x, point_y, 0)
        curve.extend(point)
        return {"sketch": sketch.name, "extended": True}

    def project_geometry(
        self, source_name: str, is_linked: bool = True, sketch_name: str | None = None
    ):
        sketch = self._sketch(sketch_name)
        body = self._body_by_name(source_name)

        projected = []
        for edge in body.edges:
            # project2, not the retired project(): only project2 takes isLinked.
            projected.extend(sketch.project2([edge], is_linked))

        return {
            "sketch": sketch.name,
            "source": source_name,
            "projected_curves": len(projected),
            "is_linked": is_linked,
        }
