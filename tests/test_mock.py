"""Tests for the mock command dispatch."""

import pytest

from addon.server.cam_tool import build_tool_json
from fusion360_mcp.mock import _DISPATCH, mock_command
from fusion360_mcp.tools import TOOLS


class TestMockDispatchCoverage:
    """Every tool defined in tools.py must have a mock handler."""

    def test_every_tool_has_a_mock_handler(self):
        tool_names = {t["name"] for t in TOOLS}
        dispatch_names = set(_DISPATCH.keys())
        missing = tool_names - dispatch_names
        assert not missing, f"Tools without mock handlers: {missing}"


class TestMockResponseStructure:
    """Every mock response must be a dict and include 'mode': 'mock'."""

    @pytest.mark.parametrize("tool_name", [t["name"] for t in TOOLS])
    def test_response_is_dict_with_mode_mock(self, tool_name):
        result = mock_command(tool_name, {})
        assert isinstance(result, dict)
        assert result["mode"] == "mock"


class TestMockPing:
    def test_ping_returns_pong(self):
        result = mock_command("ping")
        assert result["status"] == "pong"
        assert result["mode"] == "mock"


class TestMockSceneQuery:
    def test_get_scene_info(self):
        result = mock_command("get_scene_info")
        assert "design_name" in result
        assert "bodies" in result
        assert "sketches" in result

    def test_get_object_info(self):
        result = mock_command("get_object_info", {"name": "TestBody"})
        assert result["name"] == "TestBody"
        assert "faces" in result

    def test_get_bounding_box(self):
        result = mock_command("get_bounding_box", {"name": "TestBody"})
        assert result["name"] == "TestBody"
        assert result["found"] is True
        assert result["min"] == [0.0, 0.0, 0.0]
        assert len(result["size"]) == 3
        assert len(result["center"]) == 3

    def test_import_mesh(self):
        result = mock_command(
            "import_mesh",
            {
                "file_path": "/tmp/wheel_arch.stl",
                "units": "mm",
            },
        )
        assert result["imported"] is True
        assert result["file_path"] == "/tmp/wheel_arch.stl"
        assert result["units"] == "mm"
        assert "mesh_name" in result
        assert "bounding_box" in result

    def test_create_box_parametric_numeric(self):
        result = mock_command(
            "create_box_parametric",
            {
                "length": 56,
                "width": 30,
                "height": 25,
            },
        )
        assert result["created"] is True
        assert result["length"] == 56
        assert "body_name" in result
        assert "sketch_name" in result

    def test_create_box_parametric_expression(self):
        result = mock_command(
            "create_box_parametric",
            {
                "length": "boxL",
                "width": "boxW",
                "height": "boxH - wall_t",
                "body_name": "BoxRechts",
            },
        )
        assert result["body_name"] == "BoxRechts"
        assert result["height"] == "boxH - wall_t"

    def test_export_unified_infers_format(self):
        result = mock_command(
            "export",
            {
                "body_name": "BoxRechts",
                "file_path": "/tmp/BoxRechts.step",
            },
        )
        assert result["exported"] is True
        assert result["format"] == "step"
        assert result["body"] == "BoxRechts"

    def test_export_unified_explicit_format(self):
        result = mock_command(
            "export",
            {
                "format": "stl",
                "body_name": "Part1",
            },
        )
        assert result["format"] == "stl"


class TestMockSketch:
    def test_create_sketch(self):
        result = mock_command("create_sketch", {"plane": "yz"})
        assert "yz" in result["sketch_name"]
        assert result["plane"] == "yz"

    def test_draw_rectangle(self):
        result = mock_command("draw_rectangle", {"width": 5, "height": 3})
        assert result["width"] == 5
        assert result["height"] == 3

    def test_draw_circle(self):
        result = mock_command("draw_circle", {"radius": 2.5})
        assert result["radius"] == 2.5

    def test_draw_line(self):
        result = mock_command(
            "draw_line",
            {
                "start_x": 0,
                "start_y": 0,
                "end_x": 10,
                "end_y": 5,
            },
        )
        assert result["start"] == [0, 0]
        assert result["end"] == [10, 5]


class TestMockFeatures:
    def test_extrude(self):
        result = mock_command("extrude", {"height": 3, "operation": "cut"})
        assert result["height"] == 3
        assert result["operation"] == "cut"
        assert "body_name" in result

    def test_revolve(self):
        result = mock_command("revolve", {"angle": 180})
        assert result["angle"] == 180

    def test_fillet(self):
        result = mock_command("fillet", {"radius": 0.5, "body_name": "Box"})
        assert result["body_name"] == "Box"
        assert result["radius"] == 0.5

    def test_chamfer(self):
        result = mock_command("chamfer", {"distance": 0.2, "body_name": "Box"})
        assert result["body_name"] == "Box"

    def test_shell(self):
        result = mock_command("shell", {"thickness": 0.3, "body_name": "Box"})
        assert result["body_name"] == "Box"

    def test_mirror(self):
        result = mock_command("mirror", {"mirror_plane": "xz", "body_name": "Box"})
        assert result["mirror_plane"] == "xz"
        assert "new_body_name" in result

    def test_create_hole_reports_the_keys_agents_verify_against(self):
        # actual_diameter / resolved_center let a caller check what was made
        # against what it asked for; mock mode must carry them.
        result = mock_command(
            "create_hole",
            {
                "diameter": 0.52,
                "depth": 0.6,
                "body_name": "Plate",
                "center_x": 22,
                "center_y": 1.5,
            },
        )
        assert result["actual_diameter"] == 0.52
        assert result["resolved_center"][:2] == [22, 1.5]
        assert result["body_name"] == "Plate"
        # No cut_bodies: Feature.bodies reports the participant the handler set,
        # not what was cut, so the field would echo its own input. The measured
        # answer to "did it cut?" is the envelope's deltas.
        assert "cut_bodies" not in result

    def test_create_hole_falls_back_to_body_index(self):
        result = mock_command("create_hole", {"diameter": 0.5, "body_index": 1})
        assert result["body_name"] == "Body2"
        assert "cut_bodies" not in result


