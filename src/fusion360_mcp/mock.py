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
from typing import Any

from .hints import classify as _classify

# Mutation commands that get a synthetic deltas payload in mock mode.
# Keep in sync with CommandHandler._MUTATION_COMMANDS in the addon.
_MUTATION_MOCKS: frozenset[str] = frozenset(
    {
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
        "move_body",
        "boolean_operation",
        "create_box",
        "create_cylinder",
        "create_sphere",
        "create_torus",
        "thicken_surface",
        "patch_surface",
        "stitch_surfaces",
        "ruled_surface",
        "trim_surface",
        "create_flange",
        "create_bend",
        "flat_pattern",
        "unfold",
        "delete_all",
        "undo",
        "set_parameter",
        "execute_code",
        "auto_constrain",
        "create_ucs",
        "set_color",
    }
)

_MOCK_DELTAS = {
    "body_count_before": 0,
    "body_count_after": 1,
    "body_count_delta": 1,
    "mass_g_before": 0.0,
    "mass_g_after": 10.0,
    "mass_g_delta": 10.0,
    "bbox_before": None,
    "bbox_after": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
}


def _mock_error(message: str) -> dict:
    """The envelope the addon returns when a command fails.

    ``error_kind`` and ``hints`` come from the same rules the addon classifies
    with, so mock mode reports a failure the way real mode would.
    """
    kind, hint_list = _classify(message)
    return {
        "ok": False,
        "error_kind": kind,
        "error_message": message,
        "hints": hint_list,
        "traceback": f"MockError: {message}",
        "mode": "mock",
    }


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
    # appeared" numbers would claim otherwise.
    if result["ok"] and command_type in _MUTATION_MOCKS and "deltas" not in result:
        # undo removes work; the synthetic "body appeared" deltas would read
        # as a growth and are exactly what an agent must not be told.
        if command_type != "undo":
            result["deltas"] = dict(_MOCK_DELTAS)
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
    limit = max(1, int(p.get("limit") or 200))
    return {
        "body_name": p.get("body_name") or "Body1",
        "count": len(edges),
        "truncated": len(edges) > limit,
        "edges": edges[:limit],
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
        "note": (
            "Sketch curves lie in the sketch plane, so the z component was "
            "dropped instead of being added to the plane's own offset. "
            "Use create_sketch(z_offset=...) to move the plane itself."
        ),
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


def _target_body_error(p: dict) -> dict | None:
    """The add-in's refusal of ``target_body`` on a new body, or None.

    Mirrors ``CommandHandler._resolve_target_body``, wording included, because
    the hint rule matches on it.  An unknown body name is *not* refused here:
    mock mode has no design to look it up in.
    """
    if p.get("target_body") is None:
        return None
    if p.get("operation", "new_body") == "new_body":
        return _mock_error(
            "Invalid input: target_body applies only to cut, join or "
            "intersect \u2014 new_body builds a body of its own, so there is "
            "nothing to target"
        )
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


# The same four the handler accepts and tools.py advertises.  A fifth value added
# in one place and not the others would make mock mode refuse a valid call, so
# tests/test_addon_edge_selection.py asserts the three agree.
_EDGE_SELECTIONS = ("all", "top", "bottom", "vertical")


def _edge_selector_error(p: dict) -> dict | None:
    """The add-in's refusals of an edge-selector combination, or None.

    Mock mode cannot search a body, so it cannot tell which edges a selection
    matches — but the *combination* rules, the element types and the enum are pure
    parameter checks that ``_select_edges`` makes before it examines an edge.
    Echoing an accepted call here would teach a sequence Fusion refuses, which is
    the fiction #34 removed from the CAM mocks.

    These fire inside ``_select_edges``, not before the body lookup: ``fillet``
    resolves ``body_name`` first, so a call with both a bad body and a bad selector
    answers ``BODY_NOT_FOUND`` in real mode and ``INVALID_INPUT`` here.  Mock mode
    has no bodies to look up, so that difference cannot be removed.
    """
    indices = p.get("edge_indices")
    points = p.get("edge_points")
    selection = p.get("edge_selection", "all")

    if indices is not None and points is not None:
        return _mock_error(
            "Pass only one of edge_indices and edge_points — they name the "
            "same edges two ways, so one would be ignored"
        )
    if (indices is not None or points is not None) and selection != "all":
        return _mock_error(
            f"edge_selection '{selection}' cannot be combined with "
            "edge_indices or edge_points — pass one selector, not two"
        )
    if indices is not None and not indices:
        return _mock_error(
            "edge_indices was empty — name at least one edge, or omit it to "
            "use edge_selection"
        )
    if points is not None and not points:
        return _mock_error(
            "edge_points was empty — name at least one point, or omit it to "
            "use edge_selection"
        )
    for index in indices or []:
        if isinstance(index, bool) or not isinstance(index, int):
            return _mock_error(
                f"Edge index {index!r} is out of range — indices are whole "
                "numbers from list_edges"
            )
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return _mock_error("edge point needs three coordinates")
    if selection not in _EDGE_SELECTIONS:
        return _mock_error(
            f"Unknown edge_selection '{selection}' — use all/top/bottom/vertical"
        )
    return None


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
    # The handler refuses anything but top/bottom before it looks at a body, so
    # mock mode must not accept a call Fusion rejects.
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
    return {
        "renamed": True,
        "old_name": p.get("body_name", "Body1"),
        "new_name": p.get("new_name", "RenamedBody"),
    }


def _move_body(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "translation": [p.get("x", 0), p.get("y", 0), p.get("z", 0)],
    }


def _export_stl(p: dict) -> dict:
    name = p.get("body_name", "Body1")
    path = p.get("file_path", f"~/Desktop/{name}.stl")
    return {"body_name": name, "file_path": path}


def _boolean_operation(p: dict) -> dict:
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
    return {"deleted": True}


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
    refused = _target_body_error(p)
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
    return {
        "body_name": p.get("body_name", "Body1"),
        "x_count": p.get("x_count", 1),
        "y_count": p.get("y_count", 1),
        "created_bodies": p.get("x_count", 1) * p.get("y_count", 1),
    }


def _circular_pattern(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "count": p.get("count", 3),
        "axis": p.get("axis", "z"),
        "total_angle": p.get("total_angle", 360),
    }


# ── assembly tools ────────────────────────────────────────────────────


def _create_component(p: dict) -> dict:
    return {
        "component_name": p.get("name", "Component1"),
        "parent": p.get("parent_name", "RootComponent"),
    }


def _add_joint(p: dict) -> dict:
    return {
        "component_one": p.get("component_one", "Comp1"),
        "component_two": p.get("component_two", "Comp2"),
        "joint_type": p.get("joint_type", "rigid"),
        "joint_name": "Joint_mock",
    }


# value_kind -> (motion, attribute, unit), mirroring what the add-in resolves
# from the joint's motion type. The mock holds no design, so it resolves from the
# kind instead; without this it reported rotationValue/degrees for every kind,
# including the slide values that are lengths in centimetres.
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
    would teach a sequence Fusion answers differently: Python wraps ``-1`` to the
    last curve, so the real add-in used to dimension a curve nobody named and
    report success (measured live).
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
    refusal = _curve_index_error(p, ("entity_one", "entity_two", "symmetry_line"))
    if refusal is not None:
        return refusal
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


def _add_dimension(p: dict) -> dict:
    refusal = _curve_index_error(p, ("entity_one", "entity_two"))
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
    return {
        "plane_name": "ConstructionPlane_mock",
        "method": p.get("method", "offset"),
    }


def _create_construction_axis(p: dict) -> dict:
    return {
        "axis_name": "ConstructionAxis_mock",
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
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "offset_distance": p.get("offset_distance", 0.5),
        "new_curve_count": 4,
    }


def _trim_curve(p: dict) -> dict:
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "curve_index": p.get("curve_index", 0),
        "trimmed": True,
    }


