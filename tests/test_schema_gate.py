"""The schema gate: a declared constraint is refused before either mode sees it."""

import jsonschema.exceptions
import pytest

from fusion360_mcp import server, tools

CASES = [
    # (tool, params, expected fragment of error_message)
    ("draw_circles", {"count": 0, "radius": 1.0, "spacing": 1.0}, "at least 1"),
    ("draw_circles", {"count": 501, "radius": 1.0, "spacing": 1.0}, "at most 500"),
    (
        "draw_circles",
        {"count": 2, "radius": 1.0, "spacing": 1.0, "axis": "q"},
        "axis",
    ),
    ("export_stl", {}, "body_name"),
    (
        "fillet",
        {"radius": 1.0, "edge_points": [[0, 0]]},
        "edge_points needs at least 3 items",
    ),
    # The construction methods' ``Unknown method`` handlers were dead code: every
    # value in the schema's enum is dispatched, so the gate is the only refusal.
    ("create_construction_plane", {"method": "cant"}, "Unknown method"),
    ("create_construction_axis", {"method": "spiral"}, "Unknown method"),
    # ``set_design_type`` has a handler guard for a direct-wire caller; the enum is
    # what refuses this MCP caller.
    ("set_design_type", {"design_type": "hybrid"}, "design_type"),
    # The enums whose handler raises this task deleted: the gate is the only
    # refusal for a value the schema already forbids.
    ("export", {"format": "obj"}, "Unknown format"),
    ("import_mesh", {"file_path": "part.stl", "units": "furlong"}, "Unknown units"),
    ("render_view", {"view": "diagonal"}, "Unknown view"),
    ("export_view_sheet", {"views": ["current"]}, "Unknown views"),
    # ``auto_constrain`` judged its own ``result_option`` until this task; the enum is
    # what refuses a value outside the three Fusion defines now.
    ("auto_constrain", {"result_option": 4}, "Unknown result_option"),
    # ``create_bend`` judged its own ``line_position`` until this task; the enum is
    # what refuses a position outside start/center/end now.
    (
        "create_bend",
        {
            "body_name": "Bracket",
            "stationary_face_index": 0,
            "bend_line_sketch": "Sketch1",
            "line_position": "middle",
        },
        "Unknown line_position",
    ),
]


@pytest.mark.parametrize(("tool", "params", "fragment"), CASES)
def test_a_declared_constraint_is_refused_before_fusion(tool, params, fragment):
    envelope = server._schema_refusal(tool, params)
    assert envelope is not None
    assert envelope["ok"] is False
    assert envelope["error_kind"] == "INVALID_INPUT"
    assert fragment in envelope["error_message"]
    assert envelope["hints"]
    # AGENTS.md's failure shape includes a traceback; the gate never ran Fusion,
    # so its refusal carries an empty one rather than omitting the key.
    assert envelope["traceback"] == ""


def test_a_one_of_refusal_names_the_field():
    """The unshaped fallback still names the field; jsonschema's text is kept."""
    envelope = server._schema_refusal(
        "create_box_parametric", {"length": 0, "width": 1.0, "height": 1.0}
    )
    assert envelope is not None
    assert envelope["error_message"].startswith("length: ")
    assert "is not valid under any of the given schemas" in envelope["error_message"]


def test_a_valid_call_passes_through():
    params = {"count": 2, "radius": 1.0, "spacing": 1.0}
    assert server._schema_refusal("draw_circles", params) is None


def test_a_command_that_is_not_a_tool_passes_through():
    assert server._schema_refusal("no_such_command", {"anything": 1}) is None


def test_every_tool_refuses_arguments_it_does_not_declare():
    """Live: ``create_box(name=...)`` and ``patch_surface(body_name=...)`` were
    forwarded to the handler, raised ``TypeError``, and reached the caller as
    ``UNKNOWN`` with no hints.  Every schema now closes that door.
    """
    undeclared = [
        tool["name"]
        for tool in tools.TOOLS
        if tool["inputSchema"].get("additionalProperties") is not False
    ]
    assert undeclared == []


def test_an_unknown_argument_is_refused_by_name():
    envelope = server._schema_refusal(
        "create_box", {"length": 1.0, "width": 1.0, "height": 1.0, "name": "x"}
    )

    assert envelope is not None
    assert envelope["ok"] is False
    assert envelope["error_kind"] == "INVALID_INPUT"
    assert "name" in envelope["error_message"]


def test_the_declared_arguments_still_pass():
    params = {"length": 1.0, "width": 1.0, "height": 1.0}
    assert server._schema_refusal("create_box", params) is None


