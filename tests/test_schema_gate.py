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
]


@pytest.mark.parametrize(("tool", "params", "fragment"), CASES)
def test_a_declared_constraint_is_refused_before_fusion(tool, params, fragment):
    envelope = server._schema_refusal(tool, params)
    assert envelope is not None
    assert envelope["ok"] is False
    assert envelope["error_kind"] == "INVALID_INPUT"
    assert fragment in envelope["error_message"]
    assert envelope["hints"]


def test_a_valid_call_passes_through():
    params = {"count": 2, "radius": 1.0, "spacing": 1.0}
    assert server._schema_refusal("draw_circles", params) is None


def test_a_command_that_is_not_a_tool_passes_through():
    assert server._schema_refusal("no_such_command", {"anything": 1}) is None


def test_none_params_are_treated_as_empty():
    """The add-in accepts ``params=None``; the gate must not refuse it."""
    assert server._schema_refusal("ping", {}) is None


def test_send_refuses_before_mock_runs():
    """``_send`` is the single choke point, so mock mode is gated too."""
    result = server._send("mock", "export_stl", {})
    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert "mode" not in result


class TestGateMessage:
    """The four constraint shapes the schema declares, in the add-in's voice."""

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

    def test_an_unhandled_validator_keeps_the_jsonschema_message(self):
        err = jsonschema.exceptions.ValidationError(
            "1 is not of type 'string'",
            validator="type",
            validator_value="string",
            instance=1,
        )
        assert server._gate_message(err) == "1 is not of type 'string'"


def test_every_declared_enum_matches_the_set_the_add_in_refuses():
    """D12: the arbiter for the schema-shaped rows.

    Each entry is a (tool, property, the tuple the handler refuses). Where the two
    disagree the row is NOT answered by the schema: a handler that refuses a strict
    subset - ``value_kind`` per joint type, ``method`` whose
    ``perpendicular_at_point`` is advertised and refused - moves to its domain task
    as a site ``Refusal`` instead.
    """
    from addon.server.rules import EDGE_SELECTIONS

    answered = [
        ("fillet", "edge_selection", EDGE_SELECTIONS),
        ("chamfer", "edge_selection", EDGE_SELECTIONS),
    ]
    for tool, prop, refused in answered:
        spec = tools.get_tool_by_name(tool)
        assert spec is not None
        declared = spec["inputSchema"]["properties"][prop]["enum"]
        assert tuple(declared) == tuple(refused), (tool, prop)
