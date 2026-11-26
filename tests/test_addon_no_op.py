"""A mutation that changed nothing measurable says so.

``execute_command`` computed ``body_count_delta`` and ``mass_g_delta`` (through
``_compute_deltas``, from what ``_snapshot`` measured) for every mutation and nothing
read them back as a judgement, so ``execute_code`` running a script that touched
no geometry answered ``ok: true`` with both deltas zero - which reads as success to an
agent that stops at ``ok``.

Measured live on Fusion 2706.1.17: the case the brief for this feature named,
``extrude(operation="cut")`` with a profile outside every body, is **refused** by Fusion
(``3 : No target body found to cut or intersect!``), so it can never be the proof.
``execute_code`` with a script that changes nothing is the call that really is silent,
and it is what these tests pin.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# Imported from the canonical add-in module, not the package mirror: the mirror is a
# copy, and a test that reads a copy cannot fail when the two drift.
from addon.server.mutation_commands import (
    MUTATION_COMMANDS,
    NO_OP_EXEMPT,
    no_op_warning,
)
from tests.fakes.bodies import FakeBody, FakeBoundingBox
from tests.fakes.design import FakeDesign, FakeRoot

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
    """A consistent snapshot: one more body, its 10 g, and a box grown to hold it."""
    deltas = _deltas(
        body_count_after=4,
        body_count_delta=1,
        mass_g_after=7860.0,
        mass_g_delta=10.0,
        bbox_after={"min": [0.0, 0.0, 0.0], "max": [2.0, 1.0, 1.0]},
    )

    assert no_op_warning("extrude", deltas) is None


def test_a_mass_change_does_not_warn():
    """A cut that removes a gram: neither count nor bbox need move for it to be real."""
    deltas = _deltas(mass_g_after=7849.0, mass_g_delta=-1.0)

    assert no_op_warning("extrude", deltas) is None


def test_a_bounding_box_change_alone_does_not_warn():
    """``unfold`` and ``flat_pattern`` change neither count nor mass, so a two-delta
    rule would call a real unfold a no-op - the bbox is the only measure that moves."""
    deltas = _deltas(
        bbox_after={"min": [5.0, 0.0, 0.0], "max": [6.0, 1.0, 1.0]},
    )

    assert no_op_warning("unfold", deltas) is None


def test_a_move_is_never_judged_even_when_the_root_box_cannot_see_it():
    """Measured on 2706.1.17: a 1 cm move of a body inside a larger body's extents left
    the root box identical, so the union cannot prove a move did nothing - and Fusion
    refuses a zero translation anyway."""
    deltas = _deltas()

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


def test_an_empty_design_has_two_absent_bounding_boxes_that_are_not_a_change():
    """No bodies on either side: there is no box to read, so ``None`` really is
    unchanged rather than unread."""
    deltas = _deltas(
        body_count_before=0,
        body_count_after=0,
        mass_g_before=0.0,
        mass_g_after=0.0,
        bbox_before=None,
        bbox_after=None,
    )

    assert no_op_warning("delete_all", deltas) is not None


def test_bodies_with_no_bounding_box_are_unknown_not_unchanged():
    """Bodies exist, so a box exists: ``None`` on both sides means the read failed,
    and "identical" would be a claim about a measurement nobody took."""
    deltas = _deltas(bbox_before=None, bbox_after=None)

    assert no_op_warning("execute_code", deltas) is None


# ── the exemption table ───────────────────────────────────────────────

#: Pinned by name on purpose: a name reaches this table only by being listed here, so an
#: exemption cannot be added - or quietly inherited by a rename - without a test that
#: says so and a reason beside it.
_EXEMPT = {
    "auto_constrain",
    "create_thread",
    "create_ucs",
    "move_body",
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


class _MeasuredRoot(FakeRoot):
    """``FakeRoot`` plus the two shapes ``_snapshot`` reads.

    The fake root carries neither ``physicalProperties`` nor ``boundingBox``, so a
    snapshot taken through it answers ``_snapshot``'s fallbacks instead of measuring -
    and a design nothing was read from is exactly what must *not* be judged.  This root
    measures, so "unchanged" in these tests means measured twice.
    """

    def __init__(self, design, mass_kg: float, box: FakeBoundingBox | None):
        super().__init__(design=design, bodies=[FakeBody("Body1")])
        self.boundingBox = box
        self._mass_kg = mass_kg

    @property
    def physicalProperties(self):
        return SimpleNamespace(mass=self._mass_kg)


class _UnreadableMassRoot(_MeasuredRoot):
    """A design whose mass cannot be read, as a closed one's does not."""

    @property
    def physicalProperties(self):
        raise RuntimeError("4 : An API Object refers to a deleted Object")


