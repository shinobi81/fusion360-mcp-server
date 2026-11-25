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

import base64
import json
import math
import os
import tempfile
from types import SimpleNamespace

import pytest

from addon.server import fusion_api as adsk
from addon.server import hints as addon_hints
from tests.fakes.bodies import FakeBody, FakeBoundingBox
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence
from tests.fakes.mesh import FakeMeshBodies
from tests.fakes.runtime import (
    ORTHOGRAPHIC_CAMERA_TYPE,
    PERSPECTIVE_CAMERA_TYPE,
    FakePoint3D,
    FakeVector3D,
)


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


class _EmptyImport(FakeMeshBodies):
    """The current ``add(path, units)`` route, answering a file that held no mesh."""

    def add(self, file_path, units):
        return FakeMeshBodies([])


class _LegacyEmptyImport:
    """Pre-2025 ``addByFile`` answering no body, and no ``add`` to fall back from.

    ``add`` is absent rather than raising, because that is the build this models: the
    handler's ``except AttributeError`` is what takes it to the legacy call.
    """

    def addByFile(self, file_path, units):
        return None


class TestImportMeshRefusals:
    """A mesh file is a path and a file, so its refusals are not design lookups."""

    def test_a_missing_file_is_invalid_input(self, bound_handler, tmp_path):
        missing = tmp_path / "not-there.stl"

        with pytest.raises(addon_hints.Refusal) as raised:
            bound_handler(FakeDesign()).import_mesh(str(missing))

        assert raised.value.error_kind == "INVALID_INPUT"
        assert str(raised.value) == f"Mesh file not found: {missing}"
        assert raised.value.hints == ("Pass a path to a file that exists.",)

    def test_a_file_with_no_mesh_body_is_fusion_refused(self, bound_handler, tmp_path):
        source = tmp_path / "empty.stl"
        source.write_bytes(b"")
        design = FakeDesign()
        design.rootComponent.meshBodies = _EmptyImport()

        with pytest.raises(addon_hints.Refusal) as raised:
            bound_handler(design).import_mesh(str(source))

        assert raised.value.error_kind == "FUSION_REFUSED"
        assert str(raised.value) == f"No mesh bodies imported from {source}"
        assert raised.value.hints == (
            "The file has no mesh body; check it in a viewer first.",
        )

    def test_the_legacy_import_path_reports_a_missing_mesh_body(
        self, bound_handler, tmp_path
    ):
        """``addByFile`` returned one body or ``None``; a meshless file answers None."""
        source = tmp_path / "empty.stl"
        source.write_bytes(b"")
        design = FakeDesign()
        design.rootComponent.meshBodies = _LegacyEmptyImport()

        with pytest.raises(addon_hints.Refusal) as raised:
            bound_handler(design).import_mesh(str(source))

        assert raised.value.error_kind == "FUSION_REFUSED"
        assert str(raised.value) == f"No mesh body imported from {source}"
        assert raised.value.hints == (
            "The file has no mesh body; check it in a viewer first.",
        )


class _FakeCamera:
    """``adsk.core.Camera``: what the two viewport tools read and write.

    ``render_view`` and ``export_view_sheet`` both save ``eye``/``target``/``upVector``
    and ``cameraType`` and put them back afterwards, so the fake carries real
    point/vector objects rather than tuples. Fusion refuses such an assignment outright
    - the setters take a ``Point3D``/``Vector3D``, and a tuple fails SWIG's conversion -
    while the fake takes the write and raises later, at the capture or at ``state()``.
    """

    def __init__(
        self, eye=(10.0, 0.0, 0.0), target=(0.0, 0.0, 0.0), up=(0.0, 0.0, 1.0)
    ):
        self.eye = FakePoint3D(*eye)
        self.target = FakePoint3D(*target)
        self.upVector = FakeVector3D(*up)
        self.cameraType = ORTHOGRAPHIC_CAMERA_TYPE
        self.isFitView = False
        self.isSmoothTransition = False

    def copy(self) -> "_FakeCamera":
        """A camera holding the same values, as a separate object."""
        clone = _FakeCamera()
        clone.eye = FakePoint3D(self.eye.x, self.eye.y, self.eye.z)
        clone.target = FakePoint3D(self.target.x, self.target.y, self.target.z)
        clone.upVector = FakeVector3D(self.upVector.x, self.upVector.y, self.upVector.z)
        clone.cameraType = self.cameraType
        clone.isFitView = self.isFitView
        clone.isSmoothTransition = self.isSmoothTransition
        return clone

    def state(self):
        """The four values the restore has to bring back, as plain tuples."""
        return (
            (self.eye.x, self.eye.y, self.eye.z),
            (self.target.x, self.target.y, self.target.z),
            (self.upVector.x, self.upVector.y, self.upVector.z),
            self.cameraType,
        )


