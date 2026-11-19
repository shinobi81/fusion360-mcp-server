"""Scene, query and inspection commands: the document, the model tree, execution.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

import ast
import io
import math
import traceback
from contextlib import redirect_stdout

from . import fusion_api as adsk
from . import get_logger
from . import hints as _hints
from . import parameter_units as _param_units

log = get_logger("handler")


class SceneCommands:
    def new_document(self, name: str | None = None):
        """Create a design document and make it active.

        Fusion starts at the data tab with no active product, and every command
        needs a design, so this is the way in from a cold start. Created through
        the API on purpose: a document created in the Fusion UI is a Part Design
        document, which rejects ``addNewComponent``, so components and joints are
        impossible in it.
        """
        doc = self.app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        if name:
            doc.name = name

        design = doc.products.itemByProductType("DesignProductType")
        if design is None:
            raise _hints.Refusal(
                "DESIGN_TYPE_MISMATCH",
                "New document has no design product",
                hints=("new_document creates a design; check get_design_type.",),
            )

        design_types = adsk.fusion.DesignTypes
        if design.designType == design_types.ParametricDesignType:
            kind = "parametric"
        elif design.designType == design_types.DirectDesignType:
            kind = "direct"
        else:
            kind = str(design.designType)

        return {
            "created": True,
            "document": doc.name,
            "design_type": kind,
            "component": design.rootComponent.name,
        }

    def get_scene_info(self):
        design = self._design()
        root = self._root()

        bodies = []
        for i in range(root.bRepBodies.count):
            b = root.bRepBodies.item(i)
            bodies.append(
                {
                    "name": b.name,
                    "volume": b.volume,
                    "area": b.area,
                    "material": b.material.name if b.material else None,
                    "is_visible": b.isVisible,
                }
            )

        sketches = []
        for i in range(root.sketches.count):
            s = root.sketches.item(i)
            sketches.append(
                {
                    "name": s.name,
                    "profile_count": s.profiles.count,
                    "is_visible": s.isVisible,
                }
            )

        return {
            "design_name": design.parentDocument.name,
            "design_type": design.productType,
            "bodies": bodies,
            "sketches": sketches,
            "bodies_count": root.bRepBodies.count,
            "sketches_count": root.sketches.count,
            "features_count": root.features.count,
            "timeline_count": self._timeline_count(design),
            "camera": self._camera_info(),
        }

    def get_object_info(self, name: str):
        root = self._root()

        # bodies
        for i in range(root.bRepBodies.count):
            b = root.bRepBodies.item(i)
            if b.name == name:
                return {
                    "found": True,
                    "type": "body",
                    "name": name,
                    "volume": b.volume,
                    "area": b.area,
                    "material": b.material.name if b.material else None,
                    "is_visible": b.isVisible,
                    "faces_count": b.faces.count,
                    "edges_count": b.edges.count,
                    "vertices_count": b.vertices.count,
                    "bounding_box": self._bbox_dict(b.boundingBox),
                }

        # sketches
        for i in range(root.sketches.count):
            s = root.sketches.item(i)
            if s.name == name:
                return {
                    "found": True,
                    "type": "sketch",
                    "name": name,
                    "is_visible": s.isVisible,
                    "profile_count": s.profiles.count,
                    "curve_count": s.sketchCurves.count,
                }

        return {"found": False, "name": name}

    def list_edges(
        self,
        body_name: str | None = None,
        body_index: int = 0,
        limit: int = 200,
    ):
        """Every edge of a body, with the geometry needed to choose one.

        ``count`` is the body's real edge count and ``truncated`` says whether
        ``limit`` clipped the list — a body with thousands of edges must not
        flood a caller's context, but a caller that reads ``count`` as "how many
        I got back" would plan against a shorter list than the body has.
        """
        body = self._body_or_index(body_name, body_index)
        count = body.edges.count
        limit = max(1, int(limit))

        def coords(point):
            return [point.x, point.y, point.z]

        edges = []
        for index in range(min(count, limit)):
            edge = body.edges.item(index)
            edges.append(
                {
                    "index": index,
                    "start": coords(edge.startVertex.geometry),
                    "end": coords(edge.endVertex.geometry),
                    "midpoint": coords(edge.pointOnEdge),
                    "length": edge.length,
                    # The class name (``Line3D``, ``Circle3D``) rather than an
                    # enum number: an agent reads it without a lookup table.
                    "curve_type": type(edge.geometry).__name__,
                    # Fusion's own flag: a degenerate edge has no geometry, no
                    # fillet can round it, and every selector skips it. Reported
                    # so a caller comparing count against a selection can see why
                    # they differ - and so naming one by index is diagnosable.
                    "is_degenerate": bool(edge.isDegenerate),
                }
            )
        return {
            "body_name": body.name,
            "count": count,
            "truncated": len(edges) < count,
            "edges": edges,
        }

    def list_components(self):
        root = self._root()
        components = [{"name": root.name, "is_root": True}]
        for occ in root.allOccurrences:
            components.append(
                {
                    "name": occ.component.name,
                    "is_root": False,
                    "is_visible": occ.isVisible,
                }
            )
        return {"components": components, "count": len(components)}

    def get_bounding_box(self, name: str):
        """Axis-aligned bounding box for a body or component. Values in cm."""

        def _payload(obj_type, mn, mx):
            return {
                "found": True,
                "type": obj_type,
                "name": name,
                "min": mn,
                "max": mx,
                "size": [mx[i] - mn[i] for i in range(3)],
                "center": [(mn[i] + mx[i]) / 2 for i in range(3)],
            }

        # Try body first (covers root bodies + bodies inside components)
        try:
            body = self._body_by_name(name)
            bb = body.boundingBox
            return _payload(
                "body",
                [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z],
                [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z],
            )
        except RuntimeError:
            pass

        # Fall back to component: union bbox of all contained bodies
        try:
            comp = self._component_by_name(name)
        except RuntimeError:
            return {"found": False, "name": name}

        mn = [float("inf")] * 3
        mx = [float("-inf")] * 3

        def _extend(bodies):
            for i in range(bodies.count):
                bb = bodies.item(i).boundingBox
                lo = [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z]
                hi = [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z]
                for axis in range(3):
                    if lo[axis] < mn[axis]:
                        mn[axis] = lo[axis]
                    if hi[axis] > mx[axis]:
                        mx[axis] = hi[axis]

        _extend(comp.bRepBodies)
        for occ in comp.allOccurrences:
            _extend(occ.bRepBodies)

        if mn[0] == float("inf"):
            return {"found": True, "type": "component", "name": name, "empty": True}

        return _payload("component", mn, mx)

    def measure_distance(self, entity_one: str, entity_two: str):
        root = self._root()

        def get_entity(name):
            # Try as body
            for i in range(root.bRepBodies.count):
                b = root.bRepBodies.item(i)
                if b.name == name:
                    return b
            # Try as point (x,y,z format)
            if "," in name:
                coords = [float(x.strip()) for x in name.split(",")]
                return adsk.core.Point3D.create(*coords)
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                f"Entity '{name}' not found",
                hints=("Call get_scene_info for the entity names in this design.",),
            )

        e1 = get_entity(entity_one)
        e2 = get_entity(entity_two)

        measure = self.app.measureManager
        result = measure.measureMinimumDistance(e1, e2)
        return {
            "distance": result.value,
            "point_one": [
                result.positionOne.x,
                result.positionOne.y,
                result.positionOne.z,
            ],
            "point_two": [
                result.positionTwo.x,
                result.positionTwo.y,
                result.positionTwo.z,
            ],
        }

    def measure_angle(self, entity_one: str, entity_two: str):
        root = self._root()

        def get_entity(name):
            for i in range(root.bRepBodies.count):
                b = root.bRepBodies.item(i)
                if b.name == name:
                    return b.faces.item(0)  # First face
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                f"Entity '{name}' not found",
                hints=("Call get_scene_info for the entity names in this design.",),
            )

        e1 = get_entity(entity_one)
        e2 = get_entity(entity_two)

        measure = self.app.measureManager
        result = measure.measureAngle(e1, e2)
        return {"angle_degrees": math.degrees(result.value)}

    def get_physical_properties(self, body_name: str, accuracy: str = "medium"):
        body = self._body_by_name(body_name)

        accuracy_map = {
            "low": adsk.fusion.CalculationAccuracy.LowCalculationAccuracy,
            "medium": adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy,
            "high": adsk.fusion.CalculationAccuracy.HighCalculationAccuracy,
            "very_high": adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy,
        }
        acc = accuracy_map.get(accuracy, accuracy_map["medium"])

        props = body.getPhysicalProperties(acc)
        return {
            "mass": props.mass,
            "volume": props.volume,
            "area": props.area,
            "density": props.density,
            "center_of_mass": [
                props.centerOfMass.x,
                props.centerOfMass.y,
                props.centerOfMass.z,
            ],
        }

    def create_section_analysis(self, plane: str = "yz", offset: float = 0):
        root = self._root()
        analyses = root.analyses

        inp = analyses.createInput()
        inp.plane = self._construction_plane(plane)
        if offset != 0:
            inp.distance = adsk.core.ValueInput.createByReal(offset)

        analysis = analyses.add(inp)
        return {
            "created": True,
            # Named so the agent can reference it: every other builder reports a
            # name, and add() returns the SectionAnalysis the name lives on.
            "analysis_name": analysis.name,
            "plane": plane,
            "offset": offset,
        }

    def check_interference(
        self, component_names: list, include_coincident_faces: bool = False
    ):
        root = self._root()
        bodies = adsk.core.ObjectCollection.create()

        for name in component_names:
            for occ in root.allOccurrences:
                if occ.component.name == name:
                    for b in occ.bRepBodies:
                        bodies.add(b)

        if bodies.count < 2:
            raise _hints.Refusal(
                "GEOMETRY_UNSUPPORTED",
                "Need at least 2 components with bodies",
                hints=("Create the components with create_component first.",),
            )

        # Interference analysis is a Design-level API.  Component has no
        # interfere() method at all, so the previous call raised
        # AttributeError for every caller.
        design = self._design()
        inp = design.createInterferenceInput(bodies)
        inp.areCoincidentFacesIncluded = bool(include_coincident_faces)
        interference = design.analyzeInterference(inp)

        results = []
        if interference is not None:
            for i in range(interference.count):
                result = interference.item(i)
                results.append(
                    {
                        "body_one": result.entityOne.name,
                        "body_two": result.entityTwo.name,
                        "volume": result.interferenceBody.volume,
                    }
                )

        return {"interferences": results, "count": len(results)}

    def compare_meshes(self, mesh_name_a: str, mesh_name_b: str):
        """Compare two mesh bodies; report per-node deviation statistics.

        Uses PolygonMesh.compareWith (Fusion 2026): for every node in mesh A,
        the signed distance to the closest point on mesh B (cm).  Positive
        means the node lies on the surface-normal side of B.
        """
        design = self._design()
        root = design.rootComponent

        def _mesh_body_by_name(name):
            for i in range(root.meshBodies.count):
                mb = root.meshBodies.item(i)
                if mb.name == name:
                    return mb
            raise RuntimeError(
                f"Mesh body '{name}' not found in root component. "
                "Use get_scene_info to list mesh bodies."
            )

        body_a = _mesh_body_by_name(mesh_name_a)
        body_b = _mesh_body_by_name(mesh_name_b)

        mesh_a = body_a.mesh or body_a.displayMesh
        mesh_b = body_b.mesh or body_b.displayMesh
        if mesh_a is None or mesh_b is None:
            raise _hints.Refusal(
                "FUSION_REFUSED",
                "Could not obtain polygon mesh data",
                hints=("The body has no mesh to compare; export it as STL instead.",),
            )

        deviations = list(mesh_a.compareWith(mesh_b))
        if not deviations:
            raise _hints.Refusal(
                "FUSION_REFUSED",
                "compareWith returned no deviation data",
                hints=(
                    "compareWith found no deviation; check both bodies are meshes.",
                ),
            )

        abs_dev = [abs(d) for d in deviations]
        n = len(deviations)
        mean_abs = sum(abs_dev) / n
        rms = math.sqrt(sum(d * d for d in deviations) / n)
        return {
            "mesh_a": mesh_name_a,
            "mesh_b": mesh_name_b,
            "node_count": n,
            "min_deviation": min(deviations),
            "max_deviation": max(deviations),
            "mean_abs_deviation": mean_abs,
            "rms_deviation": rms,
            "max_abs_deviation": max(abs_dev),
            "units": "cm",
        }

    def set_appearance(
        self,
        target_name: str,
        appearance_name: str,
        target_type: str = "body",
        face_index: int | None = None,
    ):
        # Find appearance in library — try both known library names
        app_lib = self.app.materialLibraries.itemByName("Fusion Appearance Library")
        if app_lib is None:
            app_lib = self.app.materialLibraries.itemByName(
                "Fusion 360 Appearance Library"
            )
        if app_lib is None:
            # Fall back to searching all libraries
            for i in range(self.app.materialLibraries.count):
                lib = self.app.materialLibraries.item(i)
                if lib.appearances.count > 0:
                    app_lib = lib
                    break
        if app_lib is None:
            raise _hints.Refusal(
                "WORKSPACE_UNAVAILABLE",
                "No appearance library found",
                hints=("Open the Appearance panel once in Fusion, then retry.",),
            )

        appearance = None
        for i in range(app_lib.appearances.count):
            app = app_lib.appearances.item(i)
            if app.name == appearance_name:
                appearance = app
                break

        if not appearance:
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                f"Appearance '{appearance_name}' not found",
                hints=(
                    "Use an appearance name from the library, e.g. 'Steel - Satin'.",
                ),
            )

        # The target is resolved before anything is copied: a refusal here must not
        # leave an appearance in the design's own collection for a call that failed.
        if target_type == "body":
            target = self._body_by_name(target_name)
        elif target_type == "component":
            target = self._component_by_name(target_name)
        elif target_type == "face":
            target = self._body_by_name(target_name).faces.item(face_index)
        else:
            target = None

        # Library appearances must be copied into the design before
        # assignment — assigning a library appearance directly is
        # version-dependent and known to fail on recent Fusion builds.
        design = self._design()
        local = design.appearances.itemByName(appearance.name)
        if local is None:
            local = design.appearances.addByCopy(appearance, appearance.name)
        if local is None:
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Could not copy appearance '{appearance_name}' into the design",
                hints=("Copy the appearance into the document first, then set it.",),
            )

        if target is not None:
            target.appearance = local

        return {"applied": True, "target": target_name, "appearance": appearance_name}

    def set_color(
        self,
        body_name: str,
        red: int,
        green: int,
        blue: int,
        opacity: float = 1.0,
    ):
        """Assign a flat RGB color to a body via a design-local appearance.

        Uses the Appearances.add + Appearance.color API (July 2026), so no
        library copy is needed.  Appearances are reused when the same color
        is requested again.  opacity 1.0 = fully opaque, 0.0 = invisible.
        """
        body = self._body_by_name(body_name)
        design = self._design()

        red = max(0, min(255, int(red)))
        green = max(0, min(255, int(green)))
        blue = max(0, min(255, int(blue)))
        alpha = max(0, min(255, round(opacity * 255)))

        color_name = f"MCP_{red}_{green}_{blue}_{alpha}"
        appearance = design.appearances.itemByName(color_name)
        if appearance is None:
            appearance = design.appearances.add(color_name)
            appearance.color = adsk.core.Color.create(red, green, blue, alpha)

        body.appearance = appearance
        return {
            "body": body_name,
            "color": [red, green, blue],
            "opacity": alpha / 255.0,
            "appearance": color_name,
        }

    def get_parameters(self):
        design = self._design()
        params = []
        for param in design.userParameters:
            params.append(
                {
                    "name": param.name,
                    "value": param.value,
                    "expression": param.expression,
                    "unit": param.unit,
                    "comment": param.comment,
                }
            )
        return {"parameters": params, "count": len(params)}

    def create_parameter(
        self, name: str, value: float, unit: str, comment: str | None = None
    ):
        # Validated before the design is looked up, deliberately: a bad argument
        # is wrong whichever document is open, so INVALID_INPUT outranks
        # NO_ACTIVE_DESIGN. Before either factory too -- "inf mm" is an
        # expression Fusion would reject with no clue why, and json.loads
        # accepts Infinity/NaN, so a socket client can deliver one.
        value = _param_units.require_finite(value)
        design = self._design()
        params = design.userParameters
        unit = _param_units.normalise_unit(unit)
        # createByReal() is read in internal units (cm, radians), so a caller
        # asking for 1000 mm would get 1000 cm labelled "mm".
        value_input = _param_units.build_value_input(
            value,
            unit,
            adsk.core.ValueInput.createByString,
            adsk.core.ValueInput.createByReal,
        )
        param = params.add(name, value_input, unit, comment or "")
        return {
            "created": True,
            "name": name,
            "value": value,
            "unit": unit,
            "expression": param.expression,
        }

    def set_parameter(self, name: str, value: float):
        # Same order as create_parameter: the argument is judged before the
        # design and the name are looked up, so a bad value outranks
        # NO_ACTIVE_DESIGN and a misspelt name instead of hiding behind them.
        value = _param_units.require_finite(value)
        design = self._design()
        param = design.userParameters.itemByName(name)
        if not param:
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                f"Parameter '{name}' not found",
                hints=("Call get_parameters for the names this design has.",),
            )
        # Assigning .value would be read in internal units, silently rescaling
        # any parameter whose unit is not the internal one. Write the
        # expression, in the unit the parameter already declares.
        unit = _param_units.normalise_unit(param.unit)
        param.expression = _param_units.expression_for(value, unit)
        return {
            "updated": True,
            "name": name,
            "value": value,
            "unit": unit,
            "expression": param.expression,
        }

    def delete_parameter(self, name: str):
        design = self._design()
        param = design.userParameters.itemByName(name)
        if not param:
            raise _hints.Refusal(
                "NAME_NOT_FOUND",
                f"Parameter '{name}' not found",
                hints=("Call get_parameters for the names this design has.",),
            )
        param.deleteMe()
        return {"deleted": True, "name": name}

    def ping(self):
        return {"pong": True}

    def get_design_type(self):
        """Return current design type: 'parametric' or 'direct'."""
        design = self._design()
        dt = design.designType
        is_parametric = dt == adsk.fusion.DesignTypes.ParametricDesignType
        return {
            "design_type": "parametric" if is_parametric else "direct",
            "design_type_id": dt,
        }

    def set_design_type(self, design_type: str):
        """Switch design type. Use 'parametric' to recover from accidental
        direct-mode switches (equivalent to UI 'Capture Design History')."""
        design = self._design()
        current = design.designType

        if design_type == "parametric":
            target = adsk.fusion.DesignTypes.ParametricDesignType
            if current == target:
                return {
                    "changed": False,
                    "design_type": "parametric",
                    "message": "Already in parametric mode",
                }
            design.designType = target
            adsk.doEvents()
            # Verify it actually changed
            if design.designType != target:
                raise RuntimeError(
                    "Failed to switch to parametric mode. "
                    "Try 'Capture Design History' in the Fusion UI."
                )
            return {"changed": True, "design_type": "parametric"}

        elif design_type == "direct":
            target = adsk.fusion.DesignTypes.DirectDesignType
            if current == target:
                return {
                    "changed": False,
                    "design_type": "direct",
                    "message": "Already in direct mode",
                }
            design.designType = target
            adsk.doEvents()
            return {"changed": True, "design_type": "direct"}

        # The gate refuses a value outside the enum first for MCP callers; a client
        # on :9876 never passes it, and returning None would make execute_command
        # report {"value": None, "ok": true}.  D12 keeps this as the direct-wire
        # defence.
        raise _hints.Refusal(
            "INVALID_INPUT",
            f"Invalid design_type '{design_type}'. Use 'parametric' or 'direct'.",
            hints=("Pass design_type='parametric' or 'direct'.",),
        )

    def execute_code(self, code: str):
        design = self._design()
        type_before = design.designType

        ns = {
            "adsk": adsk,
            "app": self.app,
            "ui": self.ui,
            "design": design,
            "component": self._root(),
            "math": math,
        }

        buf = io.StringIO()

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            # ``from None`` so the parse is not rendered twice, and the parser's own
            # rendering folded into the message instead: the caret-annotated source line
            # appears nowhere else once the chained block is suppressed, and the message
            # is what reaches the agent.
            detail = "".join(traceback.format_exception_only(exc)).rstrip()
            # Drop the rendering's own final "SyntaxError: ..." line: the prefix above
            # already names it, and the agent should not read the same sentence twice.
            annotated = "\n".join(
                line
                for line in detail.splitlines()
                if not line.startswith("SyntaxError:")
            )
            raise _hints.Refusal(
                "SCRIPT_ERROR",
                f"SyntaxError: {exc}\n{annotated}",
                hints=("Fix the script's syntax; the namespace is rebuilt per call.",),
            ) from None

        last_expr_value = None
        last_expr = (
            tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        )
        if last_expr is not None:
            tree.body.pop()
            if tree.body:
                with redirect_stdout(buf):
                    exec(
                        compile(
                            ast.Module(body=tree.body, type_ignores=[]), "<mcp>", "exec"
                        ),
                        ns,
                    )
            expr_code = compile(ast.Expression(body=last_expr.value), "<mcp>", "eval")
            with redirect_stdout(buf):
                last_expr_value = eval(expr_code, ns)
        else:
            with redirect_stdout(buf):
                exec(compile(tree, "<mcp>", "exec"), ns)

        output = buf.getvalue()
        result = last_expr_value if last_expr_value is not None else output

        # Warn if design type changed during execution. The script may have closed
        # the document this design belongs to - a legitimate thing to do from a
        # REPL - and reading a closed design raises "4 : An API Object refers to a
        # deleted Object" AFTER the script has already run.  The caller was told
        # the call failed when it had succeeded.
        document_closed = not design.isValid
        type_after = type_before if document_closed else design.designType
        design_type_warning = None
        if type_before != type_after:
            parametric = adsk.fusion.DesignTypes.ParametricDesignType
            design_type_warning = (
                f"WARNING: Design type changed from "
                f"{'parametric' if type_before == parametric else 'direct'} to "
                f"{'parametric' if type_after == parametric else 'direct'} "
                f"during code execution. Use set_design_type to recover."
            )
            log.warning(design_type_warning)
        if result is not None:
            try:
                import json as _json

                _json.dumps(result)
            except (TypeError, ValueError):
                result = str(result)

        response = {"executed": True, "result": result, "output": output}
        if design_type_warning:
            response["design_type_warning"] = design_type_warning
        if document_closed:
            # Say it rather than failing: the design-type question does not apply
            # to a document that no longer exists.
            response["document_closed"] = True
        return response

    def _camera_info(self):
        try:
            cam = self.app.activeViewport.camera
            return {
                "eye": [cam.eye.x, cam.eye.y, cam.eye.z],
                "target": [cam.target.x, cam.target.y, cam.target.z],
                "up_vector": [cam.upVector.x, cam.upVector.y, cam.upVector.z],
            }
        except Exception:
            return None
