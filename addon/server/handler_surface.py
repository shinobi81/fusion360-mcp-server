"""Surface and sheet metal: ``patch_surface``, ``stitch_surfaces``,
``thicken_surface``, ``ruled_surface``, ``trim_surface``, ``create_flange``,
``create_bend``, ``flat_pattern``, ``unfold``.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import fusion_api as adsk
from . import rules as _rules

if TYPE_CHECKING:  # pragma: no cover - the mixin's contract, for type checkers only
    # This module is one of the mixins ``CommandHandler`` composes over
    # ``HandlerBase``, so ``self._root`` and friends exist at call time and not by
    # inheritance.  Naming the base under ``TYPE_CHECKING`` is what lets a checker
    # see that contract without the runtime hierarchy changing at all.
    from .handler_base import HandlerBase as _Contract
else:  # pragma: no cover - unchanged runtime hierarchy: ``object``
    _Contract = object


class SurfaceCommands(_Contract):
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
        # The shipped member is groupContinuity; the retired name is continuity.
        # Fusion accepts an unknown attribute name and ignores it, so a
        # misspelling here would be a silent no-op.
        inp.groupContinuity = cont_map.get(continuity, cont_map["connected"])

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
        # Shipped: createInput(inputFaces, thickness, isSymmetric, operation,
        # isChainSelection=True).  The fifth argument is left out so Fusion's
        # default applies; ThickenFeatureInput has no direction member, so
        # "positive" and "negative" both mean the same one-sided thicken.
        inp = thickens.createInput(
            faces,
            adsk.core.ValueInput.createByReal(thickness),
            direction == "symmetric",
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
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

    def trim_surface(
        self,
        body_name: str,
        keep: str,
        tool_name: str | None = None,
        tool_plane: str | None = None,
    ):
        """Trim a surface with a body or a base plane, keeping one side of it.

        ``TrimFeatures.createInput(trimTool)`` takes the tool alone
        (``Features/TrimFeatures.h:63``); the cells it computed are in
        ``bRepCells``, and for a trim a **selected** cell is *removed*
        (``Features/BRepCell.h:40-45``).  So ``keep`` is the complement of the
        selection: the cells on the kept side stay unselected.

        ``createInput`` opens a transaction that ``add`` closes; the header says
        leaving it open leaves Fusion in a bad state and can crash it, so every
        failure path cancels first.
        """
        root = self._root()
        target = self._body_by_name(body_name)
        if bool(tool_name) == bool(tool_plane):
            raise RuntimeError(
                "trim_surface needs exactly one of tool_name (a body) or "
                "tool_plane (xy, xz or yz)"
            )

        trims = root.features.trimFeatures
        if tool_name:
            tool = self._body_by_name(tool_name)
        # A patch body has no interior, so "inside" means nothing for it: the side
        # is its first planar face's normal, as for a plane.  Only a solid tool has
        # an inside, and only a solid target accepts one.
            kept = _keep_inside(keep) if tool.isSolid else _keep_positive(keep)
        else:
            tool = self._construction_plane(tool_plane)
            kept = _keep_positive(keep)

        inp = trims.createInput(tool)
        try:
            cells = inp.bRepCells
            for index in range(cells.count):
                cell = cells.item(index)
                centroid = cell.cellBody.physicalProperties.centerOfMass
                if tool_name and tool.isSolid:
                    on_kept_side = _inside_body(tool, centroid)
                elif tool_name:
                    on_kept_side = _on_positive_side(
                        _first_planar_face(tool), centroid
                    )
                else:
                    on_kept_side = _on_positive_side(tool, centroid)
                cell.isSelected = on_kept_side is not kept
            feat = trims.add(inp)
        except Exception:
            inp.cancel()
            raise
        return {"feature_name": feat.name, "body_name": target.name, "keep": keep}

    def create_flange(
        self,
        body_name: str,
        edge_index: int,
        distance: float = 1.0,
        angle: float = 90,
        bend_radius_override: float | None = None,
    ):
        """Edge flange: ``createEdgeFlangeInput(edges, distance)``, then the overrides.

        ``FlangeFeatures`` ships no ``createInput`` - the three builders are
        ``createBaseFlangeInput``, ``createContourFlangeInput`` and
        ``createEdgeFlangeInput`` (``SheetMetal/FlangeFeatures.h``) - and the
        input's length is ``distance``, written by ``createEdgeFlangeInput``
        itself.  ``bendRadiusOverride`` is a ``BendRadiusOverride`` object, so the
        radius goes through ``setOverride``; assigning to it raises, measured on
        2706.
        """
        root = self._root()
        body = self._body_by_name(body_name)
        edge = body.edges.item(edge_index)

        flanges = root.features.flangeFeatures
        inp = flanges.createEdgeFlangeInput(
            [edge], adsk.core.ValueInput.createByReal(distance)
        )
        inp.angle = adsk.core.ValueInput.createByString(f"{angle} deg")
        if bend_radius_override:
            inp.bendRadiusOverride.setOverride(
                adsk.core.ValueInput.createByReal(bend_radius_override)
            )

        feat = flanges.add(inp)
        return {
            "feature_name": feat.name,
            "distance": distance,
            "angle": angle,
        }

    def create_bend(
        self,
        body_name: str,
        stationary_face_index: int,
        bend_line_sketch: str,
        angle: float = 90,
        bend_radius: float | None = None,
        line_position: str = "center",
        allow_bend_relief: bool = True,
    ):
        """Fold along a sketch line: the shipped API is ``FoldFeatures``.

        ``root.features.bendFeatures`` does not exist on 2706 - the sketch-line
        bend is ``FoldFeatures.createInput(stationaryFace)`` followed by
        ``inp.bendLines.add(line, angle, position, relief)``
        (``SheetMetal/FoldFeatures.h:64``, ``FoldBendLineDefinitions.h:60``).
        The stationary face is a caller decision here rather than a guess: a fold
        about the wrong face bends the part the wrong way.
        """
        root = self._root()
        body = self._body_by_name(body_name)
        sketch = self._sketch_by_name(bend_line_sketch)
        if sketch.sketchCurves.sketchLines.count == 0:
            raise RuntimeError(f"{bend_line_sketch} has no line to bend along")
        bend_line = sketch.sketchCurves.sketchLines.item(0)

        positions = {
            "start": adsk.fusion.FoldBendLinePositionTypes
            .StartFoldBendLinePositionType,
            "center": adsk.fusion.FoldBendLinePositionTypes
            .CenterFoldBendLinePositionType,
            "end": adsk.fusion.FoldBendLinePositionTypes
            .EndFoldBendLinePositionType,
        }
        position = positions.get(line_position)
        if position is None:
            raise RuntimeError(
                f"line_position {line_position!r} is not one of "
                f"{', '.join(sorted(positions))}"
            )

        folds = root.features.foldFeatures
        inp = folds.createInput(body.faces.item(stationary_face_index))
        inp.bendLines.add(
            bend_line,
            adsk.core.ValueInput.createByString(f"{angle} deg"),
            position,
            allow_bend_relief,
        )
        if bend_radius:
            inp.bendRadiusOverride.setOverride(
                adsk.core.ValueInput.createByReal(bend_radius)
            )

        feat = folds.add(inp)
        return {
            "feature_name": feat.name,
            "angle": angle,
            "line_position": line_position,
        }

    def _stationary_face(self, body):
        """The face a flat pattern or an unfold stays fixed to: the first planar one.

        Both commands need it and Fusion's rules are the same for both - a flat
        pattern wants "a planar face in the sheet metal body that is on the top or
        bottom of the part" (``Component.h:351-352``), and the unfold's stationary
        face is what ``createInput`` takes (``UnfoldFeatures.h:63``).  A body with
        no planar face has nothing to fix, so the refusal is shared too.
        """
        for face in body.faces:
            if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
                return face
        raise RuntimeError("No planar face found for stationary face")

    def flat_pattern(self, body_name: str):
        root = self._root()
        body = self._body_by_name(body_name)

        # There is no flat-pattern feature collection: a component creates one.
        flat_pattern = root.createFlatPattern(self._stationary_face(body))
        return {"feature_name": flat_pattern.name}

    def unfold(self, body_name: str, bend_indices: list | None = None):
        root = self._root()
        body = self._body_by_name(body_name)

        unfolds = root.features.unfoldFeatures

        # createInput takes the stationary face alone; the bends go on the input.
        inp = unfolds.createInput(self._stationary_face(body))
        if bend_indices:
            inp.bendFaces = [body.faces.item(idx) for idx in bend_indices]
        else:
            inp.isUnfoldAllBends = True

        feat = unfolds.add(inp)
        return {"feature_name": feat.name}


_INSIDE_KEEPS = {"inside": True, "outside": False}
_PLANE_KEEPS = {"positive": True, "negative": False}


def _keep_inside(keep: str) -> bool:
    """Translate ``keep`` for a body tool, or refuse the word that does not fit.

    A body has an inside; a plane does not, so the two vocabularies are kept
    apart rather than one silently standing in for the other.
    """
    try:
        return _INSIDE_KEEPS[keep]
    except KeyError:
        raise RuntimeError(
            f"keep {keep!r} does not apply to a body tool - use one of "
            f"{', '.join(sorted(_INSIDE_KEEPS))}; a plane tool takes "
            f"{', '.join(sorted(_PLANE_KEEPS))}"
        ) from None


def _keep_positive(keep: str) -> bool:
    """Translate ``keep`` for a construction-plane tool: the side its normal names."""
    try:
        return _PLANE_KEEPS[keep]
    except KeyError:
        raise RuntimeError(
            f"keep {keep!r} does not apply to a plane tool - use one of "
            f"{', '.join(sorted(_PLANE_KEEPS))}; a body tool takes "
            f"{', '.join(sorted(_INSIDE_KEEPS))}"
        ) from None


def _inside_body(body, point) -> bool:
    """``BRepBody.pointContainment``: is the point inside the tool's solid?"""
    return (
        body.pointContainment(point)
        == adsk.fusion.PointContainment.PointInsidePointContainment
    )


def _first_planar_face(body):
    """The first planar face of a patch body - the plane a side is measured from."""
    for face in body.faces:
        if adsk.core.Plane.cast(face.geometry) is not None:
            return face
    raise RuntimeError(f"{body.name} has no planar face to take a side from")


def _on_positive_side(plane, point) -> bool:
    """Which side of the plane the point is on, relative to its normal."""
    geometry = adsk.core.Plane.cast(plane.geometry)
    if geometry is None:
        raise RuntimeError(f"{getattr(plane, 'name', 'the trim tool')} is not planar")
    normal, origin = geometry.normal, geometry.origin
    return (
        (point.x - origin.x) * normal.x
        + (point.y - origin.y) * normal.y
        + (point.z - origin.z) * normal.z
    ) >= 0
