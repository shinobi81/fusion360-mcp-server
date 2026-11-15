"""``export_stl`` and ``export_step``, pinned before they are merged into one.

Neither had a test that could reach it: the fake runtime had no export model, so
the two ~40-line functions were only ever exercised inside Fusion.  That is why
they were left alone in the dedupe pass — and why the model lives here first.

These are characterisation tests: the first five passed against the *unmerged*
pair, so the merge was provably behaviour-preserving rather than hopefully so.
The fake keeps Fusion's own argument order for the two option factories, because
that order is the one thing the merge must not get wrong:

    createSTLExportOptions(entity, path)      # entity first
    createSTEPExportOptions(path, entity)     # path first

The sibling hide is asserted **at execute time**.  Reading ``isVisible`` after
the handler returns can only observe the state the ``finally`` restored, so a
sweep that never ran — or one keyed on the wrong thing — would pass.
"""

from __future__ import annotations

import os

import pytest

from tests.fakes.bodies import FakeBody
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence


def _root_body() -> FakeBody:
    return FakeBody("Body1")


def _design_with(body: FakeBody) -> FakeDesign:
    return FakeDesign(bodies=[body])


class TestRootBody:
    def test_stl_creates_options_with_the_body_then_the_path(
        self, bound_handler, tmp_path
    ):
        design = _design_with(_root_body())
        target = str(tmp_path / "out.stl")

        out = bound_handler(design).export_stl("Body1", target)

        options = design.exportManager.executed[0]
        assert options.kind == "stl"
        assert options.entity is design.rootComponent.bRepBodies.item(0)
        assert options.path == target
        assert out == {"exported": True, "body": "Body1", "file_path": target}
        assert design.exportManager.visible_at_execute is None, (
            "a root body has no occurrence to sample"
        )

    def test_stl_asks_for_medium_mesh_refinement(self, bound_handler, tmp_path):
        design = _design_with(_root_body())

        bound_handler(design).export_stl("Body1", str(tmp_path / "out.stl"))

        assert design.exportManager.executed[0].meshRefinement == "medium"

    def test_step_creates_options_with_the_path_then_the_body(
        self, bound_handler, tmp_path
    ):
        design = _design_with(_root_body())
        target = str(tmp_path / "out.step")

        out = bound_handler(design).export_step("Body1", target)

        options = design.exportManager.executed[0]
        assert options.kind == "step"
        assert options.entity is design.rootComponent.bRepBodies.item(0)
        assert options.path == target
        assert out == {"exported": True, "body": "Body1", "file_path": target}

    def test_a_bare_filename_needs_no_directory_created(self, bound_handler):
        """``os.makedirs(os.path.dirname("out.stl"))`` used to raise.

        ``dirname`` of a bare name is ``""``, and ``makedirs("")`` raises
        ``FileNotFoundError``.  No other test crosses that branch because every
        one of them passes a directory.
        """
        design = _design_with(_root_body())

        out = bound_handler(design).export_stl("Body1", "out.stl")

        assert out["file_path"] == "out.stl"
        assert design.exportManager.executed[0].path == "out.stl"

    def test_f3d_takes_a_bare_filename_too(self, bound_handler):
        design = _design_with(_root_body())

        bound_handler(design).export_f3d("out.f3d")

        executed = design.exportManager.executed[0]
        assert (executed.kind, executed.path) == ("f3d", "out.f3d")

    def test_step_options_carry_no_mesh_refinement(self, bound_handler, tmp_path):
        """The one real asymmetry: only STL options expose a refinement."""
        design = _design_with(_root_body())

        bound_handler(design).export_step("Body1", str(tmp_path / "out.step"))

        assert design.exportManager.executed[0].meshRefinement is None

    @pytest.mark.parametrize(
        "method, expected_name",
        [
            ("export_stl", "Body1.stl"),
            ("export_step", "Body1.step"),
        ],
    )
    def test_the_default_path_is_the_desktop_named_after_the_body(
        self, bound_handler, tmp_path, monkeypatch, method, expected_name
    ):
        """``~/Desktop/<body>.<ext>`` - both extensions, which the merge generalised.

        The two functions used to spell ``.stl`` and ``.step`` as literals; a merge
        that wrote ``f"{body_name}.stl"`` for both would leave the STEP default
        broken and every other test here green.
        """
        design = _design_with(_root_body())
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        out = getattr(bound_handler(design), method)("Body1")

        assert out["file_path"] == os.path.join(str(tmp_path), "Desktop", expected_name)
        assert os.path.isdir(os.path.join(str(tmp_path), "Desktop"))


