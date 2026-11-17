"""One validation module, called by the add-in and by mock mode.

Mock mode has no Fusion to refuse anything, so it applies the add-in's own parameter
checks.  These tests compare the two *answers* — the envelope mock mode returns and the
exception the handler raises — instead of trusting both to call the same function: the
same ``error_kind`` and the same ``error_message``.  Every parameter set below is one
the add-in refuses before it looks at a body, which is why the body these calls pass is
a sentinel that any read of would fail on.
"""

from __future__ import annotations

import pytest

from addon.server import hints as addon_hints
from addon.server import rules
from fusion360_mcp import _rules, mock
from tests.fakes.bodies import body_with_edges
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence

#: Refused from the parameters alone, so no body is ever touched.
BAD_EDGE_SELECTORS = [
    {"edge_indices": [0], "edge_points": [[0, 0, 0]]},
    {"edge_selection": "top", "edge_indices": [0]},
    {"edge_selection": "top", "edge_points": [[0, 0, 0]]},
    {"edge_indices": []},
    {"edge_points": []},
    {"edge_selection": "diagonal"},
    {"edge_indices": [1.9]},
    {"edge_indices": [True]},
    {"edge_points": [[0, 0]]},
    {"edge_points": [0]},
    # A bare 3 is not a point: it must not read as "three coordinates" either.
    {"edge_points": [3]},
    # Neither selector is a list: iterating one used to raise ``TypeError``.
    {"edge_indices": 3},
    {"edge_points": 3},
]


@pytest.fixture
def bare_handler(handler_module):
    """A handler with no design: the parameter checks run before one is needed."""
    return handler_module.CommandHandler.__new__(handler_module.CommandHandler)


@pytest.mark.parametrize("params", BAD_EDGE_SELECTORS)
def test_the_handler_and_the_mock_refuse_an_edge_selector_alike(bare_handler, params):
    with pytest.raises(addon_hints.Refusal) as raised:
        bare_handler._select_edges(
            object(),
            params.get("edge_selection", "all"),
            indices=params.get("edge_indices"),
            points=params.get("edge_points"),
        )

    refused = mock._edge_selector_error(params)

    assert refused is not None
    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)


def test_a_usable_edge_selector_is_refused_by_neither_side():
    """The table above must not have turned a call Fusion accepts into a refusal."""
    assert mock._edge_selector_error({"edge_selection": "top"}) is None
    assert mock._edge_selector_error({"edge_indices": [0, 1]}) is None
    assert mock._edge_selector_error({"edge_points": [[0, 0, 0]]}) is None
    assert rules.edge_selector_refusal({"edge_selection": "all"}) is None
    assert rules.edge_selector_refusal({"edge_indices": [0, 1]}) is None
    assert rules.edge_selector_refusal({"edge_points": [[0, 0, 0]]}) is None


def test_the_handler_and_the_mock_refuse_a_target_body_on_a_new_body(bare_handler):
    with pytest.raises(addon_hints.Refusal) as raised:
        bare_handler._resolve_target_body("Body1", "new_body")

    refused = mock._target_body_error({"target_body": "Body1"})

    assert refused is not None
    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)


@pytest.mark.parametrize("operation", ["cut", "join", "intersect"])
def test_a_target_body_on_a_targeted_operation_is_refused_by_neither_side(operation):
    """No body is looked up here: mock mode has no design to look it up in."""
    assert rules.target_body_refusal({"target_body": "Body1"}, operation) is None
    assert (
        mock._target_body_error({"target_body": "Body1", "operation": operation})
        is None
    )


def test_a_missing_target_body_is_not_a_refusal(bare_handler):
    assert bare_handler._resolve_target_body(None, "new_body") is None
    assert rules.target_body_refusal({}, "new_body") is None
    assert mock._target_body_error({"operation": "new_body"}) is None


def test_the_handler_and_the_mock_refuse_an_unknown_rule_type_alike(bound_handler):
    """The text one place owns, compared as the handler raises it and the mock sends it.

    ``ruled_surface`` reaches the check only after it has a body and an edge, so the
    body is a fake one: the refusal is still decided by the parameter alone.
    """
    body = body_with_edges("Body1", [((0.0, 0.0, 0.0), (0.0, 10.0, 0.0))])
    handler = bound_handler(FakeDesign(bodies=[body]))

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.ruled_surface("Body1", edge_index=0, rule_type="Tangent")

    refused = mock._ruled_surface({"rule_type": "Tangent"})

    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)


@pytest.mark.parametrize("rule_type", ["normal", "tangent"])
def test_a_usable_rule_type_is_refused_by_neither_side(rule_type):
    assert rules.rule_type_refusal(rule_type) is None


def test_the_sketch_plane_z_note_is_one_sentence_on_both_sides(bare_handler):
    """A dropped z is a success note (R9), so it never becomes an error envelope."""
    result = bare_handler._report_dropped_z({"sketch": "Sketch1"}, 0.5)

    assert result["ignored_z"] == 0.5
    assert result["note"] == rules.sketch_plane_z_note()
    assert mock._sketch_plane_fields([0.5])["note"] == result["note"]
    assert "error_kind" not in result