class TestMockBodyOps:
    def test_move_body(self):
        result = mock_command("move_body", {"body_name": "B1", "x": 5, "z": 3})
        assert result["body_name"] == "B1"
        assert result["translation"] == [5, 0, 3]

    def test_export_stl(self):
        result = mock_command("export_stl", {"body_name": "B1"})
        assert result["body_name"] == "B1"
        assert "file_path" in result

    def test_boolean_operation(self):
        result = mock_command(
            "boolean_operation",
            {
                "target_body": "A",
                "tool_body": "B",
                "operation": "cut",
            },
        )
        assert result["target_body"] == "A"
        assert result["operation"] == "cut"


class TestMockSceneControl:
    def test_delete_all(self):
        result = mock_command("delete_all")
        assert result["deleted"] is True

    def test_undo(self):
        result = mock_command("undo")
        assert result["undone"] == "issued"
        assert result["verified"] is False
        assert "design_type" in result
        # an undo must not carry the synthetic "a body appeared" deltas
        assert "deltas" not in result


class TestMockExecuteCode:
    def test_execute_code(self):
        result = mock_command("execute_code", {"code": "1 + 1"})
        assert result["code"] == "1 + 1"
        assert "result" in result

    def test_execute_code_reports_that_mock_ran_nothing(self):
        """Mock executes no code, so it changed nothing - and the fabricated "a body
        appeared" deltas would claim a build mock never made. The add-in judges an
        unchanged snapshot with the same function, so both modes say the same thing
        about the same call."""
        result = mock_command("execute_code", {"code": "count = 1"})

        assert result["deltas"]["body_count_delta"] == 0
        assert result["deltas"]["mass_g_delta"] == 0.0
        # Mock's scene already has its one body: the numbers say "unchanged from here",
        # not "nothing exists".
        assert result["deltas"]["body_count_before"] == 1
        assert result["warning"].startswith("nothing changed in the snapshot: ")

    def test_a_building_mutation_carries_no_warning(self):
        """The other half of the parity: mock's extrude really does add its body."""
        result = mock_command("extrude", {"height": 3.0})

        assert result["deltas"]["body_count_delta"] == 1
        assert "warning" not in result


class TestMockNewGeometry:
    def test_sweep(self):
        result = mock_command(
            "sweep",
            {
                "profile_index": 0,
                "path_sketch_name": "PathSketch1",
            },
        )
        assert result["path_sketch_name"] == "PathSketch1"
        assert "body_name" in result

    def test_loft(self):
        result = mock_command(
            "loft",
            {
                "profile_sketch_names": ["Top", "Bottom"],
            },
        )
        assert result["profile_sketch_names"] == ["Top", "Bottom"]

    def test_create_polygon(self):
        result = mock_command("create_polygon", {"sides": 8, "radius": 2})
        assert result["sides"] == 8
        assert result["radius"] == 2

    def test_draw_arc(self):
        result = mock_command(
            "draw_arc",
            {
                "center_x": 0,
                "center_y": 0,
                "start_x": 1,
                "start_y": 0,
                "sweep_angle": 90,
            },
        )
        assert result["sweep_angle"] == 90

    def test_create_hole(self):
        result = mock_command(
            "create_hole",
            {
                "diameter": 0.5,
                "depth": 2,
                "body_name": "Plate",
            },
        )
        assert result["diameter"] == 0.5
        assert result["depth"] == 2
        assert result["body_name"] == "Plate"

    def test_rectangular_pattern(self):
        result = mock_command(
            "rectangular_pattern",
            {
                "body_name": "Pin",
                "x_count": 3,
                "y_count": 2,
            },
        )
        assert result["x_count"] == 3
        assert result["y_count"] == 2
        assert result["created_bodies"] == 6

    def test_circular_pattern(self):
        result = mock_command(
            "circular_pattern",
            {
                "body_name": "Lug",
                "count": 4,
                "axis": "z",
            },
        )
        assert result["count"] == 4
        assert result["axis"] == "z"


class TestMockAssembly:
    def test_create_component(self):
        result = mock_command("create_component", {"name": "Bracket"})
        assert result["component_name"] == "Bracket"

    def test_add_joint(self):
        result = mock_command(
            "add_joint",
            {
                "component_one": "A",
                "component_two": "B",
                "joint_type": "revolute",
                "face_one": 0,
                "face_two": 0,
            },
        )
        assert result["joint_type"] == "revolute"
        assert "joint_name" in result

    def test_list_components(self):
        result = mock_command("list_components")
        assert "components" in result
        assert len(result["components"]) > 0


class TestMockExport:
    def test_export_step(self):
        result = mock_command("export_step", {"body_name": "Shaft"})
        assert result["body_name"] == "Shaft"
        assert "file_path" in result

    def test_export_f3d(self):
        result = mock_command("export_f3d", {})
        assert "file_path" in result

    def test_export_view_sheet_defaults(self):
        result = mock_command("export_view_sheet", {})
        assert result["html_path"].endswith("view_sheet.html")
        assert result["image_size"] == [1200, 900]
        view_names = [v["view"] for v in result["views"]]
        assert view_names == ["iso", "front", "top", "right"]
        for v in result["views"]:
            assert v["path"].endswith(f"{v['view']}.png")

    def test_export_view_sheet_custom(self):
        result = mock_command(
            "export_view_sheet",
            {
                "title": "Orb v0.4",
                "views": ["iso", "front", "right"],
                "image_size": [1920, 1080],
                "output_dir": "/tmp/orb_views",
            },
        )
        assert result["title"] == "Orb v0.4"
        assert result["image_size"] == [1920, 1080]
        assert result["output_dir"] == "/tmp/orb_views"
        assert [v["view"] for v in result["views"]] == ["iso", "front", "right"]