class _Viewport:
    """``Viewport``: ``fit``, the camera, ``refresh``, and a capture that writes bytes.

    The capture writes a real file, because that is what ``render_view`` reads back and
    base64-encodes. A ``True``-returning fake that wrote nothing would not reach the
    refusal - ``mkstemp`` already made the file, so ``os.path.exists`` is true either
    way - it would hand back zero bytes and an empty string. That is why the payload is
    pinned as a round-trip rather than a length.
    """

    def __init__(self, saved: bool = True, camera: _FakeCamera | None = None):
        self.saved = saved
        self.fitted = 0
        self.refreshed = 0
        #: The camera the viewport actually holds. ``camera`` below hands out a copy.
        self._camera = camera or _FakeCamera()
        #: How many times a camera was *assigned back*. Fusion hands the camera out as a
        #: copy, so an edit has no effect until the assignment - this counts them, which
        #: pins "moved once, restored once" independently of the values themselves.
        self.camera_writes = 0
        self.captures: list[tuple[str, int, int]] = []
        #: The camera's eye at each capture, from the stored camera: the sheet puts the
        #: caller's view back, so a read afterwards reports what was there before.
        self.eyes_at_capture: list[tuple[float, float, float]] = []
        #: The up vector at each capture: ``_apply_view`` writes it per view and the
        #: restore overwrites it, so a later read cannot tell the views apart.
        self.ups_at_capture: list[tuple[float, float, float]] = []
        #: The camera type at each capture, for the same reason: ``_apply_view`` sets it
        #: orthographic and the restore writes the caller's back, so only a capture-time
        #: read sees that it was set at all.
        self.types_at_capture: list[int] = []
        #: ``isFitView`` at each capture: ``_apply_view`` sets it and the restore does
        #: not reset it, so a later read sees it too - but not at the moment it matters.
        self.fit_view_at_capture: list[bool] = []
        #: The target at each capture: ``_apply_view`` aims the camera at the frame
        #: centre and the restore writes the caller's back, so only a capture-time read
        #: shows where it pointed. A viewport looks along eye - target, so a dropped
        #: target renders the model against the origin instead of the frame's centre.
        self.targets_at_capture: list[tuple[float, float, float]] = []

    @property
    def camera(self) -> _FakeCamera:
        """``Viewport.camera``: a copy, as the stub documents it.

        "The camera returned is a copy... Editing the properties of the camera will have
        no effect on the viewport until the camera is assigned back" - so a fake that
        handed back the stored object would let a handler that never assigns back pass,
        while live it would render the caller's view four times.
        """
        return self._camera.copy()

    @camera.setter
    def camera(self, value: _FakeCamera) -> None:
        self._camera = value
        self.camera_writes += 1

    def fit(self) -> bool:
        self.fitted += 1
        return True

    def refresh(self) -> bool:
        self.refreshed += 1
        return True

    def saveAsImageFile(self, path, width, height):
        self.captures.append((path, width, height))
        eye = self._camera.eye
        self.eyes_at_capture.append((eye.x, eye.y, eye.z))
        up = self._camera.upVector
        self.ups_at_capture.append((up.x, up.y, up.z))
        self.types_at_capture.append(self._camera.cameraType)
        self.fit_view_at_capture.append(self._camera.isFitView)
        target = self._camera.target
        self.targets_at_capture.append((target.x, target.y, target.z))
        if self.saved:
            with open(path, "wb") as handle:
                # Recognisable, and *per file*: the basename goes in, so two views write
                # two different payloads and an HTML that embedded one twice fails.
                handle.write(
                    b"PNG"
                    + os.path.basename(path).encode("ascii")
                    + bytes([int(width) % 256, int(height) % 256])
                )
        return self.saved


