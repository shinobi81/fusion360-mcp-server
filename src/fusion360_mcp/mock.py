"""
Mock responses for every Fusion 360 MCP command.

Used when the server is started with ``--mode mock`` so the full
tool→response pipeline can be tested without a running Fusion instance.
Every response includes ``"mode": "mock"`` so callers know it's simulated.

The envelope matches the real addon: success results carry ``ok: True``,
mutation results carry a ``deltas`` sub-dict, and an ``__mock_error__``
sentinel in params forces a classified error response for tests.  A refusal --
invalid input, or a value the addon itself refuses -- is that same classified
error envelope and carries no ``deltas``: nothing changed, so a failed mutation
must not read as work done.
"""

import math
import os
from typing import Any

from ._mutation_commands import MUTATION_COMMANDS, no_op_warning
from ._rules import (
    CAM_GEOMETRY_PARAMETERS,
    CAM_NO_TOOL_WARNING,
    CAM_STOCK_MODES,
    as_built_geometry_refusal,
    body_name_required_refusal,
    cam_geometry_refusal,
    cam_library_tool_refusal,
    cam_stock_mode_refusal,
    cam_strategy_refusal,
    cam_target_refusal,
    cam_tool_refusal,
    components_differ_refusal,
    construction_axis_name_refusal,
    construction_plane_angle_refusal,
    construction_plane_name_refusal,
    construction_plane_tangent_refusal,
    edge_selector_refusal,
    export_body_refusal,
    export_target_refusal,
    joint_geometry_refusal,
    joint_selector_refusal,
    keep_cells_refusal,
    perpendicular_axis_refusal,
    point3d_refusal,
    rigid_group_size_refusal,
    rule_type_refusal,
    sketch_plane_z_note,
    surface_tool_refusal,
    symmetry_line_refusal,
    target_body_refusal,
)
from .hints import Refusal
from .hints import classify as _classify

# Mutation commands that get a synthetic deltas payload in mock mode.  The set is
# the add-in's, mirrored into this package, so mock mode cannot attach deltas to a
# command real mode treats as read-only.
_MUTATION_MOCKS = MUTATION_COMMANDS

#: The box mock's one body occupies - ``_MOCK_DELTAS`` grows into it, and the unchanged
#: deltas below sit on it.
_MOCK_BOX = {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}

_MOCK_DELTAS = {
    "body_count_before": 0,
    "body_count_after": 1,
    "body_count_delta": 1,
    "mass_g_before": 0.0,
    "mass_g_after": 10.0,
    "mass_g_delta": 10.0,
    "bbox_before": None,
    "bbox_after": _MOCK_BOX,
}

#: The deltas for a mutation mock *ran nothing* for.  ``execute_code`` is the one: mock
#: executes no Python, so claiming the synthetic "a body appeared" would report a build
#: that never happened.  The numbers are mock's own scene - one body, 10 g, that box -
#: unchanged, which is why the judgement adds its warning, as the add-in does for a
#: script that touched nothing.  What mock cannot know is what the script *would* have
#: built; that is a divergence recorded in ``docs/ROADMAP.md``, not one this table can
#: fix.
_NO_CHANGE_DELTAS = {
    "body_count_before": 1,
    "body_count_after": 1,
    "body_count_delta": 0,
    "mass_g_before": 10.0,
    "mass_g_after": 10.0,
    "mass_g_delta": 0.0,
    "bbox_before": _MOCK_BOX,
    "bbox_after": _MOCK_BOX,
}


def _error_envelope(error_kind: str, hints: list[str], message: str) -> dict:
    """The envelope the addon returns when a command fails."""
    return {
        "ok": False,
        "error_kind": error_kind,
        "error_message": message,
        "hints": hints,
        "traceback": f"MockError: {message}",
        "mode": "mock",
    }


def _mock_error(message: str) -> dict:
    """The envelope for a failure mock mode reports by its message.

    ``error_kind`` and ``hints`` come from the same rules the addon classifies
    with, so mock mode reports a failure the way real mode would.
    """
    error_kind, hints = _classify(message)
    return _error_envelope(error_kind, hints, message)


def _refusal_error(refusal: Refusal) -> dict:
    """The envelope for a refusal ``rules`` already named.

    ``classify`` reads the kind off the refusal rather than matching its message
    again, so mock mode reports what the add-in decided instead of a guess at it.
    """
    error_kind, hints = _classify(refusal)
    return _error_envelope(error_kind, hints, str(refusal))


def _non_finite_error(value: Any) -> dict | None:
    """The addon's refusal of Infinity/NaN, or None for a usable value.

    ``math.isfinite`` is only meaningful for a number; a schema-invalid
    non-number is left alone here rather than guessed at.
    """
    # Mirrors parameter_units.require_finite: an int is always finite (and a huge
    # one raises OverflowError if converted to float), a non-number is left alone.
    if isinstance(value, int):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return _mock_error(f"invalid parameter value: {value} is not finite")
    return None


def mock_command(command_type: str, params: dict[str, Any] | None = None) -> dict:
    """Return a plausible mock response for *command_type*.

    If *params* contains ``__mock_error__`` (a string message), the response
    simulates an addon-side failure: ``ok: False`` plus a classified
    ``error_kind`` and contextual ``hints``.
    """
    params = params or {}

    forced = params.get("__mock_error__")
    if forced is not None:
        return _mock_error(str(forced))

    handler = _DISPATCH.get(command_type, _default_mock)
    result = handler(params)
    result.setdefault("ok", True)
    # A refusal carries no deltas: nothing changed, and the synthetic "body
    # appeared" numbers would claim otherwise.  ``undo`` is the other exception —
    # it removes work, so the synthetic "body appeared" deltas would read as a
    # growth and are exactly what an agent must not be told.
    if (
        result["ok"]
        and command_type in _MUTATION_MOCKS
        and "deltas" not in result
        and command_type != "undo"
    ):
        deltas = dict(
            _NO_CHANGE_DELTAS if command_type == "execute_code" else _MOCK_DELTAS
        )
        result["deltas"] = deltas
        # The same judgement the add-in makes, from the same table: a mock rehearsal
        # that changed nothing must say so, or an agent rehearsing here learns the
        # opposite of what real mode reports.  ``setdefault`` for the same reason as
        # there: a handler's own warning outranks this one.
        if (warning := no_op_warning(command_type, deltas)) is not None:
            result.setdefault("warning", warning)
    result["mode"] = "mock"
    return result


# ── individual mock handlers ──────────────────────────────────────────


def _ping(_p: dict) -> dict:
    return {"status": "pong"}


def _get_scene_info(_p: dict) -> dict:
    return {
        "design_name": "MockDesign",
        "bodies": ["Body1"],
        "sketches": ["Sketch1"],
        "features": ["Extrude1"],
        "components": ["RootComponent"],
    }


def _get_object_info(p: dict) -> dict:
    name = p.get("name", "Unknown")
    return {
        "name": name,
        "type": "BRepBody",
        "faces": 6,
        "edges": 12,
        "vertices": 8,
        "bounding_box": {"min": [0, 0, 0], "max": [1, 1, 1]},
    }


def _list_edges(p: dict) -> dict:
    """Two edges of a plate, in the shape the handler returns.

    ``limit`` is honoured here too: a mock that ignored it would report a
    truncated list as complete, which is the one thing the real response exists
    to make impossible.
    """
    edges = [
        {
            "index": 0,
            "start": [0.0, 0.0, 0.0],
            "end": [4.0, 0.0, 0.0],
            "midpoint": [2.0, 0.0, 0.0],
            "length": 4.0,
            "curve_type": "Line3D",
            "is_degenerate": False,
        },
        {
            "index": 1,
            "start": [4.0, 0.0, 0.0],
            "end": [4.0, 2.0, 0.0],
            "midpoint": [4.0, 1.0, 0.0],
            "length": 2.0,
            "curve_type": "Line3D",
        },
    ]
    requested = p.get("limit")
    limit = 200 if requested is None else max(1, int(requested))
    return {
        "body_name": p.get("body_name") or "Body1",
        "count": len(edges),
        "truncated": len(edges) > limit,
        "edges": edges[:limit],
    }


