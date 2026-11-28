"""
Export and perception commands: STL, STEP, f3d, the view sheet, render_view.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.

Two families share the module because both drive the export manager and the
camera, and no other domain touches either: the file exports (body STL and STEP,
the document as f3d, the mesh import) and the picture exports (``render_view``,
whose canonical views are ``_VIEW_DIRS`` on the base, and ``export_view_sheet``,
which renders them into a shareable HTML sheet).
"""


import base64
import math
import os
import tempfile
import time
from contextlib import suppress
from typing import TYPE_CHECKING

from . import fusion_api as adsk
from . import hints as _hints
from . import rules as _rules

if TYPE_CHECKING:  # pragma: no cover - the mixin's contract, for type checkers only
    # Not inherited at runtime: ``CommandHandler`` supplies the base.  The reason this
    # exists at all is stated once, above ``class HandlerBase``.
    from .handler_base import HandlerBase as _Contract
else:  # pragma: no cover - unchanged runtime hierarchy: ``object``
    _Contract = object


class ExportCommands(_Contract):

    def _export_body(self, kind: str, body_name: str, file_path: str | None) -> dict:
        """Export as STL or STEP: one body's mesh, or the component holding it.

        The two APIs disagree about more than the extension.  STL's factory takes
        ``(entity, path)``, accepts a body or its occurrence, and takes a mesh
        refinement.  STEP's takes ``(path, entity)`` and accepts **only a
        Component** - ``ExportManager.h`` says "Valid geometry for this is
        currently a Component object", and measured on 2706.1.17 a ``BRepBody``
        answers ``3 : invlid argument geometry``.  So STL is a body export and STEP
        is a component export, and each reply says which it wrote.
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

        if kind == "step":
            # The component that OWNS the body: there is no single-body STEP through
            # this factory, so the reply counts what went out rather than claiming
            # one body did.
            component = body.parentComponent
            step_options = export_mgr.createSTEPExportOptions(file_path, component)
            export_mgr.execute(step_options)
            written = component.bRepBodies.count
            report = {
                "exported": True,
                "body": body_name,
                "file_path": file_path,
                "scope": "component",
                "component": component.name,
                "bodies_in_component": written,
            }
            if written > 1:
                report["note"] = (
                    f"Step exports a component, not a body: {written} bodies from "
                    f"'{component.name}' were written. Isolate the body in its own "
                    "component to export one."
                )
            return report

        occurrence = body.assemblyContext  # None if the body is at root

        def options_for(entity):
            created = export_mgr.createSTLExportOptions(entity, file_path)
            created.meshRefinement = (
                adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
            )
            return created

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
        if target_refusal := _rules.export_target_refusal(
            {"format": fmt, "file_path": file_path}
        ):
            raise target_refusal
        # F3D exports the document, so it takes no body; the body check and the
        # narrowing assert behind it belong to the two body exports only.
        if fmt == "f3d":
            return self.export_f3d(file_path)
        if body_refusal := _rules.export_body_refusal(
            {"format": fmt, "body_name": body_name}
        ):
            raise body_refusal
        # export_body_refusal refused an empty name, which is what lets the two body
        # exports below take a str.
        assert body_name is not None

        if fmt == "stl":
            return self.export_stl(body_name, file_path)

        # export_target_refusal refused every format outside _rules.EXPORT_FORMATS,
        # and stl/f3d are dispatched above, so this is step or stp.
        return self.export_step(body_name, file_path)

    def import_mesh(
        self, file_path: str, component_name: str | None = None, units: str = "mm"
    ):
        """Import mesh file (STL/OBJ/3MF) as mesh body. Values returned in cm."""
        if not os.path.exists(file_path):
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Mesh file not found: {file_path}",
                hints=("Pass a path to a file that exists.",),
            )

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
                raise _hints.Refusal(
                    "FUSION_REFUSED",
                    f"No mesh bodies imported from {file_path}",
                    hints=(
                        "The file has no mesh body; check it in a viewer first.",
                    ),
                )
            mesh_body = mesh_list.item(0)

        if mesh_body is None:
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"No mesh body imported from {file_path}",
                hints=("The file has no mesh body; check it in a viewer first.",),
            )
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
            raise _hints.Refusal(
                "WORKSPACE_UNAVAILABLE",
                "No active viewport",
                hints=("Open a viewport in Fusion, then retry.",),
            )

        # Clamp dimensions — an oversized capture would stall the main
        # thread and produce an enormous base64 payload.
        width = max(16, min(int(width), 4096))
        height = max(16, min(int(height), 4096))

        repositioned = view != "current"
        if repositioned:
            # The schema enum refuses an unknown view in both modes; a socket caller
            # that bypasses it gets the KeyError naming the value it asked for.
            spec = self._VIEW_DIRS[view]
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
                    raise _hints.Refusal(
                        "FUSION_REFUSED",
                        "saveAsImageFile returned false",
                        hints=(
                            "Retry the export; if it recurs the viewport cannot "
                            "render this view.",
                        ),
                    )
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
