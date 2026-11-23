"""CAM refusals: the workspace, a rejected strategy, and the post-processor lookup.

``cam_post_process`` resolved a short post name and a full ``.cps`` path in one
block, so the ``INVALID_INPUT`` for a path that is not there was only reachable with
a CAM ``Product``.  ``_resolve_post`` is that block, and the tests below drive it
directly; the others replace ``_get_cam`` with a stub product or a product-less
``CommandHandler``.

The stubs are the smallest shape each method reads, not a model of the CAM tree:
``_find_setup`` wants ``setups.count``/``item(i)``, and a rejected strategy is
``operations.add`` answering ``None``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from addon.server import fusion_api as adsk
from addon.server import hints as addon_hints
from tests.fakes.cam import (
    FakeCAMProduct,
    FakeCompletedFlagFuture,
    FakeCounterFuture,
    FakeGenerationFailureFuture,
    FakeGenerationFlagFuture,
    FakeNeverStartedFuture,
    FakeNoFlagFuture,
    FakeNotStartedCounterFuture,
    FakeNotStartedFuture,
    FakePostProcessInput,
)


def _items(*items):
    """A Fusion collection: ``count`` and ``item(i)``."""
    return SimpleNamespace(count=len(items), item=lambda index: items[index])


def _setup(name: str = "Setup1", operation=None) -> SimpleNamespace:
    """A setup whose ``operations.add`` answers *operation*; ``None`` is rejected."""
    return SimpleNamespace(
        name=name,
        isValid=True,
        operations=SimpleNamespace(
            count=0,
            createInput=lambda _strategy: SimpleNamespace(name=None),
            add=lambda _input: operation,
        ),
    )


def _cam(*setups, generic_post=None) -> SimpleNamespace:
    return SimpleNamespace(setups=_items(*setups), genericPostFolder=generic_post)


def _handler(handler_module):
    """A handler with no ``__init__``: these methods read no dispatch table."""
    return handler_module.CommandHandler.__new__(handler_module.CommandHandler)


def _no_cam_product(_product_type: str):
    """``products.itemByProductType``: Fusion raises when the product is absent."""
    raise RuntimeError("no CAM product")


def test_no_manufacture_workspace_is_workspace_unavailable(handler_module):
    """``_get_cam`` activates the workspace on demand; with none, it says so."""
    handler = _handler(handler_module)
    handler.app = SimpleNamespace(
        activeDocument=SimpleNamespace(
            products=SimpleNamespace(itemByProductType=_no_cam_product)
        )
    )
    handler.ui = SimpleNamespace(workspaces=SimpleNamespace(itemById=lambda _id: None))

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_list_setups()

    assert raised.value.error_kind == "WORKSPACE_UNAVAILABLE"
    assert str(raised.value) == (
        "No CAM workspace found. Open the Manufacturing workspace in Fusion 360 "
        "at least once to initialise it."
    )
    assert raised.value.hints == ("Open the Manufacturing workspace once, then retry.",)


def test_a_rejected_strategy_is_fusion_refused(handler_module):
    """The schema's enum refuses a typo; this is a name Fusion itself rejects."""
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup(operation=None))

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "face")

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert str(raised.value) == "Fusion rejected strategy 'face' for setup 'Setup1'"
    assert raised.value.hints == (
        "Check the strategy name against cam_create_operation's schema.",
    )


def test_a_short_post_name_with_no_local_folder_is_fusion_refused(handler_module):
    """The build has no local posts, so no argument but a full path can work."""
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup(), generic_post=None)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_post_process("Setup1", post_processor="fanuc")

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert str(raised.value) == (
        "This Fusion build has no local generic post folder "
        "(posts are cloud-library based). Pass the full path to "
        "the .cps file in 'post_processor' instead of a short "
        "name."
    )
    assert raised.value.hints == (
        "Pass the full path to a .cps file in post_processor.",
    )


def test_a_missing_post_processor_names_the_path(handler_module):
    """D6: a filesystem path is INVALID_INPUT, and the hints name the path."""
    handler = _handler(handler_module)
    with pytest.raises(addon_hints.Refusal) as caught:
        handler._resolve_post("/nope.cps")
    assert caught.value.error_kind == "INVALID_INPUT"
    assert str(caught.value) == "Post processor not found: /nope.cps"
    assert caught.value.hints == ("Pass a .cps path that exists on this machine.",)