class TestMockParameters:
    def test_get_parameters(self):
        result = mock_command("get_parameters")
        assert "parameters" in result
        assert len(result["parameters"]) > 0
        assert "name" in result["parameters"][0]
        assert "value" in result["parameters"][0]

    def test_create_parameter(self):
        result = mock_command(
            "create_parameter",
            {
                "name": "wall_thickness",
                "value": 2.0,
                "unit": "mm",
            },
        )
        assert result["name"] == "wall_thickness"
        assert result["value"] == 2.0
        assert result["unit"] == "mm"

    def test_set_parameter(self):
        result = mock_command(
            "set_parameter",
            {
                "name": "wall_thickness",
                "value": 3.0,
            },
        )
        assert result["name"] == "wall_thickness"
        assert result["value"] == 3.0

    def test_delete_parameter(self):
        result = mock_command("delete_parameter", {"name": "wall_thickness"})
        assert result["name"] == "wall_thickness"
        assert result["deleted"] is True


class TestMockParametersRefuseNonFiniteValues:
    """The add-in refuses Infinity/NaN; mock mode must not advertise them.

    ``json.loads`` accepts those literals, so a caller can deliver one. Mock
    mode advertises itself as agreeing with the add-in, and an ``ok: True``
    carrying ``"inf mm"`` would hide the very failure the add-in refuses.
    """

    @pytest.mark.parametrize(
        ("value", "rendered"),
        [(float("inf"), "inf"), (float("-inf"), "-inf"), (float("nan"), "nan")],
    )
    def test_create_parameter_refuses_a_non_finite_value(self, value, rendered):
        result = mock_command(
            "create_parameter",
            {"name": "wall_thickness", "value": value, "unit": "mm"},
        )
        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"
        assert result["error_message"].startswith("invalid parameter value")
        assert rendered in result["error_message"]
        assert result["hints"], "the hints come from classify(), not from prose"
        # The finiteness rule, not the generic INVALID_INPUT one that blames units.
        assert not any("unit" in hint.lower() for hint in result["hints"])
        assert result["mode"] == "mock"
        assert "expression" not in result

    @pytest.mark.parametrize(
        ("value", "rendered"),
        [(float("inf"), "inf"), (float("-inf"), "-inf"), (float("nan"), "nan")],
    )
    def test_set_parameter_refuses_a_non_finite_value(self, value, rendered):
        result = mock_command(
            "set_parameter", {"name": "wall_thickness", "value": value}
        )
        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"
        assert rendered in result["error_message"]
        # set_parameter is a mutation mock, but a refusal must not report the
        # synthetic "body appeared" deltas.
        assert "deltas" not in result

    def test_a_finite_value_still_creates_the_parameter(self):
        result = mock_command(
            "create_parameter",
            {"name": "wall_thickness", "value": 2.5, "unit": "mm"},
        )
        assert result["ok"] is True
        assert result["expression"] == "2.5 mm"

    def test_a_finite_value_still_sets_the_parameter(self):
        result = mock_command("set_parameter", {"name": "wall_thickness", "value": 3.0})
        assert result["ok"] is True
        assert "deltas" in result


class TestMockConstraints:
    def test_add_constraint_coincident(self):
        result = mock_command(
            "add_constraint",
            {
                "constraint_type": "coincident",
                "entity_one": 0,
                "entity_two": 3,
            },
        )
        assert result["constraint_type"] == "coincident"
        assert result["entity_one"] == 0
        assert result["entity_two"] == 3

    def test_add_dimension_distance(self):
        result = mock_command(
            "add_dimension",
            {
                "dimension_type": "distance",
                "value": 5.0,
                "entity_one": 0,
                "entity_two": 1,
            },
        )
        assert result["dimension_type"] == "distance"
        assert result["value"] == 5.0


class TestMockConstructionGeometry:
    def test_create_construction_plane_tangent_answers_the_handlers_keys(self):
        """The rehearsal path for the form this PR added: no design, no body lookup."""
        reply = mock_command(
            "create_construction_plane",
            {
                "method": "tangent",
                "body_name": "Body1",
                "face_index": 0,
                "plane": "xz",
            },
        )

        assert reply["created"] is True
        assert reply["method"] == "tangent"
        # The handler's keys plus the envelope's own: `plane_name` was never one.
        assert {"created", "name", "method"} <= set(reply)

    def test_mock_refuses_an_unset_plane_for_every_method_that_resolves_one(self):
        """The add-in refuses `None` and `''` alike, for `offset`, `angle` and
        `midplane`. Mock skipping an absent name rehearsed success for a call the
        add-in answers `Unknown plane None` - an MCP caller's `plane` is optional."""
        for params in (
            {"method": "offset", "offset": 5},
            {"method": "angle", "angle": 30},
            {"method": "midplane", "plane_one": "xy"},
        ):
            reply = mock_command("create_construction_plane", params)

            assert reply.get("created") is not True, params
            assert reply["error_kind"] == "INVALID_INPUT", params
            assert "Unknown plane" in reply["error_message"], params

    def test_mock_ignores_a_plane_name_the_chosen_branch_never_reads(self):
        """`offset` never resolves `plane_one`, and a tangent call with a point never
        resolves `plane`: inventing a refusal for either would answer a call the add-in
        builds."""
        offset = mock_command(
            "create_construction_plane",
            {"method": "offset", "plane": "xy", "offset": 5, "plane_one": "zz"},
        )
        tangent = mock_command(
            "create_construction_plane",
            {
                "method": "tangent",
                "body_name": "Body1",
                "face_index": 0,
                "point_one": [0.0, 0.0, 5.0],
                "plane": "",
            },
        )

        assert offset["created"] is True
        assert tangent["created"] is True

    def test_mock_refuses_a_plane_name_the_add_in_refuses(self):
        """`plane="zz"` is truthy, so the shape rule passes it: without the name check
        mock built a plane the handler refuses before Fusion is asked."""
        reply = mock_command(
            "create_construction_plane",
            {
                "method": "tangent",
                "body_name": "Body1",
                "face_index": 0,
                "plane": "zz",
            },
        )

        assert reply["error_kind"] == "INVALID_INPUT"
        assert "Unknown plane 'zz'" in reply["error_message"]

    def test_create_construction_plane_offset(self):
        result = mock_command(
            "create_construction_plane",
            {
                "method": "offset",
                "plane": "xy",
                "offset": 5,
            },
        )
        assert result["method"] == "offset"
        # The handler's keys: `created`, the plane `name`, and the method.
        assert result["created"] is True
        assert "name" in result

    def test_create_construction_axis_two_points(self):
        result = mock_command(
            "create_construction_axis",
            {
                "method": "two_points",
                "point_one": [0, 0, 0],
                "point_two": [1, 0, 0],
            },
        )
        assert result["method"] == "two_points"
        # The handler's keys: `created`, the axis `name`, and the method.
        assert result["created"] is True
        assert "name" in result


