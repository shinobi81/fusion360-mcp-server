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
from tests.fakes.bodies import FakeBody, body_with_edges
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

    refused = mock._ruled_surface({"body_name": "Body1", "rule_type": "Tangent"})

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


#: One parameter set per ``rules.py`` validator: the tool it belongs to, the
#: parameters that earn the refusal, and the exact kind, sentence and hints both
#: modes answer.  The tool is a column because two validators share the same
#: parameters (``add_joint`` and ``create_as_built_joint`` differ only by
#: ``joint_type``), and because a shared ``handler_base`` helper is reached through
#: the tools that call it rather than one of its own.
PARAMETER_REFUSALS = [
    (
        "add_joint",
        {"component_one": "A", "component_two": "A", "face_one": 0, "face_two": 0},
        "INVALID_INPUT",
        "component_one and component_two must differ",
        ("Pass two different components; a joint needs two.",),
    ),
    (
        "add_joint",
        {"component_one": "A", "component_two": "B"},
        "INVALID_INPUT",
        "add_joint needs joint geometry: pass face_one/face_two "
        "(and body_one/body_two when a component holds more than one body). "
        "Component origin points are not valid joint geometry.",
        (
            "Pass face_one and face_two.",
            "Add body_one/body_two when the component holds more than one body.",
        ),
    ),
    (
        "create_as_built_joint",
        {"component_one": "A", "component_two": "B", "joint_type": "revolute"},
        "INVALID_INPUT",
        "A revolute as-built joint needs geometry: pass face_one/face_two "
        "(and body_one/body_two when a component holds more than one body). "
        "Only 'rigid' works without it.",
        ("Pass face_one and face_two, or use joint_type='rigid'.",),
    ),
    (
        "create_rigid_group",
        {"component_names": ["A"]},
        "INVALID_INPUT",
        "Need at least 2 components for rigid group",
        ("Pass at least two component names.",),
    ),
    (
        "create_construction_plane",
        {"method": "tangent"},
        "INVALID_INPUT",
        "Tangent plane needs face selection—use execute_code",
        (
            "create_construction_plane has no face parameter; build this plane "
            "with execute_code.",
        ),
    ),
    (
        "create_construction_axis",
        {"method": "perpendicular_at_point"},
        "INVALID_INPUT",
        "Perpendicular axis needs a B-Rep face, which this tool has no "
        "parameter for — use execute_code; the method stays in the schema for "
        "wire compatibility",
        (
            "The schema advertises this method for wire compatibility; "
            "use execute_code.",
        ),
    ),
    # ``handler_base._body_by_name``: any tool that names a body reaches it, so the
    # rows ride on tools from two domains — a check wired per tool, not per domain.
    (
        "get_physical_properties",
        {"body_name": ""},
        "INVALID_INPUT",
        "A body name is required",
        ("Pass a body name; get_scene_info lists the bodies in this design.",),
    ),
    (
        "move_body",
        {"body_name": ""},
        "INVALID_INPUT",
        "A body name is required",
        ("Pass a body name; get_scene_info lists the bodies in this design.",),
    ),
    (
        "set_color",
        {"body_name": "", "red": 255, "green": 0, "blue": 0},
        "INVALID_INPUT",
        "A body name is required",
        ("Pass a body name; get_scene_info lists the bodies in this design.",),
    ),
    # ``handler_base._point3d``: reached by both construction tools, and judged per
    # point so the message names the one that is wrong.
    (
        "create_construction_plane",
        {"method": "three_points", "point_one": [0, 0]},
        "INVALID_INPUT",
        "point_one must be [x, y, z] in centimetres",
        ("Pass three numbers, in centimetres: [x, y, z].",),
    ),
    # Export and CAM: a format and a body, and a toolpath target, are all judged
    # before Fusion is asked.
    (
        "export",
        {},
        "INVALID_INPUT",
        "Specify format (stl/step/f3d) or file_path with extension",
        (
            "Pass format='stl', 'step' or 'f3d', or a file_path that ends in one "
            "of those.",
        ),
    ),
    # A path that names a format the tool cannot write keeps the sentence the handler
    # raised before the validator existed (D2); it is the one way around the enum.
    (
        "export",
        {"file_path": "model.obj"},
        "INVALID_INPUT",
        "Unknown format: obj. Expected: stl, step, f3d",
        (
            "Pass format='stl', 'step' or 'f3d', or a file_path that ends in one "
            "of those.",
        ),
    ),
    (
        "export",
        {"format": "stl"},
        "INVALID_INPUT",
        "body_name required for STL export",
        ("Pass body_name naming the body to export.",),
    ),
    (
        "export",
        {"format": "step"},
        "INVALID_INPUT",
        "body_name required for STEP export",
        ("Pass body_name naming the body to export.",),
    ),
    # A symmetry constraint's third entity, judged from the parameters alone: mock
    # mode has no sketch to look the index up in, and the handler refuses it before
    # it reads one, so both sides answer the same sentence.
    (
        "add_constraint",
        {"constraint_type": "symmetry", "entity_one": 0, "entity_two": 1},
        "INVALID_INPUT",
        "symmetry needs symmetry_line — the index of the sketch line the two "
        "entities are mirrored about",
        ("Pass symmetry_line: the index of a sketch line to mirror about.",),
    ),
    (
        "cam_generate_toolpath",
        {},
        "INVALID_INPUT",
        "Provide setup_name, operation_name, or generate_all=true",
        (
            "Pass operation_name to generate that one operation, or setup_name "
            "for all of that setup's.",
            "generate_all=true generates every setup's toolpaths.",
        ),
    ),
    # Surface trim: the tool and the cell indices are judged from the parameters
    # alone, before Fusion computes any cell to check an index against.
    (
        "trim_surface",
        {"body_name": "Surf1", "keep_cells": [0]},
        "INVALID_INPUT",
        "trim_surface needs exactly one of tool_name (a body) or tool_plane "
        "(xy, xz or yz)",
        ("Pass tool_name (a body), or tool_plane (xy, xz or yz), but not both.",),
    ),
    (
        "trim_surface",
        {"body_name": "Surf1", "keep_cells": ["left"], "tool_name": "Cutter"},
        "INVALID_INPUT",
        "keep_cells takes cell indices, not 'left'",
        ("Pass whole-number cell indices, counted from 0.",),
    ),
]