class TestRenderViewRefusals:
    def test_no_viewport_is_workspace_unavailable(self, bound_handler):
        handler = bound_handler(FakeDesign(), app=SimpleNamespace(activeViewport=None))

        with pytest.raises(addon_hints.Refusal) as raised:
            handler.render_view()

        assert raised.value.error_kind == "WORKSPACE_UNAVAILABLE"
        assert str(raised.value) == "No active viewport"
        assert raised.value.hints == ("Open a viewport in Fusion, then retry.",)

    def test_a_failed_capture_is_fusion_refused(self, bound_handler):
        viewport = _Viewport(saved=False)
        handler = bound_handler(
            FakeDesign(), app=SimpleNamespace(activeViewport=viewport)
        )

        with pytest.raises(addon_hints.Refusal) as raised:
            handler.render_view()

        assert viewport.fitted == 1, "the capture is attempted, not skipped"
        assert raised.value.error_kind == "FUSION_REFUSED"
        assert str(raised.value) == "saveAsImageFile returned false"
        assert raised.value.hints == (
            "Retry the export; if it recurs the viewport cannot render this view.",
        )


class TestExportTargetRefusals:
    def test_a_wrong_extension_keeps_the_unknown_format_sentence(self, bound_handler):
        """``export`` infers the format from ``file_path``, so ``obj`` never meets the
        schema enum.  The validator answers with the sentence the deleted raise
        carried, not the one for a call that names nothing."""
        with pytest.raises(addon_hints.Refusal) as raised:
            bound_handler(FakeDesign()).export(file_path="model.obj")

        assert raised.value.error_kind == "INVALID_INPUT"
        assert str(raised.value) == "Unknown format: obj. Expected: stl, step, f3d"
        assert raised.value.hints == (
            "Pass format='stl', 'step' or 'f3d', or a file_path that ends in one "
            "of those.",
        )

    def test_naming_neither_a_format_nor_a_path_is_a_different_sentence(
        self, bound_handler
    ):
        """Nothing was named, so the caller is told what to pass."""
        with pytest.raises(addon_hints.Refusal) as raised:
            bound_handler(FakeDesign()).export()

        assert raised.value.error_kind == "INVALID_INPUT"
        assert str(raised.value) == (
            "Specify format (stl/step/f3d) or file_path with extension"
        )

    def test_an_extension_that_names_a_format_dispatches_to_it(
        self, bound_handler, tmp_path
    ):
        """The inference still reaches the STEP export after the rewrite."""
        design = _design_with(_root_body())
        target = str(tmp_path / "out.step")

        out = bound_handler(design).export(body_name="Body1", file_path=target)

        assert out == {"exported": True, "body": "Body1", "file_path": target}
        assert design.exportManager.executed[0].kind == "step"

    @pytest.mark.parametrize("by_extension", [False, True])
    def test_export_f3d_needs_no_body(self, bound_handler, tmp_path, by_extension):
        """F3D exports the document, so neither route may ask for a body name.

        ``export_body_refusal`` returns None for f3d, so a body check ahead of the
        dispatch raised ``AssertionError`` here - which ``execute_command`` reports as
        ``UNKNOWN``, the failure mode this work removes.
        """
        design = _design_with(_root_body())
        target = str(tmp_path / "out.f3d")

        handler = bound_handler(design)
        out = (
            handler.export(file_path=target)
            if by_extension
            else handler.export(format="f3d", file_path=target)
        )

        assert out == {"exported": True, "file_path": target}
        assert design.exportManager.executed[0].kind == "f3d"


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