def test_a_zero_sketch_plane_z_carries_no_note_on_either_side(bare_handler):
    assert "note" not in bare_handler._report_dropped_z({}, 0)
    assert mock._sketch_plane_fields([0]) == {}


def test_the_point_shape_refusal_names_the_count_it_found():
    """Pinned as literal text, not as a hint match.

    ``hints.py`` classifies this by matching "needs three coordinates", so a reworded
    message that keeps the phrase would still classify and still pass a loose test.  The
    count is what tells the caller which point was wrong: a two-element point and a bare
    number are different mistakes, and one sentence reports both.
    """
    short = rules.edge_selector_refusal({"edge_points": [[0, 0]]})
    bare = rules.edge_selector_refusal({"edge_points": [3]})

    assert short is not None
    assert bare is not None
    assert (short.error_kind, str(short)) == (
        "INVALID_INPUT",
        "Each edge point needs three coordinates, got 2",
    )
    assert (bare.error_kind, str(bare)) == (
        "INVALID_INPUT",
        "Each edge point needs three coordinates, got 3",
    )


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"edge_indices": 3}, "edge_indices needs a list of whole numbers, got 3"),
        (
            {"edge_points": 3},
            "edge_points needs a list of three-number points, got 3",
        ),
    ],
)
def test_a_selector_that_is_not_a_list_is_refused_with_its_own_hints(params, message):
    """Pinned as literal text plus the hints, not just the kind.

    Iterating one raised ``TypeError`` out of the validator: the add-in reported
    ``UNKNOWN`` with no hints, and mock mode raised through ``mock_command``.  The
    hints rule matters as much as the refusal - without it the fallback answered
    with the first ``INVALID_INPUT`` entry, which advises about inf and nan.
    """
    refusal = rules.edge_selector_refusal(params)

    assert refusal is not None
    assert (refusal.error_kind, str(refusal)) == ("INVALID_INPUT", message)
    assert addon_hints.classify(refusal)[1] == [
        "An edge selector is a list; nothing was written.",
        "Pass edge_indices as whole numbers, or edge_points as [x, y, z] triples.",
    ]


#: One parameter set per assembly validator: the tool it belongs to, the parameters
#: that earn the refusal, and the kind plus a fragment of the sentence both modes
#: answer.  The tool is a column because two validators share the same parameters
#: (``add_joint`` and ``create_as_built_joint`` differ only by ``joint_type``).
ASSEMBLY_REFUSALS = [
    (
        "add_joint",
        {"component_one": "A", "component_two": "A", "face_one": 0, "face_two": 0},
        "INVALID_INPUT",
        "must differ",
    ),
    (
        "add_joint",
        {"component_one": "A", "component_two": "B"},
        "INVALID_INPUT",
        "needs joint geometry",
    ),
    (
        "create_as_built_joint",
        {"component_one": "A", "component_two": "B", "joint_type": "revolute"},
        "INVALID_INPUT",
        "as-built joint needs geometry",
    ),
    (
        "create_rigid_group",
        {"component_names": ["A"]},
        "INVALID_INPUT",
        "at least 2 components",
    ),
    (
        "create_construction_plane",
        {"method": "tangent"},
        "INVALID_INPUT",
        "needs face selection",
    ),
    (
        "create_construction_axis",
        {"method": "perpendicular_at_point"},
        "INVALID_INPUT",
        "B-Rep face",
    ),
]


@pytest.mark.parametrize(
    ("command", "params", "expected_kind", "expected_fragment"),
    ASSEMBLY_REFUSALS,
    ids=[
        "components_differ",
        "joint_geometry",
        "as_built_geometry",
        "rigid_group_size",
        "construction_method",
        "perpendicular_axis",
    ],
)
def test_the_validator_and_mock_agree(
    bound_handler, command, params, expected_kind, expected_fragment
):
    """The handler raises and mock mode answers with the same sentence and kind.

    Both sides call the validator in ``rules``; the row is what would fail if a
    call site passed a different mapping, or if one side kept its own wording.
    """
    design = FakeDesign(features=0)
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("A")))
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("B")))
    handler = bound_handler(design)

    with pytest.raises(addon_hints.Refusal) as raised:
        getattr(handler, command)(**params)

    refused = mock.mock_command(command, params)

    assert refused["ok"] is False
    assert refused["error_kind"] == raised.value.error_kind == expected_kind
    assert refused["error_message"] == str(raised.value)
    assert refused["hints"] == list(raised.value.hints)
    assert expected_fragment in str(raised.value)


def test_the_mirror_carries_the_same_validation():
    """``--check`` pins the mirror's bytes; this pins the behaviour mock mode imports.

    The two modules hold two ``Refusal`` classes, so only the text is comparable — and
    the text is what reaches the wire.
    """
    params = {"edge_indices": [0], "edge_points": [[0, 0, 0]]}

    assert str(_rules.edge_selector_refusal(params)) == str(
        rules.edge_selector_refusal(params)
    )
    assert _rules.target_body_refusal({"target_body": "B"}, "new_body") is not None
    assert _rules.sketch_plane_z_note() == rules.sketch_plane_z_note()
    assert _rules.EDGE_SELECTIONS == rules.EDGE_SELECTIONS