class TestMockSplines:
    def test_draw_spline_fit_points(self):
        pts = [[0, 0], [1, 2], [3, 1], [5, 0]]
        result = mock_command(
            "draw_spline",
            {
                "spline_type": "fit_points",
                "points": pts,
            },
        )
        assert result["spline_type"] == "fit_points"
        assert result["point_count"] == 4

    def test_draw_spline_control_points(self):
        pts = [[0, 0, 0], [1, 2, 0], [3, 1, 0]]
        result = mock_command(
            "draw_spline",
            {
                "spline_type": "control_points",
                "points": pts,
                "degree": 3,
            },
        )
        assert result["spline_type"] == "control_points"


class TestMockCurveOps:
    def test_offset_curve(self):
        result = mock_command(
            "offset_curve",
            {
                "curve_index": 0,
                "offset_distance": 0.5,
            },
        )
        assert result["offset_distance"] == 0.5
        assert "new_curve_count" in result

    def test_trim_curve(self):
        result = mock_command(
            "trim_curve",
            {
                "curve_index": 2,
                "point_x": 1.0,
                "point_y": 0.5,
            },
        )
        assert result["curve_index"] == 2
        assert result["trimmed"] is True

    def test_extend_curve(self):
        result = mock_command(
            "extend_curve",
            {
                "curve_index": 1,
                "point_x": 5.0,
                "point_y": 0,
            },
        )
        assert result["curve_index"] == 1
        assert result["extended"] is True


class TestMockAdvancedFeatures:
    def test_create_thread(self):
        result = mock_command(
            "create_thread",
            {
                "body_name": "Bolt",
                "face_index": 0,
                "thread_designation": "M8x1.25",
                "is_modeled": True,
            },
        )
        assert result["feature_name"] == "Thread1"
        assert result["body_name"] == "Bolt"
        assert result["thread_designation"] == "M8x1.25"
        assert result["is_modeled"] is True
        # External by default, so the ISO external class - the same conditional
        # default the handler applies.
        assert result["thread_class"] == "6g"
        assert result["is_internal"] is False

    def test_draft_faces(self):
        result = mock_command(
            "draft_faces",
            {
                "body_name": "Housing",
                "angle": 3,
            },
        )
        assert result["body_name"] == "Housing"
        assert result["angle"] == 3

    def test_split_body(self):
        result = mock_command("split_body", {"body_name": "Block"})
        assert result["body_name"] == "Block"
        assert len(result["result_bodies"]) == 2

    def test_split_face(self):
        result = mock_command("split_face", {"body_name": "Block"})
        assert result["body_name"] == "Block"
        assert result["faces_split"] > 0

    def test_offset_faces(self):
        result = mock_command(
            "offset_faces",
            {
                "body_name": "Box",
                "distance": 0.2,
            },
        )
        assert result["body_name"] == "Box"
        assert result["distance"] == 0.2

    def test_scale_body(self):
        result = mock_command(
            "scale_body",
            {
                "body_name": "Widget",
                "scale": 2.0,
            },
        )
        assert result["body_name"] == "Widget"
        assert result["scale"] == 2.0


class TestMockDirectPrimitives:
    def test_create_box(self):
        result = mock_command(
            "create_box",
            {
                "length": 10,
                "width": 5,
                "height": 3,
            },
        )
        assert result["length"] == 10
        assert result["width"] == 5
        assert result["height"] == 3
        assert "body_name" in result

    def test_create_cylinder(self):
        result = mock_command(
            "create_cylinder",
            {
                "radius": 2,
                "height": 8,
            },
        )
        assert result["radius"] == 2
        assert result["height"] == 8

    def test_create_sphere(self):
        result = mock_command("create_sphere", {"radius": 3})
        assert result["radius"] == 3

    def test_create_torus(self):
        result = mock_command(
            "create_torus",
            {
                "major_radius": 5,
                "minor_radius": 1,
            },
        )
        assert result["major_radius"] == 5
        assert result["minor_radius"] == 1


class TestMockAssemblyExtended:
    def test_create_as_built_joint(self):
        result = mock_command(
            "create_as_built_joint",
            {
                "component_one": "Arm",
                "component_two": "Base",
                "joint_type": "revolute",
                "face_one": 0,
                "face_two": 0,
            },
        )
        assert result["component_one"] == "Arm"
        assert result["joint_type"] == "revolute"
        assert "joint_name" in result

    def test_create_rigid_group(self):
        result = mock_command(
            "create_rigid_group",
            {
                "component_names": ["A", "B", "C"],
            },
        )
        assert result["component_names"] == ["A", "B", "C"]
        assert "rigid_group_name" in result