class TestRenderViewCapture:
    """The successful capture: the lines after the refusal nothing reached before.

    ``render_view`` writes a tempfile, reads it back and base64-encodes it, and if the
    view was repositioned it restores the camera. Every one of those steps was
    uncovered: both existing tests stop at a refusal, one of them at
    ``saveAsImageFile`` answering false.
    """

    def test_the_capture_returns_the_bytes_it_read_back(self, bound_handler):
        viewport = _Viewport()
        handler = bound_handler(
            FakeDesign(), app=SimpleNamespace(activeViewport=viewport)
        )

        result = handler.render_view(width=320, height=240)

        assert viewport.fitted == 1, "fit is asked for before the capture"
        assert result["view"] == "current"
        assert (result["width"], result["height"]) == (320, 240)
        assert result["image_format"] == "png"
        decoded = base64.b64decode(result["image_base64"])
        assert result["bytes"] == len(decoded)
        # The bytes the fake wrote, verbatim: the tempfile's name is random, so the
        # payload is checked by its fixed head and tail - a re-encode cannot pass.
        assert decoded.startswith(b"PNGfusion_render_")
        assert decoded.endswith(bytes([320 % 256, 240 % 256]))

    def test_the_capture_leaves_no_tempfile_behind(
        self, bound_handler, tmp_path, monkeypatch
    ):
        """``mkstemp`` makes the file; the ``finally`` removes it."""
        made: list[str] = []
        real_mkstemp = tempfile.mkstemp

        def recording_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, dir=tmp_path, **kwargs)
            made.append(path)
            return fd, path

        monkeypatch.setattr(tempfile, "mkstemp", recording_mkstemp)
        viewport = _Viewport()
        bound_handler(
            FakeDesign(), app=SimpleNamespace(activeViewport=viewport)
        ).render_view()

        assert made, "the capture went through a tempfile"
        assert not os.path.exists(made[0]), "and it was removed afterwards"

    def test_a_named_view_repositions_and_restores_the_camera(self, bound_handler):
        """``view="iso"`` moves the camera, and the finally puts the caller's back."""
        camera = _FakeCamera(
            eye=(5.0, 5.0, 5.0), target=(1.0, 2.0, 3.0), up=(0.0, 0.0, 1.0)
        )
        camera.cameraType = PERSPECTIVE_CAMERA_TYPE
        before = camera.state()
        viewport = _Viewport(camera=camera)
        handler = bound_handler(
            FakeDesign(), app=SimpleNamespace(activeViewport=viewport)
        )

        result = handler.render_view(view="iso")

        assert result["view"] == "iso"
        assert viewport.eyes_at_capture[0] != before[0], "iso actually moved the camera"
        # The *stored* camera, not the object this test built: Fusion hands out copies,
        # so after the first assignment the stored one is a different object, and
        # comparing the original with its own snapshot would pass over any restore.
        assert viewport.camera.state() == before, "the caller's view is what comes back"
        assert viewport.camera_writes == 2, "moved once, restored once"
        assert viewport.refreshed >= 1, "the restore refreshes the viewport"

    def test_dimensions_are_clamped_to_a_renderable_range(self, bound_handler):
        """An oversized capture would stall the main thread; the clamp is the guard."""
        viewport = _Viewport()
        handler = bound_handler(
            FakeDesign(), app=SimpleNamespace(activeViewport=viewport)
        )

        small = handler.render_view(width=1, height=1)
        large = handler.render_view(width=99999, height=99999)

        assert (small["width"], small["height"]) == (16, 16)
        assert (large["width"], large["height"]) == (4096, 4096)
        # The echo is built from the clamped locals, so what was *captured* is the
        # assertion that a clamp applied only to the reply would fail.
        assert viewport.captures[0][1:] == (16, 16)
        assert viewport.captures[1][1:] == (4096, 4096)


