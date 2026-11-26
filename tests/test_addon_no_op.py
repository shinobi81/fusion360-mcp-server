"""A mutation that changed nothing measurable says so.

``_snapshot`` computed ``body_count_delta`` and ``mass_g_delta`` for every mutation and
nothing read them back as a judgement, so ``execute_code`` running a script that touched
no geometry answered ``ok: true`` with both deltas zero - which reads as success to an
agent that stops at ``ok``.

Measured live on Fusion 2706.1.17: the case the brief for this feature named,
``extrude(operation="cut")`` with a profile outside every body, is **refused** by Fusion
(``3 : No target body found to cut or intersect!``), so it can never be the proof.
``execute_code`` with a script that changes nothing is the call that really is silent,
and it is what these tests pin.
"""

from __future__ import annotations

import pytest

# Imported from the canonical add-in modules, not the package mirrors: the mirrors are
# copies, and a test that reads a copy cannot fail when the two drift.
from addon.server.handler_base import HandlerBase
from addon.server.mutation_commands import (
    MUTATION_COMMANDS,
    NO_OP_EXEMPT,
    no_op_warning,
)
from tests.fakes.bodies import FakeBody
from tests.fakes.design import FakeDesign

UNCHANGED = {
    "body_count_before": 3,
    "body_count_after": 3,
    "body_count_delta": 0,
    "mass_g_before": 7850.0,
    "mass_g_after": 7850.0,
    "mass_g_delta": 0.0,
    "bbox_before": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
    "bbox_after": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
}


def _deltas(**overrides):
    return {**UNCHANGED, **overrides}


# ── the judgement ─────────────────────────────────────────────────────


def test_an_unchanged_snapshot_warns_and_names_the_two_deltas():
    warning = no_op_warning("execute_code", _deltas())

    assert warning is not None
    assert warning.startswith("nothing changed: ")
    assert "body_count 3 -> 3" in warning
    assert "mass_g 7850.000 -> 7850.000" in warning


def test_a_body_appearing_does_not_warn():
    deltas = _deltas(body_count_after=4, body_count_delta=1, mass_g_after=10.0)

    assert no_op_warning("extrude", deltas) is None


def test_a_mass_change_does_not_warn():
    """A cut that removes a gram: neither count nor bbox need move for it to be real."""
    deltas = _deltas(mass_g_after=7849.0, mass_g_delta=-1.0)

    assert no_op_warning("extrude", deltas) is None


def test_a_bounding_box_change_alone_does_not_warn():
    """``move_body`` changes neither count nor mass, so a two-delta rule would call a
    real move a no-op - the bbox is the only measure that moves."""
    deltas = _deltas(
        bbox_after={"min": [5.0, 0.0, 0.0], "max": [6.0, 1.0, 1.0]},
    )

    assert no_op_warning("move_body", deltas) is None


def test_a_mass_delta_below_the_tolerance_still_warns():
    """A no-op repeats Fusion's own number; the tolerance only absorbs the kg -> g
    conversion's last bit."""
    deltas = _deltas(mass_g_after=7850.0000001, mass_g_delta=1e-7)

    assert no_op_warning("execute_code", deltas) is not None


def test_an_unknown_mass_is_not_a_zero_mass():
    """``_snapshot`` is best-effort: a deltas dict without the key must not be read as
    "the mass did not move"."""
    deltas = _deltas()
    del deltas["mass_g_delta"]

    assert no_op_warning("execute_code", deltas) is None


def test_an_unknown_body_count_is_not_a_zero_delta():
    deltas = _deltas()
    del deltas["body_count_delta"]

    assert no_op_warning("execute_code", deltas) is None


def test_two_absent_bounding_boxes_compare_as_unchanged():
    """An empty design has no bbox on either side, which is not a change."""
    deltas = _deltas(bbox_before=None, bbox_after=None)

    assert no_op_warning("delete_all", deltas) is not None


# ── the exemption table ───────────────────────────────────────────────

#: Pinned by name on purpose: a mutation added later must not inherit an exemption by
#: sharing a name with one of these, and an exemption added for a new command has to
#: pass this test by being listed here.
_EXEMPT = {
    "auto_constrain",
    "create_thread",
    "create_ucs",
    "set_color",
    "set_parameter",
    "split_face",
    "suppress_feature",
    "undo",
    "unsuppress_feature",
}


def test_the_exempt_set_is_exactly_this():
    assert set(NO_OP_EXEMPT) == _EXEMPT


def test_every_exempt_command_is_a_mutation():
    """An exemption for a command that is not a mutation is dead code that reads as
    protection - and a rename in one table would otherwise go unnoticed."""
    assert set(NO_OP_EXEMPT) <= MUTATION_COMMANDS


def test_every_exemption_carries_a_reason():
    for command, reason in NO_OP_EXEMPT.items():
        assert reason.strip(), f"{command} is exempt with no reason recorded"


@pytest.mark.parametrize("command", sorted(_EXEMPT))
def test_an_exempt_command_never_warns(command):
    assert no_op_warning(command, _deltas()) is None


# ── through the envelope ──────────────────────────────────────────────


def _result(handler, command: str, **params):
    """Run *command* through the dispatch envelope, as the socket does."""
    return handler.execute_command({"type": command, "params": params})["result"]


def _fake_design():
    """A design with one body.  Its root carries no mass and no bbox, so the fake's
    snapshot is ``body_count`` alone: enough for the judgement, which reads every
    measure it is given."""
    return FakeDesign(bodies=[FakeBody("Body1")])


def test_a_script_that_changes_nothing_carries_the_warning(bound_handler):
    """The live case: Fusion accepts the call and the design does not move."""
    handler = bound_handler(_fake_design())

    result = _result(handler, "execute_code", code="count = 1")

    assert result["ok"] is True
    assert result["deltas"]["body_count_delta"] == 0
    assert "nothing changed" in result["warning"]


def test_a_mutation_that_adds_a_body_carries_no_warning(bound_handler):
    handler = bound_handler(_fake_design())

    result = _result(handler, "create_box", length=2.0, width=2.0, height=2.0)

    assert result["deltas"]["body_count_delta"] == 1
    assert "warning" not in result


def test_an_exempt_command_carries_no_warning_through_the_envelope(bound_handler):
    handler = bound_handler(_fake_design())

    result = _result(handler, "set_color", body_name="Body1", red=1, green=0, blue=0)

    assert "deltas" in result
    assert result["deltas"]["body_count_delta"] == 0
    assert "warning" not in result


def test_an_unreadable_snapshot_carries_neither_deltas_nor_a_warning(bound_handler):
    """Unknown is not zero: with no snapshot there is nothing to judge."""
    handler = bound_handler(_fake_design())
    handler._snapshot = lambda: None

    result = _result(handler, "execute_code", code="count = 1")

    assert result["ok"] is True
    assert "deltas" not in result
    assert "warning" not in result


def test_the_handler_base_snapshots_only_the_commands_it_can_judge():
    """The judgement must not reach a read-only command: no snapshot, no deltas."""
    assert "ping" not in HandlerBase._MUTATION_COMMANDS
    assert "get_scene_info" not in HandlerBase._MUTATION_COMMANDS
