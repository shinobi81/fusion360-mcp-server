"""Surface and sheet-metal commands: patch, stitch, thicken, flange, unfold.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

from . import fusion_api as adsk
from . import rules as _rules


class SurfaceCommands:
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

        # Find stationary face (first planar face)
        stationary = None
        for face in body.faces:
            if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
                stationary = face
                break

        if not stationary:
            raise RuntimeError("No planar face found for stationary face")

        # createInput takes the stationary face alone; the bends go on the input.
        inp = unfolds.createInput(stationary)
        if bend_indices:
            inp.bendFaces = [body.faces.item(idx) for idx in bend_indices]
        else:
            inp.isUnfoldAllBends = True

        feat = unfolds.add(inp)
        return {"feature_name": feat.name}
