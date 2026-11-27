"""
MCP tool definitions for every command the Fusion360MCP add-in supports.

Each entry becomes a tool an MCP client can call.  The ``inputSchema`` is
JSON Schema that the MCP SDK validates before forwarding arguments.
"""

import mcp.types as types

# The add-in's validator owns the accepted vocabularies, so the schema advertises its
# sets instead of restating them: a new value cannot land in one place only.  The
# joint selectors are read by ``tools.py`` twice each (both joint tools), so a local
# copy would be a fourth place to drift.
from ._rules import (
    CAM_GEOMETRY_PARAMETERS,
    CAM_STOCK_MODES,
    CAM_STRATEGIES,
    EDGE_SELECTIONS,
    JOINT_KEY_POINTS,
    JOINT_QUADRANTS,
    JOINT_TYPES,
)

# Sketch curves are planar: Fusion interprets their points in the sketch's own
# frame, so a z here adds to the plane's offset instead of replacing it.
_SKETCH_PLANE_Z = (
    "Ignored: sketch curves lie in the sketch plane. Leave at 0 and use "
    "create_sketch(z_offset=...) to move the plane itself."
)

# Naming the sketch is what keeps geometry out of "whatever was created last".
_SKETCH_NAME_TARGET = "Sketch to draw into (default: the most recent sketch)."

# A 3-D point as ``[x, y, z]`` in centimetres: the shape every point argument uses.
_POINT3 = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}

# ``render_view``'s camera presets: "current" (leave the camera where it is) plus every
# key of the add-in's ``CommandHandler._VIEW_DIRS``, in that order.
# ``tests/test_addon_sync.py`` asserts the two agree.
VIEW_PRESETS = (
    "current",
    "iso",
    "iso_ne",
    "iso_nw",
    "iso_sw",
    "front",
    "back",
    "top",
    "bottom",
    "right",
    "left",
)

# ``export_view_sheet``'s presets: ``VIEW_PRESETS`` without "current", because there is
# no view to render where the camera already is — the handler refuses it.
VIEW_SHEET_VIEWS = tuple(view for view in VIEW_PRESETS if view != "current")

# fillet and chamfer take the same four edge selectors; only the size argument
# differs (a radius or a distance).
_EDGE_SELECTOR = {
    "edge_selection": {
        "type": "string",
        "enum": list(EDGE_SELECTIONS),
        "default": "all",
    },
    "edge_indices": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0},
        "description": (
            "Exact edges to affect, indexed as list_edges reports them. "
            "Indices are positional, so re-run list_edges after a change."
        ),
    },
    "edge_points": {
        "type": "array",
        "items": _POINT3,
        "description": (
            "Points near the edges to affect; each snaps to the nearest "
            "edge within edge_tolerance. Ambiguous points are refused."
        ),
    },
    "edge_tolerance": {
        "type": "number",
        "default": 0.1,
        "minimum": 0.0001,
        "description": "How near a point must be to an edge (cm)",
    },
}

# The joint geometry arguments are the same on both joint tools; only the
# key_point wording differs (add_joint's was measured against Fusion's refusals,
# the as-built one did not have to be).  The sub-dicts are shared and never mutated:
# the annotations pass below writes only on the tool dict itself.
_JOINT_TYPE = {
    "type": "string",
    "enum": list(JOINT_TYPES),
    "default": "rigid",
}

# ``create_as_built_joint`` requires ``joint_type``, so its schema must not advertise
# a default: jsonschema never applies one, and a client that reads it and omits the
# field would be refused by the schema that advertised it.
_JOINT_TYPE_REQUIRED = {
    key: value for key, value in _JOINT_TYPE.items() if key != "default"
}

_JOINT_KEY_POINT = {
    "type": "string",
    "enum": list(JOINT_KEY_POINTS),
    "default": "end",
    "description": (
        "Axial position of the joint origin on a cylindrical face. "
        "`end` is the only value that produced a valid joint on "
        "Fusion 2705; others raise Invalid parameter height or "
        "InternalValidationError."
    ),
}

_AS_BUILT_KEY_POINT = {
    "type": "string",
    "enum": list(JOINT_KEY_POINTS),
    "default": "end",
    "description": ("Axial position of the joint origin on a cylindrical face."),
}


def _joint_properties(key_point: dict, joint_type: dict = _JOINT_TYPE) -> dict:
    """The joint arguments both joint tools share, in schema order.

    ``joint_type`` is ``_JOINT_TYPE`` for ``add_joint``, where the handler defaults an
    omitted one to ``rigid``; ``create_as_built_joint`` requires the argument and
    passes ``_JOINT_TYPE_REQUIRED``, which advertises no default.
    """
    return {
        "joint_type": joint_type,
        "body_one": {
            "type": "string",
            "description": (
                "Body inside component_one carrying the joint geometry. "
                "Omit when the component holds exactly one body."
            ),
        },
        "face_one": {
            "type": "integer",
            "description": ("Face index on that body (cylindrical faces work best)."),
        },
        "body_two": {
            "type": "string",
            "description": (
                "Body inside component_two carrying the joint geometry. "
                "Omit when the component holds exactly one body."
            ),
        },
        "face_two": {
            "type": "integer",
            "description": ("Face index on that body (cylindrical faces work best)."),
        },
        "axis": {
            "type": "string",
            "enum": ["x", "y", "z"],
            "default": "x",
            "description": (
                "Rotation/slide axis in MODEL terms (x/y/z), resolved against "
                "the joint's own axes: Fusion's JointDirections enum selects a "
                "joint axis, so the nearest one is used and the result's "
                "axis_world / directions report the sign actually applied. "
                "Rotation/slide axis for revolute, slider and cylindrical; "
                "primary direction for pin_slot, planar and ball."
            ),
        },
        "second_axis": {
            "type": "string",
            "enum": ["x", "y", "z"],
            "description": (
                "Secondary direction for pin_slot and ball. "
                "Defaults to an axis perpendicular to `axis`. "
                "For ball joints Fusion takes (pitch, yaw) and "
                "rejects a pitch parallel to the joint axis, so "
                "the perpendicular one is sent first."
            ),
        },
        "quadrant": {
            "type": "string",
            "enum": list(JOINT_QUADRANTS),
            "default": "middle",
            "description": (
                "Angular position of the joint origin on a cylindrical face."
            ),
        },
        "key_point": key_point,
    }


# Where the four profile-based features say the same thing, they say it once.
# Only the spellings that are actually identical are shared: revolve's
# profile_index never declared `minimum`, and it keeps its own literal, because
# adding one here would change a schema in a commit that changes none.
_PROFILE_INDEX = {
    "type": "integer",
    "default": 0,
    "minimum": 0,
    "description": (
        "Index of the profile in the chosen sketch "
        "(sketch_name, default the most recent one)"
    ),
}

_PROFILE_SKETCH = {
    "type": "string",
    "description": ("Sketch holding the profile (default: the most recent sketch)"),
}

_OPERATION = {
    "type": "string",
    "enum": ["new_body", "join", "cut", "intersect"],
    "default": "new_body",
}


def _target_body(reaches: str) -> dict:
    """``target_body`` for a feature whose reach is a profile, sweep or loft."""
    return {
        "type": "string",
        "description": (
            "Body the cut/join/intersect applies to. Without it "
            f"Fusion applies the operation to every body the {reaches} reaches."
        ),
    }


def _tool(
    _name: str, _title: str, _description: str, *, required=(), **properties
) -> dict:
    """One tool entry: the wrapper all 100 of them share.

    ``required`` and every property are keyword arguments, so a schema reads as
    the arguments it describes rather than as five levels of dict literal.  The
    dict it builds has the same keys in the same order as the literals it
    replaced (``type``, then ``required`` when there is one, then ``properties``),
    and no property is re-ordered: ``**properties`` preserves call order.

    The three positionals carry a leading underscore because tools have
    properties called ``name`` and ``title`` (and ``description``, should one ever
    be added); a plain parameter of that name would be shadowed by the
    ``**properties`` entry and raise "got multiple values for argument".
    """
    schema: dict = {"type": "object"}
    if required:
        schema["required"] = list(required)
    schema["properties"] = properties
    return {
        "name": _name,
        "title": _title,
        "description": _description,
        "inputSchema": schema,
    }