def test_a_post_that_exists_is_returned_as_given_or_resolved(handler_module, tmp_path):
    """The lookup keeps both routes: a full path verbatim, a short name against
    the build's own folder."""
    post = tmp_path / "fanuc.cps"
    post.write_text("", encoding="utf-8")
    handler = _handler(handler_module)
    handler._get_cam = lambda: SimpleNamespace(genericPostFolder=str(tmp_path))

    assert handler._resolve_post(str(post)) == str(post)
    assert handler._resolve_post("fanuc") == str(post)


def _operation(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _readable_operation(name: str) -> SimpleNamespace:
    """The shape ``cam_get_operation_info`` reads, so a regression fails legibly.

    With only ``name`` the old first-match scan would die on ``op.isValid`` - an
    ``AttributeError`` that names a missing attribute instead of the ambiguity the
    test is about.
    """
    return SimpleNamespace(name=name, isValid=True, hasToolpath=False)


def _setup_with_operations(name: str, *operations) -> SimpleNamespace:
    setup = _setup(name)
    setup.operations = _items(*operations)
    return setup


def _generating_handler(handler_module, cam):
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam
    handler._wait_future = lambda _future: None
    return handler


def test_an_operation_name_alone_generates_it_across_setups(handler_module):
    """``operation_name`` is a target on its own, as the schema says it is."""
    operation = _operation("Rough1")
    cam = _cam(_setup("Setup1"), _setup_with_operations("Setup2", operation))
    generated = []
    cam.generateToolpath = generated.append
    handler = _generating_handler(handler_module, cam)

    result = handler.cam_generate_toolpath(operation_name="Rough1")

    assert result == {
        "generated": True,
        "scope": "operation",
        "setup": "Setup2",
        "operation": "Rough1",
    }
    assert generated == [operation]


def test_setup_and_operation_generation_reports_the_setup(handler_module):
    """The narrowed path knows the setup it resolved, so the reply names it too."""
    operation = _operation("Rough1")
    cam = _cam(_setup_with_operations("Setup1", operation))
    generated = []
    cam.generateToolpath = generated.append
    handler = _generating_handler(handler_module, cam)

    result = handler.cam_generate_toolpath(setup_name="Setup1", operation_name="Rough1")

    assert result == {
        "generated": True,
        "scope": "operation",
        "setup": "Setup1",
        "operation": "Rough1",
    }
    assert generated == [operation]


def test_an_unknown_operation_in_a_named_setup_is_name_not_found(handler_module):
    """Narrowing the setup does not change what a missing name earns."""
    cam = _cam(_setup_with_operations("Setup1", _operation("Finishing")))
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(setup_name="Setup1", operation_name="Rough1")

    assert raised.value.error_kind == "NAME_NOT_FOUND"
    assert "Setup1" in str(raised.value)
    assert raised.value.hints == (
        "Call cam_list_setups, then cam_list_operations with a setup_name, "
        "to see the real names.",
    )


def test_a_duplicate_inside_the_named_setup_refuses_instead_of_picking_one(
    handler_module,
):
    """Naming the setup narrows the search, not a duplicate inside it.

    ``setup_name`` plus ``operation_name`` used to go through ``_find_operation``,
    which takes the first operation of that name: given such a pair the call
    generated one of them, reporting a success the other would also have.  The
    fixture is the shape the create path could leave behind - Fusion *suffixes* a
    rename that would duplicate a name inside a setup (measured: ``Face11`` renamed
    to ``Face10`` became ``Face101``), so a rename cannot produce this pair.
    """
    cam = _cam(
        _setup_with_operations("Setup6", _operation("Face6"), _operation("Face6"))
    )
    generated = []
    cam.generateToolpath = generated.append
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(setup_name="Setup6", operation_name="Face6")

    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == "Setup 'Setup6' holds 2 operations named 'Face6'"
    assert raised.value.hints == (
        "There is no CAM rename tool; rename all but one with execute_code "
        "(operation.name = ...) so the name selects it.",
    )
    assert generated == []


def test_an_unknown_operation_name_is_name_not_found(handler_module):
    """No setup holds it, and the hint names the list that would."""
    cam = _cam(_setup_with_operations("Setup1", _operation("Finishing")))
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    assert raised.value.error_kind == "NAME_NOT_FOUND"
    assert "'Rough1'" in str(raised.value)
    assert any("cam_list_operations" in hint for hint in raised.value.hints)


def test_a_name_held_twice_in_every_setup_does_not_advise_setup_name(handler_module):
    """``setup_name`` is only advice when narrowing to one setup can resolve it.

    Two matches in Setup1 *and* two in Setup2 make the generic "pass setup_name"
    hint a round trip into the narrowed refusal, which refuses for the same reason.
    """
    cam = _cam(
        _setup_with_operations("Setup1", _operation("Rough1"), _operation("Rough1")),
        _setup_with_operations("Setup2", _operation("Rough1"), _operation("Rough1")),
    )
    generated = []
    cam.generateToolpath = generated.append
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    assert raised.value.error_kind == "INVALID_INPUT"
    assert "Setup1" in str(raised.value) and "Setup2" in str(raised.value)
    assert not any("setup_name" in hint for hint in raised.value.hints)
    assert generated == []


def test_a_partial_duplicate_advises_only_the_setup_that_can_resolve_it(
    handler_module,
):
    """One in Setup1 and two in Setup2: ``setup_name="Setup1"`` does resolve it.

    The generic advice is still the right advice here, but only for a setup holding
    one match - so the hint names that setup and says why the other cannot help.
    """
    cam = _cam(
        _setup_with_operations("Setup1", _operation("Rough1")),
        _setup_with_operations("Setup2", _operation("Rough1"), _operation("Rough1")),
    )
    generated = []
    cam.generateToolpath = generated.append
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    pointing = [hint for hint in raised.value.hints if "setup_name" in hint]
    assert pointing, "Setup1 holds exactly one, so narrowing to it resolves the name"
    assert "'Setup1'" in pointing[0]
    assert "it holds one match" in pointing[0]
    assert "'Setup2'" in pointing[0] and "more than one" in pointing[0]
    assert generated == []


def test_the_hint_stays_readable_when_several_setups_can_resolve_it(
    handler_module,
):
    """Two resolvable setups and one ambiguous: the sentence has to stay grammatical.

    ``'S1', 'S2' holds one of them`` is what a comma-join with a fixed verb produces;
    a hint is advice, and advice a caller has to parse twice is worse than the round
    trip it was meant to save.
    """
    cam = _cam(
        _setup_with_operations("Setup1", _operation("Rough1"), _operation("Rough1")),
        _setup_with_operations("Setup2", _operation("Rough1")),
        _setup_with_operations("Setup3", _operation("Rough1")),
    )
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    pointing = [hint for hint in raised.value.hints if "setup_name" in hint]
    assert pointing
    assert "'Setup2' and 'Setup3'" in pointing[0]
    assert "they hold one match each" in pointing[0]
    assert "'Setup1' holds more than one" in pointing[0]


def test_the_hint_joins_three_names_with_a_comma_and_an_and(handler_module):
    """Three resolvable setups: ``'A', 'B' and 'C'``, not a bare comma list."""
    cam = _cam(
        _setup_with_operations("Setup1", _operation("Rough1"), _operation("Rough1")),
        _setup_with_operations("Setup2", _operation("Rough1")),
        _setup_with_operations("Setup3", _operation("Rough1")),
        _setup_with_operations("Setup4", _operation("Rough1")),
    )
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    pointing = [hint for hint in raised.value.hints if "setup_name" in hint]
    assert "'Setup2', 'Setup3' and 'Setup4'" in pointing[0]


def test_an_operation_name_in_two_setups_names_both(handler_module):
    """A shared name is ambiguous, so the refusal says which setups hold it."""
    cam = _cam(
        _setup_with_operations("Setup1", _operation("Rough1")),
        _setup_with_operations("Setup2", _operation("Rough1")),
    )
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    assert raised.value.error_kind == "INVALID_INPUT"
    message = str(raised.value)
    assert "Setup1" in message and "Setup2" in message
    assert any("setup_name" in hint for hint in raised.value.hints)


def test_a_name_held_twice_in_one_setup_refuses_instead_of_picking_one(
    handler_module,
):
    """The ambiguity one setup can hold, which narrowing to it cannot resolve.

    A rename is suffixed rather than allowed to duplicate a name inside its setup,
    so this pair is a shape the create path could leave behind and no measurement
    rules out.  The old scan took the first match per setup, so this ambiguity
    looked like a single match and the first operation was generated silently.
    """
    first = _operation("Rough1")
    second = _operation("Rough1")
    cam = _cam(_setup_with_operations("Setup1", first, second), _setup("Setup2"))
    generated = []
    cam.generateToolpath = generated.append
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(operation_name="Rough1")

    assert raised.value.error_kind == "INVALID_INPUT"
    assert "Setup1" in str(raised.value)
    # One setup holds both, so narrowing to it cannot tell them apart.
    assert raised.value.hints == (
        "There is no CAM rename tool; rename the duplicates with "
        "execute_code (operation.name = ...) so the name selects one.",
    )
    assert generated == []


@pytest.mark.parametrize(
    "future_factory",
    [FakeGenerationFlagFuture, FakeCompletedFlagFuture, FakeCounterFuture],
    ids=["isGenerationCompleted", "isCompleted", "counters"],
)
def test_wait_future_polls_the_completion_field_the_future_has(
    handler_module, future_factory
):
    """Each shape completes by polling; a read of an absent field would raise."""
    future = future_factory()

    handler_module.CommandHandler._wait_future(future, timeout=0.01)

    assert future._reads >= 2


def test_wait_future_times_out_when_the_completion_flag_never_flips(handler_module):
    future = FakeGenerationFlagFuture(completed_after=None)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(future, timeout=0.01)

    assert raised.value.error_kind == "TIMEOUT"
    assert str(raised.value) == (
        "Toolpath generation did not finish within 0.01s. The operation may still "
        "complete in the background — check with cam_list_operations before "
        "regenerating."
    )


def test_wait_future_refuses_a_future_with_no_completion_field(handler_module):
    """No flag means nothing was verified, so the caller gets a typed refusal."""
    future = FakeNoFlagFuture()

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(future, timeout=0.01)

    assert raised.value.error_kind == "INTERNAL_ERROR"
    assert "FakeNoFlagFuture" in str(raised.value)
    assert any("cam_list_operations" in hint for hint in raised.value.hints)


def test_wait_future_polls_through_a_not_started_flag(handler_module):
    """The flag raises until generation begins; that is present-and-not-done."""
    future = FakeNotStartedFuture(starts_after=3)

    handler_module.CommandHandler._wait_future(future, timeout=0.01)

    assert future._reads >= 3


def test_wait_future_times_out_when_generation_never_starts(handler_module):
    future = FakeNeverStartedFuture()

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(future, timeout=0.01)

    assert raised.value.error_kind == "TIMEOUT"
    assert str(raised.value) == (
        "Toolpath generation did not finish within 0.01s. The operation may still "
        "complete in the background — check with cam_list_operations before "
        "regenerating."
    )
    assert raised.value.hints == (
        "The wait is the add-in's own bound (25 s), not the bridge's 30 s timeout.",
        "cam_list_operations reports whether the toolpath finished in the background.",
    )


def test_wait_future_lets_an_unrelated_runtime_error_out(handler_module):
    """Only "Generation not started" is tolerated; a real failure is Fusion's.

    Re-raising it is only half the answer: the handler classifies what the wait
    raises, so the message has to reach the caller with a kind and advice rather
    than ``UNKNOWN`` with none.
    """
    future = FakeGenerationFailureFuture()

    with pytest.raises(RuntimeError, match="3 : generation failed") as raised:
        handler_module.CommandHandler._wait_future(future, timeout=0.01)

    kind, hints = addon_hints.classify(str(raised.value))
    assert kind == "FUSION_REFUSED"
    assert any("cam_list_operations" in hint for hint in hints)


def test_wait_future_polls_through_not_started_counters(handler_module):
    """The counter pair gets the same tolerant read as the boolean flag."""
    future = FakeNotStartedCounterFuture()

    handler_module.CommandHandler._wait_future(future, timeout=0.01)

    assert future._reads >= 2


def test_operation_only_generation_reaches_generate_toolpath(handler_module):
    """The operation-only scope runs the real wait and reports what it generated."""
    operation = _operation("Rough1")
    setup = _setup_with_operations("Setup1", operation)
    cam = FakeCAMProduct([setup], FakeGenerationFlagFuture(completed_after=1))
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam

    result = handler.cam_generate_toolpath(operation_name="Rough1")

    assert result == {
        "generated": True,
        "scope": "operation",
        "setup": "Setup1",
        "operation": "Rough1",
    }
    assert cam.generated == [operation]


def test_post_process_refuses_a_name_held_twice_instead_of_posting_the_first(
    handler_module, tmp_path
):
    """G-code for the wrong operation is worse than a refusal.

    ``_find_operation`` took the first match, so a setup holding two operations of
    one name posted the first of them and reported success for a call that named
    neither in particular.
    """
    cam = _cam(
        _setup_with_operations("Setup1", _operation("Rough1"), _operation("Rough1")),
        generic_post=str(tmp_path),
    )
    posted = []
    cam.postProcess = lambda *args: posted.append(args)
    handler = _generating_handler(handler_module, cam)
    handler._resolve_post = lambda _name: str(tmp_path / "fanuc.cps")

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_post_process(
            "Setup1", operation_name="Rough1", output_folder=str(tmp_path)
        )

    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == "Setup 'Setup1' holds 2 operations named 'Rough1'"
    assert raised.value.hints == (
        "There is no CAM rename tool; rename all but one with execute_code "
        "(operation.name = ...) so the name selects it.",
    )
    assert posted == []


def test_operation_info_refuses_a_name_held_twice_instead_of_describing_the_first(
    handler_module,
):
    """The read has the same ambiguity as the write: describe neither, refuse both."""
    cam = _cam(
        _setup_with_operations(
            "Setup1", _readable_operation("Rough1"), _readable_operation("Rough1")
        )
    )
    handler = _generating_handler(handler_module, cam)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_get_operation_info("Setup1", "Rough1")

    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == "Setup 'Setup1' holds 2 operations named 'Rough1'"
    assert raised.value.hints == (
        "There is no CAM rename tool; rename all but one with execute_code "
        "(operation.name = ...) so the name selects it.",
    )


def test_post_process_hands_the_post_input_the_four_arguments_it_recorded(
    handler_module, tmp_path
):
    """The fake stores the fields so a reordered call is caught, not waved through.

    ``PostProcessInput.create`` takes ``programName``, ``postConfiguration``,
    ``outputFolder`` and ``outputUnits`` in that order; a fake that accepts four
    values of any kind proves the arity and nothing about the order.
    """
    operation = _operation("Rough1")
    cam = _cam(_setup_with_operations("Setup1", operation), generic_post=str(tmp_path))
    posted = []
    cam.postProcess = lambda *args: posted.append(args)
    handler = _generating_handler(handler_module, cam)
    handler._resolve_post = lambda _name: str(tmp_path / "fanuc.cps")

    handler.cam_post_process(
        "Setup1", operation_name="Rough1", output_folder=str(tmp_path)
    )

    assert len(posted) == 1
    posted_operation, post_input = posted[0]
    assert posted_operation is operation
    assert post_input.programName == "Setup1"
    assert post_input.postConfiguration == str(tmp_path / "fanuc.cps")
    assert post_input.outputFolder == str(tmp_path)
    assert post_input.isOpenInEditor is False
    # ``2`` is what Fusion 2706.1.17 answers for ``MillimetersOutput``.  The fake's
    # members are plain ints, so these two assertions pass for a bare ``2`` as well as
    # for the member - they pin the value, not the identity.
    assert post_input.outputUnits == adsk.cam.PostOutputUnitOptions.MillimetersOutput
    assert post_input.outputUnits == 2


def test_operation_info_describes_the_one_operation_named(handler_module):
    """The read path has only ever been exercised on its refusal.

    ``_readable_operation`` exists so a regression fails legibly; this is the test that
    makes it describe something, and the cheapest coverage ``handler_cam`` has left.
    """
    operation = SimpleNamespace(
        name="Rough1",
        isValid=True,
        hasToolpath=True,
        tool=SimpleNamespace(description="6mm flat end mill"),
        parameters=[
            SimpleNamespace(name="stepdown", expression="2 mm"),
            SimpleNamespace(name="tool_feedCutting", expression="600 mm/min"),
        ],
    )
    cam = _cam(_setup_with_operations("Setup1", operation))
    handler = _generating_handler(handler_module, cam)

    info = handler.cam_get_operation_info("Setup1", "Rough1")

    assert info == {
        "name": "Rough1",
        "is_valid": True,
        "has_toolpath": True,
        "tool": {"description": "6mm flat end mill"},
        "parameters": {
            "stepdown": "2 mm",
            "tool_feedCutting": "600 mm/min",
        },
    }


def test_operation_info_omits_the_fields_the_operation_does_not_carry(handler_module):
    """The guards' *false* branches are what this test exists for.

    Their true branches run in the positive test; the false ones had no test at all,
    because the refusal tests raise before the dict is built and the positive test's
    operation carries a tool and parameters.  Deleting either guard - or the ``str()``
    conversion - stayed green until these three arms existed.
    """
    bare = _readable_operation("Rough1")
    handler = _generating_handler(
        handler_module, _cam(_setup_with_operations("Setup1", bare))
    )

    assert handler.cam_get_operation_info("Setup1", "Rough1") == {
        "name": "Rough1",
        "is_valid": True,
        "has_toolpath": False,
    }

    # ``Operation.tool`` is null for an operation with no tool, which the guard must
    # drop rather than answer ``{"description": "None"}``.
    tool_less = SimpleNamespace(
        name="Rough1", isValid=False, hasToolpath=False, tool=None, parameters=[]
    )
    handler = _generating_handler(
        handler_module, _cam(_setup_with_operations("Setup1", tool_less))
    )

    info = handler.cam_get_operation_info("Setup1", "Rough1")
    assert "tool" not in info
    assert info["parameters"] == {}, "an empty list is a map, not a missing key"

    # A tool that is not an object still names itself: ``str()`` is what makes it
    # serialisable, and a ``str`` tool would pass with or without the conversion.
    counted = SimpleNamespace(
        name="Rough1", isValid=False, hasToolpath=False, tool=6, parameters=[]
    )
    handler = _generating_handler(
        handler_module, _cam(_setup_with_operations("Setup1", counted))
    )

    assert handler.cam_get_operation_info("Setup1", "Rough1")["tool"] == {
        "description": "6"
    }


def test_the_post_input_fake_refuses_construction_like_fusion_does():
    """The fake's guard is the only thing standing between a handler edit and Fusion.

    Fusion's ``PostProcessInput`` has no constructor - ``create`` is the sole way
    in - so the fake must refuse the same call.  Without this test, deleting the raise
    would let a ``PostProcessInput(a, b, c, d)`` regression pass and die live.
    """
    with pytest.raises(AttributeError, match="No constructor defined"):
        FakePostProcessInput("Setup1", "fanuc.cps", "/tmp", 2)


def _contour_operation(strategy: str = "contour2d", parameter_name: str = "contours"):
    """An operation whose parameter set carries one CAD-contour machining parameter.

    ``stockContours`` is there too, because every strategy has it and the discovery
    must skip it - that is the measured shape: ``contours`` for ``contour2d``,
    ``pockets`` for ``pocket2d``, ``machiningBoundarySel`` for ``adaptive``.
    """
    applied = {}

    class _Selections:
        def __init__(self):
            self.cleared = 0
            self.selectors = []

        def clear(self):
            self.cleared += 1

        def createNewFaceContourSelection(self):
            selection = SimpleNamespace(inputGeometry=None)
            self.selectors.append(selection)
            return selection

    class _Value:
        def __init__(self):
            self.selections = _Selections()

        def getCurveSelections(self):
            return self.selections

        def applyCurveSelections(self, selections):
            applied["selections"] = selections

    value = _Value()
    operation = SimpleNamespace(
        name=None,
        strategy=strategy,
        parameters=[
            # A *second* CAD-contour value, so the ``stockContours`` name check is the
            # only thing that can skip it - a value without the method would let a
            # deleted name check stay green.
            SimpleNamespace(name="stockContours", value=_Value()),
            SimpleNamespace(name=parameter_name, value=value),
        ],
        deleted=0,
    )

    def delete_me():
        operation.deleted += 1
        # Fusion may refuse property reads on a deleted object; modelling that is what
        # makes "read the strategy *before* deleting" a testable order.
        operation.strategy = None
        operation.parameters = None

    operation.deleteMe = delete_me
    return operation, value, applied


def test_a_refused_face_selection_removes_the_operation(handler_module):
    """The parameter is emptied before the selection is applied.

    So a failure there must not leave the operation behind with no geometry.
    """
    operation, value, applied = _contour_operation()

    def refuse(_selections):
        raise RuntimeError("3 : some input argument is invalid")

    value.applyCurveSelections = refuse
    handler = _creation_handler(handler_module, operation, faces=1)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Body1",
            face_indices=[0],
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert "some input argument is invalid" in str(raised.value)
    assert operation.deleted == 1
    assert applied == {}


def test_an_add_in_defect_in_the_seam_keeps_its_own_kind(handler_module):
    """An ``AttributeError`` is our bug, not Fusion refusing: it keeps its kind."""
    operation, value, _applied = _contour_operation()

    def invented(_selections):
        raise AttributeError("'CadContours2dParameterValue' has no attribute 'apply'")

    value.applyCurveSelections = invented
    handler = _creation_handler(handler_module, operation, faces=1)

    with pytest.raises(AttributeError):
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Body1",
            face_indices=[0],
        )

    assert operation.deleted == 0, "an add-in defect is not recovered from by deleting"