@pytest.mark.parametrize(
    ("command", "params", "expected_kind", "expected_message", "expected_hints"),
    PARAMETER_REFUSALS,
    ids=[
        "components_differ",
        "joint_geometry",
        "as_built_geometry",
        "rigid_group_size",
        "construction_method",
        "perpendicular_axis",
        "body_name_required",
        "body_name_required_move",
        "body_name_required_color",
        "point3d_shape",
        "export_target",
        "export_unknown_format",
        "export_body_stl",
        "export_body_step",
        "symmetry_line",
        "cam_target",
        "trim_tool",
        "trim_keep_cells",
    ],
)
def test_the_validator_and_mock_agree(
    bound_handler,
    command,
    params,
    expected_kind,
    expected_message,
    expected_hints,
):
    """The handler raises and mock mode answers with the exact sentence and hints.

    The whole message is pinned, not a fragment: once these rows leave
    ``_UNCLASSIFIED_BASELINE``, a reflowed em dash or an added period would
    otherwise stay green.  The hints are pinned too, so a validator that drops its
    ``hints=`` tuple falls through to the kind default here instead of shipping
    boilerplate.
    """
    design = FakeDesign(features=0, bodies=[FakeBody("Surf1"), FakeBody("Cutter")])
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("A")))
    design.rootComponent.occurrences.add(FakeOccurrence(FakeComponent("B")))
    handler = bound_handler(design)

    with pytest.raises(addon_hints.Refusal) as raised:
        getattr(handler, command)(**params)

    assert raised.value.error_kind == expected_kind
    assert str(raised.value) == expected_message
    assert list(raised.value.hints) == list(expected_hints)
    assert addon_hints.classify(raised.value)[1] == list(expected_hints)

    refused = mock.mock_command(command, params)

    assert refused["ok"] is False
    assert refused["error_kind"] == expected_kind
    assert refused["error_message"] == expected_message
    assert refused["hints"] == list(expected_hints)


def test_a_usable_trim_target_is_refused_by_neither_side():
    """The table above must not have turned a call Fusion accepts into a refusal."""
    assert rules.surface_tool_refusal({"tool_name": "Cutter"}) is None
    assert rules.surface_tool_refusal({"tool_plane": "xy"}) is None
    assert rules.keep_cells_refusal({"keep_cells": [0, 2]}) is None
    assert rules.keep_cells_refusal({}) is None


def test_a_usable_export_or_cam_target_is_refused_by_neither_side():
    """The table above must not have turned a call Fusion accepts into a refusal."""
    assert rules.export_target_refusal({"format": "stl"}) is None
    assert rules.export_target_refusal({"file_path": "out.step"}) is None
    assert rules.export_body_refusal({"format": "stl", "body_name": "Body1"}) is None
    assert rules.export_body_refusal({"format": "f3d"}) is None
    assert rules.cam_target_refusal({"generate_all": True}) is None
    assert rules.cam_target_refusal({"setup_name": "Setup1"}) is None
    assert rules.cam_target_refusal({"operation_name": "Rough1"}) is None


@pytest.mark.parametrize("symmetry_line", [0, 2])
def test_a_symmetry_line_index_is_refused_by_neither_side(symmetry_line):
    """A line index is an index: 0 is the first line, not "unset".

    ``is not None`` is what keeps a falsy index usable, and nothing else pins it —
    the refusal row passes no line at all, and the handler test that adds one
    passes 2.
    """
    params = {"constraint_type": "symmetry", "symmetry_line": symmetry_line}

    assert rules.symmetry_line_refusal(params) is None
    refused = mock.mock_command(
        "add_constraint",
        {
            "constraint_type": "symmetry",
            "entity_one": 0,
            "entity_two": 1,
            "symmetry_line": symmetry_line,
        },
    )
    assert refused["ok"] is True


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "Specify format (stl/step/f3d) or file_path with extension"),
        (
            {"file_path": "model.igs"},
            "Unknown format: igs. Expected: stl, step, f3d",
        ),
    ],
)
def test_the_export_target_refusal_keeps_both_sentences(params, message):
    """D2: a named-but-unsupported format reads as the raise it replaced.

    ``export`` infers the format from ``file_path``, so ``model.igs`` reaches the
    validator without meeting the gate; the old final ``Unknown format`` raise is the
    sentence that answered it, and the plan freezes message text.  Only the call that
    names nothing keeps the older ``Specify format`` sentence.
    """
    refusal = rules.export_target_refusal(params)

    assert refusal is not None
    assert refusal.error_kind == "INVALID_INPUT"
    assert str(refusal) == message


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