class TestMockInspection:
    def test_measure_distance(self):
        result = mock_command(
            "measure_distance",
            {
                "entity_one": "Body1",
                "entity_two": "Body2",
            },
        )
        assert result["entity_one"] == "Body1"
        assert isinstance(result["distance"], float)
        assert "point_one" in result

    def test_measure_angle(self):
        result = mock_command(
            "measure_angle",
            {
                "entity_one": "TopFace",
                "entity_two": "SideFace",
            },
        )
        assert result["entity_one"] == "TopFace"
        assert "angle_degrees" in result

    def test_get_physical_properties(self):
        result = mock_command(
            "get_physical_properties",
            {
                "body_name": "Bracket",
            },
        )
        assert result["body_name"] == "Bracket"
        assert "mass" in result
        assert "volume" in result
        assert "area" in result
        assert "center_of_mass" in result

    def test_create_section_analysis(self):
        result = mock_command(
            "create_section_analysis",
            {
                "plane": "xz",
                "offset": 2.5,
            },
        )
        assert result["plane"] == "xz"
        assert result["offset"] == 2.5
        assert "analysis_name" in result

    def test_check_interference(self):
        result = mock_command(
            "check_interference",
            {
                "component_names": ["Gear1", "Gear2"],
            },
        )
        assert result["component_names"] == ["Gear1", "Gear2"]
        assert "interference_count" in result


class TestMockAppearance:
    def test_set_appearance(self):
        result = mock_command(
            "set_appearance",
            {
                "target_name": "Housing",
                "appearance_name": "Aluminum - Anodized Red",
            },
        )
        assert result["target_name"] == "Housing"
        assert result["appearance_name"] == "Aluminum - Anodized Red"
        assert result["applied"] is True


class TestMockProjectGeometry:
    def test_project_geometry(self):
        result = mock_command(
            "project_geometry",
            {
                "source_name": "TopEdge",
                "sketch_name": "Sketch2",
            },
        )
        # The keys the real handler reports, not the request's own names: mock
        # mode exists so an agent can rehearse against the real envelope.
        assert result["source"] == "TopEdge"
        assert result["sketch"] == "Sketch2"
        assert result["is_linked"] is True
        assert "projected_curves" in result


class TestMockTimelineControl:
    def test_suppress_feature(self):
        result = mock_command("suppress_feature", {"feature_name": "Extrude1"})
        assert result["feature_name"] == "Extrude1"
        assert result["suppressed"] is True

    def test_unsuppress_feature(self):
        result = mock_command("unsuppress_feature", {"feature_name": "Extrude1"})
        assert result["feature_name"] == "Extrude1"
        assert result["suppressed"] is False


class TestMockSurfaceOps:
    def test_patch_surface(self):
        result = mock_command("patch_surface", {"sketch_name": "Boundary1"})
        assert result["sketch_name"] == "Boundary1"
        assert "body_name" in result

    def test_stitch_surfaces(self):
        result = mock_command(
            "stitch_surfaces",
            {
                "body_names": ["Surf1", "Surf2"],
            },
        )
        assert result["body_names"] == ["Surf1", "Surf2"]
        assert "result_body" in result

    def test_thicken_surface(self):
        result = mock_command(
            "thicken_surface",
            {
                "body_name": "Surf1",
                "thickness": 0.2,
            },
        )
        assert result["body_name"] == "Surf1"
        assert result["thickness"] == 0.2
        assert "result_body" in result

    def test_ruled_surface(self):
        result = mock_command(
            "ruled_surface",
            {
                "body_name": "Body1",
                "edge_index": 2,
                "distance": 1.5,
            },
        )
        assert result["edge_index"] == 2
        assert result["distance"] == 1.5
        assert result["rule_type"] == "normal"
        assert result["feature_name"] == "Ruled Surface1"

    def test_an_internal_thread_defaults_to_the_internal_class(self):
        result = mock_command(
            "create_thread", {"body_name": "Nut", "is_internal": True}
        )

        assert result["is_internal"] is True
        assert result["thread_class"] == "6H"

    def test_an_unknown_rule_type_is_refused_like_the_handler(self):
        """Mock mode must not echo a call Fusion rejects with ok: true.

        The body is named because ``ruled_surface`` looks it up before it judges the
        rule type — the handler would refuse an empty name first, too.
        """
        result = mock_command(
            "ruled_surface", {"body_name": "Body1", "rule_type": "Tangent"}
        )

        assert result["ok"] is False
        assert "normal" in result["error_message"]

    def test_trim_surface(self):
        result = mock_command(
            "trim_surface",
            {
                "body_name": "Surf1",
                "keep_cells": [0],
                "tool_name": "Cutter",
            },
        )
        assert result["body_name"] == "Surf1"
        assert result["kept_cells"] == [0]
        assert result["tool_name"] == "Cutter"
        assert result["trimmed"] is True


class TestMockSheetMetal:
    def test_create_flange(self):
        result = mock_command(
            "create_flange",
            {
                "body_name": "Sheet1",
                "edge_index": 0,
                "distance": 2.0,
            },
        )
        assert result["body_name"] == "Sheet1"
        assert result["distance"] == 2.0

    def test_create_bend(self):
        result = mock_command(
            "create_bend",
            {
                "body_name": "Sheet1",
                "stationary_face_index": 1,
                "bend_line_sketch": "Sketch1",
                "angle": 45,
            },
        )
        assert result["body_name"] == "Sheet1"
        assert result["stationary_face_index"] == 1
        assert result["angle"] == 45

    def test_flat_pattern(self):
        result = mock_command("flat_pattern", {"body_name": "Sheet1"})
        assert result["body_name"] == "Sheet1"
        assert "flat_pattern_name" in result

    def test_unfold(self):
        result = mock_command(
            "unfold",
            {
                "body_name": "Sheet1",
                "bend_indices": [0, 2, 3],
            },
        )
        assert result["body_name"] == "Sheet1"
        assert result["bends_unfolded"] == 3


