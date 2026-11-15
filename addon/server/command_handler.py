"""
Fusion360 Command Handler

Executes commands using the Fusion 360 API.  Every method in this class
is called on the **main thread** (via EventBridge), so Fusion API access
is safe.
"""

import base64
import math
import os
import tempfile
import time
from contextlib import suppress
from typing import Any

# One import site for Autodesk's API, resolved lazily so this module imports outside
# Fusion; every ``adsk.`` use below goes through the adapter.
from . import fusion_api as adsk
from . import get_logger
from . import parameter_units as _param_units
from . import rules as _rules
from .handler_assembly import AssemblyCommands
from .handler_base import HandlerBase
from .handler_features import FeatureCommands
from .handler_primitives import PrimitiveCommands
from .handler_scene import SceneCommands
from .handler_sketch import SketchCommands

log = get_logger("handler")


class CommandHandler(
    SketchCommands,
    FeatureCommands,
    PrimitiveCommands,
    SceneCommands,
    AssemblyCommands,
    HandlerBase,
):
    """Runs Fusion API operations.  Instantiated once; reused across requests."""

    def _export_body(self, kind: str, body_name: str, file_path: str | None) -> dict:
        """Export one body as STL or STEP, hiding its siblings when it is nested.

        The two APIs differ in more than the extension: STL's factory takes
        ``(entity, path)`` and accepts a mesh refinement, STEP's takes
        ``(path, entity)``.  Everything else - the Desktop default, the sibling
        sweep keyed on ``entityToken``, the restore in a ``finally`` - is the same
        for both, which is why this is one function and not two ~40-line twins.
        """
        body = self._body_by_name(body_name)

        if file_path is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, f"{body_name}.{kind}")

        # A bare filename has no directory to make, and os.makedirs("") raises.
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        export_mgr = self._design().exportManager
        occurrence = body.assemblyContext  # None if the body is at root

        def options_for(entity):
            if kind == "stl":
                created = export_mgr.createSTLExportOptions(entity, file_path)
                created.meshRefinement = (
                    adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
                )
                return created
            return export_mgr.createSTEPExportOptions(file_path, entity)

        if occurrence is None:
            export_mgr.execute(options_for(body))
            return {"exported": True, "body": body_name, "file_path": file_path}

        # The body lives in a component occurrence: hide its siblings so the
        # export contains only this one.  Identified by entityToken, not name,
        # so a component holding two bodies called "Body1" still exports one.
        target_token = body.entityToken
        hidden = []
        for i in range(occurrence.bRepBodies.count):
            sibling = occurrence.bRepBodies.item(i)
            if sibling.entityToken != target_token and sibling.isVisible:
                sibling.isVisible = False
                hidden.append(sibling)

        try:
            export_mgr.execute(options_for(occurrence))
        finally:
            for sibling in hidden:
                sibling.isVisible = True

        return {"exported": True, "body": body_name, "file_path": file_path}

    def export_stl(self, body_name: str, file_path: str | None = None):
        return self._export_body("stl", body_name, file_path)

    def export_step(self, body_name: str, file_path: str | None = None):
        return self._export_body("step", body_name, file_path)

    def export_f3d(self, file_path: str | None = None):
        design = self._design()
        doc_name = design.parentDocument.name

        if file_path is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, f"{doc_name}.f3d")

        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        export_mgr = design.exportManager
        f3d_opts = export_mgr.createFusionArchiveExportOptions(file_path)
        export_mgr.execute(f3d_opts)

        return {"exported": True, "file_path": file_path}

    def _scene_center_and_radius(self):
        """Return (center, radius) covering all visible root bodies."""
        root = self._root()
        minp = [float("inf")] * 3
        maxp = [float("-inf")] * 3
        found = False

        def _grow(bb):
            nonlocal found
            for j, coord in enumerate(("x", "y", "z")):
                minp[j] = min(minp[j], getattr(bb.minPoint, coord))
                maxp[j] = max(maxp[j], getattr(bb.maxPoint, coord))
            found = True

        for i in range(root.bRepBodies.count):
            b = root.bRepBodies.item(i)
            if b.isVisible:
                _grow(b.boundingBox)
        for i in range(root.occurrences.count):
            occ = root.occurrences.item(i)
            if not occ.isVisible:
                continue
            for j in range(occ.bRepBodies.count):
                b = occ.bRepBodies.item(j)
                if b.isVisible:
                    _grow(b.boundingBox)

        if not found:
            return (0.0, 0.0, 0.0), 10.0
        center = tuple((minp[i] + maxp[i]) / 2 for i in range(3))
        span = max(maxp[i] - minp[i] for i in range(3))
        return center, max(span, 1.0)

    def _apply_view(self, view_name: str, center, radius: float):
        """Point the active viewport camera at *center* from *view_name*."""
        dir_vec, up_vec = self._VIEW_DIRS[view_name]
        length = math.sqrt(sum(c * c for c in dir_vec))
        dist = radius * 3.0  # give fit() headroom
        eye = tuple(center[i] + dir_vec[i] / length * dist for i in range(3))
        vp = self.app.activeViewport
        cam = vp.camera
        cam.isSmoothTransition = False
        cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
        cam.eye = adsk.core.Point3D.create(*eye)
        cam.target = adsk.core.Point3D.create(*center)
        cam.upVector = adsk.core.Vector3D.create(*up_vec)
        cam.isFitView = True
        vp.camera = cam
        vp.refresh()
        adsk.doEvents()

    def export_view_sheet(
        self,
        title: str | None = None,
        notes: str = "",
        views: list | None = None,
        image_size: list | None = None,
        output_dir: str | None = None,
    ):
        """Render canonical views as PNGs + a shareable HTML sheet.

        Args:
            title: heading on the sheet (default: document name).
            notes: free-form text rendered below the views (newlines
                preserved; HTML is escaped).
            views: ordered list of view names. Valid: iso, iso_ne,
                iso_nw, iso_sw, front, back, top, bottom, right, left.
                Default: ["iso", "front", "top", "right"].
            image_size: [width, height] in pixels (default [1200, 900]).
            output_dir: destination folder
                (default: ~/Desktop/<doc>_views_<timestamp>).
        """
        import html
        import json as _json

        design = self._design()
        doc_name = design.parentDocument.name
        sheet_title = title or doc_name
        views = views or ["iso", "front", "top", "right"]
        image_size = image_size or [1200, 900]
        width, height = int(image_size[0]), int(image_size[1])

        unknown = [v for v in views if v not in self._VIEW_DIRS]
        if unknown:
            raise RuntimeError(
                f"Unknown views: {unknown}. Valid: {sorted(self._VIEW_DIRS)}"
            )

        if output_dir is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join(
                os.path.expanduser("~"),
                "Desktop",
                f"{doc_name}_views_{ts}",
            )
        os.makedirs(output_dir, exist_ok=True)

        vp = self.app.activeViewport
        orig = vp.camera
        orig_state = {
            "eye": (orig.eye.x, orig.eye.y, orig.eye.z),
            "target": (orig.target.x, orig.target.y, orig.target.z),
            "up": (orig.upVector.x, orig.upVector.y, orig.upVector.z),
            "type": orig.cameraType,
        }

        center, radius = self._scene_center_and_radius()

        rendered = []
        try:
            for view_name in views:
                self._apply_view(view_name, center, radius)
                png_path = os.path.join(output_dir, f"{view_name}.png")
                vp.saveAsImageFile(png_path, width, height)
                rendered.append({"view": view_name, "path": png_path})
        finally:
            cam = vp.camera
            cam.isSmoothTransition = False
            cam.cameraType = orig_state["type"]
            cam.eye = adsk.core.Point3D.create(*orig_state["eye"])
            cam.target = adsk.core.Point3D.create(*orig_state["target"])
            cam.upVector = adsk.core.Vector3D.create(*orig_state["up"])
            vp.camera = cam
            vp.refresh()

        # Build self-contained HTML with base64-embedded PNGs.
        figures = []
        for r in rendered:
            with open(r["path"], "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            label = r["view"].replace("_", " ").upper()
            figures.append(
                "<figure>"
                f'<img src="data:image/png;base64,{b64}" alt="{label}">'
                f"<figcaption>{label}</figcaption>"
                "</figure>"
            )

        notes_block = ""
        if notes:
            notes_block = (
                '<section class="notes"><h2>Notes</h2>'
                f"<pre>{html.escape(notes)}</pre></section>"
            )

        timestamp = time.strftime("%Y-%m-%d %H:%M")
        html_doc = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{html.escape(sheet_title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
           sans-serif; color: #111; max-width: 1400px;
           margin: 2rem auto; padding: 0 2rem; }}
  header {{ border-bottom: 1px solid #d0d0d0; padding-bottom: .75rem;
            margin-bottom: 2rem; }}
  header h1 {{ margin: 0; font-weight: 500; font-size: 1.6rem; }}
  header .meta {{ color: #666; font-size: .85rem; margin-top: .25rem; }}
  .views {{ display: grid; grid-template-columns: 1fr 1fr;
            gap: 1.25rem; }}
  figure {{ margin: 0; border: 1px solid #e0e0e0; padding: .5rem;
            background: #fafafa; }}
  figure img {{ width: 100%; display: block; background: #fff; }}
  figcaption {{ text-align: center; font-size: .75rem; color: #555;
                margin-top: .35rem; letter-spacing: .15em; }}
  .notes {{ margin-top: 2rem; padding-top: 1rem;
            border-top: 1px solid #e0e0e0; }}
  .notes h2 {{ font-size: 1rem; font-weight: 500; margin: 0 0 .5rem; }}
  .notes pre {{ font-family: inherit; white-space: pre-wrap;
                margin: 0; color: #333; }}
  @media print {{
    body {{ max-width: none; margin: 0; padding: 1cm; }}
    .views {{ gap: .5cm; }}
    figure {{ break-inside: avoid; }}
  }}
</style>
</head><body>
<header>
  <h1>{html.escape(sheet_title)}</h1>
  <div class="meta">{html.escape(doc_name)} * {timestamp}</div>
</header>
<section class="views">{"".join(figures)}</section>
{notes_block}
</body></html>
"""
        html_path = os.path.join(output_dir, "view_sheet.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_doc)

        # Sidecar manifest - machine-readable record of what was emitted.
        manifest = {
            "title": sheet_title,
            "document": doc_name,
            "views": rendered,
            "html_path": html_path,
            "image_size": [width, height],
        }
        with open(os.path.join(output_dir, "manifest.json"), "w") as f:
            _json.dump(manifest, f, indent=2)

        return {
            "html_path": html_path,
            "output_dir": output_dir,
            "views": rendered,
            "title": sheet_title,
            "image_size": [width, height],
        }

    def export(
        self,
        format: str | None = None,
        body_name: str | None = None,
        file_path: str | None = None,
    ):
        """Unified export — dispatches to export_stl/export_step/export_f3d."""
        fmt = format.lower() if format else None
        if not fmt and file_path:
            fmt = os.path.splitext(file_path)[1].lstrip(".").lower()
        if not fmt:
            raise RuntimeError(
                "Specify format (stl/step/f3d) or file_path with extension"
            )

        if fmt == "stl":
            if not body_name:
                raise RuntimeError("body_name required for STL export")
            return self.export_stl(body_name, file_path)
        if fmt in ("step", "stp"):
            if not body_name:
                raise RuntimeError("body_name required for STEP export")
            return self.export_step(body_name, file_path)
        if fmt == "f3d":
            return self.export_f3d(file_path)

        raise RuntimeError(f"Unknown format: {fmt}. Expected: stl, step, f3d")

    def import_mesh(
        self, file_path: str, component_name: str | None = None, units: str = "mm"
    ):
        """Import mesh file (STL/OBJ/3MF) as mesh body. Values returned in cm."""
        if not os.path.exists(file_path):
            raise RuntimeError(f"Mesh file not found: {file_path}")

        target = (
            self._component_by_name(component_name) if component_name else self._root()
        )

        unit_map = {
            "mm": adsk.fusion.MeshUnits.MillimeterMeshUnit,
            "cm": adsk.fusion.MeshUnits.CentimeterMeshUnit,
            "m": adsk.fusion.MeshUnits.MeterMeshUnit,
            "in": adsk.fusion.MeshUnits.InchMeshUnit,
            "ft": adsk.fusion.MeshUnits.FootMeshUnit,
        }
        if units not in unit_map:
            raise RuntimeError(
                f"Unknown units '{units}'. Expected one of: {sorted(unit_map)}"
            )

        mesh_body = None  # bound by whichever import path below succeeds
        try:
            # MeshBodies.add(fullFilename, units) — the current API.
            # Returns a MeshBodyList (a file can contain several bodies).
            mesh_list = target.meshBodies.add(file_path, unit_map[units])
        except AttributeError:
            # Pre-2025 builds exposed this as addByFile returning one body.
            mesh_list = None
            mesh_body = target.meshBodies.addByFile(file_path, unit_map[units])
        if mesh_list is not None:
            if mesh_list.count == 0:
                raise RuntimeError(f"No mesh bodies imported from {file_path}")
            mesh_body = mesh_list.item(0)

        if mesh_body is None:
            raise RuntimeError(f"No mesh body imported from {file_path}")
        bb = mesh_body.boundingBox
        return {
            "imported": True,
            "file_path": file_path,
            "mesh_name": mesh_body.name,
            "component": target.name,
            "units": units,
            "bounding_box": {
                "min": [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z],
                "max": [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z],
                "size": [
                    bb.maxPoint.x - bb.minPoint.x,
                    bb.maxPoint.y - bb.minPoint.y,
                    bb.maxPoint.z - bb.minPoint.z,
                ],
            },
        }

    # Attributes stored as an angle, so ``units`` applies to them. Everything
    # else is a length in Fusion's internal unit, cm, and passes through.
    _JOINT_ANGLE_ATTRIBUTES = frozenset(
        {"rotationValue", "pitchValue", "yawValue", "rollValue"}
    )

    def patch_surface(
        self, sketch_name: str, profile_index: int = 0, continuity: str = "connected"
    ):
        root = self._root()
        sketch = self._sketch_by_name(sketch_name)

        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)

        patches = root.features.patchFeatures
        inp = patches.createInput(
            profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )

        sct = adsk.fusion.SurfaceContinuityTypes
        cont_map = {
            "connected": sct.ConnectedSurfaceContinuityType,
            "tangent": sct.TangentSurfaceContinuityType,
            "curvature": sct.CurvatureSurfaceContinuityType,
        }
        inp.boundaryContinuity = cont_map.get(continuity, cont_map["connected"])

        feat = patches.add(inp)
        return {"feature_name": feat.name, "continuity": continuity}

    def stitch_surfaces(self, body_names: list, tolerance: float = 0.01):
        root = self._root()
        bodies = adsk.core.ObjectCollection.create()
        for name in body_names:
            bodies.add(self._body_by_name(name))

        stitches = root.features.stitchFeatures
        inp = stitches.createInput(
            bodies,
            adsk.core.ValueInput.createByReal(tolerance),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        )
        feat = stitches.add(inp)
        return {"feature_name": feat.name, "body_count": len(body_names)}

    def thicken_surface(
        self, body_name: str, thickness: float, direction: str = "symmetric"
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        faces = adsk.core.ObjectCollection.create()
        for face in body.faces:
            faces.add(face)

        thickens = root.features.thickenFeatures
        inp = thickens.createInput(
            faces,
            adsk.core.ValueInput.createByReal(thickness),
            False,
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
            direction == "symmetric",
        )
        feat = thickens.add(inp)
        return {"feature_name": feat.name, "thickness": thickness}

    def ruled_surface(
        self,
        body_name: str,
        edge_index: int,
        distance: float = 1.0,
        rule_type: str = "normal",
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        edge = body.edges.item(edge_index)

        ruled = root.features.ruledSurfaceFeatures
        # The shipped signature is createInput(profile, distance, angle, type) and
        # it takes a Profile, not an edge: the two-argument edge form raises "Wrong
        # number or type of arguments" on every invocation.  Measured on 2706: a
        # sketch profile does NOT work here - a closed rectangle answers
        # "3 : face profiles not supported" and a bare sketch line "3 : invalid
        # profile for Ruled Surface Feature", despite the SDK's wording ("defines the
        # sketch geometry or edges").  A sheet body's free edge is the only source.
        profile = root.createBRepEdgeProfile(edge, True)
        # The schema's enum is advisory: a socket caller is not the schema, and mock
        # mode applies the same check, so both sides refuse the same value.
        refusal = _rules.rule_type_refusal(rule_type)
        if refusal is not None:
            raise refusal
        # ``rule_type_refusal`` accepts these keys, so anything else is already refused.
        ruled_type = {
            "tangent": adsk.fusion.RuledSurfaceTypes.TangentRuledSurfaceType,
            "normal": adsk.fusion.RuledSurfaceTypes.NormalRuledSurfaceType,
        }[rule_type]
        inp = ruled.createInput(
            profile,
            adsk.core.ValueInput.createByReal(distance),
            adsk.core.ValueInput.createByReal(0.0),
            ruled_type,
        )
        feat = ruled.add(inp)
        return {
            "feature_name": feat.name,
            "distance": distance,
            "rule_type": rule_type,
        }

    def trim_surface(self, body_name: str, tool_name: str):
        root = self._root()
        body = self._body_by_name(body_name)
        tool = self._body_by_name(tool_name)

        trims = root.features.trimFeatures
        inp = trims.createInput(body, tool)
        feat = trims.add(inp)
        return {"feature_name": feat.name}

    def create_flange(
        self,
        body_name: str,
        edge_index: int,
        height: float = 1.0,
        angle: float = 90,
        bend_radius: float | None = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        edge = body.edges.item(edge_index)

        flanges = root.features.flangeFeatures
        inp = flanges.createInput(edge, True)
        inp.angle = adsk.core.ValueInput.createByString(f"{angle} deg")
        inp.height = adsk.core.ValueInput.createByReal(height)
        if bend_radius:
            inp.bendRadius = adsk.core.ValueInput.createByReal(bend_radius)

        feat = flanges.add(inp)
        return {"feature_name": feat.name, "height": height, "angle": angle}

    def create_bend(
        self,
        body_name: str,
        bend_line_sketch: str | None = None,
        angle: float = 90,
        bend_radius: float | None = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        if bend_line_sketch:
            sketch = self._sketch_by_name(bend_line_sketch)
            bend_line = sketch.sketchCurves.sketchLines.item(0)

            bends = root.features.bendFeatures
            inp = bends.createInput(body, bend_line, True)
            inp.bendAngle = adsk.core.ValueInput.createByString(f"{angle} deg")
            if bend_radius:
                inp.bendRadius = adsk.core.ValueInput.createByReal(bend_radius)

            feat = bends.add(inp)
            return {"feature_name": feat.name, "angle": angle}
        else:
            raise RuntimeError("bend_line_sketch is required")

    def flat_pattern(self, body_name: str):
        root = self._root()
        body = self._body_by_name(body_name)

        flat_patterns = root.features.flatPatternFeatures
        inp = flat_patterns.createInput(body)
        feat = flat_patterns.add(inp)
        return {"feature_name": feat.name}

    def unfold(self, body_name: str, bend_indices: list | None = None):
        root = self._root()
        body = self._body_by_name(body_name)

        unfolds = root.features.unfoldFeatures

        bends = adsk.core.ObjectCollection.create()
        if bend_indices:
            for idx in bend_indices:
                # Get bend faces from sheet metal body
                bends.add(body.faces.item(idx))
        else:
            # Unfold all bends
            for face in body.faces:
                bends.add(face)

        # Find stationary face (first planar face)
        stationary = None
        for face in body.faces:
            if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
                stationary = face
                break

        if not stationary:
            raise RuntimeError("No planar face found for stationary face")

        inp = unfolds.createInput(bends, stationary)
        feat = unfolds.add(inp)
        return {"feature_name": feat.name}

    def _get_cam(self):
        """Get the CAM product from the active document.

        On recent Fusion builds the CAM product is only instantiated once
        the Manufacture workspace has been activated for the document, so
        activate it on demand instead of failing outright.  Note:
        itemByProductType *raises* when the product doesn't exist yet.
        """
        doc = self.app.activeDocument

        def _find_cam_product():
            try:
                return doc.products.itemByProductType("CAMProductType")
            except Exception:
                return None

        cam_product = _find_cam_product()
        if cam_product is None:
            ws = self.ui.workspaces.itemById("CAMEnvironment")
            if ws is not None:
                try:
                    ws.activate()
                    adsk.doEvents()
                except Exception as exc:
                    log.warning("Manufacture workspace activation failed: %s", exc)
                cam_product = _find_cam_product()

        if cam_product is None:
            raise RuntimeError(
                "No CAM workspace found. Open the Manufacturing workspace "
                "in Fusion 360 at least once to initialise it."
            )
        return cam_product

    def _find_setup(self, cam, name: str):
        for i in range(cam.setups.count):
            s = cam.setups.item(i)
            if s.name == name:
                return s
        raise RuntimeError(f"Setup '{name}' not found")

    def _find_operation(self, setup, name: str):
        for i in range(setup.operations.count):
            op = setup.operations.item(i)
            if op.name == name:
                return op
        raise RuntimeError(f"Operation '{name}' not found in setup '{setup.name}'")

    def cam_list_setups(self):
        cam = self._get_cam()
        result = []
        for i in range(cam.setups.count):
            setup = cam.setups.item(i)
            ops = []
            for j in range(setup.operations.count):
                ops.append(setup.operations.item(j).name)
            result.append(
                {
                    "name": setup.name,
                    "operations": ops,
                    "is_valid": setup.isValid,
                }
            )
        return {"setups": result, "count": len(result)}

    def cam_list_operations(self, setup_name: str):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)
        result = []
        for i in range(setup.operations.count):
            op = setup.operations.item(i)
            result.append(
                {
                    "name": op.name,
                    "has_toolpath": op.hasToolpath,
                    "is_valid": op.isValid,
                }
            )
        return {"setup": setup_name, "operations": result, "count": len(result)}

    def cam_get_operation_info(self, setup_name: str, operation_name: str):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)
        op = self._find_operation(setup, operation_name)

        info = {
            "name": op.name,
            "is_valid": op.isValid,
            "has_toolpath": op.hasToolpath,
        }

        if hasattr(op, "tool") and op.tool:
            tool = op.tool
            desc = tool.description if hasattr(tool, "description") else str(tool)
            info["tool"] = {"description": desc}

        if hasattr(op, "parameters"):
            params = {}
            for param in op.parameters:
                with suppress(Exception):
                    params[param.name] = param.expression
            info["parameters"] = params

        return info

    def cam_create_setup(
        self,
        body_name: str,
        name: str | None = None,
        operation_type: str = "milling",
        stock_mode: str = "relative_box",
        stock_offset_sides: float = 0,
        stock_offset_top: float = 0,
        stock_offset_bottom: float = 0,
    ):
        # Judged before any object exists: the refusal's hint says nothing was
        # written, so a setup must not already be in the tree when it fires.
        stock_offset_sides = _param_units.require_finite(stock_offset_sides)
        stock_offset_top = _param_units.require_finite(stock_offset_top)
        stock_offset_bottom = _param_units.require_finite(stock_offset_bottom)

        cam = self._get_cam()
        body = self._body_by_name(body_name)

        op_type_map = {
            "milling": adsk.cam.OperationTypes.MillingOperation,
            "turning": adsk.cam.OperationTypes.TurningOperation,
            "cutting": adsk.cam.OperationTypes.JetOperation,
        }
        op_type = op_type_map.get(operation_type)
        if op_type is None:
            raise RuntimeError(
                f"Unknown operation_type '{operation_type}' "
                "— use milling/turning/cutting"
            )

        setup_input = cam.setups.createInput(op_type)
        setup_input.models = [body]

        if name:
            setup_input.name = name

        setup = cam.setups.add(setup_input)

        # Stock parameters live on the created setup, not the input.
        # Names/enumeration values verified against Fusion 2705: the
        # "Relative size box" UI choice has the id 'default'.
        stock_mode_map = {
            "relative_box": "default",
            "fixed_box": "fixedbox",
            "relative_cylinder": "relativecylinder",
            "fixed_cylinder": "fixedcylinder",
            "from_solid": "solid",
        }
        applied_stock: dict[str, Any] = {}
        failed_stock: dict[str, Any] = {}
        if stock_mode:
            mode_id = stock_mode_map.get(stock_mode, stock_mode)
            if self._set_cam_parameter(setup, "job_stockMode", mode_id, by_string=True):
                applied_stock["stock_mode"] = mode_id
            else:
                failed_stock["stock_mode"] = stock_mode
        for param_name, value in (
            ("job_stockOffset", stock_offset_sides),
            ("job_stockOffsetTop", stock_offset_top),
            ("job_stockOffsetBottom", stock_offset_bottom),
        ):
            if value:
                if self._set_cam_parameter(setup, param_name, value):
                    applied_stock[param_name] = value
                else:
                    failed_stock[param_name] = value

        result = {
            "name": setup.name,
            "body": body_name,
            "operation_type": operation_type,
        }
        if applied_stock:
            result["stock_applied"] = applied_stock
        if failed_stock:
            result["stock_failed"] = failed_stock
            result["warning"] = (
                "Some stock parameters could not be applied — parameter "
                "names vary by Fusion build; inspect via cam_get_operation_info"
            )
        return result

    @staticmethod
    def _set_cam_parameter(target, param_name, value, by_string=False):
        """Set a CAM parameter on a setup or operation. Returns success.

        Raises ``ValueError`` for a non-finite numeric value — that is a bad
        argument, not an unavailable parameter name, and the two callers would
        otherwise report it as the latter.

        CAMParameter.value is read-only on current Fusion builds — values
        must be assigned via the ``expression`` property.  Enum parameters
        (e.g. tool_coolant) take quoted lowercase strings ('flood').
        """
        # Judged outside the try so a bad value classifies as INVALID_INPUT instead
        # of being reported as False - which both callers read as "that parameter
        # name is unavailable" and would answer by retrying the same value.
        value = _param_units.require_finite(value)
        try:
            params = getattr(target, "parameters", None)
            if params is None:
                return False
            p = params.itemByName(param_name)
            if p is None:
                return False
            p.expression = f"'{value}'" if by_string else str(value)
            return True
        except Exception as exc:
            log.debug("CAM parameter %s=%r failed: %s", param_name, value, exc)
            return False

    def cam_create_operation(
        self,
        setup_name: str,
        strategy: str,
        name: str | None = None,
        tool_number: int | None = None,
        tool_diameter: float | None = None,
        stepdown: float | None = None,
        stepover: float | None = None,
        feed_rate: float | None = None,
        spindle_speed: float | None = None,
        coolant: str = "flood",
    ):
        # Judged before the operation is created, so a refusal's hint ("nothing
        # was written") stays true: a bad value is not an unavailable name.
        for _numeric in (tool_number, stepdown, stepover, feed_rate, spindle_speed):
            _param_units.require_finite(_numeric)

        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)

        if tool_diameter is not None:
            raise RuntimeError(
                "tool_diameter cannot be set on an operation — tool geometry "
                "comes from a tool in the CAM tool library. Select the tool "
                "via tool_number instead."
            )

        op_input = setup.operations.createInput(strategy)
        if name:
            op_input.name = name

        op = setup.operations.add(op_input)
        if op is None:
            raise RuntimeError(
                f"Fusion rejected strategy '{strategy}' for setup '{setup_name}'"
            )

        # Operation parameters (stepdown, feeds, speeds...) only exist on
        # the created operation, keyed by strategy-dependent names.
        applied = {}
        failed = {}
        for param_name, value, by_string in (
            ("tool_number", tool_number, False),
            ("maximumStepdown", stepdown, False),
            ("maximumStepover", stepover, False),
            ("tool_feedCutting", feed_rate, False),
            ("tool_spindleSpeed", spindle_speed, False),
            ("tool_coolant", coolant, True),
        ):
            if value is None:
                continue
            if self._set_cam_parameter(op, param_name, value, by_string):
                applied[param_name] = value
            else:
                failed[param_name] = value

        result = {"name": op.name, "setup": setup_name, "strategy": strategy}
        if applied:
            result["parameters_applied"] = applied
        if failed:
            result["parameters_failed"] = failed
            result["warning"] = (
                "Some parameters are not available for this strategy — "
                "check available names via cam_get_operation_info"
            )
        return result

    def cam_generate_toolpath(
        self,
        setup_name: str | None = None,
        operation_name: str | None = None,
        generate_all: bool = False,
    ):
        cam = self._get_cam()

        if generate_all:
            future = cam.generateAllToolpaths(False)
            self._wait_future(future)
            return {"generated": True, "scope": "all"}

        if operation_name and setup_name:
            setup = self._find_setup(cam, setup_name)
            op = self._find_operation(setup, operation_name)
            future = cam.generateToolpath(op)
            self._wait_future(future)
            return {
                "generated": True,
                "scope": "operation",
                "operation": operation_name,
            }

        if setup_name:
            setup = self._find_setup(cam, setup_name)
            ops = adsk.core.ObjectCollection.create()
            for i in range(setup.operations.count):
                ops.add(setup.operations.item(i))
            future = cam.generateToolpath(ops)
            self._wait_future(future)
            return {"generated": True, "scope": "setup", "setup": setup_name}

        raise RuntimeError("Provide setup_name, operation_name, or generate_all=true")

    def cam_post_process(
        self,
        setup_name: str,
        operation_name: str | None = None,
        post_processor: str = "fanuc",
        output_folder: str | None = None,
        output_units: str = "mm",
    ):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)

        if not output_folder:
            output_folder = os.path.join(os.path.expanduser("~"), "Desktop")

        # Accept a full path to a .cps file, or resolve a short name against
        # the legacy local post folder when the build still provides one.
        if post_processor.endswith(".cps") or os.path.sep in post_processor:
            post_config = post_processor
        else:
            post_folder = getattr(cam, "genericPostFolder", None)
            if not post_folder:
                raise RuntimeError(
                    "This Fusion build has no local generic post folder "
                    "(posts are cloud-library based). Pass the full path to "
                    "the .cps file in 'post_processor' instead of a short "
                    "name."
                )
            post_config = os.path.join(post_folder, f"{post_processor}.cps")

        if not os.path.isfile(post_config):
            raise RuntimeError(f"Post processor not found: {post_config}")

        units = (
            adsk.cam.PostOutputUnitOptions.MillimetersOutput
            if output_units == "mm"
            else adsk.cam.PostOutputUnitOptions.InchesOutput
        )

        post_input = adsk.cam.PostProcessInput.create(
            setup_name, post_config, output_folder, units
        )
        post_input.isOpenInEditor = False

        if operation_name:
            op = self._find_operation(setup, operation_name)
            cam.postProcess(op, post_input)
        else:
            cam.postProcess(setup, post_input)

        return {
            "setup": setup_name,
            "post_processor": post_processor,
            "output_folder": output_folder,
            "units": output_units,
        }

    def render_view(
        self,
        view: str = "current",
        width: int = 1024,
        height: int = 768,
        fit: bool = True,
    ):
        """Save the active viewport to a PNG and return base64-encoded bytes.

        * ``view`` — ``"current"`` keeps the existing camera, or one of
          ``_VIEW_DIRS`` keys (iso, front, top, ...) to reposition first.
        * ``width``/``height`` — pixel dimensions.
        * ``fit`` — call viewport.fit() before capture so the model frames.

        If ``view != "current"``, the camera is restored to its prior state
        before returning so the user's view isn't disturbed.
        """
        viewport = self.app.activeViewport
        if viewport is None:
            raise RuntimeError("No active viewport")

        # Clamp dimensions — an oversized capture would stall the main
        # thread and produce an enormous base64 payload.
        width = max(16, min(int(width), 4096))
        height = max(16, min(int(height), 4096))

        repositioned = view != "current"
        if repositioned:
            spec = self._VIEW_DIRS.get(view)
            if spec is None:
                raise RuntimeError(
                    f"Unknown view '{view}'. "
                    f"Expected: current, {', '.join(self._VIEW_DIRS)}"
                )
            orig = viewport.camera
            orig_state = {
                "eye": (orig.eye.x, orig.eye.y, orig.eye.z),
                "target": (orig.target.x, orig.target.y, orig.target.z),
                "up": (orig.upVector.x, orig.upVector.y, orig.upVector.z),
                "type": orig.cameraType,
            }
            self._orient_camera(viewport, spec)

        try:
            if fit:
                with suppress(Exception):
                    # fit() can fail on empty designs; keep going
                    viewport.fit()

            # saveAsImageFile requires a real path; write to a tempfile.
            fd, path = tempfile.mkstemp(suffix=".png", prefix="fusion_render_")
            os.close(fd)
            try:
                ok = viewport.saveAsImageFile(path, int(width), int(height))
                if not ok or not os.path.exists(path):
                    raise RuntimeError("saveAsImageFile returned false")
                with open(path, "rb") as f:
                    data = f.read()
            finally:
                with suppress(Exception):
                    os.remove(path)
        finally:
            if repositioned:
                cam = viewport.camera
                cam.isSmoothTransition = False
                cam.cameraType = orig_state["type"]
                cam.eye = adsk.core.Point3D.create(*orig_state["eye"])
                cam.target = adsk.core.Point3D.create(*orig_state["target"])
                cam.upVector = adsk.core.Vector3D.create(*orig_state["up"])
                viewport.camera = cam
                with suppress(Exception):
                    viewport.refresh()

        return {
            "view": view,
            "width": width,
            "height": height,
            "image_format": "png",
            "image_base64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data),
        }

    def _orient_camera(self, viewport, spec):
        """Position the camera at a canonical view relative to the model.

        ``spec`` is ``(eye_dir, up_vec)`` from ``_VIEW_DIRS``.
        """
        eye_dir, up_vec = spec
        # _design(), not activeProduct: in the Manufacture workspace the active
        # product is CAM and has no rootComponent.  A view still renders without a
        # design - the target then stays at the origin - so a missing design is not
        # fatal here.
        try:
            design = self._design()
        except RuntimeError:
            design = None
        root = design.rootComponent if design is not None else None

        # Target is the model centroid (or origin if no bodies).
        target = adsk.core.Point3D.create(0.0, 0.0, 0.0)
        distance = 20.0
        if root is not None and root.bRepBodies.count > 0:
            with suppress(Exception):
                bbox = root.boundingBox
                if bbox is not None:
                    cx = (bbox.minPoint.x + bbox.maxPoint.x) * 0.5
                    cy = (bbox.minPoint.y + bbox.maxPoint.y) * 0.5
                    cz = (bbox.minPoint.z + bbox.maxPoint.z) * 0.5
                    target = adsk.core.Point3D.create(cx, cy, cz)
                    dx = bbox.maxPoint.x - bbox.minPoint.x
                    dy = bbox.maxPoint.y - bbox.minPoint.y
                    dz = bbox.maxPoint.z - bbox.minPoint.z
                    distance = max(dx, dy, dz, 1.0) * 2.5

        eye = adsk.core.Point3D.create(
            target.x + eye_dir[0] * distance,
            target.y + eye_dir[1] * distance,
            target.z + eye_dir[2] * distance,
        )
        up = adsk.core.Vector3D.create(up_vec[0], up_vec[1], up_vec[2])

        cam = viewport.camera
        cam.eye = eye
        cam.target = target
        cam.upVector = up
        cam.isSmoothTransition = False
        viewport.camera = cam