def _extend_curve(p: dict) -> dict:
    return {
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "curve_index": p.get("curve_index", 0),
        "extended": True,
    }


# ── advanced features ─────────────────────────────────────────────────


def _create_thread(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "face_index": p.get("face_index", 0),
        "is_modeled": p.get("is_modeled", False),
        "thread_designation": p.get("thread_designation", "M10x1.5"),
    }


def _draft_faces(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "angle": p.get("angle", 5),
        "face_count": 4,
    }


def _split_body(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "result_bodies": ["Body1", "Body1_split"],
    }


def _split_face(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "faces_split": 2,
    }


def _offset_faces(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "distance": p.get("distance", 0.5),
    }


def _scale_body(p: dict) -> dict:
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
    return {
        "component_one": p.get("component_one", "Comp1"),
        "component_two": p.get("component_two", "Comp2"),
        "joint_type": p.get("joint_type", "rigid"),
        "joint_name": "AsBuiltJoint_mock",
    }


def _create_rigid_group(p: dict) -> dict:
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
    return {
        "target_name": p.get("target_name", "Body1"),
        "appearance_name": p.get("appearance_name", "Steel - Satin"),
        "applied": True,
    }


# ── project geometry ─────────────────────────────────────────────────


def _project_geometry(p: dict) -> dict:
    return {
        "source_name": p.get("source_name", "Body1"),
        "sketch_name": p.get("sketch_name", "Sketch1"),
        "projected_curves": 4,
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
    return {
        "body_names": p.get("body_names", []),
        "result_body": "StitchedBody_mock",
        "tolerance": p.get("tolerance", 0.01),
    }


def _thicken_surface(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Surface1"),
        "thickness": p.get("thickness", 0.1),
        "result_body": "ThickenedBody_mock",
    }


def _ruled_surface(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "edge_index": p.get("edge_index", 0),
        "distance": p.get("distance", 1.0),
        "result_body": "RuledSurface_mock",
    }


def _trim_surface(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Surface1"),
        "tool_name": p.get("tool_name", "Tool1"),
        "trimmed": True,
    }


# ── sheet metal ─────────────────────────────────────────────────────


def _create_flange(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "edge_index": p.get("edge_index", 0),
        "height": p.get("height", 1.0),
        "angle": p.get("angle", 90),
    }


def _create_bend(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "angle": p.get("angle", 90),
        "bend_radius": p.get("bend_radius", 0.1),
    }


def _flat_pattern(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "flat_pattern_name": "FlatPattern_mock",
    }


def _unfold(p: dict) -> dict:
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
    # The handler maps the string onto adsk.cam.OperationTypes and refuses
    # anything it does not know, before an operation object exists.  Echoing an
    # arbitrary string described a setup Fusion would never create.
    operation_type = p.get("operation_type", "milling")
    if operation_type not in ("milling", "turning", "cutting"):
        return _mock_error(
            f"Unknown operation_type '{operation_type}' — use milling/turning/cutting"
        )
    return {
        "setup_name": p.get("name", "Setup1"),
        "body_name": p.get("body_name", "Body1"),
        "operation_type": operation_type,
        "stock_mode": p.get("stock_mode", "relative_box"),
    }


def _cam_create_operation(p: dict) -> dict:
    # Same order as the handler: the numeric guards fire before the refusal, and
    # the refusal fires before any operation exists.  tool_diameter is not a
    # parameter at all -- tool geometry comes from the CAM tool library -- and
    # echoing it back here described an operation Fusion would never create.
    for key in ("tool_number", "stepdown", "stepover", "feed_rate", "spindle_speed"):
        refusal = _non_finite_error(p.get(key))
        if refusal is not None:
            return refusal
    if p.get("tool_diameter") is not None:
        return _mock_error(
            "tool_diameter cannot be set on an operation — tool geometry comes "
            "from a tool in the CAM tool library. Select the tool via "
            "tool_number instead."
        )
    return {
        "setup_name": p.get("setup_name", "Setup1"),
        "operation_name": p.get("name", "Operation1"),
        "strategy": p.get("strategy", "2d_contour"),
    }


def _cam_generate_toolpath(p: dict) -> dict:
    return {
        "setup_name": p.get("setup_name", "Setup1"),
        "operation_name": p.get("operation_name"),
        "generated": True,
        "toolpath_count": 1,
    }


def _cam_post_process(p: dict) -> dict:
    setup = p.get("setup_name", "Setup1")
    post = p.get("post_processor", "fanuc")
    return {
        "setup_name": setup,
        "post_processor": post,
        "output_file": f"~/Desktop/{setup}.nc",
        "output_units": p.get("output_units", "mm"),
    }


def _cam_list_setups(_p: dict) -> dict:
    return {
        "setups": [
            {
                "name": "Setup1",
                "operation_type": "milling",
                "operation_count": 2,
            },
        ],
    }


def _cam_list_operations(p: dict) -> dict:
    return {
        "setup_name": p.get("setup_name", "Setup1"),
        "operations": [
            {
                "name": "Face1",
                "strategy": "face",
                "has_toolpath": True,
            },
            {
                "name": "2D Contour1",
                "strategy": "2d_contour",
                "has_toolpath": False,
            },
        ],
    }


def _cam_get_operation_info(p: dict) -> dict:
    return {
        "setup_name": p.get("setup_name", "Setup1"),
        "operation_name": p.get("operation_name", "Face1"),
        "strategy": "face",
        "tool_diameter": 0.6,
        "stepdown": 0.1,
        "feed_rate": 100.0,
        "spindle_speed": 10000,
        "has_toolpath": True,
        "toolpath_valid": True,
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