def _list_faces(p: dict) -> dict:
    """Two faces of a plate, in the shape the handler returns.

    One planar and one not, because the shape differs: only a planar face carries a
    ``normal``, and a mock that always emitted one would rehearse a key Fusion does not
    send. ``limit`` is honoured for the reason ``_list_edges`` honours it - a mock that
    reported a clipped list as complete would hide the one thing ``count``/``truncated``
    exist to say.
    """
    faces = [
        {
            "index": 0,
            "surface_type": "Plane",
            "is_planar": True,
            "area": 20.0,
            "centroid": [0.0, 0.0, 0.5],
            "normal": [0.0, 0.0, 1.0],
        },
        {
            "index": 1,
            "surface_type": "Cylinder",
            "is_planar": False,
            "area": 5.0,
            "centroid": [0.0, -2.5, 0.0],
        },
    ]
    requested = p.get("limit")
    limit = 200 if requested is None else max(1, int(requested))
    return {
        "body_name": p.get("body_name") or "Body1",
        "count": len(faces),
        "truncated": len(faces) > limit,
        "faces": faces[:limit],
    }


def _get_bounding_box(p: dict) -> dict:
    name = p.get("name", "Unknown")
    return {
        "found": True,
        "type": "body",
        "name": name,
        "min": [0.0, 0.0, 0.0],
        "max": [50.0, 30.0, 15.0],
        "size": [50.0, 30.0, 15.0],
        "center": [25.0, 15.0, 7.5],
    }


def _create_sketch(p: dict) -> dict:
    plane = p.get("plane", "xy")
    return {"sketch_name": f"Sketch_mock_{plane}", "plane": plane}


def _sketch_plane_fields(z_values: list) -> dict:
    """Mirror the add-in: a non-zero z is dropped, and saying so is not optional.

    Mock mode has no sketch plane, so the model position is the sketch position
    with z flattened — the point is that the same keys arrive as from Fusion.
    """
    dropped = [z for z in z_values if z]
    if not dropped:
        return {}
    return {
        "ignored_z": dropped[0] if len(dropped) == 1 else dropped,
        "note": sketch_plane_z_note(),
    }


def _draw_rectangle(p: dict) -> dict:
    x, y = p.get("origin_x", 0), p.get("origin_y", 0)
    return {
        "sketch_name": p.get("sketch_name") or "Sketch_mock_xy",
        "width": p.get("width", 1),
        "height": p.get("height", 1),
        "model_origin": [x, y, 0.0],
        **_sketch_plane_fields([p.get("origin_z", 0)]),
    }


def _draw_circle(p: dict) -> dict:
    x, y = p.get("center_x", 0), p.get("center_y", 0)
    return {
        "sketch_name": p.get("sketch_name") or "Sketch_mock_xy",
        "radius": p.get("radius", 1),
        "model_center": [x, y, 0.0],
        **_sketch_plane_fields([p.get("center_z", 0)]),
    }


def _draw_line(p: dict) -> dict:
    start = [p.get("start_x", 0), p.get("start_y", 0)]
    end = [p.get("end_x", 1), p.get("end_y", 1)]
    return {
        "sketch_name": p.get("sketch_name") or "Sketch_mock_xy",
        "start": start,
        "end": end,
        "model_start": [*start, 0.0],
        "model_end": [*end, 0.0],
        **_sketch_plane_fields([p.get("start_z", 0), p.get("end_z", 0)]),
    }


def _body_name_required_error(p: dict, field: str = "body_name") -> dict | None:
    """The add-in's refusal of a body lookup with no name, or None.

    ``handler_base._body_by_name`` refuses an empty name before Fusion is asked, and
    ``body_name_required_refusal`` is that same check, so mock mode answers it instead
    of reporting work a body-less lookup cannot do.  ``field`` names the tool parameter
    the handler passes in; the validator's own key is always ``body_name``, because the
    refusal's sentence is the same whichever parameter was short.
    """
    refusal = body_name_required_refusal({"body_name": p.get(field)})
    return None if refusal is None else _refusal_error(refusal)


def _target_body_error(p: dict) -> dict | None:
    """The add-in's refusal of ``target_body`` on a new body, or None.

    ``target_body_refusal`` is the handler's own check, wording included, because
    the hint rule matches on it.  An unknown body name is *not* refused here:
    mock mode has no design to look it up in — but an *empty* one is, because
    ``_resolve_target_body`` looks it up and ``_body_by_name`` refuses it.  A missing
    ``target_body`` is not refused: that is a new body, and the handler returns early.
    """
    refusal = target_body_refusal(p, p.get("operation", "new_body"))
    if refusal is not None:
        return _refusal_error(refusal)
    if p.get("target_body") == "":
        return _body_name_required_error(p, "target_body")
    return None


def _extrude(p: dict) -> dict:
    refused = _target_body_error(p)
    if refused is not None:
        return refused
    return {
        "body_name": "Body_mock",
        "sketch": p.get("sketch_name") or "Sketch_mock_xy",
        "height": p.get("height", 1),
        "operation": p.get("operation", "new_body"),
        "target_body": p.get("target_body"),
    }


def _revolve(p: dict) -> dict:
    refused = _target_body_error(p)
    if refused is not None:
        return refused
    return {
        "body_name": "Body_mock_revolve",
        "sketch": p.get("sketch_name") or "Sketch_mock_xy",
        "angle": p.get("angle", 360),
        "operation": p.get("operation", "new_body"),
        "target_body": p.get("target_body"),
    }


def _edge_selector_error(p: dict) -> dict | None:
    """The add-in's refusals of an edge-selector combination, or None.

    Mock mode cannot search a body, so it cannot tell which edges a selection
    matches — but the *combination* rules, the element types and the four
    ``edge_selection`` values are pure parameter checks that ``_select_edges`` makes
    before it examines an edge, and ``edge_selector_refusal`` is where both sides
    make them: mock mode refuses a fifth value because it is the same check.
    Echoing an accepted call here would teach a sequence Fusion refuses.

    These fire inside ``_select_edges``, not before the body lookup: ``fillet``
    resolves ``body_name`` first, so a call with both a bad body and a bad selector
    answers ``BODY_NOT_FOUND`` in real mode and ``INVALID_INPUT`` here.  Mock mode
    has no bodies to look up, so that difference cannot be removed.
    """
    refusal = edge_selector_refusal(p)
    return None if refusal is None else _refusal_error(refusal)


def _selected_edge_count(p: dict) -> int:
    """How many edges the call named, so the echo matches the real response.

    Mock mode cannot search a body, but it must not report "all edges" for a
    call that named three: ``edges_count`` is what a caller checks its own
    sequence against.  A refused call never reaches here — see
    ``_edge_selector_error``.
    """
    indices = p.get("edge_indices")
    if indices is not None:
        return len(dict.fromkeys(int(i) for i in indices))
    points = p.get("edge_points")
    if points is not None:
        return len(points)
    return 12  # a plausible whole-body count for edge_selection "all"


def _fillet(p: dict) -> dict:
    refusal = _edge_selector_error(p)
    if refusal is not None:
        return refusal
    return {
        "body_name": p.get("body_name", "Body1"),
        "radius": p.get("radius", 0.1),
        "edges_count": _selected_edge_count(p),
    }


def _chamfer(p: dict) -> dict:
    refusal = _edge_selector_error(p)
    if refusal is not None:
        return refusal
    return {
        "body_name": p.get("body_name", "Body1"),
        "distance": p.get("distance", 0.1),
        "edges_count": _selected_edge_count(p),
    }


_SHELL_SELECTIONS = ("top", "bottom")