class TestMockCAM:
    def test_cam_create_setup(self):
        result = mock_command(
            "cam_create_setup",
            {
                "body_name": "Part1",
                "name": "MySetup",
            },
        )
        # The handler's keys: `name`, `body`, and the stock under `stock_applied`.
        assert result["name"] == "MySetup"
        assert result["body"] == "Part1"
        assert result["operation_type"] == "milling"
        assert result["stock_applied"] == {"stock_mode": "default"}

    def test_cam_create_operation(self):
        result = mock_command(
            "cam_create_operation",
            {
                "setup_name": "Setup1",
                "strategy": "adaptive2d",
                "name": "Rough1",
            },
        )
        assert result["strategy"] == "adaptive2d"
        assert result["name"] == "Rough1"
        assert result["setup"] == "Setup1"

    def test_cam_create_operation_echoes_the_geometry_parameter(self):
        """Mock answers the parameter name from the measured map, not from Fusion.

        An agent that branches on ``geometry.parameter`` develops the sequence in mock
        mode, so a replay that omitted it would KeyError on the call it rehearsed.
        """
        result = mock_command(
            "cam_create_operation",
            {
                "setup_name": "Setup1",
                "strategy": "pocket2d",
                "body_name": "Body1",
                "face_indices": [0],
            },
        )

        assert result["geometry"] == {
            "parameter": "pockets",
            "face_indices": [0],
        }

    def test_cam_generate_toolpath(self):
        """The handler's shape: `generated` plus the scope it resolved.

        `toolpath_count` was never a handler key - an agent that read it here got a
        KeyError against Fusion.
        """
        result = mock_command("cam_generate_toolpath", {"setup_name": "Setup1"})

        assert result["generated"] is True
        assert result["scope"] == "setup"
        assert result["setup"] == "Setup1"
        assert "toolpath_count" not in result

    def test_cam_generate_toolpath_names_the_operation_it_was_given(self):
        result = mock_command(
            "cam_generate_toolpath",
            {"setup_name": "Setup1", "operation_name": "Rough1"},
        )

        assert result["scope"] == "operation"
        assert result["operation"] == "Rough1"

    def test_cam_generate_all_reports_the_all_scope(self):
        result = mock_command("cam_generate_toolpath", {"generate_all": True})

        assert result["scope"] == "all"

    def test_cam_post_process(self):
        result = mock_command(
            "cam_post_process",
            {
                "setup_name": "Setup1",
                "post_processor": "grbl",
            },
        )
        # The handler's keys: the folder and the unit word, not a made-up file path.
        assert result["post_processor"] == "grbl"
        assert result["setup"] == "Setup1"
        assert "output_folder" in result
        assert result["units"] == "mm"

    def test_cam_list_setups(self):
        result = mock_command("cam_list_setups")
        assert result["count"] == len(result["setups"]) == 1
        # `{name, operations, is_valid}` per setup, as the handler answers.
        assert set(result["setups"][0]) == {"name", "operations", "is_valid"}

    def test_cam_list_operations(self):
        result = mock_command(
            "cam_list_operations",
            {
                "setup_name": "Setup1",
            },
        )
        assert result["setup"] == "Setup1"
        assert result["count"] == len(result["operations"]) == 2
        assert set(result["operations"][0]) == {"name", "has_toolpath", "is_valid"}

    def test_cam_get_operation_info(self):
        result = mock_command(
            "cam_get_operation_info",
            {
                "setup_name": "Setup1",
                "operation_name": "Face1",
            },
        )
        # The handler's keys: `name`, the flags, the tool, and the operation's own
        # parameters - `strategy`/`tool_diameter` live inside `parameters` live.
        assert result["name"] == "Face1"
        assert set(result) == {
            "name",
            "is_valid",
            "has_toolpath",
            "tool",
            "parameters",
            "ok",
            "mode",
        }
        assert "tool_diameter" in result["parameters"]

    def test_cam_create_setup_answers_fusions_id_like_the_handler(self):
        """The name is the caller's, the id is Fusion's - and both modes answer the id.

        Mock used to echo the name the caller sent, which was the one *value* in the
        rehearsal that met a different one live (`from_solid` -> `solid`).
        """
        result = mock_command(
            "cam_create_setup", {"body_name": "Part1", "stock_mode": "from_solid"}
        )

        assert result["ok"] is True
        assert result["stock_applied"] == {"stock_mode": "solid"}

    @pytest.mark.parametrize(
        "field", ["stock_offset_sides", "stock_offset_top", "stock_offset_bottom"]
    )
    def test_cam_create_setup_refuses_a_non_finite_stock_offset(self, field):
        """The add-in calls ``require_finite`` on all three before any object exists.

        Mock mode accepting ``inf`` reported a setup Fusion would never create —
        and mock mode is where an agent develops the sequence it will replay.
        """
        result = mock_command(
            "cam_create_setup", {"body_name": "Part1", field: float("inf")}
        )
        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"
        assert result["hints"], "a refusal without a next step is a dead end"

    @pytest.mark.parametrize(
        "field",
        [
            "tool_number",
            "tool_diameter",
            "tool_length",
            "tool_flutes",
            "stepdown",
            "stepover",
            "feed_rate",
            "spindle_speed",
        ],
    )
    def test_cam_create_operation_refuses_a_non_finite_number(self, field):
        params = {"strategy": "contour2d", field: float("inf")}
        result = mock_command("cam_create_operation", params)
        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"

    def test_cam_create_operation_attaches_a_library_tool_by_number(self):
        """The feature this PR exists for, rehearsed: number 1 is what mock holds."""
        result = mock_command(
            "cam_create_operation",
            {"setup_name": "Setup1", "strategy": "pocket2d", "tool_number": 1},
        )

        assert result["ok"] is True
        assert result["tool"] == {"number": 1, "from_library": True}
        assert "diameter_cm" not in result["tool"], "the diameter is the library's"
        assert "tool_warning" not in result, "a tool arrived, so nothing is missing"

    def test_cam_create_operation_attaches_a_tool_for_a_diameter(self):
        """``tool_diameter`` builds the tool now, so mock mode must not refuse it.

        It used to be refused outright - tool geometry is library-side - and the reply
        now carries the same ``tool`` key the handler answers, because that is the key
        an agent rehearses here and then reads against Fusion.  Rehearsing a refusal
        for a call that works is the drift this test exists to catch.
        """
        params = {"strategy": "contour2d", "tool_diameter": 0.6}
        result = mock_command("cam_create_operation", params)

        assert result["ok"] is True
        assert result["tool"]["diameter_cm"] == 0.6
        assert "tool_warning" not in result
        # No description: the handler's is a read-back from Fusion, so mock promises
        # only the key the handler always answers.
        assert "description" not in result["tool"]

    def test_cam_create_operation_without_a_tool_says_generation_will_fail(self):
        """No tool source is a reply, not a refusal: Fusion's own sentence warns."""
        result = mock_command("cam_create_operation", {"strategy": "contour2d"})

        assert result["ok"] is True
        assert result["tool"] is None
        assert "requires tool to be selected" in result["tool_warning"]

    def test_cam_create_operation_refuses_a_tool_json_and_a_diameter_together(self):
        """One tool, one source: judged from the parameters, so mock refuses too."""
        params = {
            "strategy": "contour2d",
            # Complete, so the *conflict* is what answers: the shape check accepts any
            # non-empty object (Fusion ships tools without a holder), so a partial one
            # would not be refused there.
            "tool_json": build_tool_json(tool_diameter=0.6, description="mine"),
            "tool_diameter": 0.6,
        }
        result = mock_command("cam_create_operation", params)

        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"
        assert any("tool_json" in hint for hint in result["hints"])

    def test_cam_create_setup_refuses_an_unknown_operation_type(self):
        """The handler refuses any type outside milling/turning/cutting.

        Mock mode echoed the string back, so a setup that cannot exist read as
        created — and the real refusal matched no hints rule.
        """
        result = mock_command(
            "cam_create_setup", {"body_name": "Part1", "operation_type": "laser"}
        )
        assert result["ok"] is False
        assert result["error_kind"] == "INVALID_INPUT"
        assert any("milling" in hint for hint in result["hints"])

    @pytest.mark.parametrize("operation_type", ["milling", "turning", "cutting"])
    def test_cam_create_setup_accepts_the_three_types(self, operation_type):
        result = mock_command(
            "cam_create_setup", {"body_name": "Part1", "operation_type": operation_type}
        )
        assert result["ok"] is True
        assert result["operation_type"] == operation_type


