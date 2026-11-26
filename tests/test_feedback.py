"""Tests for agent-feedback additions: hints, deltas, render_view, formatting."""

import base64

import mcp.types as types
import pytest

from fusion360_mcp.hints import Refusal, classify
from fusion360_mcp.mock import _MUTATION_MOCKS, mock_command
from fusion360_mcp.server import _format_result


def _blocks(result):
    """Content blocks of a _format_result payload, whichever shape it took.

    The function returns a CallToolResult on the error path and a plain list of
    blocks on the success path, so tests narrow once here instead of asserting
    on a union type.
    """
    return result.content if isinstance(result, types.CallToolResult) else result


def _text_of(result, index: int = 0) -> str:
    block = _blocks(result)[index]
    assert isinstance(block, types.TextContent)
    return block.text


class TestHintClassification:
    """The hint table maps exception messages to an error_kind + hints."""

    @pytest.mark.parametrize(
        "msg,expected_kind",
        [
            ("No profiles in sketch", "PROFILE_NOT_CLOSED"),
            ("No active design", "NO_ACTIVE_DESIGN"),
            ("Body SomeBody not found", "BODY_NOT_FOUND"),
            ("Sketch Sketch1 not found", "SKETCH_NOT_FOUND"),
            ("Sweep self-intersects at T=0.4", "SELF_INTERSECTION"),
            ("Regeneration failed for feature Extrude7", "REGEN_FAILED"),
            ("Boolean subtract failed — empty result", "BOOLEAN_NO_OP"),
            ("Invalid input: angle must be > 0", "INVALID_INPUT"),
            (
                "Editing is not permitted in parametric edit mode",
                "DESIGN_TYPE_MISMATCH",
            ),
            ("Unknown command: bogus", "UNKNOWN_COMMAND"),
            ("Operation timeout after 30s", "TIMEOUT"),
            (
                "3 : AutoConstrain is not available since user is restricted",
                "NOT_ENTITLED",
            ),
        ],
    )
    def test_classify_known_messages(self, msg, expected_kind):
        kind, hints = classify(msg)
        assert kind == expected_kind, f"'{msg}' classified as {kind}"
        assert hints, f"'{expected_kind}' should ship with at least one hint"

    @pytest.mark.parametrize(
        "message",
        [
            # Every feature tool raises this itself for a mistyped ``operation``.
            # Without a rule it was UNKNOWN with no hints, so a caller that wrote
            # ``union`` was told nothing at all — the failure mode this table
            # exists to stop shipping. ``Unknown operation_type`` belongs to the
            # CAM rule above and must keep its own wording.
            "Unknown operation 'union' — use new_body/join/cut/intersect",
            "Unknown boolean op 'union' — use join/cut/intersect",
        ],
    )
    def test_a_mistyped_operation_names_the_ones_that_exist(self, message):
        kind, hints = classify(message)
        assert kind == "INVALID_INPUT"
        assert any("join" in hint for hint in hints)

    def test_the_operation_rule_does_not_swallow_the_cam_operation_type_rule(self):
        """``operation_type`` is a CAM command parameter, not a mistyped enum."""
        kind, hints = classify("Unknown operation_type 'laser' — use milling")
        assert kind == "INVALID_INPUT"
        assert any("milling" in hint for hint in hints)

    def test_a_cut_that_reaches_no_body_says_so(self):
        """Found live on a sweep whose profile sat outside every block.

        Fusion's own wording, and it classified as UNKNOWN with no hints — the
        caller was told nothing about why nothing was cut.
        """
        msg = "3 : NO_TARGET_SWEEP_BODY - No intersecting target body was found."
        kind, hints = classify(msg)
        assert kind == "INVALID_INPUT"
        assert any("reaches no body" in hint for hint in hints)
        assert any("overlaps a body" in hint for hint in hints)

    def test_tool_diameter_refusal_points_at_the_tool_library(self):
        """The add-in refuses ``tool_diameter`` on an operation, and had no rule.

        Without one it classified as ``UNKNOWN`` with no hints, so the caller was
        told nothing about where tool geometry actually comes from — the failure
        mode ``hints.py`` exists to stop shipping.
        """
        msg = (
            "tool_diameter cannot be set on an operation — tool geometry comes "
            "from a tool in the CAM tool library. Select the tool via "
            "tool_number instead."
        )
        kind, hints = classify(msg)
        assert kind == "INVALID_INPUT"
        assert any("tool_number" in hint for hint in hints)

    @pytest.mark.parametrize(
        ("msg", "expected_kind"),
        [
            # The CAM entry points raise these themselves, before any object
            # exists. Both were UNKNOWN with no hints — the caller was told
            # nothing about the three accepted operation types, and nothing
            # about which call lists the setups that do exist.
            (
                "Unknown operation_type 'laser' — use milling/turning/cutting",
                "INVALID_INPUT",
            ),
            # A name that does not exist is NAME_NOT_FOUND, not a bad argument:
            # the rule's own hints already send the caller to cam_list_setups,
            # which is NAME_NOT_FOUND's next move. A client that branches on the
            # kind was told the wrong thing to do with it.
            ("Setup 'Nope' not found", "NAME_NOT_FOUND"),
            ("Operation 'Rough1' not found in setup 'Setup1'", "NAME_NOT_FOUND"),
        ],
    )
    def test_cam_lookup_and_enum_refusals_are_classified(self, msg, expected_kind):
        kind, hints = classify(msg)
        assert kind == expected_kind, f"'{msg}' classified as {kind}"
        assert hints, f"'{msg}' must ship with a next step"

    def test_a_missing_cam_name_answers_one_kind_whichever_way_it_is_raised(self):
        """`cam_generate_toolpath` raises a typed NAME_NOT_FOUND for its own
        search; the lookup rule classifies the same sentence as a RuntimeError.
        One fault, one kind — otherwise a client branches twice for one mistake.

        The first assertion compares the *same* text both ways on purpose:
        ``classify(Refusal(...))`` returns the literal it was handed, so asserting
        only that would pass with no rule in the table at all.
        """
        typed = Refusal("NAME_NOT_FOUND", "Operation 'Rough1' not found in any setup")

        assert classify(typed)[0] == classify(str(typed))[0] == "NAME_NOT_FOUND"
        assert classify("Setup 'Nope' not found")[0] == "NAME_NOT_FOUND"

    def test_the_cam_rules_do_not_swallow_the_body_and_sketch_rules(self):
        """A body named after a sketch must still be BODY_NOT_FOUND.

        The new rule anchors on a quoted name after ``setup``/``operation``, so
        adding it must not re-order the long-standing precedence below it.
        """
        assert classify("Body 'Sketch1' not found")[0] == "BODY_NOT_FOUND"
        assert classify("Sketch 'Body1' not found")[0] == "SKETCH_NOT_FOUND"

    @pytest.mark.parametrize(
        "msg",
        [
            "No faces matched selection 'top'",
            "No faces matched 'bottom'",
        ],
    )
    def test_no_face_in_that_plane_is_geometry_unsupported(self, msg):
        """The selector is not mistyped — the body has no face in that plane.

        That is the same class as a component with no sheet-metal rule, which
        already answers GEOMETRY_UNSUPPORTED: the body does not have the geometry
        the call needs. A mistyped selector has its own rule, so this message can
        never be a parameter fault. Unchanged: the three hints that say which
        faces the selector means and where the indices come from.
        """
        kind, hints = classify(msg)

        assert kind == "GEOMETRY_UNSUPPORTED"
        assert any("selected plane" in hint for hint in hints)
        assert any("list_faces" in hint for hint in hints)

    @pytest.mark.parametrize(
        "msg",
        [
            # The add-in raises this itself when the undo command is missing.
            # The right answer is the specific next step it names, not
            # "do not retry" — this message must not drift into NOT_ENTITLED.
            "Undo command is not available in the current workspace. "
            "The design was NOT modified — delete the failed feature instead.",
            "Some parameters are not available for this strategy",
        ],
    )
    def test_availability_wording_is_not_an_entitlement_refusal(self, msg):
        """Guards the rule against overshooting: only entitlement stays refused."""
        assert classify(msg)[0] != "NOT_ENTITLED"

    def test_entitlement_refusal_tells_the_agent_not_to_retry(self):
        """A refused API is not a parameter problem: retrying only burns calls.

        Fusion answers auto_constrain with "... is not available since user is
        restricted" on accounts without the entitlement. Classified as UNKNOWN
        with no hints, that invites the same call again and again.
        """
        kind, hints = classify(
            "3 : AutoConstrain is not available since user is restricted"
        )
        assert kind == "NOT_ENTITLED"
        joined = " ".join(hints).lower()
        assert "do not retry" in joined
        assert "entitlement" in joined

    def test_classify_unknown_falls_back(self):
        kind, hints = classify("totally novel failure mode xyz")
        assert kind == "UNKNOWN"
        assert hints == []

    def test_classify_accepts_exception(self):
        kind, hints = classify(RuntimeError("No profiles in sketch"))
        assert kind == "PROFILE_NOT_CLOSED"
        assert len(hints) >= 1