def test_send_treats_none_params_as_empty():
    """The server's own ``_read`` passes ``None``; validating it would refuse."""
    result = server._send("mock", "ping", None)
    assert result["status"] == "pong"
    assert result["mode"] == "mock"


def test_send_refuses_before_mock_runs():
    """``_send`` is the single choke point, so mock mode is gated too."""
    result = server._send("mock", "export_stl", {})
    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert "mode" not in result


def test_send_refuses_before_connecting(monkeypatch):
    """Socket mode is gated too: the refusal never opens a connection."""

    def _explode(*_args, **_kwargs):
        raise AssertionError("the gate must refuse before get_connection")

    monkeypatch.setattr(server, "get_connection", _explode)
    result = server._send("socket", "export_stl", {})
    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"


class TestGateMessage:
    """The constraint shapes the schema declares, in the add-in's voice."""

    def test_an_enum_names_the_field_and_every_accepted_value(self):
        err = jsonschema.exceptions.ValidationError(
            "'q' is not one of ['x', 'y']",
            validator="enum",
            validator_value=["x", "y"],
            instance="q",
            path=["axis"],
        )
        assert server._gate_message(err) == ("Unknown axis: 'q'. Expected one of: x, y")

    def test_a_minimum_says_the_floor_and_the_value(self):
        err = jsonschema.exceptions.ValidationError(
            "0 is less than the minimum of 1",
            validator="minimum",
            validator_value=1,
            instance=0,
            path=["count"],
        )
        assert server._gate_message(err) == "count must be at least 1, got 0"

    def test_a_maximum_says_the_ceiling_and_the_value(self):
        err = jsonschema.exceptions.ValidationError(
            "501 is greater than the maximum of 500",
            validator="maximum",
            validator_value=500,
            instance=501,
            path=["count"],
        )
        assert server._gate_message(err) == "count must be at most 500, got 501"

    def test_a_required_names_the_missing_field(self):
        err = jsonschema.exceptions.ValidationError(
            "'body_name' is a required property",
            validator="required",
            validator_value=["body_name"],
        )
        assert server._gate_message(err) == "body_name is required"

    def test_a_type_names_the_field_the_expected_type_and_the_value(self):
        err = jsonschema.exceptions.ValidationError(
            "'abc' is not of type 'number'",
            validator="type",
            validator_value="number",
            instance="abc",
            path=["height"],
        )
        assert server._gate_message(err) == "height must be of type number, got 'abc'"

    def test_min_items_names_the_property_not_the_item_index(self):
        err = jsonschema.exceptions.ValidationError(
            "[0, 0] is too short",
            validator="minItems",
            validator_value=3,
            instance=[0, 0],
            path=["edge_points", 0],
        )
        assert server._gate_message(err) == "edge_points needs at least 3 items"

    def test_max_items_names_the_property_not_the_item_index(self):
        err = jsonschema.exceptions.ValidationError(
            "[0, 0, 0, 0] is too long",
            validator="maxItems",
            validator_value=3,
            instance=[0, 0, 0, 0],
            path=["edge_points", 0],
        )
        assert server._gate_message(err) == "edge_points allows at most 3 items"

    def test_an_unhandled_validator_keeps_the_jsonschema_message(self):
        err = jsonschema.exceptions.ValidationError(
            "'abc' does not match '^[0-9]+$'",
            validator="pattern",
            validator_value="^[0-9]+$",
            instance="abc",
        )
        assert server._gate_message(err) == "'abc' does not match '^[0-9]+$'"


def test_every_declared_enum_matches_the_set_the_add_in_refuses():
    """D12: the arbiter for the schema-shaped rows.

    Each entry is a (tool, property, the tuple the handler refuses). Where the two
    disagree the row is NOT answered by the schema: a handler that refuses a strict
    subset - ``value_kind`` per joint type, ``method`` whose
    ``perpendicular_at_point`` is advertised and refused - moves to its domain task
    as a site ``Refusal`` instead.
    """
    from addon.server.rules import EDGE_SELECTIONS, EXPORT_FORMATS

    answered = [
        ("fillet", "edge_selection", EDGE_SELECTIONS),
        ("chamfer", "edge_selection", EDGE_SELECTIONS),
        ("export", "format", EXPORT_FORMATS),
        # The guards restored for a direct-wire caller: the add-in refuses these
        # too, so deleting the enum would reopen the hole rather than move it.
        ("draw_circles", "axis", ("x", "y")),
        ("set_design_type", "design_type", ("parametric", "direct")),
    ]
    for tool, prop, refused in answered:
        spec = tools.get_tool_by_name(tool)
        assert spec is not None
        declared = spec["inputSchema"]["properties"][prop]["enum"]
        assert tuple(declared) == tuple(refused), (tool, prop)