class TestMockDesignTypeSafety:
    def test_get_design_type(self):
        result = mock_command("get_design_type")
        assert result["design_type"] == "parametric"
        assert result["design_type_id"] == 1
        assert result["mode"] == "mock"

    def test_set_design_type_parametric(self):
        result = mock_command("set_design_type", {"design_type": "parametric"})
        assert result["changed"] is True
        assert result["design_type"] == "parametric"

    def test_set_design_type_direct(self):
        result = mock_command("set_design_type", {"design_type": "direct"})
        assert result["changed"] is True
        assert result["design_type"] == "direct"


class TestMockRenameBody:
    def test_rename_body(self):
        result = mock_command(
            "rename_body", {"body_name": "Body1", "new_name": "ShellTop"}
        )
        assert result["renamed"] is True
        assert result["old_name"] == "Body1"
        assert result["new_name"] == "ShellTop"


class TestMockSetJointValue:
    """The mock must resolve the attribute and unit the add-in would.

    It holds no design, so it resolves from value_kind rather than from the
    joint's motion type. Reporting rotationValue/degrees for every kind would
    reproduce, in mock mode, the bug that made slides 57x too short.
    """

    @pytest.mark.parametrize(
        "value_kind,attribute,units",
        [
            (None, "rotationValue", "deg"),
            ("rotation", "rotationValue", "deg"),
            ("slide", "slideValue", "cm"),
            ("primary_slide", "primarySlideValue", "cm"),
            ("secondary_slide", "secondarySlideValue", "cm"),
            ("pitch", "pitchValue", "deg"),
            ("yaw", "yawValue", "deg"),
            ("roll", "rollValue", "deg"),
        ],
    )
    def test_resolves_attribute_and_unit(self, value_kind, attribute, units):
        params = {"value": 2}
        if value_kind is not None:
            params["value_kind"] = value_kind

        result = mock_command("set_joint_value", params)

        assert result["attribute"] == attribute
        assert result["units"] == units

    def test_slide_values_are_not_converted(self):
        result = mock_command("set_joint_value", {"value": 2, "value_kind": "slide"})
        assert result["read_back"] == 2
        assert result["units"] == "cm"


class TestMockFallback:
    def test_unknown_command_returns_warning(self):
        result = mock_command("totally_unknown_command", {"x": 1})
        assert "warning" in result
        assert result["mode"] == "mock"
        assert result["params_received"] == {"x": 1}