class TestMockForcedError:
    """Sending __mock_error__ in params produces an ok=False envelope."""

    def test_forced_error_shape(self):
        result = mock_command(
            "extrude",
            {
                "height": 1,
                "__mock_error__": "No profiles in sketch",
            },
        )
        assert result["ok"] is False
        assert result["error_kind"] == "PROFILE_NOT_CLOSED"
        assert result.get("hints")
        assert result["error_message"] == "No profiles in sketch"
        assert result["mode"] == "mock"

    def test_forced_error_unknown_kind(self):
        result = mock_command("extrude", {"__mock_error__": "something weird"})
        assert result["ok"] is False
        assert result["error_kind"] == "UNKNOWN"
        assert result["hints"] == []


#: The names these commands look up, under the parameter each takes them by.  They
#: are given because the body-naming mocks refuse an empty or absent one, the way
#: ``_body_by_name`` does; a refused call is not a mutation, so it carries no deltas
#: and TestMockDeltas would fail on it for the right reason.
_MUTATION_MOCK_NAMES = {
    "boolean_operation": {"target_body": "Body1", "tool_body": "Body2"},
    "set_appearance": {"target_name": "Body1"},
    "project_geometry": {"source_name": "Body1"},
    "stitch_surfaces": {"body_names": ["Body1"]},
    # ``trim_surface`` now refuses a call with neither tool, as the handler does.
    "trim_surface": {"tool_name": "Cutter", "keep_cells": [0]},
}