class _ImportingMeshBodies:
    """``MeshBodies`` with the current ``add``, which answers a ``MeshBodyList``.

    ``count``/``item(i)``, not a Python list: the handler reads those two, and a list
    would break it in a way no fake should model as normal.

    The handler tries ``add`` first and falls back to ``addByFile`` on
    ``AttributeError``, so a fake with both would never exercise the fallback and one
    with only the legacy method would never exercise the current path.
    """

    def __init__(self, mesh_count: int = 1):
        self.calls: list[tuple[str, object]] = []
        self._mesh_count = mesh_count

    def add(self, path, units):
        self.calls.append((path, units))
        body = FakeBody(
            name="Mesh1",
            # Not the fake's default 0..1 box: `size` and `maxPoint` coincide there, so
            # an assertion on size alone could not tell the two apart.
            bounding_box=FakeBoundingBox((-1.0, -2.0, -3.0), (2.0, 4.0, 6.0)),
        )
        return SimpleNamespace(count=self._mesh_count, item=lambda index: body)


class _LegacyMeshBodies:
    """A build without ``MeshBodies.add``: the handler's ``AttributeError`` fallback.

    A separate class, because ``del instance.add`` does not hide a method - the class
    still answers the lookup, so the fallback would never run.
    """

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def addByFile(self, path, units):
        self.calls.append((path, units))
        return FakeBody(name="Mesh1")


class TestImportMeshSuccess:
    """The path a caller with a real file takes: import, then describe."""

    def test_a_imported_mesh_body_is_reported(self, bound_handler, tmp_path):
        source = tmp_path / "part.stl"
        source.write_bytes(b"solid part")
        design = FakeDesign()
        bodies = _ImportingMeshBodies()
        design.rootComponent.meshBodies = bodies

        result = bound_handler(design).import_mesh(str(source))

        assert result["imported"] is True
        assert result["file_path"] == str(source)
        assert result["mesh_name"] == "Mesh1"
        assert result["component"] == design.rootComponent.name
        assert result["units"] == "mm"
        assert result["bounding_box"]["min"] == [-1.0, -2.0, -3.0]
        assert result["bounding_box"]["max"] == [2.0, 4.0, 6.0]
        assert result["bounding_box"]["size"] == [3.0, 6.0, 9.0]
        assert bodies.calls == [(str(source), adsk.fusion.MeshUnits.MillimeterMeshUnit)]

    def test_the_units_argument_reaches_fusions_enum(self, bound_handler, tmp_path):
        source = tmp_path / "part.stl"
        source.write_bytes(b"solid part")
        design = FakeDesign()
        bodies = _ImportingMeshBodies()
        design.rootComponent.meshBodies = bodies

        bound_handler(design).import_mesh(str(source), units="in")

        assert bodies.calls == [(str(source), adsk.fusion.MeshUnits.InchMeshUnit)]

    def test_the_legacy_import_path_still_imports(self, bound_handler, tmp_path):
        """A build without ``MeshBodies.add`` takes ``addByFile``."""
        source = tmp_path / "part.stl"
        source.write_bytes(b"solid part")
        design = FakeDesign()
        bodies = _LegacyMeshBodies()
        design.rootComponent.meshBodies = bodies

        result = bound_handler(design).import_mesh(str(source))

        assert result["mesh_name"] == "Mesh1"
        assert bodies.calls == [(str(source), adsk.fusion.MeshUnits.MillimeterMeshUnit)]


class TestExportDispatch:
    def test_export_dispatches_stl_to_the_body_export(self, bound_handler, tmp_path):
        """``export`` infers the format from the extension and hands stl on.

        Every existing ``export`` test names step or f3d, so this branch was
        unreachable from the suite while the two it calls were covered.
        """
        body = _root_body()
        design = _design_with(body)
        target = tmp_path / "part.stl"

        result = bound_handler(design).export(body_name="Body1", file_path=str(target))

        assert result["exported"] is True
        assert result["body"] == "Body1"
        assert result["file_path"] == str(target)
        executed = design.exportManager.executed
        assert executed[-1].kind == "stl", "the stl options, not step's"


