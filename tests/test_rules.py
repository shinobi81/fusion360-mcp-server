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