def _shell(p: dict) -> dict:
    # Same order as the handler: the wall is judged before the selection, so a call
    # wrong in both ways reports the same first error here as in Fusion.  Fusion
    # answers a wall of zero or less with an opaque "3 : Some input argument is
    # invalid.", which is why the handler - and this - refuse it first.
    thickness = p.get("thickness", 0.1)
    refusal = _non_finite_error(thickness)
    if refusal is not None:
        # The handler prepends the field, so mock reports the same sentence.
        return _mock_error(
            f"thickness must be finite, in cm: {refusal['error_message']}"
        )
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)):
        return _mock_error(
            f"thickness must be a positive number in cm, got {thickness!r}"
        )
    if thickness <= 0:
        return _mock_error(
            f"thickness must be a positive number in cm, got {thickness!r} - a "
            "shell removes material, so the wall has to be a real distance"
        )

    selection = p.get("face_selection", "top")
    if selection not in _SHELL_SELECTIONS:
        return _mock_error(f"Unknown face_selection '{selection}' — use top/bottom")
    return {
        "body_name": p.get("body_name", "Body1"),
        "thickness": p.get("thickness", 0.1),
        "face_selection": selection,
    }


def _mirror(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "mirror_plane": p.get("mirror_plane", "yz"),
        "new_body_name": "Body1_mirrored",
    }


def _rename_body(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "renamed": True,
        "old_name": p.get("body_name", "Body1"),
        "new_name": p.get("new_name", "RenamedBody"),
    }


def _move_body(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "translation": [p.get("x", 0), p.get("y", 0), p.get("z", 0)],
    }