class TestMockDeltas:
    """Mutation mocks carry a deltas sub-dict; read-only mocks do not."""

    def test_mutation_has_deltas(self):
        for cmd in _MUTATION_MOCKS:
            params = {"body_name": "Body1", **_MUTATION_MOCK_NAMES.get(cmd, {})}
            result = mock_command(cmd, params)
            if cmd == "undo":
                # undo removes work: the synthetic "body appeared" deltas would
                # report growth, so it deliberately carries none.
                assert "deltas" not in result
                continue
            assert "deltas" in result, f"{cmd} should expose deltas"
            deltas = result["deltas"]
            assert "body_count_delta" in deltas
            assert "mass_g_delta" in deltas
            assert "bbox_after" in deltas

    def test_read_only_has_no_deltas(self):
        for cmd in (
            "ping",
            "get_scene_info",
            "get_parameters",
            "measure_distance",
            "check_interference",
        ):
            result = mock_command(cmd, {})
            assert "deltas" not in result, f"{cmd} must not fabricate deltas"

    def test_success_is_ok_true(self):
        assert mock_command("ping")["ok"] is True
        assert mock_command("extrude", {"height": 1})["ok"] is True


class TestMockRenderView:
    """render_view returns image_base64 that decodes as PNG bytes."""

    def test_render_view_shape(self):
        result = mock_command("render_view", {"view": "iso"})
        assert result["ok"] is True
        assert result["image_format"] == "png"
        assert result["view"] == "iso"
        assert isinstance(result["image_base64"], str)
        decoded = base64.b64decode(result["image_base64"])
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_render_view_is_read_only(self):
        result = mock_command("render_view", {})
        assert "deltas" not in result