#: Every mock handler whose add-in counterpart passes an empty name straight into
#: ``_body_by_name``: the tool, the call that proves it, and the parameters that name
#: nothing.  ``body_name_required_refusal`` is judged from the parameters alone, so mock
#: mode has to answer it or a development run reports work the add-in never does.
EMPTY_BODY_NAME = [
    # ``handler_base._body_by_name`` is shared; each row is one of its call sites.
    ("create_construction_axis", {"method": "edge", "body_name": ""}),
    (
        "create_construction_axis",
        {
            "method": "perpendicular_at_point",
            "body_name": "",
            "face_index": 0,
            "point_one": [0, 0, 0],
        },
    ),
    ("cam_create_setup", {"body_name": ""}),
    ("export_stl", {"body_name": ""}),
    ("export_step", {"body_name": ""}),
    ("rectangular_pattern", {"body_name": ""}),
    ("circular_pattern", {"body_name": ""}),
    ("create_thread", {"body_name": ""}),
    ("draft_faces", {"body_name": ""}),
    ("split_body", {"body_name": ""}),
    ("split_face", {"body_name": ""}),
    ("offset_faces", {"body_name": ""}),
    ("scale_body", {"body_name": ""}),
    ("rename_body", {"body_name": ""}),
    ("move_body", {"body_name": ""}),
    ("get_physical_properties", {"body_name": ""}),
    ("set_color", {"body_name": ""}),
    ("thicken_surface", {"body_name": ""}),
    ("ruled_surface", {"body_name": "", "edge_index": 0}),
    ("trim_surface", {"body_name": ""}),
    ("create_flange", {"body_name": ""}),
    ("create_bend", {"body_name": ""}),
    ("flat_pattern", {"body_name": ""}),
    ("unfold", {"body_name": ""}),
    # The same lookup under the tool's own parameter name.
    ("boolean_operation", {"target_body": "", "tool_body": "Body2"}),
    ("boolean_operation", {"target_body": "Body1", "tool_body": ""}),
    ("project_geometry", {"source_name": ""}),
    ("stitch_surfaces", {"body_names": ["Body1", ""]}),
    ("set_appearance", {"target_name": "", "target_type": "body"}),
    ("set_appearance", {"target_name": "", "target_type": "face"}),
    ("extrude", {"target_body": "", "operation": "cut"}),
    ("revolve", {"target_body": "", "operation": "cut"}),
    ("sweep", {"target_body": "", "operation": "cut"}),
    ("loft", {"target_body": "", "operation": "cut"}),
]


@pytest.mark.parametrize(
    ("command", "params"), EMPTY_BODY_NAME, ids=[c for c, _p in EMPTY_BODY_NAME]
)
def test_an_empty_body_name_is_refused(command, params):
    """``move_body({"body_name": ""})`` used to answer ``ok: true`` here.

    ``body_name`` is a required string with no ``minLength``, so ``""`` passes the
    schema gate and reaches both modes; the add-in refuses it in ``_body_by_name``
    before Fusion is asked, and a mock that answered would teach a sequence real mode
    rejects.
    """
    refused = mock_command(command, params)

    assert refused["ok"] is False
    assert refused["error_kind"] == "INVALID_INPUT"
    assert refused["error_message"] == "A body name is required"
    assert refused["hints"] == [
        "Pass a body name; get_scene_info lists the bodies in this design."
    ]


@pytest.mark.parametrize(
    ("command", "params"),
    [
        # body_name is unused on this branch: two points, not a body edge.
        (
            "create_construction_axis",
            {
                "method": "two_points",
                "point_one": [0, 0, 0],
                "point_two": [1, 0, 0],
                "body_name": "",
            },
        ),
        # An empty splitting_body means "cut with the plane", not "look up nothing".
        ("split_body", {"body_name": "Body1", "splitting_body": ""}),
        # The same for trim_surface's tool_name: tool_plane answers instead.
        (
            "trim_surface",
            {"body_name": "Body1", "tool_name": "", "tool_plane": "xy"},
        ),
        # _body_or_index: an empty body_name means "use body_index", never a lookup.
        ("fillet", {"body_name": "", "edge_selection": "all", "radius": 0.5}),
    ],
    ids=["unused-branch", "splitting-body", "trim-tool-name", "body-or-index"],
)
def test_an_empty_name_the_handler_does_not_look_up_is_not_refused(command, params):
    """The check is the lookup's: an empty name a caller may use is not refused."""
    assert mock_command(command, params)["ok"] is True


def test_cam_create_operation_promises_no_description_for_a_supplied_tool():
    """The handler reads the tool back and may answer ``{}``: promise no more.

    It used to answer ``{"description": "flat end mill"}`` for any ``tool_json`` -
    invented for a ball-nose, and absent live when Fusion declines to describe the
    tool - so a rehearsal indexing that key broke against Fusion.
    """
    params = {
        "strategy": "pocket2d",
        "tool_json": build_tool_json(tool_diameter=0.8, description="8mm ball"),
    }
    result = mock_command("cam_create_operation", params)

    assert result["ok"] is True
    assert result["tool"] == {}


class TestMockListFaces:
    """The face list a caller rehearses, in the shape the handler returns."""

    def test_a_planar_face_carries_a_normal_and_a_curved_one_does_not(self):
        """Only a planar face has a ``normal``; mock must not invent one for the others.

        A rehearsal that reads ``faces[i]["normal"]`` on every entry would break live,
        which is the drift mock mode exists to prevent.
        """
        faces = mock_command("list_faces", {"body_name": "Body1"})["faces"]

        assert faces[0]["is_planar"] is True
        assert faces[0]["normal"] == [0.0, 0.0, 1.0]
        assert faces[1]["is_planar"] is False
        assert "normal" not in faces[1]

    def test_the_limit_is_honoured_and_count_stays_the_real_total(self):
        """``count`` is the body's total and ``truncated`` says the list was clipped."""
        result = mock_command("list_faces", {"body_name": "Body1", "limit": 1})

        assert len(result["faces"]) == 1
        assert result["count"] == 2
        assert result["truncated"] is True


@pytest.mark.parametrize(("limit", "expected"), [(None, 2), (0, 1), (1, 1)])
def test_the_mock_list_tools_floor_the_limit_like_the_handler(limit, expected):
    """``None`` -> the default, ``0`` -> one, in both mock list tools.

    ``0`` used to mean 200 here (`or 200` swallowed it) while the handler floored it to
    one, so the same call rehearsed a different list than Fusion would return.
    """
    params = {} if limit is None else {"limit": limit}

    assert len(mock_command("list_faces", params)["faces"]) == expected
    assert len(mock_command("list_edges", params)["edges"]) == expected