def _export_stl(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    name = p.get("body_name", "Body1")
    path = p.get("file_path", f"~/Desktop/{name}.stl")
    return {"body_name": name, "file_path": path}


def _boolean_operation(p: dict) -> dict:
    # Both names go straight into ``_body_by_name``, target first as the handler does.
    for field in ("target_body", "tool_body"):
        refused = _body_name_required_error(p, field)
        if refused is not None:
            return refused
    return {
        "target_body": p.get("target_body", "Body1"),
        "tool_body": p.get("tool_body", "Body2"),
        "operation": p.get("operation", "join"),
        # Echoed raw, like the add-in: coercing here would report ``True`` for a
        # malformed ``"false"`` that Fusion would reject.
        "keep_tool": p.get("keep_tool", False),
        "result_body": p.get("target_body", "Body1"),
    }


def _delete_all(_p: dict) -> dict:
    # Mock's scene is one body; sweeping it leaves nothing, which is the one command
    # whose real effect the synthetic "a body appeared" would invert.
    return {
        "deleted": True,
        "deltas": {
            "body_count_before": 1,
            "body_count_after": 0,
            "body_count_delta": -1,
            "mass_g_before": 10.0,
            "mass_g_after": 0.0,
            "mass_g_delta": -10.0,
            "bbox_before": _MOCK_BOX,
            "bbox_after": None,
        },
    }


def _undo(_p: dict) -> dict:
    return {
        "undone": "issued",
        "verified": False,
        "design_type": "direct",
        "note": (
            "Mock mode has no timeline, so this mirrors the direct-design path: "
            "the real add-in steps a parametric design's timeline marker back "
            "and reports verified: true."
        ),
        "hints": ["Fusion's undo is asynchronous; confirm with get_scene_info."],
    }


def _execute_code(p: dict) -> dict:
    return {"executed": True, "code": p.get("code", ""), "result": "None", "output": ""}


# ── design type safety ───────────────────────────────────────────────


def _get_design_type(_p: dict) -> dict:
    return {"design_type": "parametric", "design_type_id": 1}


def _set_design_type(p: dict) -> dict:
    dt = p.get("design_type", "parametric")
    return {"changed": True, "design_type": dt}


# ── new geometry tools ────────────────────────────────────────────────


def _sweep(p: dict) -> dict:
    refused = _target_body_error(p) or _curve_index_error(p, ("path_curve_index",))
    if refused is not None:
        return refused
    return {
        "body_name": "Body_mock_sweep",
        "sketch": p.get("sketch_name") or "Sketch_mock_xy",
        "path_sketch_name": p.get("path_sketch_name", "PathSketch"),
        "operation": p.get("operation", "new_body"),
        "target_body": p.get("target_body"),
    }


def _loft(p: dict) -> dict:
    refused = _target_body_error(p)
    if refused is not None:
        return refused
    names = p.get("profile_sketch_names")
    # The schema requires two, but a raw socket caller is not the schema. A
    # *missing* list is left alone: real mode rejects that in dispatch before the
    # handler sees it, so refusing here would invent a failure real mode cannot
    # produce (and would break the deltas guard for every empty-params mock).
    if names is not None and len(names) < 2:
        return _mock_error(
            f"Invalid input: a loft needs at least two profiles — got {len(names)}"
        )
    return {
        "body_name": "Body_mock_loft",
        "profile_sketch_names": names or [],
        "operation": p.get("operation", "new_body"),
        "target_body": p.get("target_body"),
    }


def _create_polygon(p: dict) -> dict:
    x, y = p.get("center_x", 0), p.get("center_y", 0)
    return {
        "sketch_name": p.get("sketch_name") or "Sketch_mock_xy",
        "sides": p.get("sides", 6),
        "radius": p.get("radius", 1),
        "model_center": [x, y, 0.0],
        **_sketch_plane_fields([p.get("center_z", 0)]),
    }


def _draw_circles(p: dict) -> dict:
    count = p.get("count", 1)
    return {
        "sketch": p.get("sketch_name") or "Sketch_mock_xy",
        "added": count,
        "total_curves": count,
        "radius": p.get("radius", 1),
        "spacing": p.get("spacing", 1),
        "axis": p.get("axis", "x"),
    }


def _draw_arc(p: dict) -> dict:
    return {
        "sketch_name": p.get("sketch_name") or "Sketch_mock_xy",
        "center": [p.get("center_x", 0), p.get("center_y", 0)],
        "sweep_angle": p.get("sweep_angle", 90),
        "model_center": [p.get("center_x", 0), p.get("center_y", 0), 0.0],
        **_sketch_plane_fields([p.get("center_z", 0), p.get("start_z", 0)]),
    }


def _create_hole(p: dict) -> dict:
    body = p.get("body_name") or f"Body{p.get('body_index', 0) + 1}"
    diameter = p.get("diameter", 0.5)
    return {
        "feature_name": "Hole_mock",
        "body_name": body,
        "diameter": diameter,
        "depth": p.get("depth", 1),
        "actual_diameter": diameter,
        "resolved_center": [p.get("center_x", 0), p.get("center_y", 0), 0.0],
    }


def _rectangular_pattern(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "x_count": p.get("x_count", 1),
        "y_count": p.get("y_count", 1),
        "created_bodies": p.get("x_count", 1) * p.get("y_count", 1),
    }


def _circular_pattern(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    # "z" mirrors circular_pattern's own default in handler_features.
    axis_refusal = construction_axis_name_refusal(p.get("axis", "z"))
    if axis_refusal is not None:
        return _refusal_error(axis_refusal)
    # The handler answers `feature_name`, `count` and `total_angle` - not the body name
    # or the axis it was given, which an agent would then read back as a fact.
    return {
        "feature_name": "CircularPattern_mock",
        "count": p.get("count", 3),
        "total_angle": p.get("total_angle", 360),
    }


# ── assembly tools ────────────────────────────────────────────────────


def _create_component(p: dict) -> dict:
    return {
        "component_name": p.get("name", "Component1"),
        "parent": p.get("parent_name", "RootComponent"),
    }


def _add_joint(p: dict) -> dict:
    # The order is the handler's: the selector refusal is raised before anything reads
    # the design, so a call with two faults earns the same sentence on both sides.
    refusal = (
        joint_selector_refusal(p)
        or components_differ_refusal(p)
        or joint_geometry_refusal(p)
    )
    if refusal is not None:
        return _refusal_error(refusal)
    return {
        "component_one": p.get("component_one", "Comp1"),
        "component_two": p.get("component_two", "Comp2"),
        "joint_type": p.get("joint_type", "rigid"),
        "joint_name": "Joint_mock",
    }


# value_kind -> (motion, attribute, unit), mirroring what the add-in resolves
# from the joint's motion type. The mock holds no design, so it resolves from the
# kind; a rotationValue/degrees pair for every kind would give the slide values,
# which are lengths in centimetres, the wrong unit.
_MOCK_JOINT_VALUES: dict[str, tuple[str, str, str]] = {
    "rotation": ("RevoluteJointMotion", "rotationValue", "deg"),
    "slide": ("SliderJointMotion", "slideValue", "cm"),
    "primary_slide": ("PlanarJointMotion", "primarySlideValue", "cm"),
    "secondary_slide": ("PlanarJointMotion", "secondarySlideValue", "cm"),
    "pitch": ("BallJointMotion", "pitchValue", "deg"),
    "yaw": ("BallJointMotion", "yawValue", "deg"),
    "roll": ("BallJointMotion", "rollValue", "deg"),
}
_MOCK_JOINT_DEFAULT = ("RevoluteJointMotion", "rotationValue", "deg")


def _set_joint_value(p: dict) -> dict:
    value_kind = p.get("value_kind")
    motion, attribute, unit = _MOCK_JOINT_VALUES.get(
        value_kind or "", _MOCK_JOINT_DEFAULT
    )
    return {
        "joint_name": p.get("joint_name", "Joint_mock"),
        "motion": motion,
        "value_kind": value_kind,
        "attribute": attribute,
        "value": p.get("value", 0),
        "units": unit if unit == "cm" else p.get("units", "deg"),
        "read_back": p.get("value", 0),
        "applied": True,
    }


def _list_components(_p: dict) -> dict:
    return {
        "components": [
            {"name": "RootComponent", "bodies": ["Body1"]},
            {"name": "SubComponent1", "bodies": []},
        ],
    }


# ── export tools ──────────────────────────────────────────────────────


def _export_step(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    name = p.get("body_name", "Body1")
    path = p.get("file_path", f"~/Desktop/{name}.step")
    return {"body_name": name, "file_path": path}


def _export_f3d(p: dict) -> dict:
    path = p.get("file_path", "~/Desktop/MockDesign.f3d")
    return {"file_path": path}


def _export_view_sheet(p: dict) -> dict:
    views = p.get("views") or ["iso", "front", "top", "right"]
    size = p.get("image_size") or [1200, 900]
    out = p.get("output_dir", "~/Desktop/MockDesign_views_mock")
    title = p.get("title", "MockDesign")
    return {
        "html_path": f"{out}/view_sheet.html",
        "output_dir": out,
        "title": title,
        "image_size": list(size),
        "views": [{"view": v, "path": f"{out}/{v}.png"} for v in views],
    }


def _export(p: dict) -> dict:
    # Both checks are the add-in's, in its order: no usable format is judged before
    # the body the format would need.  ``export_stl``/``export_step`` refuse an empty
    # body name themselves, through ``_body_by_name``.
    for refusal in (export_target_refusal(p), export_body_refusal(p)):
        if refusal is not None:
            return _refusal_error(refusal)
    fmt = (p.get("format") or "").lower()
    path = p.get("file_path", "")
    if not fmt and path:
        fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    name = p.get("body_name", "Body1")
    return {
        "exported": True,
        "format": fmt or "f3d",
        "body": name,
        "file_path": path or f"~/Desktop/{name}.{fmt or 'f3d'}",
    }


def _import_mesh(p: dict) -> dict:
    path = p.get("file_path", "/tmp/mesh.stl")
    units = p.get("units", "mm")
    component = p.get("component_name") or "RootComponent"
    return {
        "imported": True,
        "file_path": path,
        "mesh_name": "MeshBody_mock",
        "component": component,
        "units": units,
        "bounding_box": {
            "min": [0.0, 0.0, 0.0],
            "max": [10.0, 5.0, 2.0],
            "size": [10.0, 5.0, 2.0],
        },
    }


def _create_box_parametric(p: dict) -> dict:
    # The add-in refuses a non-finite dimension or extent at method entry, so
    # mock mode must not report success for a value Fusion would never accept.
    for key in ("length", "width", "height", "origin_x", "origin_y", "origin_z"):
        refusal = _non_finite_error(p.get(key, 0))
        if refusal is not None:
            return refusal
    return {
        "created": True,
        "body_name": p.get("body_name") or "BoxParametric_mock",
        "feature_name": "Extrude_mock",
        "sketch_name": "Sketch_mock",
        "length": p.get("length", 1),
        "width": p.get("width", 1),
        "height": p.get("height", 1),
        "origin": [
            p.get("origin_x", 0),
            p.get("origin_y", 0),
            p.get("origin_z", 0),
        ],
        "plane": p.get("plane", "xy"),
        "component": p.get("component_name") or "RootComponent",
    }


# ── parameter tools ───────────────────────────────────────────────────


def _get_parameters(_p: dict) -> dict:
    return {
        "parameters": [
            {"name": "width", "value": 10.0, "unit": "mm", "comment": ""},
            {"name": "height", "value": 5.0, "unit": "mm", "comment": ""},
        ],
    }


def _create_parameter(p: dict) -> dict:
    value = p.get("value", 0)
    # The addon refuses Infinity/NaN before either ValueInput factory, so mock
    # mode refuses them too instead of returning an "inf mm" expression.
    error = _non_finite_error(value)
    if error is not None:
        return error
    # The addon trims the unit and treats blank as unitless; mirror both so
    # mock and real modes agree. "unit" is required by the schema, so the
    # default only covers a caller that omitted it entirely.
    unit = ("mm" if p.get("unit") is None else p["unit"]).strip()
    return {
        "created": True,
        "name": p.get("name", "param1"),
        "value": value,
        "unit": unit,
        "expression": f"{value} {unit}" if unit else f"{value}",
        "comment": p.get("comment", ""),
    }


def _set_parameter(p: dict) -> dict:
    error = _non_finite_error(p.get("value", 0))
    if error is not None:
        return error
    # The real handler reports the unit the target parameter already declares
    # and the expression Fusion stored. Mock mode holds no design, so it
    # cannot know either -- report null rather than invent "mm".
    return {
        "updated": True,
        "name": p.get("name", "param1"),
        "value": p.get("value", 0),
        "unit": None,
        "expression": None,
    }


def _delete_parameter(p: dict) -> dict:
    return {"name": p.get("name", "param1"), "deleted": True}


# ── sketch constraints & dimensions ───────────────────────────────────


def _curve_index_error(p: dict, fields: tuple[str, ...]) -> dict | None:
    """The index checks the add-in makes before it reads a sketch, or None.

    Mock mode has no sketch, so it cannot know whether an index is past the end -
    but a negative index, a fractional one and a boolean are invalid in *every*
    sketch, and the handler refuses them before it touches geometry.  Echoing one
    would teach a sequence Fusion answers differently: ``-1`` wraps to the last
    curve, so a caller of ``-1`` dimensioned the last curve and got ``ok: true``
    (measured live).

    Every mock handler that takes a curve index calls this - the six the add-in
    guards - so mock mode cannot answer ``ok`` for an index real mode refuses.
    """
    for field in fields:
        index = p.get(field)
        if index is None:
            continue
        if isinstance(index, bool) or not isinstance(index, int):
            return _mock_error(
                f"{field} must be a whole-number curve index, got {index!r}"
            )
        if index < 0:
            return _mock_error(
                f"{field} {index} is outside sketch '{p.get('sketch_name', 'Sketch1')}'"
                " - curve indices are 0-based, and a negative one is refused "
                "rather than wrapped"
            )
    return None


def _add_constraint(p: dict) -> dict:
    # First, because the handler refuses it before it reads a sketch: a symmetry call
    # short of its mirror line is a parameter problem, not a sketch one.
    if symmetry := symmetry_line_refusal(p):
        return _refusal_error(symmetry)
    refused = _entity_shape_error(
        p, "constraint", _CONSTRAINT_NEEDS_TWO, "constraint_type"
    ) or _curve_index_error(p, ("entity_one", "entity_two", "symmetry_line"))
    if refused is not None:
        return refused
    return {
        "constraint_type": p.get("constraint_type", "coincident"),
        "entity_one": p.get("entity_one", 0),
        "entity_two": p.get("entity_two", 1),
        "sketch_name": p.get("sketch_name", "Sketch1"),
    }


def _auto_constrain(p: dict) -> dict:
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "is_fully_constrained": True,
        "constraints_added": 4,
        "dimensions_added": 2,
        "entities_moved": 0,
        "result_option": p.get("result_option", 1),
    }


#: Which entities each dimension type needs.  The add-in's table, mirrored: mock
#: mode is where an agent develops the sequence it replays, so a shape real mode
#: refuses must not come back ``ok`` here.  A parity test drives both.
_DIMENSION_NEEDS_TWO: dict[str, bool] = {
    "distance": True,
    "horizontal": True,
    "vertical": True,
    "angular": True,
    "radial": False,
    "diameter": False,
}

#: The same for constraints: every type needs ``entity_two`` except these three.
_CONSTRAINT_NEEDS_TWO: dict[str, bool] = {
    "coincident": True,
    "parallel": True,
    "perpendicular": True,
    "tangent": True,
    "equal": True,
    "fix": False,
    "horizontal": False,
    "vertical": False,
    "concentric": True,
    "collinear": True,
    "smooth": True,
    "midpoint": True,
    "symmetry": True,
}


def _entity_shape_error(
    p: dict, tool: str, table: dict[str, bool], type_field: str
) -> dict | None:
    """The entity-count check the add-in makes per type, or None.

    Mock mode has no sketch, so it cannot know an index is past the end - but it
    does know which types take one entity and which take two, and that is a shape
    check, not a geometry one.  ``addParallel(e1, None)`` reaches Fusion and reports
    success; mock mode should not teach the same call.
    """
    kind = p.get(type_field)
    needs_two = table.get(kind) if isinstance(kind, str) else None
    if needs_two is None:
        return {
            "ok": False,
            "error_kind": "INVALID_INPUT",
            "error_message": (
                f"Unknown {type_field.replace('_type', '')} type: {kind} "
                f"(expected one of {', '.join(sorted(table))})"
            ),
            "hints": [f"Choose one of: {', '.join(sorted(table))}."],
        }
    if p.get("entity_one") is None:
        return {
            "ok": False,
            "error_kind": "INVALID_INPUT",
            "error_message": (
                f"a {kind} {tool} needs entity_one - mock mode has no sketch, so "
                "the index itself is not checked here"
            ),
            "hints": ["Pass entity_one: every type takes a first entity."],
        }
    if needs_two and p.get("entity_two") is None:
        return {
            "ok": False,
            "error_kind": "INVALID_INPUT",
            "error_message": (
                f"a {kind} {tool} needs entity_two - mock mode has no sketch, so "
                "the index itself is not checked here"
            ),
            "hints": ["Pass entity_two: this type takes two entities."],
        }
    return None


def _add_dimension(p: dict) -> dict:
    refusal = _entity_shape_error(
        p, "dimension", _DIMENSION_NEEDS_TWO, "dimension_type"
    ) or _curve_index_error(p, ("entity_one", "entity_two"))
    if refusal is not None:
        return refusal
    return {
        "dimension_type": p.get("dimension_type", "distance"),
        "value": p.get("value", 1.0),
        "entity_one": p.get("entity_one", 0),
        "sketch_name": p.get("sketch_name", "Sketch1"),
    }


# ── construction geometry ─────────────────────────────────────────────


def _create_construction_plane(p: dict) -> dict:
    refusal = construction_plane_tangent_refusal(p)
    if refusal is None and p.get("method") == "three_points":
        # The add-in builds a Point3D per point on this branch only, so the points an
        # offset or midplane call leaves unset are not judged.
        refusal = point3d_refusal(
            {
                "point_one": p.get("point_one"),
                "point_two": p.get("point_two"),
                "point_three": p.get("point_three"),
            }
        )
    if refusal is not None:
        return _refusal_error(refusal)
    if p.get("method") == "tangent":
        # The tangent branches name a body, and `_body_by_name` refuses an empty name
        # before Fusion is asked - and *before* the plane is resolved, which is the
        # handler's order too.  The same split the axis makes for its body branches.
        refused = _body_name_required_error(p)
        if refused is not None:
            return refused
    # Only the names the chosen branch resolves, in the handler's order: an unset one
    # is refused by the add-in ('' and None alike) and a name belonging to another
    # branch was never looked up.  A tangent call with a point never reads `plane` -
    # the point form takes none - so asking here would invent a fault.
    by_method: dict[str, tuple[str, ...]] = {
        "offset": ("plane",),
        "angle": ("plane",),
        "midplane": ("plane_one", "plane_two"),
        "tangent": () if p.get("point_one") is not None else ("plane",),
    }
    if p.get("method") == "angle":
        # The handler judges the same three names in this order: the angle (its own
        # rule, before the API call), then the axis ``setByAngle`` resolves first, then
        # the plane.  A call carrying two faults must get the *same* sentence from both
        # sides - the order, not just the rules, is part of the contract.
        angle_refusal = construction_plane_angle_refusal(p)
        if angle_refusal is not None:
            return _refusal_error(angle_refusal)
        # `or "x"` mirrors the handler's fallback (handler_assembly, the angle branch).
        axis_refusal = construction_axis_name_refusal(p.get("edge_name") or "x")
        if axis_refusal is not None:
            return _refusal_error(axis_refusal)
    resolved = by_method.get(str(p.get("method")), ())
    for field in resolved:
        name_refusal = construction_plane_name_refusal(p.get(field))
        if name_refusal is not None:
            return _refusal_error(name_refusal)
    # The handler's keys, as for the axis: `plane_name` was never one of them.
    return {
        "created": True,
        "name": "ConstructionPlane_mock",
        "method": p.get("method", "offset"),
    }


def _create_construction_axis(p: dict) -> dict:
    refusal = perpendicular_axis_refusal(p)
    if refusal is None and p.get("method") == "two_points":
        refusal = point3d_refusal(
            {
                "point_one": p.get("point_one"),
                "point_two": p.get("point_two"),
            }
        )
    if refusal is None and p.get("method") == "perpendicular_at_point":
        # One point, not two: the axis passes through it, normal to the face.
        refusal = point3d_refusal({"point_one": p.get("point_one")})
    if refusal is not None:
        return _refusal_error(refusal)
    if p.get("method") in ("edge", "perpendicular_at_point"):
        # The branches that name a body: the other two build from points or planes.
        refused = _body_name_required_error(p)
        if refused is not None:
            return refused
    # The handler's keys: `created`, the axis `name`, and the `method` it built from.
    # `axis_name` was a key no call ever returned.
    return {
        "created": True,
        "name": "ConstructionAxis_mock",
        "method": p.get("method", "two_points"),
    }


# ── splines ───────────────────────────────────────────────────────────


def _draw_spline(p: dict) -> dict:
    points = p.get("points", [])
    return {
        "sketch_name": p.get("sketch_name") or "Sketch_mock_xy",
        "spline_type": p.get("spline_type", "fit_points"),
        "point_count": len(points),
        "points_count": len(points),
        "model_points": [[pt[0], pt[1], 0.0] for pt in points],
        **_sketch_plane_fields([pt[2] for pt in points if len(pt) > 2 and pt[2]]),
    }


# ── sketch curve operations ──────────────────────────────────────────


def _offset_curve(p: dict) -> dict:
    refused = _curve_index_error(p, ("curve_index",))
    if refused is not None:
        return refused
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "offset_distance": p.get("offset_distance", 0.5),
        "new_curve_count": 4,
    }


def _trim_curve(p: dict) -> dict:
    refused = _curve_index_error(p, ("curve_index",))
    if refused is not None:
        return refused
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "curve_index": p.get("curve_index", 0),
        "trimmed": True,
    }