class TestFormatResult:
    """_format_result converts mock/addon envelopes to MCP content blocks."""

    def test_error_path_sets_isError(self):
        result = {
            "ok": False,
            "error_kind": "PROFILE_NOT_CLOSED",
            "error_message": "No profiles in sketch",
            "hints": ["close the loop", "verify coincident constraints"],
            "traceback": "Traceback (...)",
        }
        out = _format_result("extrude", result)
        assert isinstance(out, types.CallToolResult)
        assert out.isError is True
        text = _text_of(out)
        assert "PROFILE_NOT_CLOSED" in text
        assert "close the loop" in text
        assert "No profiles in sketch" in text

    def test_success_path_lists_fields(self):
        result = {
            "ok": True,
            "body_name": "Body1",
            "height": 3.0,
            "mode": "mock",
        }
        out = _format_result("extrude", result)
        assert isinstance(out, list)
        text = _text_of(out)
        assert "**extrude** OK" in text
        assert "body_name: Body1" in text
        assert "height: 3.0" in text
        # "ok" is a control field — it should not appear in the rendered body
        assert "\n  ok:" not in text

    def test_deltas_are_rendered(self):
        result = {
            "ok": True,
            "body_name": "Body1",
            "deltas": {
                "body_count_before": 0,
                "body_count_after": 1,
                "body_count_delta": 1,
                "mass_g_before": 0.0,
                "mass_g_after": 7.85,
                "mass_g_delta": 7.85,
                "bbox_before": None,
                "bbox_after": {"min": [0, 0, 0], "max": [1, 1, 1]},
            },
        }
        out = _format_result("extrude", result)
        text = _text_of(out)
        assert "deltas:" in text
        assert "body_count: 0 → 1" in text
        assert "+1" in text
        assert "7.85" in text

    def test_an_unknown_mass_renders_as_unknown_not_as_nothing(self):
        """``_snapshot`` answers ``null`` for a mass it could not read; a renderer that
        skipped the line would leave the caller unable to tell that from a massless
        design."""
        result = {
            "ok": True,
            "deltas": {
                "body_count_before": 1,
                "body_count_after": 1,
                "body_count_delta": 0,
                "mass_g_before": None,
                "mass_g_after": None,
                "mass_g_delta": None,
                "bbox_before": None,
                "bbox_after": None,
            },
        }
        out = _format_result("execute_code", result)

        assert "mass_g:     unknown → unknown" in _text_of(out)

    def test_a_half_readable_mass_keeps_the_side_that_was_measured(self):
        """The delta is blank whenever either side is, but the side that was read is a
        fact - and `unknown` for both would tell a caller more than is true."""
        result = {
            "ok": True,
            "deltas": {
                "body_count_before": 1,
                "body_count_after": 1,
                "body_count_delta": 0,
                "mass_g_before": None,
                "mass_g_after": 500.0,
                "mass_g_delta": None,
            },
        }
        out = _format_result("execute_code", result)

        assert "mass_g:     unknown → 500.000 (Δ unknown)" in _text_of(out)

    def test_a_body_count_without_a_delta_renders_as_unknown(self):
        """``_compute_deltas`` always sends the three; a caller-supplied dict need not,
        and the renderer must not raise on the one field it prints signed."""
        result = {
            "ok": True,
            "deltas": {"body_count_before": 1, "body_count_after": 2},
        }
        out = _format_result("execute_code", result)

        assert "body_count: 1 → 2 (Δ unknown)" in _text_of(out)

    def test_a_no_op_warning_reaches_the_rendered_text(self):
        """What this pins is that the key is *not* in ``_SPECIAL_KEYS``: a render that
        dropped the fields it does not know would leave an MCP caller with ``ok: true``
        and nothing else.  The envelope is mock's, so it also pins that mock's deltas
        meet the same judgement the add-in's do."""
        out = _format_result("execute_code", mock_command("execute_code", {}))

        assert "warning: nothing changed in the snapshot: " in _text_of(out)

    def test_render_view_returns_image_content(self):
        result = mock_command("render_view", {})
        out = _format_result("render_view", result)
        assert isinstance(out, list)
        # First block is text metadata, second is the image.
        kinds = [b.type for b in out]
        assert kinds == ["text", "image"]
        image = out[1]
        assert isinstance(image, types.ImageContent)
        assert image.mimeType == "image/png"
        assert image.data == result["image_base64"]

    def test_non_dict_result(self):
        out = _format_result("ping", "pong")
        assert isinstance(out, list)
        assert "pong" in _text_of(out)

    def test_success_path_renders_hints(self):
        """Success results can carry hints (undo's issued-but-unverified branch).

        ``hints`` sits in _SPECIAL_KEYS, and the success path skipped every
        special key, so guidance produced for a *successful* call was dropped in
        transit — the agent saw ``undone: issued`` with no next step.
        """
        out = _format_result(
            "undo",
            {
                "ok": True,
                "undone": "issued",
                "verified": False,
                "hints": ["call get_scene_info to confirm before undoing again"],
            },
        )

        text = _text_of(out)
        assert "get_scene_info" in text