class TestExportViewSheet:
    """The sheet's whole body: four PNGs, the HTML with them embedded, and the manifest.

    None of it had ever run - not one of the lines from `_scene_center_and_radius`
    through the manifest write. The viewport captures into the sheet's own directory,
    which is what makes the PNG files assertable.
    """

    def test_the_sheet_writes_the_images_the_html_and_the_manifest(
        self, bound_handler, tmp_path
    ):
        body = _root_body()
        design = _design_with(body)
        viewport = _Viewport()
        handler = bound_handler(design, app=SimpleNamespace(activeViewport=viewport))

        result = handler.export_view_sheet(
            title="Bracket & <Plate>",
            notes="check the bore & <gap>\nthen ship",
            views=["iso", "front"],
            image_size=[400, 300],
            output_dir=str(tmp_path),
        )

        assert result["html_path"] == os.path.join(str(tmp_path), "view_sheet.html")
        assert result["title"] == "Bracket & <Plate>"
        assert result["image_size"] == [400, 300]
        assert [view["view"] for view in result["views"]] == ["iso", "front"]
        for view in result["views"]:
            assert os.path.exists(view["path"]), view
            assert view["path"].endswith(f"{view['view']}.png")
        assert [capture[1:] for capture in viewport.captures] == [
            (400, 300),
            (400, 300),
        ]

        html = (tmp_path / "view_sheet.html").read_text(encoding="utf-8")
        assert html.count("<figure>") == 2, "one figure per view"
        # Each view's own bytes, once: a count is what notices a second figure that
        # embedded the first view's payload - both used to be identical.
        for name in ("iso.png", "front.png"):
            payload = base64.b64encode(
                b"PNG" + name.encode("ascii") + bytes([400 % 256, 300 % 256])
            ).decode("ascii")
            assert html.count(f"data:image/png;base64,{payload}") == 1, name
        # `html.escape(sheet_title)` runs twice - the <title> and the <h1> - so a count
        # is what notices either one being dropped.
        assert html.count("&lt;Plate&gt;") == 2, "the title is escaped in both places"
        assert "&amp;" in html
        # Markup in the notes, because text without `&`/`<`/`>` cannot show that
        # `html.escape` ran: the unescaped string is in the page either way.
        assert "check the bore &amp; &lt;gap&gt;\nthen ship" in html, (
            "the notes are escaped and keep their newline"
        )
        assert "<gap>" not in html, "no raw markup survives"
        assert "ISO" in html and "FRONT" in html, "the labels are the view names"

        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["title"] == "Bracket & <Plate>"
        assert manifest["views"] == result["views"]
        assert manifest["image_size"] == [400, 300]
        assert manifest["html_path"] == result["html_path"]
        assert manifest["document"] == design.parentDocument.name

    def test_an_empty_views_list_falls_back_to_the_defaults(
        self, bound_handler, tmp_path
    ):
        """``views=[]`` is falsy, so the defaults apply - the documented behaviour."""
        design = _design_with(_root_body())
        handler = bound_handler(design, app=SimpleNamespace(activeViewport=_Viewport()))

        result = handler.export_view_sheet(views=[], output_dir=str(tmp_path))

        assert [view["view"] for view in result["views"]] == [
            "iso",
            "front",
            "top",
            "right",
        ]

    def test_the_camera_the_user_had_is_put_back(self, bound_handler, tmp_path):
        """Two views, two camera moves, and the caller's own view at the end."""
        camera = _FakeCamera(eye=(7.0, 8.0, 9.0), target=(1.0, 1.0, 1.0))
        camera.cameraType = PERSPECTIVE_CAMERA_TYPE
        before = camera.state()
        viewport = _Viewport(camera=camera)
        handler = bound_handler(
            _design_with(_root_body()), app=SimpleNamespace(activeViewport=viewport)
        )

        handler.export_view_sheet(views=["iso", "top"], output_dir=str(tmp_path))

        assert viewport.camera.state() == before
        assert viewport.camera_writes == 3, "two moves and one restore"
        # The body's box is 0..1, so the frame is centred on (0.5, 0.5, 0.5) at radius 1
        # and the iso eye sits 3 cm out - the visible-body branch, not the fallback.
        assert viewport.eyes_at_capture[0] == pytest.approx(
            (2.232, -1.232, 2.232), abs=1e-3
        )
        assert [eye != before[0] for eye in viewport.eyes_at_capture] == [True, True]
        # Each view writes its own up vector, which the restore then overwrites: a
        # transposed up column in _VIEW_DIRS shows here and nowhere else.
        assert viewport.ups_at_capture == [(0.0, 0.0, 1.0), (0.0, 1.0, 0.0)]
        # Orthographic at every capture: the caller's camera is perspective here, so a
        # dropped ``cam.cameraType = …`` in _apply_view would leave perspective frames.
        assert viewport.types_at_capture == [
            ORTHOGRAPHIC_CAMERA_TYPE,
            ORTHOGRAPHIC_CAMERA_TYPE,
        ]
        assert viewport.fit_view_at_capture == [True, True], (
            "_apply_view asks for a fit"
        )
        # Aimed at the body's box centre, the same point for both views.
        assert viewport.targets_at_capture == [(0.5, 0.5, 0.5), (0.5, 0.5, 0.5)]
        # One refresh per view from _apply_view, one more from the restore: the bare
        # ``>= 1`` a refusal test can use would be satisfied by the restore alone.
        assert viewport.refreshed == 3

    def test_a_document_with_no_visible_body_frames_the_origin(
        self, bound_handler, tmp_path
    ):
        """``_scene_center_and_radius`` has a no-body answer: the origin, radius 10."""
        design = FakeDesign(features=0)
        viewport = _Viewport()
        handler = bound_handler(design, app=SimpleNamespace(activeViewport=viewport))

        result = handler.export_view_sheet(views=["iso"], output_dir=str(tmp_path))

        assert result["views"][0]["view"] == "iso"
        # No visible body, so the frame is taken from the origin at radius 10 and the
        # eye sits 3x that away when the frame is captured - the only moment it holds,
        # since the sheet restores the caller's view afterwards.
        eye = viewport.eyes_at_capture[0]
        distance = math.sqrt(sum(coordinate * coordinate for coordinate in eye))
        assert distance == pytest.approx(30.0)
        assert viewport.targets_at_capture == [(0.0, 0.0, 0.0)], (
            "the origin is the centre"
        )