def test_create_operation_refuses_an_unknown_body_before_creating_anything(
    handler_module,
):
    """The body is resolved before `add`, so a wrong name writes nothing.

    This is the path review found leaking: resolution ran inside the selection step,
    so every body-name refusal left an operation the caller had to discover.
    """
    operation, _value, applied = _contour_operation()
    created = []
    handler = _creation_handler(handler_module, operation, faces=1, created=created)

    def unknown(_name):
        raise addon_hints.Refusal("NAME_NOT_FOUND", "Body 'Nope' not found")

    handler._body_by_name = unknown

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Nope",
            face_indices=[0],
        )

    assert raised.value.error_kind == "NAME_NOT_FOUND"
    assert created == []
    assert applied == {}


def _creation_handler(handler_module, operation, faces, created=None):
    added: list = [] if created is None else created

    def add(op_input):
        added.append(op_input)
        return operation

    setup = SimpleNamespace(
        name="Setup1",
        operations=SimpleNamespace(
            count=0,
            createInput=lambda _strategy: SimpleNamespace(name=None),
            add=add,
        ),
    )
    handler = _generating_handler(handler_module, _cam(setup))
    handler._body_by_name = lambda name: SimpleNamespace(
        name=name, faces=_items(*[SimpleNamespace() for _ in range(faces)])
    )
    return handler