def _extend_curve(p: dict) -> dict:
    refused = _curve_index_error(p, ("curve_index",))
    if refused is not None:
        return refused
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "curve_index": p.get("curve_index", 0),
        "extended": True,
    }


# ── advanced features ─────────────────────────────────────────────────


def _create_thread(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    is_internal = p.get("is_internal", False)
    requested_class = p.get("thread_class")
    return {
        "feature_name": "Thread1",
        "body_name": p.get("body_name", "Body1"),
        "face_index": p.get("face_index", 0),
        "is_modeled": p.get("is_modeled", False),
        "thread_type": p.get("thread_type", "ISO Metric profile"),
        "thread_designation": p.get("thread_designation", "M10x1.5"),
        # The same conditional default the handler applies: ISO 965 gives internal
        # threads 6H and external ones 6g.
        "thread_class": (
            requested_class
            if requested_class is not None
            else ("6H" if is_internal else "6g")
        ),
        "is_internal": is_internal,
        # No face to measure here, so the size check cannot run; saying so is
        # better than reporting two diameters nobody measured.
        "note": (
            "mock mode has no face to measure, so the thread/face size check the "
            "add-in makes is skipped"
        ),
    }


def _draft_faces(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "angle": p.get("angle", 5),
        "face_count": 4,
    }


def _split_body(p: dict) -> dict:
    # ``splitting_body`` is guarded in the handler: empty means "cut with a plane".
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "result_bodies": ["Body1", "Body1_split"],
    }