TOOLS: list[dict] = [
    # ── scene / query ────────────────────────────────────────────────
    _tool(
        "get_scene_info",
        "Get Scene Info",
        "Get design name, bodies, sketches, features, camera info",
    ),
    _tool(
        "get_object_info",
        "Get Object Info",
        "Get detailed info about a named body or sketch",
        required=["name"],
        name={"type": "string", "description": "Object name"},
    ),
    _tool(
        "get_bounding_box",
        "Get Bounding Box",
        (
            "Axis-aligned bounding box for a body or component by name. "
            "Returns min, max, size, and center in cm (Fusion internal units). "
            "For components, unions bounding boxes of all contained bodies. "
            "Useful for measuring imported reference geometry."
        ),
        required=["name"],
        name={
            "type": "string",
            "description": "Body or component name",
        },
    ),
    # ── sketch ───────────────────────────────────────────────────────
    _tool(
        "create_sketch",
        "Create Sketch",
        "Create a new sketch on xy/yz/xz plane, optionally offset",
        plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "default": "xy",
        },
        z_offset={
            "type": "number",
            "description": "Offset distance from the plane (cm)",
        },
    ),
    _tool(
        "draw_rectangle",
        "Draw Rectangle",
        "Draw a rectangle in the most recent sketch, or in sketch_name",
        required=["width", "height"],
        width={"type": "number", "minimum": 0.001},
        height={"type": "number", "minimum": 0.001},
        origin_x={"type": "number", "default": 0},
        origin_y={"type": "number", "default": 0},
        origin_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    _tool(
        "draw_circle",
        "Draw Circle",
        "Draw a circle in the most recent sketch, or in sketch_name",
        required=["radius"],
        radius={"type": "number", "minimum": 0.001},
        center_x={"type": "number", "default": 0},
        center_y={"type": "number", "default": 0},
        center_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    _tool(
        "draw_line",
        "Draw Line",
        "Draw a line in the most recent sketch, or in sketch_name",
        required=["start_x", "start_y", "end_x", "end_y"],
        start_x={"type": "number"},
        start_y={"type": "number"},
        start_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        end_x={"type": "number"},
        end_y={"type": "number"},
        end_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    # ── features ─────────────────────────────────────────────────────
    _tool(
        "extrude",
        "Extrude",
        (
            "Extrude a sketch profile. A cut/join/intersect applies to "
            "target_body when named; without it Fusion applies the operation "
            "to every body the profile reaches."
        ),
        required=["height"],
        height={"type": "number"},
        profile_index=_PROFILE_INDEX,
        operation=_OPERATION,
        direction={
            "type": "string",
            "enum": ["positive", "negative", "symmetric"],
            "default": "positive",
        },
        sketch_name=_PROFILE_SKETCH,
        target_body=_target_body("profile"),
    ),
    _tool(
        "revolve",
        "Revolve",
        (
            "Revolve a sketch profile (default: the most recent sketch) about an axis. "
            "axis_origin and axis_direction are model space (cm). The axis "
            "must be coplanar with the profile: a world-aligned direction "
            "through the model origin uses Fusion's own construction axis, "
            "anything else becomes a construction line in the sketch, and an "
            "axis leaving the sketch plane is refused with AXIS_OUT_OF_PLANE. "
            "The result reports axis_model_start/axis_model_end. A "
            "cut/join/intersect applies to target_body when named; without it "
            "Fusion applies the operation to every body the profile reaches."
        ),
        required=["angle"],
        angle={"type": "number", "minimum": 0.1, "maximum": 360},
        profile_index={
            "type": "integer",
            "default": 0,
            "description": (
                "Index of the profile in the chosen sketch "
                "(sketch_name, default the most recent one)"
            ),
        },
        sketch_name=_PROFILE_SKETCH,
        axis_origin_x={
            "type": "number",
            "default": 0,
            "description": "Axis origin X, model space (cm)",
        },
        axis_origin_y={
            "type": "number",
            "default": 0,
            "description": "Axis origin Y, model space (cm)",
        },
        axis_origin_z={
            "type": "number",
            "default": 0,
            "description": (
                "Axis origin Z, model space (cm). Must be the "
                "profile's own plane height; an offset along the plane "
                "normal is dropped and reported."
            ),
        },
        axis_direction_x={
            "type": "number",
            "default": 1,
            "description": "Axis direction X, model space (normalised)",
        },
        axis_direction_y={
            "type": "number",
            "default": 0,
            "description": "Axis direction Y, model space (normalised)",
        },
        axis_direction_z={
            "type": "number",
            "default": 0,
            "description": "Axis direction Z, model space (normalised)",
        },
        operation=_OPERATION,
        target_body=_target_body("profile"),
    ),
    _tool(
        "fillet",
        "Fillet Edges",
        (
            "Round edges of a body: all/top/bottom/vertical, or exact edges by "
            "edge_indices (from list_edges) or by edge_points near them"
        ),
        required=["radius"],
        radius={"type": "number", "minimum": 0.001},
        body_name={"type": "string", "description": "Body name (preferred)"},
        body_index={"type": "integer", "default": 0},
        **_EDGE_SELECTOR,
    ),
    _tool(
        "chamfer",
        "Chamfer Edges",
        (
            "Chamfer edges of a body: all/top/bottom/vertical, or exact edges by "
            "edge_indices (from list_edges) or by edge_points near them"
        ),
        required=["distance"],
        distance={"type": "number", "minimum": 0.001},
        body_name={"type": "string"},
        body_index={"type": "integer", "default": 0},
        **_EDGE_SELECTOR,
    ),
    _tool(
        "shell",
        "Shell Body",
        "Hollow out a body by removing a face",
        required=["thickness"],
        thickness={"type": "number", "minimum": 0.001},
        body_name={"type": "string"},
        body_index={"type": "integer", "default": 0},
        face_selection={
            "type": "string",
            "enum": ["top", "bottom"],
            "default": "top",
        },
    ),
    _tool(
        "mirror",
        "Mirror Body",
        "Mirror a body across a construction plane",
        required=["mirror_plane"],
        mirror_plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
        },
        body_name={"type": "string"},
        body_index={"type": "integer", "default": 0},
    ),
    # ── new commands ─────────────────────────────────────────────────
    _tool(
        "rename_body",
        "Rename Body",
        "Rename a body (searches root and all components)",
        required=["body_name", "new_name"],
        body_name={
            "type": "string",
            "description": "Current body name",
        },
        new_name={
            "type": "string",
            "description": "New name for the body",
        },
    ),
    _tool(
        "move_body",
        "Move Body",
        "Translate a named body by (x, y, z)",
        required=["body_name"],
        body_name={"type": "string"},
        x={"type": "number", "default": 0},
        y={"type": "number", "default": 0},
        z={"type": "number", "default": 0},
    ),
    _tool(
        "export_stl",
        "Export STL",
        "Export a named body as an STL file",
        required=["body_name"],
        body_name={"type": "string"},
        file_path={
            "type": "string",
            "description": "Destination path (default: ~/Desktop/<name>.stl)",
        },
    ),
    _tool(
        "boolean_operation",
        "Boolean Operation",
        "Combine two named bodies (join/cut/intersect)",
        required=["target_body", "tool_body"],
        target_body={"type": "string"},
        tool_body={"type": "string"},
        operation={
            "type": "string",
            "enum": ["join", "cut", "intersect"],
            "default": "join",
        },
        keep_tool={
            "type": "boolean",
            "default": False,
            "description": (
                "Keep the tool body after combining (Fusion consumes it by default)"
            ),
        },
    ),
    _tool(
        "delete_all",
        "Delete All",
        "Clear the design (delete all timeline items)",
    ),
    _tool(
        "undo",
        "Undo",
        (
            "Step the design back one operation. Parametric designs move the "
            "timeline marker back one step (synchronous and verified; the "
            "feature stays in the timeline, suppressed, and returns if you roll "
            "forward). Direct designs issue Fusion's asynchronous undo command "
            "and report undone: 'issued', verified: false — confirm with "
            "get_scene_info. Reports undone: false when there is nothing to undo."
        ),
    ),
    # ── code execution ───────────────────────────────────────────────
    _tool(
        "execute_code",
        "Execute Code",
        (
            "Run arbitrary Python in Fusion 360. "
            "The last expression's value is returned (REPL-style). "
            "Pre-defined names: app, ui, design, component, adsk, math."
        ),
        required=["code"],
        code={"type": "string"},
        checkpoint={
            "type": "boolean",
            "default": False,
            "description": (
                "Save the document before running the script, so a crash cannot take "
                "the unsaved state. Opt-in: the default writes nothing."
            ),
        },
    ),
    # ── additional geometry ───────────────────────────────────────────
    _tool(
        "sweep",
        "Sweep",
        (
            "Sweep a sketch profile along a path (sketch curve). A "
            "cut/join/intersect applies to target_body when named; without it "
            "Fusion applies the operation to every body the sweep reaches."
        ),
        required=["profile_index", "path_sketch_name"],
        profile_index=_PROFILE_INDEX,
        path_sketch_name={
            "type": "string",
            "description": "Name of the sketch containing the sweep path",
        },
        path_curve_index={"type": "integer", "default": 0, "minimum": 0},
        sketch_name=_PROFILE_SKETCH,
        operation=_OPERATION,
        target_body=_target_body("sweep"),
    ),
    _tool(
        "loft",
        "Loft",
        (
            "Loft between two or more sketch profiles. A cut/join/intersect "
            "applies to target_body when named; without it Fusion applies the "
            "operation to every body the loft reaches."
        ),
        required=["profile_sketch_names"],
        profile_sketch_names={
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "description": (
                "Ordered list of sketch names whose first profile will be lofted"
            ),
        },
        operation=_OPERATION,
        target_body=_target_body("loft"),
    ),
    _tool(
        "create_polygon",
        "Create Polygon",
        ("Draw a regular polygon in the most recent sketch, or in sketch_name"),
        required=["sides", "radius"],
        sides={"type": "integer", "minimum": 3, "maximum": 64},
        radius={
            "type": "number",
            "minimum": 0.001,
            "description": "Circumradius (cm)",
        },
        center_x={"type": "number", "default": 0},
        center_y={"type": "number", "default": 0},
        center_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    _tool(
        "draw_arc",
        "Draw Arc",
        ("Draw an arc in the most recent sketch (center + start point + sweep angle)"),
        required=["center_x", "center_y", "start_x", "start_y", "sweep_angle"],
        center_x={"type": "number"},
        center_y={"type": "number"},
        center_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        start_x={"type": "number"},
        start_y={"type": "number"},
        start_z={
            "type": "number",
            "default": 0,
            "description": _SKETCH_PLANE_Z,
        },
        sweep_angle={
            "type": "number",
            "description": "Sweep angle in degrees (positive = CCW)",
            "minimum": -360,
            "maximum": 360,
        },
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    _tool(
        "create_hole",
        "Create Hole",
        "Create a hole feature on a body face",
        required=["diameter", "depth"],
        diameter={"type": "number", "minimum": 0.001},
        depth={"type": "number", "minimum": 0.001},
        body_name={"type": "string"},
        body_index={"type": "integer", "default": 0},
        face_selection={
            "type": "string",
            "enum": ["top", "bottom"],
            "default": "top",
            "description": (
                "Drill into the highest up-facing (top) or lowest "
                "down-facing (bottom) planar face, which must be "
                "near-horizontal (within ~0.6 deg)"
            ),
        },
        center_x={
            "type": "number",
            "default": 0,
            "description": "Hole centre X in model space (cm)",
        },
        center_y={
            "type": "number",
            "default": 0,
            "description": "Hole centre Y in model space (cm)",
        },
    ),
    _tool(
        "rectangular_pattern",
        "Rectangular Pattern",
        "Pattern a body in rows and columns",
        required=["body_name"],
        body_name={"type": "string"},
        x_count={"type": "integer", "minimum": 1, "default": 1},
        x_spacing={
            "type": "number",
            "default": 1.0,
            "description": "Spacing between columns (cm)",
        },
        y_count={"type": "integer", "minimum": 1, "default": 1},
        y_spacing={
            "type": "number",
            "default": 1.0,
            "description": "Spacing between rows (cm)",
        },
    ),
    _tool(
        "circular_pattern",
        "Circular Pattern",
        "Pattern a body around an axis",
        required=["body_name", "count"],
        body_name={"type": "string"},
        count={"type": "integer", "minimum": 2},
        axis={
            "type": "string",
            "enum": ["x", "y", "z"],
            "default": "z",
        },
        total_angle={
            "type": "number",
            "default": 360,
            "minimum": 1,
            "maximum": 360,
            "description": "Total angle to distribute copies over (degrees)",
        },
    ),
    # ── assembly ───────────────────────────────────────────────────────
    _tool(
        "new_document",
        "New Document",
        (
            "Create a new design document and make it active. Every other tool "
            "needs an active design, and Fusion sits at the data tab with none "
            "after a fresh launch, so this is the way in from a cold start. The "
            "document is created through the API on purpose: documents created "
            "in the Fusion UI are Part Design documents, which reject "
            "addNewComponent, so components and joints are impossible in them."
        ),
        name={
            "type": "string",
            "description": "Optional document name.",
        },
    ),
    _tool(
        "create_component",
        "Create Component",
        "Create a new component (sub-assembly) in the design",
        required=["name"],
        name={"type": "string", "description": "Component name"},
        parent_name={
            "type": "string",
            "description": "Parent component name (omit for root)",
        },
    ),
    _tool(
        "add_joint",
        "Add Joint",
        (
            "Add a joint between two components using a pair of faces as "
            "joint geometry. face_one/face_two are mandatory: a joint cannot be "
            "built from component origins, because a bare point carries no "
            "component association. Pass a cylindrical face on each side "
            "(list_faces reports them, with each face's surface_type) - for a hinge "
            "that is "
            "the knuckle bore on each leaf. NOTE: creating a joint MOVES the "
            "components so the joint geometry becomes coincident - use "
            "create_as_built_joint when the parts are already positioned."
        ),
        required=["component_one", "component_two", "face_one", "face_two"],
        component_one={"type": "string"},
        component_two={"type": "string"},
        **_joint_properties(_JOINT_KEY_POINT),
    ),
    _tool(
        "set_joint_value",
        "Set Joint Value",
        (
            "Drive a joint to a value and confirm Fusion kept it. Angles are in "
            "degrees unless units='rad'; slide values are lengths in cm and are "
            "never converted. Works on as-built joints unless as_built=False. "
            "Fusion resets joint values to zero on the next design.computeAll(), "
            "so avoid recomputing after this call - the command itself does not."
        ),
        required=["value"],
        value={
            "type": "number",
            "description": (
                "Target value: degrees for rotations (or radians with "
                "units='rad'), centimetres for slide values."
            ),
        },
        joint_name={
            "type": "string",
            "description": "Joint to drive. Omit to use joint_index.",
        },
        joint_index={
            "type": "integer",
            "default": 0,
            "description": (
                "Index into the joint collection when joint_name is omitted."
            ),
        },
        units={
            "type": "string",
            "enum": ["deg", "rad"],
            "default": "deg",
            "description": ("Units for angle values only; slide values are always cm."),
        },
        value_kind={
            "type": "string",
            "enum": [
                "rotation",
                "slide",
                "primary_slide",
                "secondary_slide",
                "pitch",
                "yaw",
                "roll",
            ],
            "description": (
                "Which value to drive on joints carrying more than one. "
                "Defaults to rotation (pitch for ball joints). Use "
                "primary_slide/secondary_slide for planar and "
                "pitch/yaw/roll for ball."
            ),
        },
        as_built={
            "type": "boolean",
            "default": True,
            "description": ("Search as-built joints (True) or regular joints (False)."),
        },
    ),
    _tool(
        "list_edges",
        "List Edges",
        (
            "List a body's edges with index, endpoints, midpoint, length and curve "
            "type; the indices are what fillet and chamfer take as edge_indices"
        ),
        body_name={
            "type": "string",
            "description": "Body name (default: the body at body_index)",
        },
        body_index={"type": "integer", "default": 0},
        limit={
            "type": "integer",
            "default": 200,
            "minimum": 1,
            "maximum": 5000,
            "description": "Maximum edges returned; count is the real total",
        },
    ),
    _tool(
        "list_faces",
        "List Faces",
        (
            "List a body's faces with index, surface_type (Plane, Cylinder, Cone, "
            "...), planarity, area and centroid, plus the outward normal on a planar "
            "face; these are the indices face_indices takes"
        ),
        body_name={
            "type": "string",
            "description": "Body name (default: the body at body_index)",
        },
        body_index={"type": "integer", "default": 0},
        limit={
            "type": "integer",
            "default": 200,
            "minimum": 1,
            "maximum": 5000,
            "description": "Maximum faces returned; count is the real total",
        },
    ),
    _tool(
        "list_components",
        "List Components",
        "List all components in the design",
    ),
    # ── export ─────────────────────────────────────────────────────────
    _tool(
        "export_step",
        "Export STEP",
        "Export a body or component as a STEP file",
        required=["body_name"],
        body_name={"type": "string"},
        file_path={
            "type": "string",
            "description": "Destination path (default: ~/Desktop/<name>.step)",
        },
    ),
    _tool(
        "export_f3d",
        "Export F3D",
        "Export the design as a native Fusion 360 archive (.f3d)",
        file_path={
            "type": "string",
            "description": ("Destination path (default: ~/Desktop/<design_name>.f3d)"),
        },
    ),
    _tool(
        "export_view_sheet",
        "Export View Sheet",
        (
            "Render canonical orthographic + isometric views as PNGs and "
            "emit a self-contained HTML sheet suitable for sharing with a "
            "mechanical engineer. Opens in any browser; Print -> Save as "
            "PDF for a static artifact. Restores the viewport camera "
            "after rendering."
        ),
        title={
            "type": "string",
            "description": ("Heading shown on the sheet (default: document name)."),
        },
        notes={
            "type": "string",
            "description": (
                "Free-form notes rendered below the views. "
                "Newlines preserved; HTML is escaped."
            ),
        },
        views={
            "type": "array",
            "items": {
                "type": "string",
                "enum": list(VIEW_SHEET_VIEWS),
            },
            "description": (
                "Ordered list of views to render (default: iso, front, top, right)."
            ),
        },
        image_size={
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
            "maxItems": 2,
            "description": ("[width, height] in pixels (default [1200, 900])."),
        },
        output_dir={
            "type": "string",
            "description": (
                "Destination folder (default: ~/Desktop/<doc>_views_<timestamp>)."
            ),
        },
    ),
    _tool(
        "export",
        "Export (unified)",
        (
            "Unified export wrapper — dispatches to export_stl / export_step / "
            "export_f3d based on format or file extension. "
            "Format is auto-detected from file_path extension if not specified. "
            "STL and STEP require body_name; F3D exports the whole design."
        ),
        format={
            "type": "string",
            "enum": ["stl", "step", "stp", "f3d"],
            "description": (
                "Output format. Inferred from file_path extension if omitted."
            ),
        },
        body_name={
            "type": "string",
            "description": "Body to export (required for stl/step)",
        },
        file_path={
            "type": "string",
            "description": ("Destination path (default: ~/Desktop/<name>.<ext>)"),
        },
    ),
    # ── import ─────────────────────────────────────────────────────────
    _tool(
        "import_mesh",
        "Import Mesh",
        (
            "Import a mesh file (STL, OBJ, or 3MF) as a mesh body. "
            "Returns the mesh name and bounding box. "
            "Use for reference geometry (e.g. exported SketchUp model)."
        ),
        required=["file_path"],
        file_path={
            "type": "string",
            "description": "Absolute path to mesh file (.stl/.obj/.3mf)",
        },
        component_name={
            "type": "string",
            "description": ("Target component name (omit for root component)"),
        },
        units={
            "type": "string",
            "enum": ["mm", "cm", "m", "in", "ft"],
            "default": "mm",
            "description": "Source mesh units (default: mm)",
        },
    ),
    # ── parameters ─────────────────────────────────────────────────────
    _tool(
        "get_parameters",
        "Get Parameters",
        "List all user parameters in the design",
    ),
    _tool(
        "create_parameter",
        "Create Parameter",
        "Create a new user parameter",
        required=["name", "value", "unit"],
        name={"type": "string", "description": "Parameter name"},
        value={
            "type": "number",
            "description": "Numeric value, expressed in `unit`",
        },
        unit={
            "type": "string",
            "description": (
                "Unit the value is given in (e.g. 'mm', 'cm', 'in', "
                "'deg'). Empty means unitless."
            ),
        },
        comment={"type": "string", "description": "Optional comment"},
    ),
    _tool(
        "set_parameter",
        "Set Parameter",
        "Update the value of an existing user parameter",
        required=["name", "value"],
        name={"type": "string", "description": "Parameter name"},
        value={
            "type": "number",
            "description": (
                "New numeric value, expressed in the unit the "
                "parameter already declares"
            ),
        },
    ),
    _tool(
        "delete_parameter",
        "Delete Parameter",
        "Remove a user parameter",
        required=["name"],
        name={"type": "string", "description": "Parameter name"},
    ),
    # ── sketch constraints ─────────────────────────────────────────────
    _tool(
        "draw_circles",
        "Draw Circles (bulk)",
        (
            "Add several equally spaced circles to the most recent sketch in a "
            "single solve. Fusion re-solves the sketch on every entity insert, so "
            "adding circles one per call is superlinear in the entity count; this "
            "defers the solve across all inserts and restores the previous state "
            "afterwards. Measured at 100 circles: 68 ms against 912 ms for the "
            "same inserts one at a time."
        ),
        required=["count", "radius", "spacing"],
        count={"type": "integer", "minimum": 1, "maximum": 500},
        radius={"type": "number", "minimum": 0.001},
        spacing={
            "type": "number",
            "description": "Centre-to-centre distance (cm)",
        },
        axis={
            "type": "string",
            "enum": ["x", "y"],
            "default": "x",
            "description": "Direction the row runs in",
        },
        center_x={"type": "number", "default": 0},
        center_y={"type": "number", "default": 0},
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    _tool(
        "add_constraint",
        "Add Sketch Constraint",
        (
            "Add a geometric constraint in the active sketch. "
            "Entities are referenced by index within the sketch."
        ),
        required=["constraint_type"],
        constraint_type={
            "type": "string",
            "enum": [
                "coincident",
                "parallel",
                "perpendicular",
                "tangent",
                "equal",
                "fix",
                "midpoint",
                "concentric",
                "horizontal",
                "vertical",
                "symmetry",
                "collinear",
                "smooth",
            ],
        },
        entity_one={
            "type": "integer",
            "description": (
                "Index of the first entity: a sketch POINT for midpoint, "
                "a curve for every other type"
            ),
            "minimum": 0,
        },
        entity_two={
            "type": "integer",
            "description": (
                "Index of the second sketch entity "
                "(not needed for fix/horizontal/vertical)"
            ),
            "minimum": 0,
        },
        symmetry_line={
            "type": "integer",
            "description": (
                "Index of the symmetry line (only for symmetry constraint)"
            ),
            "minimum": 0,
        },
        sketch_name={
            "type": "string",
            "description": "Sketch name (default: most recent)",
        },
    ),
    _tool(
        "auto_constrain",
        "Auto-Constrain Sketch",
        (
            "Automatically add geometric constraints and dimensions to fully "
            "constrain a sketch (Fusion 2026+ AutoConstrain API). "
            "result_option: 1 = thorough/slow (default), 2 = fast, "
            "3 = may move geometry within tolerance."
        ),
        sketch_name={
            "type": "string",
            "description": "Sketch name (default: most recent)",
        },
        result_option={
            "type": "integer",
            "enum": [1, 2, 3],
            "default": 1,
            "description": (
                "1 = most thorough (slowest), 2 = fastest, "
                "3 = adjusts geometry within tolerance"
            ),
        },
    ),
    # ── sketch dimensions ──────────────────────────────────────────────
    _tool(
        "add_dimension",
        "Add Sketch Dimension",
        (
            "Add a driving dimension to constrain sketch geometry. "
            "Value is in cm for distances, degrees for angles."
        ),
        required=["dimension_type", "value"],
        dimension_type={
            "type": "string",
            "enum": [
                "distance",
                "horizontal",
                "vertical",
                "angular",
                "radial",
                "diameter",
            ],
        },
        value={
            "type": "number",
            "description": "Dimension value (cm or degrees)",
        },
        entity_one={
            "type": "integer",
            "description": (
                "Index of the curve to measure (radial and diameter take this one only)"
            ),
            "minimum": 0,
        },
        entity_two={
            "type": "integer",
            "description": (
                "Index of the second curve (distance, horizontal, vertical "
                "and angular need it; radial and diameter do not)"
            ),
            "minimum": 0,
        },
        sketch_name={
            "type": "string",
            "description": "Sketch name (default: most recent)",
        },
    ),
    # ── construction geometry ──────────────────────────────────────────
    _tool(
        "create_construction_plane",
        "Create Construction Plane",
        "Create a construction plane for sketching",
        required=["method"],
        method={
            "type": "string",
            "enum": [
                "offset",
                "angle",
                "midplane",
                "three_points",
                "tangent",
            ],
        },
        plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "description": (
                "Reference plane: what an offset/angle is measured from, and the "
                "reference a tangent plane's angle is measured from"
            ),
        },
        offset={
            "type": "number",
            "description": "Offset distance in cm (for offset)",
        },
        angle={
            "type": "number",
            "description": (
                "Angle in degrees (for angle, and for tangent without point_one)"
            ),
        },
        edge_name={
            "type": "string",
            "description": ("Axis to rotate around: x, y or z (for angle method)"),
        },
        plane_one={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "description": "First plane (for midplane)",
        },
        plane_two={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "description": "Second plane (for midplane)",
        },
        point_one={
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
            "description": "[x,y,z] first point",
        },
        point_two={
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
            "description": "[x,y,z] second point",
        },
        point_three={
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
            "description": "[x,y,z] third point",
        },
        body_name={
            "type": "string",
            "description": "Body holding the face (for tangent)",
        },
        face_index={
            "type": "integer",
            "minimum": 0,
            "description": (
                "Face the plane is tangent to (for tangent): list_faces reports the "
                "indices. The at-a-angle form needs a cylindrical face and a "
                "reference plane whose normal is not parallel to its axis; passing "
                "point_one instead builds the plane through that point, on any face "
                "including a cone"
            ),
        },
    ),
    _tool(
        "create_construction_axis",
        "Create Construction Axis",
        "Create a construction axis",
        required=["method"],
        method={
            "type": "string",
            "enum": [
                "two_points",
                "intersection",
                "edge",
                "perpendicular_at_point",
            ],
        },
        point_one={
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
        },
        point_two={
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
        },
        plane_one={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "description": ("First plane (for intersection)"),
        },
        plane_two={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "description": ("Second plane (for intersection)"),
        },
        body_name={
            "type": "string",
            "description": "Body name (for edge and perpendicular_at_point)",
        },
        edge_index={
            "type": "integer",
            "description": "Edge index on the body",
            "minimum": 0,
        },
        face_index={
            "type": "integer",
            "description": (
                "Face on that body (for perpendicular_at_point): the axis is normal "
                "to it at point_one. list_faces reports the indices"
            ),
            "minimum": 0,
        },
    ),
    _tool(
        "create_ucs",
        "Create User Coordinate System",
        (
            "Create a UCS at (x, y, z) with optional rotation (Fusion 2026+ "
            "UCS API, preview). A hidden reference sketch is created to anchor "
            "the UCS — do not delete it."
        ),
        name={"type": "string", "description": "UCS name"},
        x={"type": "number", "default": 0, "description": "Origin X (cm)"},
        y={"type": "number", "default": 0, "description": "Origin Y (cm)"},
        z={"type": "number", "default": 0, "description": "Origin Z (cm)"},
        angle_x={
            "type": "number",
            "default": 0,
            "description": "Rotation about X (degrees)",
        },
        angle_y={
            "type": "number",
            "default": 0,
            "description": "Rotation about Y (degrees)",
        },
        angle_z={
            "type": "number",
            "default": 0,
            "description": "Rotation about Z (degrees)",
        },
    ),
    # ── splines ────────────────────────────────────────────────────────
    _tool(
        "draw_spline",
        "Draw Spline",
        (
            "Draw a spline in the most recent sketch. "
            "Use fit_points for a curve through points, or "
            "control_points for a control-polygon spline."
        ),
        required=["spline_type", "points"],
        spline_type={
            "type": "string",
            "enum": ["fit_points", "control_points"],
        },
        points={
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 3,
            },
            "minItems": 2,
            "description": ("Array of [x,y] or [x,y,z] points. " + _SKETCH_PLANE_Z),
        },
        degree={
            "type": "integer",
            "enum": [3, 5],
            "default": 3,
            "description": ("Spline degree (only for control_points, 3 or 5)"),
        },
        sketch_name={
            "type": "string",
            "description": _SKETCH_NAME_TARGET,
        },
    ),
    # ── sketch curve operations ────────────────────────────────────────
    _tool(
        "offset_curve",
        "Offset Curve",
        (
            "Offset connected sketch curves by a distance. "
            "Direction is determined by the direction_point."
        ),
        required=["curve_index", "offset_distance"],
        curve_index={
            "type": "integer",
            "minimum": 0,
            "description": ("Index of a curve in the connected loop"),
        },
        offset_distance={
            "type": "number",
            "minimum": 0.001,
            "description": "Offset distance (cm)",
        },
        direction_x={
            "type": "number",
            "default": 1,
            "description": "X of direction point",
        },
        direction_y={
            "type": "number",
            "default": 0,
            "description": "Y of direction point",
        },
        sketch_name={
            "type": "string",
            "description": ("Sketch name (default: most recent)"),
        },
    ),
    _tool(
        "trim_curve",
        "Trim Curve",
        (
            "Trim a sketch curve at its intersections. "
            "The segment nearest to the given point is removed."
        ),
        required=["curve_index", "point_x", "point_y"],
        curve_index={
            "type": "integer",
            "minimum": 0,
            "description": "Index of the curve to trim",
        },
        point_x={
            "type": "number",
            "description": ("X near the segment to remove"),
        },
        point_y={
            "type": "number",
            "description": ("Y near the segment to remove"),
        },
        sketch_name={"type": "string"},
    ),
    _tool(
        "extend_curve",
        "Extend Curve",
        (
            "Extend a sketch curve to the nearest intersection. "
            "The end nearest to the given point is extended."
        ),
        required=["curve_index", "point_x", "point_y"],
        curve_index={
            "type": "integer",
            "minimum": 0,
            "description": "Index of the curve to extend",
        },
        point_x={
            "type": "number",
            "description": "X near the end to extend",
        },
        point_y={
            "type": "number",
            "description": "Y near the end to extend",
        },
        sketch_name={"type": "string"},
    ),
    # ── advanced features ──────────────────────────────────────────────
    _tool(
        "create_thread",
        "Create Thread",
        (
            "Add threads to a cylindrical face (cosmetic or modeled). Fusion sizes "
            "the body to the designation's diameter, so a designation that does not "
            "match the face is refused (M6x1 on a 20 mm shaft would leave a 6 mm "
            "one); allow_resize=true accepts that. The result reports "
            "face_diameter_cm, measured before the feature runs, and "
            "thread_diameter_cm."
        ),
        required=["body_name", "face_index"],
        body_name={"type": "string"},
        face_index={
            "type": "integer",
            "minimum": 0,
            "description": ("Index of the cylindrical face"),
        },
        is_internal={
            "type": "boolean",
            "default": False,
            "description": "True for internal (nut) threads",
        },
        thread_type={
            "type": "string",
            "default": "ISO Metric profile",
            "description": (
                "Thread standard "
                "(e.g. 'ISO Metric profile', 'ANSI Unified Screw Threads')"
            ),
        },
        thread_designation={
            "type": "string",
            "default": "M10x1.5",
            "description": ("Size designation (e.g. 'M10x1.5')"),
        },
        thread_class={
            "type": "string",
            "description": (
                "Thread class. For an ISO metric thread the default is 6H "
                "when internal and 6g when external, which is what ISO 965 "
                "assigns; pass it explicitly for another thread standard."
            ),
        },
        is_modeled={
            "type": "boolean",
            "default": False,
            "description": ("True = physical geometry, False = cosmetic"),
        },
        is_full_length={
            "type": "boolean",
            "default": True,
            "description": "Thread entire cylinder length",
        },
        allow_resize={
            "type": "boolean",
            "default": False,
            "description": (
                "Fusion sizes the body to the thread's diameter, so a designation "
                "that does not match the face is refused by default. Set this true "
                "to accept the body being resized; face_diameter_cm is measured "
                "before the feature runs."
            ),
        },
        thread_length={
            "type": "number",
            "description": ("Thread length in cm (only if is_full_length=false)"),
        },
    ),
    _tool(
        "draft_faces",
        "Draft / Taper Faces",
        ("Add a draft angle to faces of a body (for mold release / injection molding)"),
        required=["body_name", "angle"],
        body_name={"type": "string"},
        angle={
            "type": "number",
            "minimum": 0.1,
            "maximum": 89,
            "description": "Draft angle in degrees",
        },
        face_selection={
            "type": "string",
            "enum": ["all", "top", "bottom", "vertical"],
            "default": "vertical",
            "description": "Which faces to draft",
        },
        pull_direction_plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "default": "xy",
            "description": "Plane defining the pull direction",
        },
        is_tangent_chain={
            "type": "boolean",
            "default": True,
            "description": ("Include tangent-connected faces"),
        },
    ),
    _tool(
        "split_body",
        "Split Body",
        "Split a body using a plane or face",
        required=["body_name"],
        body_name={"type": "string"},
        splitting_plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "default": "xy",
            "description": ("Plane to split with (or use splitting_body)"),
        },
        splitting_body={
            "type": "string",
            "description": (
                "Name of a body/surface to use as splitting tool (overrides plane)"
            ),
        },
        extend_tool={
            "type": "boolean",
            "default": True,
            "description": ("Extend tool to cut through entire body"),
        },
    ),
    _tool(
        "split_face",
        "Split Face",
        "Split faces of a body using a plane",
        required=["body_name"],
        body_name={"type": "string"},
        face_indices={
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "description": ("Indices of faces to split (default: all faces)"),
        },
        splitting_plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "default": "xy",
        },
        extend_tool={
            "type": "boolean",
            "default": True,
        },
    ),
    _tool(
        "offset_faces",
        "Offset Faces",
        ("Push/pull faces of a body by a distance"),
        required=["body_name", "distance"],
        body_name={"type": "string"},
        distance={
            "type": "number",
            "description": ("Offset distance in cm (positive = outward)"),
        },
        face_selection={
            "type": "string",
            "enum": ["all", "top", "bottom"],
            "default": "top",
            "description": "Which faces to offset",
        },
        face_indices={
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "description": ("Specific face indices (overrides face_selection)"),
        },
    ),
    _tool(
        "scale_body",
        "Scale Body",
        "Scale a body uniformly or non-uniformly",
        required=["body_name", "scale"],
        body_name={"type": "string"},
        scale={
            "type": "number",
            "minimum": 0.001,
            "description": "Uniform scale factor",
        },
        scale_x={
            "type": "number",
            "minimum": 0.001,
            "description": ("X scale (overrides uniform scale)"),
        },
        scale_y={
            "type": "number",
            "minimum": 0.001,
            "description": "Y scale",
        },
        scale_z={
            "type": "number",
            "minimum": 0.001,
            "description": "Z scale",
        },
        anchor_x={
            "type": "number",
            "default": 0,
            "description": "Scale anchor point X",
        },
        anchor_y={
            "type": "number",
            "default": 0,
            "description": "Scale anchor point Y",
        },
        anchor_z={
            "type": "number",
            "default": 0,
            "description": "Scale anchor point Z",
        },
    ),
    # ── direct primitives ──────────────────────────────────────────────
    _tool(
        "create_box",
        "Create Box",
        (
            "Create a box primitive (non-parametric via TemporaryBRepManager), "
            "centred on (center_x, center_y, center_z): it spans half the "
            "length, width and height either side of that point on every axis"
        ),
        required=["length", "width", "height"],
        length={
            "type": "number",
            "minimum": 0.001,
            "description": "Size along X, centred on center_x",
        },
        width={
            "type": "number",
            "minimum": 0.001,
            "description": "Size along Y, centred on center_y",
        },
        height={
            "type": "number",
            "minimum": 0.001,
            "description": "Size along Z, centred on center_z",
        },
        center_x={
            "type": "number",
            "default": 0,
            "description": "Centre of the box in X (cm), not a face",
        },
        center_y={
            "type": "number",
            "default": 0,
            "description": "Centre of the box in Y (cm), not a face",
        },
        center_z={
            "type": "number",
            "default": 0,
            "description": (
                "Centre of the box in Z (cm), not its base: the box "
                "spans center_z - height/2 to center_z + height/2"
            ),
        },
    ),
    _tool(
        "create_box_parametric",
        "Create Parametric Box",
        (
            "Create a history-based rectangular box via sketch rectangle + "
            "extrude (unlike create_box which uses TemporaryBRepManager). "
            "length/width/height accept a number (cm, Fusion internal unit) "
            "or a string expression referencing User Parameters "
            "(e.g. 'boxL', '56 mm', 'outer - 2 * wall_t'). "
            "Call create_parameter first to define named parameters."
        ),
        required=["length", "width", "height"],
        length={
            "oneOf": [
                {"type": "number", "minimum": 0.001},
                {"type": "string"},
            ],
            "description": "Along sketch X: number (cm) or expression",
        },
        width={
            "oneOf": [
                {"type": "number", "minimum": 0.001},
                {"type": "string"},
            ],
            "description": "Along sketch Y: number (cm) or expression",
        },
        height={
            "oneOf": [
                {"type": "number", "minimum": 0.001},
                {"type": "string"},
            ],
            "description": "Extrude distance: number (cm) or expression",
        },
        origin_x={"type": "number", "default": 0},
        origin_y={"type": "number", "default": 0},
        origin_z={
            "type": "number",
            "default": 0,
            "description": "Z-offset of sketch plane (cm)",
        },
        plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "default": "xy",
        },
        component_name={
            "type": "string",
            "description": "Target component (omit for root)",
        },
        body_name={
            "type": "string",
            "description": "Optional name for the resulting body",
        },
    ),
    _tool(
        "create_cylinder",
        "Create Cylinder",
        ("Create a cylinder primitive (non-parametric via TemporaryBRepManager)"),
        required=["radius", "height"],
        radius={"type": "number", "minimum": 0.001},
        height={"type": "number", "minimum": 0.001},
        base_x={"type": "number", "default": 0},
        base_y={"type": "number", "default": 0},
        base_z={"type": "number", "default": 0},
        axis={
            "type": "string",
            "enum": ["x", "y", "z"],
            "default": "z",
            "description": "Cylinder axis direction",
        },
    ),
    _tool(
        "create_sphere",
        "Create Sphere",
        ("Create a sphere primitive (non-parametric via TemporaryBRepManager)"),
        required=["radius"],
        radius={"type": "number", "minimum": 0.001},
        center_x={"type": "number", "default": 0},
        center_y={"type": "number", "default": 0},
        center_z={"type": "number", "default": 0},
    ),
    _tool(
        "create_torus",
        "Create Torus",
        ("Create a torus primitive (non-parametric via TemporaryBRepManager)"),
        required=["major_radius", "minor_radius"],
        major_radius={
            "type": "number",
            "minimum": 0.001,
            "description": "Distance from center to tube center",
        },
        minor_radius={
            "type": "number",
            "minimum": 0.001,
            "description": "Tube cross-section radius",
        },
        center_x={"type": "number", "default": 0},
        center_y={"type": "number", "default": 0},
        center_z={"type": "number", "default": 0},
        axis={
            "type": "string",
            "enum": ["x", "y", "z"],
            "default": "z",
        },
    ),
    # ── assembly (extended) ────────────────────────────────────────────
    _tool(
        "create_as_built_joint",
        "Create As-Built Joint",
        (
            "Create a joint that keeps both components exactly where they are, "
            "capturing the current pose instead of enforcing a new one. Use this "
            "when the parts are already positioned correctly; add_joint instead "
            "moves components to make the joint geometry coincident. "
            "Fusion needs a face pair (face_one/face_two) for every joint type "
            "except rigid."
        ),
        required=[
            "component_one",
            "component_two",
            "joint_type",
        ],
        component_one={"type": "string"},
        component_two={"type": "string"},
        **_joint_properties(_AS_BUILT_KEY_POINT, _JOINT_TYPE_REQUIRED),
    ),
    _tool(
        "create_rigid_group",
        "Create Rigid Group",
        "Lock multiple components together",
        required=["component_names"],
        component_names={
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "description": "Names of components to group",
        },
        include_children={
            "type": "boolean",
            "default": True,
            "description": ("Include child sub-components"),
        },
    ),
    # ── inspection / analysis ──────────────────────────────────────────
    _tool(
        "measure_distance",
        "Measure Distance",
        ("Measure minimum distance between two entities"),
        required=["entity_one", "entity_two"],
        entity_one={
            "type": "string",
            "description": ("First entity name (body, sketch, or point 'x,y,z')"),
        },
        entity_two={
            "type": "string",
            "description": "Second entity name or point",
        },
    ),
    _tool(
        "measure_angle",
        "Measure Angle",
        "Measure angle between two entities",
        required=["entity_one", "entity_two"],
        entity_one={
            "type": "string",
            "description": "First entity name (face, edge)",
        },
        entity_two={
            "type": "string",
            "description": "Second entity name",
        },
    ),
    _tool(
        "get_physical_properties",
        "Get Physical Properties",
        ("Get mass, volume, surface area, center of mass, and density of a body"),
        required=["body_name"],
        body_name={"type": "string"},
        accuracy={
            "type": "string",
            "enum": ["low", "medium", "high", "very_high"],
            "default": "medium",
        },
    ),
    _tool(
        "create_section_analysis",
        "Create Section Analysis",
        "Cut a section plane through the model",
        plane={
            "type": "string",
            "enum": ["xy", "yz", "xz"],
            "default": "yz",
        },
        offset={
            "type": "number",
            "default": 0,
            "description": "Offset from the plane (cm)",
        },
    ),
    _tool(
        "check_interference",
        "Check Interference",
        ("Detect collisions between components/bodies"),
        required=["component_names"],
        component_names={
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "description": ("Names of components to check"),
        },
        include_coincident_faces={
            "type": "boolean",
            "default": False,
            "description": ("Count touching faces as interference"),
        },
    ),
    _tool(
        "compare_meshes",
        "Compare Mesh Bodies",
        (
            "Compare two mesh bodies and return deviation statistics "
            "(min/max/mean/RMS signed distance in cm) — e.g. validate an "
            "imported STL against a reference mesh. Requires Fusion 2026+."
        ),
        required=["mesh_name_a", "mesh_name_b"],
        mesh_name_a={
            "type": "string",
            "description": "Name of the first mesh body",
        },
        mesh_name_b={
            "type": "string",
            "description": "Name of the reference mesh body",
        },
    ),
    # ── appearance / material ──────────────────────────────────────────
    _tool(
        "set_appearance",
        "Set Appearance",
        (
            "Assign a material appearance to a body, face, "
            "or component from the Fusion appearance library"
        ),
        required=["target_name", "appearance_name"],
        target_name={
            "type": "string",
            "description": "Name of body or component",
        },
        appearance_name={
            "type": "string",
            "description": (
                "Library appearance name "
                "(e.g. 'Steel - Satin', "
                "'Aluminum - Anodized Red')"
            ),
        },
        target_type={
            "type": "string",
            "enum": ["body", "component", "face"],
            "default": "body",
        },
        face_index={
            "type": "integer",
            "minimum": 0,
            "description": ("Face index (if target_type=face)"),
        },
    ),
    _tool(
        "set_color",
        "Set Body Color",
        (
            "Assign a flat RGB color to a body (creates/reuses a design-local "
            "appearance). Useful for visually distinguishing parts before "
            "render_view."
        ),
        required=["body_name", "red", "green", "blue"],
        body_name={"type": "string", "description": "Body name"},
        red={"type": "integer", "minimum": 0, "maximum": 255},
        green={"type": "integer", "minimum": 0, "maximum": 255},
        blue={"type": "integer", "minimum": 0, "maximum": 255},
        opacity={
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 1,
            "description": "1.0 = opaque, 0.0 = invisible",
        },
    ),
    # ── project geometry ───────────────────────────────────────────────
    _tool(
        "project_geometry",
        "Project Geometry",
        ("Project edges or bodies onto the active sketch plane"),
        required=["source_name"],
        source_name={
            "type": "string",
            "description": ("Name of body or edge to project"),
        },
        is_linked={
            "type": "boolean",
            "default": True,
            "description": ("True = parametrically linked to source geometry"),
        },
        sketch_name={
            "type": "string",
            "description": ("Target sketch (default: most recent)"),
        },
    ),
    # ── timeline control ──────────────────────────────────────────────
    _tool(
        "suppress_feature",
        "Suppress Feature",
        "Suppress (disable) a feature in the timeline",
        required=["feature_name"],
        feature_name={"type": "string"},
    ),
    _tool(
        "unsuppress_feature",
        "Unsuppress Feature",
        "Unsuppress (re-enable) a feature in the timeline",
        required=["feature_name"],
        feature_name={"type": "string"},
    ),
    # ── surface operations ─────────────────────────────────────────────
    _tool(
        "patch_surface",
        "Patch Surface",
        ("Create a patch surface from a sketch profile"),
        required=["sketch_name"],
        sketch_name={
            "type": "string",
            "description": "Sketch with boundary curves",
        },
        profile_index={
            "type": "integer",
            "default": 0,
            "minimum": 0,
        },
        continuity={
            "type": "string",
            "enum": ["connected", "tangent", "curvature"],
            "default": "connected",
        },
    ),
    _tool(
        "stitch_surfaces",
        "Stitch Surfaces",
        ("Stitch surface bodies into a single body"),
        required=["body_names"],
        body_names={
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
        tolerance={
            "type": "number",
            "default": 0.01,
            "description": "Stitch tolerance (cm)",
        },
    ),
    _tool(
        "thicken_surface",
        "Thicken Surface",
        "Thicken a surface body into a solid",
        required=["body_name", "thickness"],
        body_name={"type": "string"},
        thickness={
            "type": "number",
            "minimum": 0.001,
            "description": "Thickness (cm)",
        },
        direction={
            "type": "string",
            "enum": ["positive", "negative", "symmetric"],
            "default": "symmetric",
        },
    ),
    _tool(
        "ruled_surface",
        "Ruled Surface",
        (
            "Create a ruled surface from a free edge: a sheet body's boundary, "
            "not a solid's edge (two faces share every edge of a solid, and "
            'Fusion refuses it with "invalid free edge"). distance extends '
            "it in cm."
        ),
        required=["body_name", "edge_index"],
        body_name={"type": "string"},
        edge_index={
            "type": "integer",
            "minimum": 0,
        },
        distance={
            "type": "number",
            "default": 1.0,
            "description": "Ruled surface distance (cm)",
        },
        rule_type={
            "type": "string",
            "enum": ["normal", "tangent"],
            "default": "normal",
        },
    ),
    _tool(
        "trim_surface",
        "Trim Surface",
        "Trim a surface body with another body or a base plane",
        required=["body_name", "keep_cells"],
        body_name={
            "type": "string",
            "description": "Surface body to trim",
        },
        keep_cells={
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "description": (
                "Indices of the cells Fusion's trim produced that survive. Every "
                "other cell is removed. The refusal reports how many cells exist."
            ),
        },
        tool_name={
            "type": "string",
            "description": "Trimming tool body",
        },
        tool_plane={
            "type": "string",
            "enum": ["xy", "xz", "yz"],
            "description": "Base plane used as the trimming tool instead of a body",
        },
    ),
    # ── sheet metal ────────────────────────────────────────────────────
    _tool(
        "create_flange",
        "Create Flange",
        ("Create a sheet metal flange on an edge"),
        required=["body_name", "edge_index"],
        body_name={"type": "string"},
        edge_index={
            "type": "integer",
            "minimum": 0,
        },
        distance={
            "type": "number",
            "minimum": 0.001,
            "description": "Flange length (cm)",
        },
        angle={
            "type": "number",
            "default": 90,
            "description": "Bend angle (degrees)",
        },
        bend_radius_override={
            "type": "number",
            "description": "Bend radius for this flange only (cm)",
        },
    ),
    _tool(
        "create_bend",
        "Create Bend",
        "Fold a sheet metal body along a sketch line",
        required=["body_name", "stationary_face_index", "bend_line_sketch"],
        body_name={"type": "string"},
        stationary_face_index={
            "type": "integer",
            "minimum": 0,
            "description": (
                "Face of body_name that stays fixed during the fold - a wrong one "
                "bends the part the wrong way"
            ),
        },
        bend_line_sketch={
            "type": "string",
            "description": "Sketch whose first line the fold runs along",
        },
        angle={
            "type": "number",
            "default": 90,
            "description": "Bend angle (degrees)",
        },
        bend_radius={
            "type": "number",
            "description": "Override bend radius (cm)",
        },
        line_position={
            "type": "string",
            "enum": ["start", "center", "end"],
            "default": "center",
            "description": "Where the bend line sits in the flat state",
        },
        allow_bend_relief={
            "type": "boolean",
            "default": True,
            "description": "Allow bend relief at the ends of this bend line",
        },
    ),
    _tool(
        "flat_pattern",
        "Flat Pattern",
        ("Create a flat pattern from a sheet metal body"),
        required=["body_name"],
        body_name={"type": "string"},
    ),
    _tool(
        "unfold",
        "Unfold",
        "Unfold specific bends in a sheet metal body",
        required=["body_name"],
        body_name={"type": "string"},
        bend_indices={
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "description": ("Indices of bends to unfold (omit to unfold all)"),
        },
    ),
    # ── CAM / manufacturing ──────────────────────────────────────────
    _tool(
        "cam_create_setup",
        "Create CAM Setup",
        (
            "Create a manufacturing setup for a body. "
            "Defines the stock, coordinate system, and "
            "operation type (milling/turning/cutting)."
        ),
        required=["body_name"],
        body_name={
            "type": "string",
            "description": "Body to machine",
        },
        name={
            "type": "string",
            "description": "Setup name",
        },
        operation_type={
            "type": "string",
            "enum": ["milling", "turning", "cutting"],
            "default": "milling",
        },
        stock_mode={
            "type": "string",
            "enum": list(CAM_STOCK_MODES),
            "default": "relative_box",
            "description": (
                "How the setup's stock is defined, measured against Fusion "
                "2706.1.17: "
                + ", ".join(CAM_STOCK_MODES)
                + ". The names this schema used to advertise included from_body, "
                "which Fusion refuses as an invalid enumeration value and never "
                "worked - from_solid is the working name for it."
            ),
        },
        stock_offset_sides={
            "type": "number",
            "default": 0,
            "description": "Side offset (cm)",
        },
        stock_offset_top={
            "type": "number",
            "default": 0,
            "description": "Top offset (cm)",
        },
        stock_offset_bottom={
            "type": "number",
            "default": 0,
            "description": "Bottom offset (cm)",
        },
    ),
    _tool(
        "cam_create_operation",
        "Create CAM Operation",
        (
            "Add a machining operation to a setup. "
            "Strategy determines the toolpath type."
        ),
        required=["setup_name", "strategy"],
        setup_name={
            "type": "string",
            "description": "Name of the parent setup",
        },
        strategy={
            "type": "string",
            "enum": list(CAM_STRATEGIES),
            "description": (
                "Machining strategy, in Fusion's own spelling. Measured against "
                "Operations.compatibleStrategies on 2706.1.17: of the fifteen names "
                "this schema carried, five were Fusion's (kept here) and ten were "
                "invented and refused as 'Unknown strategy'. "
                "face_indices aims "
                f"{', '.join(k for k in CAM_GEOMETRY_PARAMETERS if k != 'face')} and "
                "face - the strategies measured to accept a selection. face has none "
                "of its own, so it is aimed through its stock boundary "
                "(stockContours), which Fusion honours while useStockContours is true."
            ),
        },
        name={
            "type": "string",
            "description": "Operation name",
        },
        tool_number={
            "type": "integer",
            "minimum": 1,
            "maximum": 100000,
            "description": (
                "Number the post writes. On its own it selects a tool the "
                "document tool library already holds - the reply says "
                "from_library, and a number nothing holds is refused naming the "
                "numbers that would work - or saying the library is empty. Beside "
                "tool_diameter it numbers the tool that creates. A tool supplied as "
                "tool_json carries its own "
                "number in its post-process block, so passing tool_number beside "
                "tool_json is refused rather than dropped."
            ),
        },
        tool_diameter={
            "type": "number",
            "minimum": 0.001,
            "maximum": 1000,
            "description": (
                "Diameter (cm) of the flat end mill this operation gets. The add-in "
                "builds a complete tool object, hands it to Fusion, and the operation "
                "can generate. Without a tool an operation cannot: Fusion answers "
                "'Toolpath requires tool to be selected.'"
            ),
        },
        tool_length={
            "type": "number",
            "minimum": 0.001,
            "maximum": 1000,
            "description": (
                "Flute length (cm) of the tool tool_diameter creates; defaults to "
                "three diameters."
            ),
        },
        tool_flutes={
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "description": (
                "Flute count of the tool tool_diameter creates; defaults to 2."
            ),
        },
        tool_json={
            "type": "string",
            "description": (
                "A complete tool object as JSON, taken from a Fusion tool library "
                "(one entry of its data array). Used verbatim instead of "
                "tool_diameter/tool_length/tool_flutes. It must be complete: a "
                "partial object crashed Fusion 2706.1.17."
            ),
        },
        stepdown={
            "type": "number",
            "minimum": 0.001,
            "description": "Axial depth of cut (cm)",
        },
        stepover={
            "type": "number",
            "minimum": 0.001,
            "description": ("Radial stepover (cm)"),
        },
        feed_rate={
            "type": "number",
            "description": "Feed rate (cm/min)",
        },
        spindle_speed={
            "type": "number",
            "description": "Spindle speed (RPM)",
        },
        coolant={
            "type": "string",
            "enum": [
                "disabled",
                "flood",
                "mist",
                "through_tool",
            ],
            "default": "flood",
        },
        body_name={
            "type": "string",
            "description": (
                "Body whose faces carry the operation's geometry; required with "
                "face_indices. Only the "
                f"{len(CAM_GEOMETRY_PARAMETERS)} strategies in CAM_GEOMETRY_PARAMETERS "
                "take a selection, and face is one of them - through its stock "
                "boundary, which aims the operation."
            ),
        },
        face_indices={
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "minItems": 1,
            "description": (
                "Faces to machine, by 0-based index in the body's own order "
                "(list_faces reports them, with each face's surface_type). Applied "
                "to the strategy's geometry parameter (contours/pockets/"
                "machiningBoundarySel/stockContours). Refused for any strategy "
                "without one."
            ),
        },
        checkpoint={
            "type": "boolean",
            "default": False,
            "description": (
                "Save the document first. A partial tool_json crashed Fusion 2706.1.17 "
                "and took the document's unsaved state with it; this is the guard, "
                "opt-in per call."
            ),
        },
    ),
    _tool(
        "cam_generate_toolpath",
        "Generate Toolpath",
        ("Generate toolpaths for a specific operation or all operations in a setup"),
        setup_name={
            "type": "string",
            "description": ("Setup name (generates all its operations)"),
        },
        operation_name={
            "type": "string",
            "description": (
                "Specific operation name; searched in every setup unless "
                "setup_name narrows it. generate_all=true takes precedence "
                "over both."
            ),
        },
        generate_all={
            "type": "boolean",
            "default": False,
            "description": "Generate all toolpaths",
        },
    ),
    _tool(
        "cam_post_process",
        "Post Process",
        ("Post-process toolpaths to generate NC code (G-code)"),
        required=["setup_name"],
        setup_name={
            "type": "string",
            "description": "Setup to post-process",
        },
        operation_name={
            "type": "string",
            "description": ("Specific operation (omit to post all in setup)"),
        },
        post_processor={
            "type": "string",
            "default": "fanuc",
            "description": (
                "Post processor short name ('fanuc', 'grbl', 'haas') "
                "resolved against the local post folder when the "
                "Fusion build provides one, or a full path to a "
                ".cps file (required on cloud-post builds)"
            ),
        },
        output_folder={
            "type": "string",
            "description": ("Output directory (default: ~/Desktop)"),
        },
        output_units={
            "type": "string",
            "enum": ["mm", "in"],
            "default": "mm",
        },
    ),
    _tool(
        "cam_list_setups",
        "List CAM Setups",
        ("List all manufacturing setups in the document"),
    ),
    _tool(
        "cam_list_operations",
        "List CAM Operations",
        ("List operations within a setup"),
        required=["setup_name"],
        setup_name={
            "type": "string",
        },
    ),
    _tool(
        "cam_get_operation_info",
        "Get CAM Operation Info",
        (
            "Get details about a specific operation "
            "(strategy, tool, parameters, toolpath status)"
        ),
        required=["setup_name", "operation_name"],
        setup_name={"type": "string"},
        operation_name={"type": "string"},
    ),
    # ── health ───────────────────────────────────────────────────────
    _tool(
        "ping",
        "Ping",
        ("Health check — returns immediately without touching Fusion API"),
    ),
    _tool(
        "health",
        "Health",
        (
            "Health check that runs on Fusion's main thread: the app version, the open "
            "document and how many commands are queued. Answers only when the main "
            "thread is actually executing work - ping answers from the socket thread, "
            "so a wedged Fusion still replies to it."
        ),
    ),
    _tool(
        "save_document",
        "Save Document",
        (
            "Save the active document in place, or save an untitled one by name into "
            "Fusion's active data folder. Measured on 2706.1.17: this API has no "
            "local-file save - saveAs takes a data folder and a name, not a path - and "
            "an untitled document is refused unless a name is given, because choosing "
            "a name or a folder for the caller is a write they did not ask for."
        ),
        name={
            "type": "string",
            "description": (
                "Name to save an untitled document under, in Fusion's active data "
                "folder. Omit for a document that already has one."
            ),
        },
    ),
    # ── design type safety ──────────────────────────────────────────────
    _tool(
        "get_design_type",
        "Get Design Type",
        (
            "Check if the design is in parametric or direct mode. "
            "Use this to detect accidental mode switches."
        ),
    ),
    _tool(
        "set_design_type",
        "Set Design Type",
        (
            "Switch design type between 'parametric' and 'direct'. "
            "Use 'parametric' to recover from accidental direct-mode "
            "switches (equivalent to Capture Design History in the UI)."
        ),
        required=["design_type"],
        design_type={
            "type": "string",
            "enum": ["parametric", "direct"],
            "description": "Target design type",
        },
    ),
    # ── perception ──────────────────────────────────────────────────────
    _tool(
        "render_view",
        "Render Viewport",
        (
            "Capture the active viewport as a PNG so you can visually verify "
            "the model. Pass a canonical view (iso/front/top/etc.) to "
            "reposition the camera first, or 'current' to keep it as is. "
            "Returns base64-encoded image bytes alongside metadata; the MCP "
            "server delivers it as an image content block."
        ),
        view={
            "type": "string",
            "enum": list(VIEW_PRESETS),
            "default": "current",
            "description": ("Camera preset; 'current' preserves the existing view"),
        },
        width={
            "type": "integer",
            "minimum": 64,
            "maximum": 4096,
            "default": 1024,
        },
        height={
            "type": "integer",
            "minimum": 64,
            "maximum": 4096,
            "default": 768,
        },
        fit={
            "type": "boolean",
            "default": True,
            "description": "Call Viewport.fit() before capture",
        },
    ),
]