def test_a_fillet_with_nothing_to_round_is_classified():
    """Fusion's own refusal, measured on a revolved cone's degenerate edges.

    It used to classify as UNKNOWN with no hints, so a caller learned nothing
    about why nothing was rounded.
    """
    message = (
        "3 : Fillet2 / Compute Failed // FILLET_NO_EDGE_FOUND - No fillet edge found."
    )

    kind, hints = classify(message)

    assert kind == "INVALID_INPUT"
    assert any("is_degenerate" in hint for hint in hints), hints


class TestFusionRefusals:
    """Fusion's own opaque refusals must still reach the caller with advice.

    Both once arrived unclassified: the first is Fusion rejecting the
    input's state, the second is a wall thickness a shell cannot honour. Neither
    matched a rule, so both arrived as ``UNKNOWN`` with no hints - the failure mode
    every rule in the table exists to stop.
    """

    def test_an_internal_validation_error_is_a_fusion_refusal(self):
        """The rule's own advice says the arguments were fine, so the kind agrees.

        Live: ``trim_surface`` on a solid answered ``2 :
        InternalValidationError : this->executeStep(editingFeature)`` and reached
        the caller as ``INVALID_INPUT`` while the hint printed beside it said
        "Fusion rejected the input's state, not its arguments."  A caller told the
        arguments are fine must not be told to fix them.  Pattern and hints are
        unchanged; only the kind moved.
        """
        kind, hints = classify(
            "2 : InternalValidationError : this->executeStep(editingFeature)"
        )

        assert kind == "FUSION_REFUSED"
        assert hints, "an opaque Fusion refusal still needs a next step"

    def test_a_generic_argument_refusal_is_advice_not_unknown(self):
        """``3 : Some input argument is invalid`` - measured for a zero shell wall.

        It is also what Fusion answers for a dimension label it will not accept,
        so the family recurs; the rule names the two cases measured.
        """
        kind, hints = classify("3 : Some input argument is invalid.")

        assert kind == "INVALID_INPUT"
        assert any("thickness" in hint for hint in hints)

    def test_a_bare_numbered_fusion_failure_is_a_fusion_refusal(self):
        """Fusion numbers its own failures; an unrecognised one must not be UNKNOWN.

        The numbered messages the table already owns ("3 : Some input argument is
        invalid", "2 : InternalValidationError ...") are matched by their own rules
        above this one, so a bare number falls through to the general rule only.
        """
        kind, hints = classify("3 : something new")

        assert kind == "FUSION_REFUSED"
        assert hints, "an opaque Fusion refusal still needs a next step"

    def test_a_non_positive_shell_thickness_is_advice_not_unknown(self):
        kind, hints = classify("thickness must be positive, got 0.0 cm")

        assert kind == "INVALID_INPUT"
        assert any("cm" in hint for hint in hints)


class TestLiveRefusalsFromFusion:
    """Two refusals found by running the merged code against Fusion 2706."""

    def test_a_ruled_surface_needs_a_free_edge(self):
        """Every edge of a solid is shared by two faces; a ruled surface is not.

        Live: `createBRepEdgeProfile` answers "3 : invalid free edge" for a box
        edge.  Before the rule it reached the caller as UNKNOWN with no hints.
        """
        kind, hints = classify("3 : invalid free edge")

        assert kind == "INVALID_INPUT"
        assert any("free edge" in hint for hint in hints), hints

    def test_a_component_without_a_sheet_metal_rule_says_which_body_to_use(self):
        """Live: ``create_flange`` answers ``3 : component has no sheet metal rule``.

        It matched no rule, so the caller got ``UNKNOWN`` with no hints.  The fix
        is a different body, not a different argument, so the kind is
        ``GEOMETRY_UNSUPPORTED``.
        """
        kind, hints = classify("3 : component has no sheet metal rule")

        assert kind == "GEOMETRY_UNSUPPORTED"
        assert any("sheet-metal rule" in hint for hint in hints), hints


class TestThreadSizeRefusal:
    """``create_thread`` refuses a designation that does not match the face."""

    def test_the_refusal_reaches_the_caller_as_invalid_input(self):
        kind, hints = classify(
            "The face is 20.00 mm across but M6x1 is 5.88 mm: Fusion would resize "
            "the body to match the thread. M20x2.5 (6g) matches that diameter."
        )

        assert kind == "INVALID_INPUT"
        assert any("allow_resize" in hint for hint in hints), hints