# ── the joint selectors ──────────────────────────────────────────────


#: One unknown value per selector, each judged from the parameters alone.  The last
#: three are the shapes a socket caller can send and the schema never will: they must be
#: refused, not raised on.  ``value not in accepted`` is safe for them only because
#: ``accepted`` is a tuple - a set would raise ``TypeError: unhashable`` for the list.
BAD_JOINT_SELECTORS = [
    {"joint_type": "weld"},
    {"quadrant": "corner"},
    {"key_point": "tip"},
    {"quadrant": ["start"]},
    {"joint_type": None},
    {"key_point": 3},
]


@pytest.mark.parametrize("params", BAD_JOINT_SELECTORS)
def test_the_handler_and_the_mock_refuse_an_unknown_joint_selector_alike(
    bare_handler, params
):
    """The socket is not the schema, so an unknown selector reaches the handler.

    ``add_joint`` indexes two lookup tables with ``quadrant`` and ``key_point``, and
    ``joint_type`` through ``_JOINT_MOTION_SETTERS``; a value outside the enum used to
    raise a bare ``KeyError`` that classified as ``UNKNOWN`` with no advice.
    """
    call = {"component_one": "Comp1", "component_two": "Comp2", **params}

    with pytest.raises(addon_hints.Refusal) as raised:
        bare_handler.add_joint(**call)

    refused = mock._add_joint(call)

    assert refused is not None
    assert raised.value.error_kind == "INVALID_INPUT"
    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)


@pytest.mark.parametrize("params", BAD_JOINT_SELECTORS)
def test_the_as_built_joint_refuses_the_same_selectors_on_both_sides(
    bare_handler, params
):
    """``create_as_built_joint`` shares the three arguments, so it shares the check."""
    call = {
        "component_one": "Comp1",
        "component_two": "Comp2",
        "joint_type": "rigid",
        **params,
    }

    with pytest.raises(addon_hints.Refusal) as raised:
        bare_handler.create_as_built_joint(**call)

    refused = mock._create_as_built_joint(call)

    assert refused is not None
    assert raised.value.error_kind == "INVALID_INPUT"
    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)


def test_a_usable_joint_selector_is_refused_by_neither_side():
    """The defaults the schema advertises, and every value in it, stay usable."""
    assert rules.joint_selector_refusal({}) is None
    assert (
        rules.joint_selector_refusal(
            {"joint_type": "ball", "quadrant": "third_quarter", "key_point": "center"}
        )
        is None
    )
    # ``face_one``/``face_two`` are present so the *next* rule in the chain stays quiet:
    # this asserts the selector rule, not the geometry one.
    for name, accepted in (
        ("joint_type", rules.JOINT_TYPES),
        ("quadrant", rules.JOINT_QUADRANTS),
        ("key_point", rules.JOINT_KEY_POINTS),
    ):
        for value in accepted:
            params = {name: value, "face_one": 0, "face_two": 0}
            assert rules.joint_selector_refusal(params) is None, params
            assert mock._add_joint(params).get("error_kind") is None, params


@pytest.mark.parametrize(
    ("method", "params"),
    [
        # Two faults at once: the answers must agree on which one wins, not only on
        # the kind - a caller that sees "components differ" from mock and "unknown
        # quadrant" from Fusion cannot tell which call it actually made.
        (
            "add_joint",
            {
                "component_one": "A",
                "component_two": "A",
                "quadrant": "corner",
                "face_one": 0,
                "face_two": 0,
            },
        ),
        (
            "add_joint",
            {"component_one": "A", "component_two": "A", "joint_type": "weld"},
        ),
        (
            "create_as_built_joint",
            {
                "component_one": "A",
                "component_two": "A",
                "joint_type": "rigid",
                "key_point": "tip",
            },
        ),
    ],
)
def test_two_faults_at_once_earn_the_same_refusal_on_both_sides(
    bare_handler, method, params
):
    """Precedence is part of the contract, so it is pinned where the two orders live.

    The handler raises the selector refusal first, before it reads a design; mock
    mode's chain has to list the rules in that same order.
    """
    with pytest.raises(addon_hints.Refusal) as raised:
        getattr(bare_handler, method)(**params)

    refused = (
        mock._add_joint(params)
        if method == "add_joint"
        else mock._create_as_built_joint(params)
    )

    assert refused is not None
    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)