class TestComponentBody:
    """A body that lives in an occurrence, next to siblings that must be hidden.

    The layout is Fusion's, not a convenient one: the body is reachable only
    through the occurrence (``_body_by_name`` searches ``root.allOccurrences``),
    which is also how the handler learns it is nested.

    One thing the fake cannot represent: Fusion hands back a *proxy* body inside
    an occurrence, while ``FakeOccurrence.bRepBodies`` returns the component's own
    bodies.  Native and proxy are the same object here, so ``assemblyContext`` is
    what tells the handler a body is nested - not the collection it came from.
    """

    def _design(self, *, fail: bool = False):
        target = FakeBody("Body1")
        same_name = FakeBody("Body1")  # same name, different entityToken
        already_hidden = FakeBody("Hidden")
        already_hidden.isVisible = False

        component = FakeComponent("Comp1", bodies=[target, same_name, already_hidden])
        occurrence = FakeOccurrence(component)
        design = FakeDesign(features=0, bodies=[])
        design.rootComponent.occurrences.add(occurrence)
        # Fusion hands back a proxy body inside an occurrence, and its
        # ``assemblyContext`` is that occurrence - which is how the handler learns
        # the body is nested and what to hand the exporter.
        for body in component.bRepBodies:
            body.assemblyContext = occurrence
        design.exportManager.fail = fail
        return design, target, same_name, already_hidden, occurrence

    def test_siblings_are_hidden_while_the_export_runs(self, bound_handler, tmp_path):
        design, _target, _same_name, _hidden, occurrence = self._design()

        bound_handler(design).export_stl("Body1", str(tmp_path / "out.stl"))

        options = design.exportManager.executed[0]
        assert options.entity is occurrence, "the occurrence is what Fusion is handed"
        assert design.exportManager.visible_at_execute == [True, False, False], (
            "the target visible, both siblings hidden - by entityToken, so the "
            "same-named sibling counts as a sibling"
        )

    def test_siblings_are_restored_afterwards(self, bound_handler, tmp_path):
        design, target, same_name, already_hidden, _occurrence = self._design()

        bound_handler(design).export_stl("Body1", str(tmp_path / "out.stl"))

        assert same_name.isVisible is True, "a hidden sibling was never restored"
        assert already_hidden.isVisible is False, (
            "a sibling that was already hidden must not be made visible"
        )
        assert target.isVisible is True

    def test_siblings_are_restored_when_the_export_fails(self, bound_handler, tmp_path):
        design, _target, same_name, _hidden, occurrence = self._design(fail=True)
        assert occurrence.bRepBodies.count == 3

        with pytest.raises(RuntimeError):
            bound_handler(design).export_stl("Body1", str(tmp_path / "out.stl"))

        assert same_name.isVisible is True

    def test_step_exports_the_occurrence_and_reports_the_body(
        self, bound_handler, tmp_path
    ):
        design, _target, _same_name, _hidden, occurrence = self._design()
        target_path = str(tmp_path / "out.step")

        out = bound_handler(design).export_step("Body1", target_path)

        options = design.exportManager.executed[0]
        assert (options.kind, options.entity) == ("step", occurrence)
        assert out == {"exported": True, "body": "Body1", "file_path": target_path}


class TestNameCollision:
    def test_a_root_body_wins_over_an_occurrence_body_with_the_same_name(
        self, bound_handler, tmp_path
    ):
        """``_body_by_name`` searches root bodies first; this pins that order.

        It matters for export: the root body takes the plain path, the nested one
        the sibling-hiding path, and the caller's name is all they gave.
        """
        root_body = FakeBody("Body1")
        nested = FakeBody("Body1")
        component = FakeComponent("Comp1", bodies=[nested])
        occurrence = FakeOccurrence(component)
        design = FakeDesign(features=0, bodies=[root_body])
        design.rootComponent.occurrences.add(occurrence)
        nested.assemblyContext = occurrence

        out = bound_handler(design).export_stl("Body1", str(tmp_path / "out.stl"))

        executed = design.exportManager.executed[0]
        assert executed.entity is root_body
        assert design.exportManager.visible_at_execute is None
        assert out["body"] == "Body1"