_BOX = FakeBoundingBox(min_point=(0.0, 0.0, 0.0), max_point=(1.0, 1.0, 1.0))


def _measured_design(
    root_class=_MeasuredRoot,
    mass_kg: float = 7.85,
    box: FakeBoundingBox | None = _BOX,
):
    """A one-body design whose snapshot is measured, not guessed."""
    design = FakeDesign(bodies=[FakeBody("Body1")])
    design.rootComponent = root_class(design, mass_kg, box)
    return design


def test_a_script_that_changes_nothing_carries_the_warning(bound_handler):
    """The live call, rehearsed: Fusion accepts it and the design does not move."""
    handler = bound_handler(_measured_design())

    result = _result(handler, "execute_code", code="count = 1")

    assert result["ok"] is True
    assert result["deltas"]["body_count_delta"] == 0
    assert result["deltas"]["mass_g_delta"] == 0.0
    assert "nothing changed" in result["warning"]
    assert "script" in result["warning"], (
        "the advice has to fit the call that most often produces this warning"
    )


def test_a_mutation_that_adds_a_body_carries_no_warning(bound_handler):
    handler = bound_handler(_measured_design())

    result = _result(handler, "create_box", length=2.0, width=2.0, height=2.0)

    assert result["deltas"]["body_count_delta"] == 1
    assert "warning" not in result


def test_an_exempt_command_carries_no_warning_through_the_envelope(bound_handler):
    """Measured-instance parity: these deltas are identical on every measure, so only
    the exemption keeps the key off."""
    handler = bound_handler(_measured_design())

    result = _result(handler, "set_color", body_name="Body1", red=1, green=0, blue=0)

    assert result["deltas"]["body_count_delta"] == 0
    assert result["deltas"]["mass_g_delta"] == 0.0
    assert "warning" not in result


def test_an_unreadable_snapshot_carries_neither_deltas_nor_a_warning(bound_handler):
    """Unknown is not zero: with no snapshot there is nothing to judge."""
    handler = bound_handler(_measured_design())
    handler._snapshot = lambda: None

    result = _result(handler, "execute_code", code="count = 1")

    assert result["ok"] is True
    assert "deltas" not in result
    assert "warning" not in result


def test_an_unreadable_mass_is_reported_as_unknown_not_as_zero(bound_handler):
    """A design whose mass cannot be read answers ``None``, and nothing is judged: the
    old fallback answered 0.0, which reads as "the mass did not move"."""
    handler = bound_handler(_measured_design(root_class=_UnreadableMassRoot))

    result = _result(handler, "execute_code", code="count = 1")

    assert result["deltas"]["mass_g_delta"] is None
    assert "warning" not in result


def test_a_design_with_bodies_and_no_bounding_box_is_not_judged(bound_handler):
    """The other unreadable measure, through the envelope this time."""
    handler = bound_handler(_measured_design(box=None))

    result = _result(handler, "execute_code", code="count = 1")

    assert result["deltas"]["bbox_after"] is None
    assert "warning" not in result


def test_a_read_only_command_gets_no_deltas_and_no_warning(bound_handler):
    """The judgement lives inside the mutation branch, not beside it."""
    handler = bound_handler(_measured_design())

    result = _result(handler, "get_scene_info")

    assert result["ok"] is True
    assert "deltas" not in result
    assert "warning" not in result
