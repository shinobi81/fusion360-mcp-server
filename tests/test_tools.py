"""Tests for the tool registry."""

from fusion360_mcp.tools import TOOLS, get_tool_by_name, get_tool_list


def test_all_tools_have_required_keys():
    for t in TOOLS:
        assert "name" in t, f"Tool missing 'name': {t}"
        assert "title" in t, f"Tool {t['name']} missing 'title'"
        assert "description" in t, f"Tool {t['name']} missing 'description'"
        assert "inputSchema" in t, f"Tool {t['name']} missing 'inputSchema'"


def test_all_schemas_are_objects():
    for t in TOOLS:
        schema = t["inputSchema"]
        assert schema.get("type") == "object", (
            f"Tool {t['name']} schema type is not 'object'"
        )


def test_required_fields_exist_in_properties():
    """Every field listed in 'required' must also appear in 'properties'."""
    for t in TOOLS:
        schema = t["inputSchema"]
        required = schema.get("required", [])
        props = schema.get("properties", {})
        for field in required:
            assert field in props, (
                f"Tool {t['name']}: required field '{field}' "
                f"not in properties {list(props)}"
            )


def test_no_duplicate_tool_names():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names)), (
        f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"
    )


def test_get_tool_list_returns_mcp_types():
    tools = get_tool_list()
    assert len(tools) == len(TOOLS)
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "inputSchema")


def test_get_tool_by_name_found():
    assert get_tool_by_name("ping") is not None
    assert get_tool_by_name("extrude") is not None


def test_get_tool_by_name_missing():
    assert get_tool_by_name("nonexistent_tool") is None


def test_expected_tools_present():
    """Verify the full set of commands we expect."""
    names = {t["name"] for t in TOOLS}
    expected = {
        # documents
        "new_document",
        # scene / query
        "get_scene_info",
        "get_object_info",
        "list_edges",
        "get_bounding_box",
        # sketch
        "create_sketch",
        "draw_rectangle",
        "draw_circle",
        "draw_line",
        # features
        "extrude",
        "revolve",
        "fillet",
        "chamfer",
        "shell",
        "mirror",
        # body ops
        "move_body",
        "export_stl",
        "boolean_operation",
        # scene control
        "delete_all",
        "undo",
        # code execution
        "execute_code",
        # health
        "ping",
        # new geometry
        "sweep",
        "loft",
        "create_polygon",
        "draw_circles",
        "draw_arc",
        "create_hole",
        "rectangular_pattern",
        "circular_pattern",
        # assembly
        "create_component",
        "add_joint",
        "set_joint_value",
        "list_components",
        # export
        "export_step",
        "export_f3d",
        "export_view_sheet",
        "export",
        # import
        "import_mesh",
        # parameters
        "get_parameters",
        "create_parameter",
        "set_parameter",
        "delete_parameter",
        # sketch constraints & dimensions
        "add_constraint",
        "auto_constrain",
        "add_dimension",
        # construction geometry
        "create_construction_plane",
        "create_construction_axis",
        "create_ucs",
        # splines
        "draw_spline",
        # sketch curve operations
        "offset_curve",
        "trim_curve",
        "extend_curve",
        # advanced features
        "create_thread",
        "draft_faces",
        "split_body",
        "split_face",
        "offset_faces",
        "scale_body",
        # direct primitives
        "create_box",
        "create_cylinder",
        "create_sphere",
        "create_torus",
        "create_box_parametric",
        # assembly (extended)
        "create_as_built_joint",
        "create_rigid_group",
        # inspection / analysis
        "measure_distance",
        "measure_angle",
        "get_physical_properties",
        "create_section_analysis",
        "check_interference",
        "compare_meshes",
        # appearance
        "set_appearance",
        "set_color",
        # project geometry
        "project_geometry",
        # timeline control
        "suppress_feature",
        "unsuppress_feature",
        # surface operations
        "patch_surface",
        "stitch_surfaces",
        "thicken_surface",
        "ruled_surface",
        "trim_surface",
        # sheet metal
        "create_flange",
        "create_bend",
        "flat_pattern",
        "unfold",
        # CAM / manufacturing
        "cam_create_setup",
        "cam_create_operation",
        "cam_generate_toolpath",
        "cam_post_process",
        "cam_list_setups",
        "cam_list_operations",
        "cam_get_operation_info",
        # design type safety
        "get_design_type",
        "set_design_type",
        # utility
        "rename_body",
        # perception
        "render_view",
    }
    missing = expected - names
    assert not missing, f"Missing tools: {missing}"
    extra = names - expected
    assert not extra, f"Unexpected tools: {extra}"


def test_all_tools_have_annotations():
    """Every tool should have annotations after module load."""
    for t in TOOLS:
        ann = t.get("annotations")
        assert ann is not None, f"Tool {t['name']} missing annotations"
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint"):
            assert key in ann, f"Tool {t['name']} missing annotation '{key}'"
            assert isinstance(ann[key], bool), f"Tool {t['name']}.{key} should be bool"


def test_property_types_are_valid():
    """Every property in every schema should have a valid JSON Schema type."""
    valid_types = {"string", "number", "integer", "boolean", "array", "object"}
    for t in TOOLS:
        props = t["inputSchema"].get("properties", {})
        for field, spec in props.items():
            if "type" in spec:
                assert spec["type"] in valid_types, (
                    f"Tool {t['name']}.{field}: invalid type '{spec['type']}'"
                )


def test_enum_fields_are_lists():
    """Every 'enum' in a property should be a non-empty list."""
    for t in TOOLS:
        props = t["inputSchema"].get("properties", {})
        for field, spec in props.items():
            if "enum" in spec:
                assert isinstance(spec["enum"], list), (
                    f"Tool {t['name']}.{field}: enum not a list"
                )
                assert len(spec["enum"]) > 0, f"Tool {t['name']}.{field}: enum is empty"