def _split_face(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "faces_split": 2,
    }


def _offset_faces(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "distance": p.get("distance", 0.5),
    }


def _scale_body(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Body1"),
        "scale": p.get("scale", 1.0),
    }


# ── direct primitives ────────────────────────────────────────────────


def _create_box(p: dict) -> dict:
    return {
        "body_name": "Box_mock",
        "length": p.get("length", 1),
        "width": p.get("width", 1),
        "height": p.get("height", 1),
    }


def _create_cylinder(p: dict) -> dict:
    return {
        "body_name": "Cylinder_mock",
        "radius": p.get("radius", 1),
        "height": p.get("height", 1),
    }


def _create_sphere(p: dict) -> dict:
    return {
        "body_name": "Sphere_mock",
        "radius": p.get("radius", 1),
    }


def _create_torus(p: dict) -> dict:
    return {
        "body_name": "Torus_mock",
        "major_radius": p.get("major_radius", 2),
        "minor_radius": p.get("minor_radius", 0.5),
    }


# ── assembly (extended) ──────────────────────────────────────────────


def _create_as_built_joint(p: dict) -> dict:
    # Order matches the handler's, as above.
    refusal = (
        joint_selector_refusal(p)
        or components_differ_refusal(p)
        or as_built_geometry_refusal(p)
    )
    if refusal is not None:
        return _refusal_error(refusal)
    return {
        "component_one": p.get("component_one", "Comp1"),
        "component_two": p.get("component_two", "Comp2"),
        "joint_type": p.get("joint_type", "rigid"),
        "joint_name": "AsBuiltJoint_mock",
    }


def _create_rigid_group(p: dict) -> dict:
    refusal = rigid_group_size_refusal(p)
    if refusal is not None:
        return _refusal_error(refusal)
    return {
        "component_names": p.get("component_names", []),
        "rigid_group_name": "RigidGroup_mock",
    }


# ── inspection / analysis ────────────────────────────────────────────


def _measure_distance(p: dict) -> dict:
    return {
        "entity_one": p.get("entity_one", "Body1"),
        "entity_two": p.get("entity_two", "Body2"),
        "distance": 2.54,
        "point_one": [0, 0, 0],
        "point_two": [2.54, 0, 0],
    }


def _measure_angle(p: dict) -> dict:
    return {
        "entity_one": p.get("entity_one", "Face1"),
        "entity_two": p.get("entity_two", "Face2"),
        "angle_degrees": 90.0,
    }


def _get_physical_properties(p: dict) -> dict:
    refusal = body_name_required_refusal(p)
    if refusal is not None:
        return _refusal_error(refusal)
    return {
        "body_name": p.get("body_name", "Body1"),
        "mass": 0.785,
        "volume": 1.0,
        "area": 6.0,
        "density": 0.00785,
        "center_of_mass": [0.5, 0.5, 0.5],
    }


def _create_section_analysis(p: dict) -> dict:
    return {
        "plane": p.get("plane", "yz"),
        "offset": p.get("offset", 0),
        "analysis_name": "SectionAnalysis_mock",
    }


def _check_interference(p: dict) -> dict:
    return {
        "component_names": p.get("component_names", []),
        "interference_count": 0,
        "interferences": [],
    }


def _compare_meshes(p: dict) -> dict:
    return {
        "mesh_a": p.get("mesh_name_a", "Mesh1"),
        "mesh_b": p.get("mesh_name_b", "Mesh2"),
        "node_count": 1200,
        "min_deviation": -0.004,
        "max_deviation": 0.006,
        "mean_abs_deviation": 0.001,
        "rms_deviation": 0.0015,
        "max_abs_deviation": 0.006,
        "units": "cm",
    }


def _create_ucs(p: dict) -> dict:
    name = p.get("name", "UCS1")
    return {
        "name": name,
        "origin": [p.get("x", 0), p.get("y", 0), p.get("z", 0)],
        "angles_deg": [
            p.get("angle_x", 0),
            p.get("angle_y", 0),
            p.get("angle_z", 0),
        ],
        "reference_sketch": f"UCS_{name}_ref",
    }


def _set_color(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    r, g, b = p.get("red", 255), p.get("green", 0), p.get("blue", 0)
    alpha = round(p.get("opacity", 1.0) * 255)
    return {
        "body": p.get("body_name", "Body1"),
        "color": [r, g, b],
        "opacity": p.get("opacity", 1.0),
        "appearance": f"MCP_{r}_{g}_{b}_{alpha}",
    }


# ── appearance ────────────────────────────────────────────────────────


def _set_appearance(p: dict) -> dict:
    # A component name is resolved by ``_component_by_name``, not this lookup, so only
    # the two body-shaped targets are judged here.
    body_target = p.get("target_type", "body") in ("body", "face")
    if body_target and (refused := _body_name_required_error(p, "target_name")):
        return refused
    return {
        "target_name": p.get("target_name", "Body1"),
        "appearance_name": p.get("appearance_name", "Steel - Satin"),
        "applied": True,
    }


# ── project geometry ─────────────────────────────────────────────────


def _project_geometry(p: dict) -> dict:
    if refused := _body_name_required_error(p, "source_name"):
        return refused
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "source": p.get("source_name", "Body1"),
        "projected_curves": 4,
        "is_linked": p.get("is_linked", True),
    }


# ── timeline control ─────────────────────────────────────────────────


def _suppress_feature(p: dict) -> dict:
    return {
        "feature_name": p.get("feature_name", "Feature1"),
        "suppressed": True,
    }


def _unsuppress_feature(p: dict) -> dict:
    return {
        "feature_name": p.get("feature_name", "Feature1"),
        "suppressed": False,
    }


# ── surface operations ──────────────────────────────────────────────


def _patch_surface(p: dict) -> dict:
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "body_name": "PatchSurface_mock",
        "continuity": p.get("continuity", "connected"),
    }


def _stitch_surfaces(p: dict) -> dict:
    # Every name is looked up, so one empty entry refuses the call.
    for name in p.get("body_names") or []:
        if refused := _body_name_required_error({"body_name": name}):
            return refused
    return {
        "body_names": p.get("body_names", []),
        "result_body": "StitchedBody_mock",
        "tolerance": p.get("tolerance", 0.01),
    }


def _thicken_surface(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "Surface1"),
        "thickness": p.get("thickness", 0.1),
        "result_body": "ThickenedBody_mock",
    }


def _ruled_surface(p: dict) -> dict:
    # The body is looked up before the rule_type is judged, so that refusal wins.
    if refused := _body_name_required_error(p):
        return refused
    # The handler refuses an unknown rule_type; a mock that echoed it with ok:true
    # would let an agent rehearse a call Fusion rejects (mock.py's own rule).
    rule_type = p.get("rule_type", "normal")
    refusal = rule_type_refusal(rule_type)
    if refusal is not None:
        return _refusal_error(refusal)
    return {
        "feature_name": "Ruled Surface1",
        "body_name": p.get("body_name", "Body1"),
        "edge_index": p.get("edge_index", 0),
        "distance": p.get("distance", 1.0),
        "rule_type": rule_type,
        "result_body": "RuledSurface_mock",
    }


