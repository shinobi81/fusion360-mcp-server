"""``undo`` must do something it can verify, and say so honestly when it can't.

Measured against Fusion 2706 (`command_handler.undo` in 0.3.1):

* ``UndoCommand.execute()`` is **asynchronous**. Four of five consecutive calls
  returned ``undone: true`` while the design was untouched, and 57 event pumps
  inside one handler did not make a queued undo land — it applies only after
  the handler returns.
* The design-type guard therefore compared ``designType`` before the undo
  landed, i.e. it could never fire.

So undo is now two paths:

* **parametric** — move ``timeline.markerPosition`` back one step. The API is
  synchronous, so the change is observable and verifiable in the same call.
  The feature stays in the timeline (suppressed) and returns if the marker moves
  forward again.
* **direct / no timeline** — Fusion has no synchronous handle, so the UI command
  is issued and reported as ``undone: "issued"`` with ``verified: False`` rather
  than claiming success nobody checked.

The add-in cannot be imported under pytest (it needs Fusion's ``adsk``), so
these tests drive ``command_handler.py`` against the fake design in
``tests.fakes.design``.
"""

from __future__ import annotations

import pytest

from tests.fakes.design import DIRECT, PARAMETRIC, FakeDesign, undo_rig


@pytest.fixture
def rig(handler_module):
    """A handler wired to a fake design, with both UI commands stubbed."""

    def factory(design=None, with_undo=True, with_redo=True):
        built = undo_rig(
            handler_module,
            design=design,
            with_undo=with_undo,
            with_redo=with_redo,
        )
        return built.design, built.handler

    return factory


class TestParametricUndo:
    def test_rolls_the_marker_back_one_step(self, rig):
        design, handler = rig(FakeDesign(features=2))

        result = handler.undo()

        assert design.marker == 1
        assert result["undone"] is True
        assert result["verified"] is True
        assert result["marker_position"] == 1

    def test_leaves_the_feature_in_the_timeline(self, rig):
        """Rollback suppresses rather than deletes — worth saying out loud."""
        design, handler = rig(FakeDesign(features=2))

        result = handler.undo()

        assert design.timeline_count == 2, "the feature must not be deleted"
        assert "suppressed" in result["note"].lower()
        assert result["timeline_count"] == 2

    def test_does_not_use_the_async_ui_command(self, rig):
        design, handler = rig(FakeDesign(features=2))

        handler.undo()

        assert design.undo_commands_executed == 0, (
            "parametric undo must not fall back to the asynchronous UI command"
        )

    def test_reports_nothing_to_undo_at_the_start_of_history(self, rig):
        design, handler = rig(FakeDesign(features=2, marker=0))

        result = handler.undo()

        assert result["undone"] is False
        assert result["reason"]
        assert result["marker_position"] == 0
        assert design.marker == 0

    def test_rolls_forward_again(self, rig):
        """The rollback is reversible, which is a free redo."""
        design, handler = rig(FakeDesign(features=2))

        handler.undo()
        design.timeline.markerPosition = 2

        assert design.marker == 2
        assert design.marker_writes == [1, 2]

    def test_empty_timeline_reports_nothing_to_undo(self, rig):
        """No features means no undo — not an async command nobody can verify."""
        design, handler = rig(FakeDesign(features=0))

        result = handler.undo()

        assert result["undone"] is False
        assert result["verified"] is True
        assert design.undo_commands_executed == 0


class TestDirectModeFallback:
    def test_get_scene_info_works_on_a_direct_design(self, rig):
        """get_scene_info must not explode in direct mode.

        It read ``design.timeline`` behind ``hasattr``, but hasattr only swallows
        AttributeError and the property raises RuntimeError — so the tool undo's
        own hint sends agents to was an UNKNOWN error in exactly that mode.
        """
        design, handler = rig(
            FakeDesign(features=0, design_type=DIRECT, timeline_raises=True)
        )
        design.productType = "DesignProductType"
        handler._camera_info = lambda: {}

        result = handler.get_scene_info()

        assert result["timeline_count"] == 0
        assert result["bodies_count"] == 0

    def test_undo_works_when_design_timeline_raises(self, rig):
        """In direct mode ``design.timeline`` raises; undo must not read it.

        Measured in Fusion 2706: the property raises "3 : this is not a
        parametric design", which turned undo into an UNKNOWN error instead of
        the documented issued-but-unverified result.
        """
        design, handler = rig(FakeDesign(design_type=DIRECT, timeline_raises=True))

        result = handler.undo()

        assert result["undone"] == "issued"
        assert result["verified"] is False
        assert design.undo_commands_executed == 1

    def test_reports_issued_but_unverified(self, rig):
        design, handler = rig(FakeDesign(design_type=DIRECT))

        result = handler.undo()

        assert result["undone"] == "issued"
        assert result["verified"] is False
        assert design.undo_commands_executed == 1
        combined = (result.get("note", "") + " ".join(result.get("hints", []))).lower()
        assert "async" in combined or "later" in combined
        assert "get_scene_info" in combined

    def test_missing_undo_command_still_refuses(self, rig):
        design, handler = rig(FakeDesign(design_type=DIRECT), with_undo=False)

        with pytest.raises(RuntimeError, match="not available"):
            handler.undo()

        assert design.undo_commands_executed == 0


class TestDesignTypeGuard:
    def test_aborts_if_rolling_back_switches_the_design_type(self, rig):
        design, handler = rig(FakeDesign(features=2, marker_switches_type=True))

        with pytest.raises(RuntimeError, match="Undo aborted"):
            handler.undo()

        assert design.designType == PARAMETRIC, "design was left in direct mode"
        assert design.marker == 2, "the marker was not restored"