def test_create_operation_puts_a_face_selection_on_the_strategy_parameter(
    handler_module,
):
    """The geometry seam: one face selection, applied to the parameter Fusion exposes.

    The parameter cannot be named in advance - it differs per strategy and only Fusion
    knows it - so the handler discovers the CAD-contour value that is not the stock
    boundary.  This test pins that discovery, the clear-before-add, and the reply.
    """
    operation, value, applied = _contour_operation()
    handler = _creation_handler(handler_module, operation, faces=3)

    result = handler.cam_create_operation(
        setup_name="Setup1",
        strategy="contour2d",
        body_name="Body1",
        face_indices=[2, 0],
    )

    assert value.selections.cleared == 1
    assert len(value.selections.selectors) == 1
    selection = value.selections.selectors[0]
    faces = handler._body_by_name("Body1").faces
    assert selection.inputGeometry == [faces.item(2), faces.item(0)], (
        "the reply names faces in the order the caller gave them"
    )
    assert applied["selections"] is value.selections
    assert result["geometry"] == {"parameter": "contours", "face_indices": [2, 0]}


def test_create_operation_refuses_a_face_index_the_body_does_not_have(handler_module):
    """An index is judged against the body *before* the operation exists.

    Resolving the body and checking the range inside the selection step left a created
    operation behind on every body-name refusal - the caller retried and the setup held
    two.  Both checks now run first, so nothing is written and nothing needs removing.
    """
    operation, _value, applied = _contour_operation()
    created = []
    handler = _creation_handler(handler_module, operation, faces=2, created=created)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Body1",
            face_indices=[7],
        )

    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == (
        "Face index 7 is out of range for body 'Body1' (2 faces)"
    )
    assert created == [], "the operation was never added"
    assert operation.deleted == 0
    assert applied == {}, "nothing was applied to the parameter"


def test_create_operation_removes_the_operation_when_no_parameter_is_found(
    handler_module,
):
    """The discovery step is a defence: if the measurement moves, nothing is left."""
    operation, _value, _applied = _contour_operation()
    operation.parameters = [SimpleNamespace(name="stockContours", value=object())]
    handler = _creation_handler(handler_module, operation, faces=1)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Body1",
            face_indices=[0],
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert "Strategy 'contour2d'" in str(raised.value), (
        "the strategy has to be read before the operation is deleted"
    )
    assert "the operation was removed again" in str(raised.value)
    assert operation.deleted == 1