def _trim_surface(p: dict) -> dict:
    # The handler looks the body up before it judges the tool, so an empty name
    # refuses here too; the tool choice and the cell selector are parameter-only.
    if refused := _body_name_required_error(p):
        return refused
    if tool_refusal := surface_tool_refusal(
        {"tool_name": p.get("tool_name"), "tool_plane": p.get("tool_plane")}
    ):
        return _refusal_error(tool_refusal)
    if cells_refusal := keep_cells_refusal({"keep_cells": p.get("keep_cells")}):
        return _refusal_error(cells_refusal)
    return {
        "body_name": p.get("body_name", "Surface1"),
        "kept_cells": p.get("keep_cells", [0]),
        "tool_name": p.get("tool_name"),
        "tool_plane": p.get("tool_plane"),
        "trimmed": True,
    }


# ── sheet metal ─────────────────────────────────────────────────────


def _create_flange(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "edge_index": p.get("edge_index", 0),
        "distance": p.get("distance", 1.0),
        "angle": p.get("angle", 90),
    }


def _create_bend(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "stationary_face_index": p.get("stationary_face_index", 0),
        "angle": p.get("angle", 90),
        "bend_radius": p.get("bend_radius"),
        "line_position": p.get("line_position", "center"),
    }


def _flat_pattern(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "flat_pattern_name": "FlatPattern_mock",
    }


def _unfold(p: dict) -> dict:
    if refused := _body_name_required_error(p):
        return refused
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "bends_unfolded": len(p.get("bend_indices", [0, 1])),
    }


# ── CAM / manufacturing ─────────────────────────────────────────────


def _cam_create_setup(p: dict) -> dict:
    # The add-in calls require_finite on all three offsets before it looks up the
    # body or touches the CAM tree, so mock mode must not report a setup Fusion
    # would refuse.  Mock mode is where an agent develops the sequence it replays.
    for key in ("stock_offset_sides", "stock_offset_top", "stock_offset_bottom"):
        refusal = _non_finite_error(p.get(key, 0))
        if refusal is not None:
            return refusal
    # The stock vocabulary is judged before the body, as the handler does: it is a
    # pure enum, and a typo must not describe a setup Fusion would never create. Its own
    # name, because a ``Refusal`` and the envelope below are different types.
    if stock_refusal := cam_stock_mode_refusal(p):
        return _refusal_error(stock_refusal)
    # The body is looked up before the operation type is mapped, so that wins.
    if refused := _body_name_required_error(p):
        return refused
    # The handler maps the string onto adsk.cam.OperationTypes and refuses
    # anything it does not know, before an operation object exists.  Echoing an
    # arbitrary string described a setup Fusion would never create.
    operation_type = p.get("operation_type", "milling")
    if operation_type not in ("milling", "turning", "cutting"):
        return _mock_error(
            f"Unknown operation_type '{operation_type}' — use milling/turning/cutting"
        )
    # The handler's keys, and the handler's *values*: Fusion's id for the mode
    # (`from_solid` -> `solid`), and the three offsets under Fusion's own parameter
    # names - but only when they are non-zero, which is the handler's own guard.
    stock: dict = {"stock_mode": CAM_STOCK_MODES[p.get("stock_mode", "relative_box")]}
    for argument, parameter in (
        ("stock_offset_sides", "job_stockOffset"),
        ("stock_offset_top", "job_stockOffsetTop"),
        ("stock_offset_bottom", "job_stockOffsetBottom"),
    ):
        if p.get(argument):
            stock[parameter] = p[argument]
    return {
        "name": p.get("name", "Setup1"),
        "body": p.get("body_name", "Body1"),
        "operation_type": operation_type,
        "stock_applied": stock,
    }


#: The tool numbers mock mode's document library holds.  One tool, because a fake
#: cannot model what a caller's Fusion document holds - and a number it does not hold is
#: answered with the sentence the handler would give for that same list.
DOCUMENT_TOOL_LIBRARY = (1,)


def _cam_create_operation(p: dict) -> dict:
    # Same order as the handler: the numeric guards fire before the refusals, and every
    # refusal fires before an operation exists.  Tool arguments are judged from the
    # parameters alone, so a mock rehearsal refuses what Fusion demands rather than
    # describing an operation the add-in would never create.
    for key in (
        "tool_number",
        "tool_diameter",
        "tool_length",
        "tool_flutes",
        "stepdown",
        "stepover",
        "feed_rate",
        "spindle_speed",
    ):
        refusal = _non_finite_error(p.get(key))
        if refusal is not None:
            return refusal
    selector_refusal = (
        cam_strategy_refusal(p) or cam_geometry_refusal(p) or cam_tool_refusal(p)
    )
    if selector_refusal is not None:
        return _refusal_error(selector_refusal)
    # A number alone selects from the document library, so a miss is the library's
    # answer and not a shape fault.
    if p.get("tool_diameter") is None and p.get("tool_json") is None:
        library_refusal = cam_library_tool_refusal(
            p.get("tool_number"), DOCUMENT_TOOL_LIBRARY
        )
        if library_refusal is not None:
            return _refusal_error(library_refusal)
    result = {
        "name": p.get("name", "Operation1"),
        "setup": p.get("setup_name", "Setup1"),
        "strategy": p.get("strategy", "contour2d"),
    }
    if p.get("face_indices"):
        strategy = p.get("strategy")
        result["geometry"] = {
            "parameter": (
                CAM_GEOMETRY_PARAMETERS.get(strategy)
                if isinstance(strategy, str)
                else None
            ),
            "face_indices": list(p["face_indices"]),
        }
    # The tool keys use the handler's spelling, because that is what an agent rehearses
    # here and then reads against Fusion.
    if p.get("tool_diameter") is not None:
        # Only the key the handler always answers: its description is a read-back
        # from Fusion, so live it may be absent - and the string would not match this
        # placeholder anyway (``#1 Ø6mm Flat Endmill``).
        result["tool"] = {"diameter_cm": p["tool_diameter"]}
    elif p.get("tool_json") is not None:
        # The handler reads the created tool back for its description and may answer
        # this same empty object, so mock mode promises nothing it cannot know: a
        # rehearsal that indexed ``result["tool"]["description"]`` here would break
        # live for a JSON Fusion declines to describe.
        result["tool"] = {}
    elif p.get("tool_number") is not None:
        # A number on its own selects a library tool. The handler also answers its
        # description, read back from Fusion - which a fake cannot know, so this
        # promises only the two keys the call itself settles.
        result["tool"] = {"number": p["tool_number"], "from_library": True}
    else:
        result["tool"] = None
        result["tool_warning"] = CAM_NO_TOOL_WARNING
    # The handler answers these under Fusion's own parameter names, and only for the
    # values it was given - so an agent that rehearses ``parameters_applied`` reads the
    # same keys live. ``coolant`` defaults to flood in both, so a live success carries
    # ``tool_coolant`` too.
    applied: dict = {}
    for argument, parameter in (
        ("stepdown", "maximumStepdown"),
        ("stepover", "maximumStepover"),
        ("feed_rate", "tool_feedCutting"),
        ("spindle_speed", "tool_spindleSpeed"),
    ):
        if p.get(argument) is not None:
            applied[parameter] = p[argument]
    coolant = p.get("coolant", "flood")
    if coolant is not None:
        applied["tool_coolant"] = coolant
    if applied:
        result["parameters_applied"] = applied
    return result