# ── tool annotations ──────────────────────────────────────────────────
# Applied after definition for cleanliness. Classifies each tool by its
# side-effect profile so MCP clients can auto-approve safe operations.

_READ_ONLY = {
    "get_scene_info",
    "get_object_info",
    "list_edges",
    "list_faces",
    "get_bounding_box",
    "list_components",
    "get_parameters",
    "get_physical_properties",
    "measure_distance",
    "measure_angle",
    "check_interference",
    "compare_meshes",
    "ping",
    "health",
    "cam_list_setups",
    "cam_list_operations",
    "cam_get_operation_info",
    "get_design_type",
    "render_view",
}
_DESTRUCTIVE = {"delete_all", "delete_parameter", "execute_code"}
# Every read-only tool is also idempotent (repeating a read changes nothing),
# plus the setters whose second application lands on the same state.
_IDEMPOTENT = _READ_ONLY | {
    "set_parameter",
    "set_appearance",
    "set_color",
    "set_design_type",
    "rename_body",
}

for _t in TOOLS:
    _name = _t["name"]
    # One loop rather than 100 schema edits: the gate validates every tool against
    # this dict, and a client that skips the gate to reach :9876 directly must not
    # be the only caller an undeclared argument slips past.  A tool's inputSchema
    # lists every argument it accepts, so anything else is refused by name.
    _t["inputSchema"]["additionalProperties"] = False
    _t["annotations"] = {
        "readOnlyHint": _name in _READ_ONLY,
        "destructiveHint": _name in _DESTRUCTIVE,
        "idempotentHint": _name in _IDEMPOTENT,
    }


def get_tool_list() -> list[types.Tool]:
    """Convert tool dicts to MCP Tool objects."""
    result = []
    for t in TOOLS:
        ann = t.get("annotations")
        tool = types.Tool(
            name=t["name"],
            title=t["title"],
            description=t["description"],
            inputSchema=t["inputSchema"],
            annotations=types.ToolAnnotations(**ann) if ann else None,
        )
        result.append(tool)
    return result


def get_tool_by_name(name: str) -> dict | None:
    for t in TOOLS:
        if t["name"] == name:
            return t
    return None