def test_minimum_less_than_maximum():
    """If both min and max are set, min should be < max."""
    for t in TOOLS:
        props = t["inputSchema"].get("properties", {})
        for field, spec in props.items():
            if "minimum" in spec and "maximum" in spec:
                assert spec["minimum"] < spec["maximum"], (
                    f"Tool {t['name']}.{field}: "
                    f"min ({spec['minimum']}) >= max ({spec['maximum']})"
                )


def test_descriptions_are_nonempty():
    """Every tool should have a non-empty description."""
    for t in TOOLS:
        assert len(t["description"].strip()) > 0, (
            f"Tool {t['name']} has empty description"
        )
        assert len(t["title"].strip()) > 0, f"Tool {t['name']} has empty title"


def test_tool_names_are_snake_case():
    """Tool names should be snake_case."""
    import re

    for t in TOOLS:
        assert re.match(r"^[a-z][a-z0-9_]*$", t["name"]), (
            f"Tool name '{t['name']}' is not snake_case"
        )


def test_get_tool_list_annotations_propagated():
    """MCP Tool objects should carry annotations."""
    tools = get_tool_list()
    for tool in tools:
        assert tool.annotations is not None, f"MCP Tool {tool.name} missing annotations"


def test_get_tool_by_name_returns_correct_tool():
    """get_tool_by_name should return the exact matching tool."""
    for t in TOOLS:
        found = get_tool_by_name(t["name"])
        assert found is t, f"get_tool_by_name('{t['name']}') returned wrong object"


def test_get_tool_by_name_edge_cases():
    assert get_tool_by_name("") is None
    assert get_tool_by_name("PING") is None  # case sensitive
    assert get_tool_by_name("ping ") is None  # trailing space


#: How many arguments each tool declares.
#:
#: Not the registry the old ``test_expected_tools_present`` copied - that restated
#: the tool *names*, which ``test_addon_sync.py`` and ``TestMockDispatchCoverage``
#: already pin twice.  Nothing pinned a tool's *shape*, and the schema literal in
#: ``tools.py`` is far too large to review line by line, so a dropped argument was
#: a silent change to the contract every agent reads.  A count catches a drop or an
#: addition; a *rename* keeps the count and shows up in the schema diff instead.
#: Regenerated with a dict comprehension over ``TOOLS`` - see the PR that added it.
_TOOL_ARGUMENT_COUNTS = {
    "get_scene_info": 0,
    "get_object_info": 1,
    "get_bounding_box": 1,
    "create_sketch": 2,
    "draw_rectangle": 6,
    "draw_circle": 5,
    "draw_line": 7,
    "extrude": 6,
    "revolve": 11,
    "fillet": 7,
    "chamfer": 7,
    "shell": 4,
    "mirror": 3,
    "rename_body": 2,
    "move_body": 4,
    "export_stl": 2,
    "boolean_operation": 4,
    "delete_all": 0,
    "undo": 0,
    "execute_code": 1,
    "sweep": 6,
    "loft": 3,
    "create_polygon": 6,
    "draw_arc": 8,
    "create_hole": 7,
    "rectangular_pattern": 5,
    "circular_pattern": 4,
    "new_document": 1,
    "create_component": 2,
    "add_joint": 11,
    "set_joint_value": 6,
    "list_edges": 3,
    "list_components": 0,
    "export_step": 2,
    "export_f3d": 1,
    "export_view_sheet": 5,
    "export": 3,
    "import_mesh": 3,
    "get_parameters": 0,
    "create_parameter": 4,
    "set_parameter": 2,
    "delete_parameter": 1,
    "draw_circles": 7,
    "add_constraint": 5,
    "auto_constrain": 2,
    "add_dimension": 5,
    "create_construction_plane": 10,
    "create_construction_axis": 7,
    "create_ucs": 7,
    "draw_spline": 4,
    "offset_curve": 5,
    "trim_curve": 4,
    "extend_curve": 4,
    "create_thread": 9,
    "draft_faces": 5,
    "split_body": 4,
    "split_face": 4,
    "offset_faces": 4,
    "scale_body": 8,
    "create_box": 6,
    "create_box_parametric": 9,
    "create_cylinder": 6,
    "create_sphere": 4,
    "create_torus": 6,
    "create_as_built_joint": 11,
    "create_rigid_group": 2,
    "measure_distance": 2,
    "measure_angle": 2,
    "get_physical_properties": 2,
    "create_section_analysis": 2,
    "check_interference": 2,
    "compare_meshes": 2,
    "set_appearance": 4,
    "set_color": 5,
    "project_geometry": 3,
    "suppress_feature": 1,
    "unsuppress_feature": 1,
    "patch_surface": 3,
    "stitch_surfaces": 2,
    "thicken_surface": 3,
    "ruled_surface": 4,
    "trim_surface": 2,
    "create_flange": 5,
    "create_bend": 4,
    "flat_pattern": 1,
    "unfold": 2,
    "cam_create_setup": 7,
    "cam_create_operation": 10,
    "cam_generate_toolpath": 3,
    "cam_post_process": 5,
    "cam_list_setups": 0,
    "cam_list_operations": 1,
    "cam_get_operation_info": 2,
    "ping": 0,
    "get_design_type": 0,
    "set_design_type": 1,
    "render_view": 4,
}


def test_each_tool_declares_the_number_of_arguments_it_does_today():
    """A dropped or added argument cannot pass silently."""
    current = {t["name"]: len(t["inputSchema"]["properties"]) for t in TOOLS}

    assert current == _TOOL_ARGUMENT_COUNTS