def _cam_generate_toolpath(p: dict) -> dict:
    # The add-in refuses a call with no target before it looks up the CAM product, so
    # mock mode must not report a toolpath a call never asked for.
    if refusal := cam_target_refusal(p):
        return _refusal_error(refusal)
    # The handler answers `generated` and `scope`, naming the setup (and the operation
    # when one was named). `toolpath_count` was never a handler key: an agent reading it
    # here got a KeyError live.
    if p.get("generate_all"):
        return {"generated": True, "scope": "all"}
    # When the caller named no setup but did name an operation, the handler resolves the
    # owning setup from the design. Mock has no design, so it answers the caller's name
    # or this placeholder - the *keys* are what a rehearsal reads.
    setup = p.get("setup_name", "Setup1")
    if p.get("operation_name"):
        return {
            "generated": True,
            "scope": "operation",
            "setup": setup,
            "operation": p["operation_name"],
        }
    return {"generated": True, "scope": "setup", "setup": setup}


def _cam_post_process(p: dict) -> dict:
    setup = p.get("setup_name", "Setup1")
    post = p.get("post_processor", "fanuc")
    # The handler answers the folder (`output_folder`) and the unit word (`units`);
    # `output_file`/`output_units` were keys no call ever returned. The default folder
    # is resolved the way the handler resolves it, so a rehearsal prints a real path.
    return {
        "setup": setup,
        "post_processor": post,
        "output_folder": p.get("output_folder")
        or os.path.join(os.path.expanduser("~"), "Desktop"),
        "units": p.get("output_units", "mm"),
    }


def _cam_list_setups(_p: dict) -> dict:
    # `{name, operations, is_valid}` per setup and a top-level `count`, as the handler.
    return {
        "setups": [
            {
                "name": "Setup1",
                "operations": ["Face1", "2D Contour1"],
                "is_valid": True,
            },
        ],
        "count": 1,
    }


def _cam_list_operations(p: dict) -> dict:
    # `setup` (not `setup_name`), and each operation with the three keys the handler
    # reports - `strategy` was never one of them.
    operations = [
        {"name": "Face1", "has_toolpath": True, "is_valid": True},
        {"name": "2D Contour1", "has_toolpath": False, "is_valid": True},
    ]
    return {
        "setup": p.get("setup_name", "Setup1"),
        "operations": operations,
        "count": len(operations),
    }


def _cam_get_operation_info(p: dict) -> dict:
    # The handler's keys: `name`, the two validity flags, the tool (a read-back, so a
    # description) and the operation's own parameter map. The last two are *conditional*
    # live - an operation with no tool, or a shape without `parameters`, reports neither
    # - and mock cannot model that absence, so it always answers both.
    return {
        "name": p.get("operation_name", "Face1"),
        "is_valid": True,
        "has_toolpath": True,
        "tool": {"description": "Ø6mm flat (mock)"},
        # The parameter names measured on 2706 (roadmap item 6) and the feed ones the
        # handler writes. `strategy` is an Operation *property* live, not a parameter,
        # so it is not in here.
        "parameters": {
            "tool_diameter": "6.",
            "maximumStepdown": "0.1",
            "tool_feedCutting": "100.",
            "tool_spindleSpeed": "10000.",
        },
    }


# ── perception (viewport render) ─────────────────────────────────────

# 1x1 transparent PNG, enough to exercise the image-content code path.
_MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
    "EQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)


def _render_view(p: dict) -> dict:
    return {
        "view": p.get("view", "current"),
        "width": int(p.get("width", 1024)),
        "height": int(p.get("height", 768)),
        "image_format": "png",
        "image_base64": _MOCK_PNG_B64,
        "bytes": len(_MOCK_PNG_B64),
    }


# ── default fallback ─────────────────────────────────────────────────


def _default_mock(p: dict) -> dict:
    return {"warning": "no mock handler for this command", "params_received": p}


# ── dispatch table ────────────────────────────────────────────────────


def _new_document(p: dict) -> dict:
    return {
        "created": True,
        "document": p.get("name", "Untitled"),
        "design_type": "parametric",
        "component": "Component1",
    }


_DISPATCH: dict[str, Any] = {
    "ping": _ping,
    "new_document": _new_document,
    "get_scene_info": _get_scene_info,
    "get_object_info": _get_object_info,
    "list_edges": _list_edges,
    "list_faces": _list_faces,
    "get_bounding_box": _get_bounding_box,
    "create_sketch": _create_sketch,
    "draw_rectangle": _draw_rectangle,
    "draw_circle": _draw_circle,
    "draw_line": _draw_line,
    "extrude": _extrude,
    "revolve": _revolve,
    "fillet": _fillet,
    "chamfer": _chamfer,
    "shell": _shell,
    "mirror": _mirror,
    "rename_body": _rename_body,
    "move_body": _move_body,
    "export_stl": _export_stl,
    "boolean_operation": _boolean_operation,
    "delete_all": _delete_all,
    "undo": _undo,
    "execute_code": _execute_code,
    "sweep": _sweep,
    "loft": _loft,
    "create_polygon": _create_polygon,
    "draw_circles": _draw_circles,
    "draw_arc": _draw_arc,
    "create_hole": _create_hole,
    "rectangular_pattern": _rectangular_pattern,
    "circular_pattern": _circular_pattern,
    "create_component": _create_component,
    "add_joint": _add_joint,
    "set_joint_value": _set_joint_value,
    "list_components": _list_components,
    "export_step": _export_step,
    "export_f3d": _export_f3d,
    "export_view_sheet": _export_view_sheet,
    "export": _export,
    "import_mesh": _import_mesh,
    "create_box_parametric": _create_box_parametric,
    "get_parameters": _get_parameters,
    "create_parameter": _create_parameter,
    "set_parameter": _set_parameter,
    "delete_parameter": _delete_parameter,
    # sketch constraints & dimensions
    "add_constraint": _add_constraint,
    "auto_constrain": _auto_constrain,
    "add_dimension": _add_dimension,
    # construction geometry
    "create_construction_plane": _create_construction_plane,
    "create_construction_axis": _create_construction_axis,
    # splines
    "draw_spline": _draw_spline,
    # sketch curve operations
    "offset_curve": _offset_curve,
    "trim_curve": _trim_curve,
    "extend_curve": _extend_curve,
    # advanced features
    "create_thread": _create_thread,
    "draft_faces": _draft_faces,
    "split_body": _split_body,
    "split_face": _split_face,
    "offset_faces": _offset_faces,
    "scale_body": _scale_body,
    # direct primitives
    "create_box": _create_box,
    "create_cylinder": _create_cylinder,
    "create_sphere": _create_sphere,
    "create_torus": _create_torus,
    # assembly (extended)
    "create_as_built_joint": _create_as_built_joint,
    "create_rigid_group": _create_rigid_group,
    # inspection / analysis
    "measure_distance": _measure_distance,
    "measure_angle": _measure_angle,
    "get_physical_properties": _get_physical_properties,
    "create_section_analysis": _create_section_analysis,
    "check_interference": _check_interference,
    "compare_meshes": _compare_meshes,
    "create_ucs": _create_ucs,
    "set_color": _set_color,
    # appearance
    "set_appearance": _set_appearance,
    # project geometry
    "project_geometry": _project_geometry,
    # timeline control
    "suppress_feature": _suppress_feature,
    "unsuppress_feature": _unsuppress_feature,
    # surface operations
    "patch_surface": _patch_surface,
    "stitch_surfaces": _stitch_surfaces,
    "thicken_surface": _thicken_surface,
    "ruled_surface": _ruled_surface,
    "trim_surface": _trim_surface,
    # sheet metal
    "create_flange": _create_flange,
    "create_bend": _create_bend,
    "flat_pattern": _flat_pattern,
    "unfold": _unfold,
    # CAM / manufacturing
    "cam_create_setup": _cam_create_setup,
    "cam_create_operation": _cam_create_operation,
    "cam_generate_toolpath": _cam_generate_toolpath,
    "cam_post_process": _cam_post_process,
    "cam_list_setups": _cam_list_setups,
    "cam_list_operations": _cam_list_operations,
    "cam_get_operation_info": _cam_get_operation_info,
    # design type safety
    "get_design_type": _get_design_type,
    "set_design_type": _set_design_type,
    # perception
    "render_view": _render_view,
}