class TestTheTwoDefaultPaths:
    """The two branches that decide a path when the caller names none.

    Both were unreached: every sheet test passes ``output_dir`` and every f3d test
    passes ``file_path``, while the stl and step twins are pinned. The defaults here are
    a timestamped Desktop folder and ``<doc>.f3d``, so the home directory is patched.
    """

    def test_a_sheet_with_no_output_dir_lands_in_a_timestamped_desktop_folder(
        self, bound_handler, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        viewport = _Viewport()
        handler = bound_handler(
            _design_with(_root_body()), app=SimpleNamespace(activeViewport=viewport)
        )

        result = handler.export_view_sheet(views=["iso"])

        expected_folder = tmp_path / "Desktop"
        assert os.path.dirname(result["output_dir"]) == str(expected_folder)
        assert os.path.basename(result["output_dir"]).startswith(
            f"{_design_with(_root_body()).parentDocument.name}_views_"
        )
        assert os.path.exists(result["html_path"])

    def test_f3d_with_no_path_lands_on_the_desktop_named_after_the_document(
        self, bound_handler, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        design = _design_with(_root_body())

        result = bound_handler(design).export_f3d()

        assert result["file_path"] == os.path.join(
            str(tmp_path), "Desktop", f"{design.parentDocument.name}.f3d"
        )
        assert design.exportManager.executed[-1].kind == "f3d"
