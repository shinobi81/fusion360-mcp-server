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

import json
from types import SimpleNamespace

import pytest

from addon.server import fusion_api as adsk
from addon.server import hints as addon_hints
from addon.server import rules as addon_rules
from addon.server.cam_tool import build_tool_json
from tests.fakes.cam import (
    FakeCAMProduct,
    FakeCompletedFlagFuture,
    FakeCounterFuture,
    FakeDocumentToolLibrary,
    FakeGenerationFailureFuture,
    FakeGenerationFlagFuture,
    FakeLibraryTool,
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


def _cam(*setups, generic_post=None, tool_numbers=()) -> SimpleNamespace:
    """A CAM product: setups, the post folder, and the document tool library.

    The library defaults to empty, so a test that passes ``tool_number`` on its own has
    to say what Fusion's document holds - which is the point, since mock mode declares
    its own list and the two must answer one sentence for the same numbers.
    """
    return SimpleNamespace(
        setups=_items(*setups),
        genericPostFolder=generic_post,
        documentToolLibrary=FakeDocumentToolLibrary(
            [FakeLibraryTool(number) for number in tool_numbers]
        ),
    )


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
    # The generation tests are about the target, not the wait; the wait takes the
    # operations it attributes an error to, so the stand-in accepts them.
    handler._wait_future = lambda _future, **_kwargs: None
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

    def refuse(selections):
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
    assert "strategy 'contour2d'" in str(raised.value), (
        "the strategy is read before the operation is deleted"
    )
    assert operation.deleted == 1
    assert applied == {}


def test_an_add_in_defect_in_the_seam_is_an_internal_error(handler_module):
    """An invented API is our bug: typed ``INTERNAL_ERROR``, not ``UNKNOWN``.

    Re-raising left the caller with ``UNKNOWN`` and an empty hint list - the exact shape
    #138 removed - and a half-cleared operation in the setup; the generic branch would
    have blamed the caller's faces.  The operation is removed, as in the sibling branch.
    """
    operation, value, _applied = _contour_operation()

    def invented(selections):
        raise AttributeError("'CadContours2dParameterValue' has no attribute 'apply'")

    value.applyCurveSelections = invented
    handler = _creation_handler(handler_module, operation, faces=1)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Body1",
            face_indices=[0],
        )

    assert raised.value.error_kind == "INTERNAL_ERROR"
    assert "does not have" in str(raised.value)
    assert "Strategy 'contour2d'" in str(raised.value), (
        "the strategy is read before the operation is deleted"
    )
    assert "The operation was removed" in str(raised.value)
    assert raised.value.hints == (
        "This is an add-in defect, not an input problem.",
        "Read the call against the shipped binding; "
        "`scripts/check_fusion_api.py` covers `adsk.<name>`, not methods.",
    )
    assert addon_hints.classify(raised.value)[0] == "INTERNAL_ERROR"
    assert operation.deleted == 1, "the half-cleared operation is removed"


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


def test_a_face_operation_is_aimed_through_its_stock_contours(handler_module):
    """``face`` has no selection of its own, so the table names its stock boundary.

    Measured on 2706.1.17: ``stockContours`` accepts a ``FaceContourSelection`` and the
    operation regenerates with a toolpath, so the boundary is how a face operation is
    aimed.  The parameter is looked up by the name ``rules.CAM_GEOMETRY_PARAMETERS``
    records rather than by the old "not the stock boundary" discovery, which finds
    nothing on a strategy whose only contour value *is* the stock boundary.
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
        strategy="face",
        parameters=[SimpleNamespace(name="stockContours", value=value)],
        deleted=0,
    )
    operation.deleteMe = lambda: None
    handler = _creation_handler(handler_module, operation, faces=2)

    result = handler.cam_create_operation(
        setup_name="Setup1",
        strategy="face",
        body_name="Body1",
        face_indices=[1],
    )

    assert value.selections.cleared == 1
    assert len(value.selections.selectors) == 1
    selection = value.selections.selectors[0]
    faces = handler._body_by_name("Body1").faces
    assert selection.inputGeometry == [faces.item(1)], (
        "the faces the caller named, not the whole body"
    )
    assert applied["selections"] is value.selections
    assert result["geometry"] == {
        "parameter": "stockContours",
        "face_indices": [1],
    }


def test_a_table_name_holding_a_plain_parameter_falls_through_to_discovery(
    handler_module,
):
    """The mapped name is only used when its value can take a selection.

    A build that exposes ``contours`` as a plain parameter must fall through to the
    discovery, not raise out of ``getCurveSelections`` and be reported as an add-in
    defect with the operation removed.
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

    discovery = _Value()
    operation = SimpleNamespace(
        name=None,
        strategy="contour2d",
        parameters=[
            SimpleNamespace(name="stockContours", value=_Value()),
            # The table's name, holding a value with no selection API.
            SimpleNamespace(name="contours", value=object()),
            SimpleNamespace(name="contours2d", value=discovery),
        ],
        deleted=0,
    )
    operation.deleteMe = lambda: None
    handler = _creation_handler(handler_module, operation, faces=2)

    result = handler.cam_create_operation(
        setup_name="Setup1",
        strategy="contour2d",
        body_name="Body1",
        face_indices=[0],
    )

    assert applied["selections"] is discovery.selections
    assert result["geometry"]["parameter"] == "contours2d"
    assert operation.deleted == 0, "the fallback found a parameter; nothing to remove"


def test_a_build_that_spells_the_parameter_differently_falls_back(handler_module):
    """The table names what was measured here; a build that spells it otherwise still
    works through the old discovery - which is why it was kept."""
    operation, value, applied = _contour_operation(parameter_name="contours2d")
    handler = _creation_handler(handler_module, operation, faces=2)

    result = handler.cam_create_operation(
        setup_name="Setup1",
        strategy="contour2d",
        body_name="Body1",
        face_indices=[0],
    )

    assert applied["selections"] is value.selections
    assert result["geometry"]["parameter"] == "contours2d"


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


# ── a CAM operation's tool ───────────────────────────────────────────────────
# Measured on Fusion 2706.1.17: an operation with no tool cannot generate
# (``"Toolpath requires tool to be selected."``), ``Tool.createFromJson`` accepts a
# complete tool object, and assigning the result to ``Operation.tool`` registers it
# in the document library. These tests cover the add-in's side of that seam.


def _tool_op(name: str = "Op1", accepted=None):
    """The operation shape the create path writes into: a name and a tool slot.

    ``deleteMe`` is there because a tool refusal removes the operation again - the
    same promise the geometry seam keeps, so a retry cannot leave a second one behind.
    """
    # A real operation takes parameters, so this one does too: a `None` for every name
    # made `_set_cam_parameter` fail for all of them, and the reply then looked nothing
    # like Fusion's. *accepted* is the set of names this strategy exposes - a name
    # outside it answers `None`, which is what Fusion does and what sends the handler
    # down its ``parameters_failed`` path.
    written: dict = {}

    def item_by_name(parameter_name):
        if accepted is not None and parameter_name not in accepted:
            return None
        return written.setdefault(parameter_name, SimpleNamespace(expression=None))

    operation = SimpleNamespace(
        name=name,
        parameters=SimpleNamespace(itemByName=item_by_name),
        written=written,
        deleted=0,
    )
    operation.deleteMe = lambda: setattr(operation, "deleted", operation.deleted + 1)
    return operation


def _recording_setup(operation):
    """A setup whose ``operations.add`` records that it created anything at all."""
    created = []

    def add(_input):
        created.append(operation)
        return operation

    return (
        SimpleNamespace(
            name="Setup1",
            operations=SimpleNamespace(
                count=0,
                createInput=lambda _strategy: SimpleNamespace(name=None),
                add=add,
            ),
        ),
        created,
    )


def test_a_diameter_attaches_a_tool_the_operation_can_generate_with(handler_module):
    operation = _tool_op()
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))

    result = handler.cam_create_operation(
        "Setup1", "pocket2d", tool_diameter=0.6, coolant=None
    )

    payload = json.loads(operation.tool.json)
    assert payload["unit"] == "millimeters"
    assert payload["geometry"]["DC"] == 6.0
    assert result["tool"] == {
        "description": operation.tool.description,
        "diameter_cm": 0.6,
    }


def test_tool_json_reaches_fusion_verbatim(handler_module):
    """A caller who measured their own tool object is not second-guessed."""
    operation = _tool_op()
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))
    # A complete object, because a partial one crashed Fusion (see cam_tool.py). The
    # shape rule cannot tell the difference - Fusion ships tools with no holder - which
    # is why the builder emits the whole shape rather than the check enforcing it.
    supplied = build_tool_json(tool_diameter=0.6, description="mine")

    result = handler.cam_create_operation(
        "Setup1", "pocket2d", tool_json=supplied, coolant=None
    )

    assert operation.tool.json == supplied
    assert result["tool"] == {"description": operation.tool.description}


def test_a_tool_json_and_a_diameter_together_are_refused_first(handler_module):
    """Two sources for one tool is an ambiguity, and nothing may be created for it."""
    operation = _tool_op()
    setup, created = _recording_setup(operation)
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            "Setup1",
            "pocket2d",
            tool_json='{"type": "flat end mill"}',
            tool_diameter=0.6,
        )

    assert raised.value.error_kind == "INVALID_INPUT"
    assert raised.value.hints
    assert created == []


def test_a_non_numeric_diameter_is_refused_by_name(handler_module):
    """``require_finite`` passes a string through, so this is the last guard."""
    setup, created = _recording_setup(_tool_op())
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "pocket2d", tool_diameter="6mm")

    assert raised.value.error_kind == "INVALID_INPUT"
    assert "tool_diameter" in str(raised.value)
    assert created == []


def test_a_tool_number_selects_a_tool_the_library_holds(handler_module):
    """Measured on 2706.1.17: the library has no by-number lookup, so the handler reads
    each tool's own ``tool_number`` parameter, and ``Operation.tool`` takes the result.

    The reply says where the tool came from and carries no ``diameter_cm``: its
    diameter is the library's, not something this call chose.
    """
    operation = _tool_op()
    setup, created = _recording_setup(operation)
    cam = _cam(setup, tool_numbers=(7, 9))
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam

    result = handler.cam_create_operation("Setup1", "pocket2d", tool_number=9)

    assert operation.tool is cam.documentToolLibrary.item(1)
    assert result["tool"]["number"] == 9
    assert result["tool"]["from_library"] is True
    assert "diameter_cm" not in result["tool"]
    assert created == [operation], "the operation the call created, and only it"


def test_a_tool_number_no_tool_holds_is_name_not_found(handler_module):
    """The sentence names the numbers that would have worked, and nothing is created."""
    setup, created = _recording_setup(_tool_op())
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup, tool_numbers=(7, 9))

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "pocket2d", tool_number=3)

    assert raised.value.error_kind == "NAME_NOT_FOUND"
    assert "No tool numbered 3" in str(raised.value)
    assert "7, 9" in str(raised.value)
    assert created == [], "a miss must not leave an operation behind"


def test_the_scan_reads_a_float_parameter_and_skips_an_unreadable_entry(handler_module):
    """Two shapes a real library holds: Fusion reports some parameters as ``6.``, and
    one corrupt entry must not cost the caller the numbers the others carry."""
    setup, _created = _recording_setup(_tool_op())
    cam = _cam(setup)
    # Out of order, one float-valued (as Fusion reports them) and one unreadable.
    cam.documentToolLibrary = FakeDocumentToolLibrary(
        [
            FakeLibraryTool(9.0),
            FakeLibraryTool(0, unreadable=True),
            FakeLibraryTool(7),
        ]
    )
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "pocket2d", tool_number=3)

    # Sorted, integral, and without the entry that could not be read. `endswith`, not
    # `in`: "7, 9" is a prefix of "7, 9.0", so a substring assertion would pass with the
    # truncation removed - which is the only thing it is here to pin.
    assert str(raised.value).endswith("the numbers it holds are 7, 9")


def test_two_tools_on_one_number_take_the_first_and_list_it_once(handler_module):
    """Two vendor libraries merged really can hold one number twice.

    The first in library order wins - the reply's description is how a caller sees
    which it got - and the sentence lists the number once, because "7, 7" reads like two
    usable tools when there is one number.
    """
    operation = _tool_op()
    setup, _created = _recording_setup(operation)
    first = FakeLibraryTool(7, description="the first seven")
    second = FakeLibraryTool(7, description="the second seven")
    cam = _cam(setup)
    cam.documentToolLibrary = FakeDocumentToolLibrary(
        [first, second, FakeLibraryTool(9)]
    )
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam

    result = handler.cam_create_operation("Setup1", "pocket2d", tool_number=7)

    assert operation.tool is first, "the first in library order, not the last"
    assert result["tool"]["description"] == "the first seven"

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "pocket2d", tool_number=3)

    assert "the numbers it holds are 7, 9" in str(raised.value)


def test_a_missing_tool_number_is_answered_before_a_missing_setup(handler_module):
    """The order mock can follow: it has no setups to look in, so the tool sentence is
    the one both modes answer for a call carrying two faults."""
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(tool_numbers=(7,))

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("NoSuchSetup", "pocket2d", tool_number=3)

    assert "No tool numbered 3" in str(raised.value)


def test_a_missing_tool_number_is_answered_before_a_missing_body(handler_module):
    """The same, one block earlier: a body mock cannot resolve either."""
    handler = _handler(handler_module)
    # Mock's own list, so the two sentences are comparable rather than coincidentally
    # close: the numbers are part of the sentence.
    handler._get_cam = lambda: _cam(tool_numbers=_mock_document_library())

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            "Setup1", "pocket2d", body_name="Nope", face_indices=[0], tool_number=3
        )

    from fusion360_mcp.mock import mock_command

    refused = mock_command(
        "cam_create_operation",
        {
            "setup_name": "Setup1",
            "strategy": "pocket2d",
            "body_name": "Nope",
            "face_indices": [0],
            "tool_number": 3,
        },
    )

    assert "No tool numbered 3" in str(raised.value)
    assert refused["error_message"] == str(raised.value)


@pytest.mark.parametrize(
    "extra",
    [
        # A parameter fault, which the rules answer before the library is consulted.
        {"strategy": "2d_contour"},
        {"strategy": "contour2d", "face_indices": [0]},
    ],
    ids=["unknown strategy", "face_indices without a body name"],
)
def test_a_parameter_fault_outranks_the_library_check_on_both_sides(
    handler_module, extra
):
    """The library check sits below the parameter rules, and neither mode may drift.

    Mock runs the rules before the library, so a handler that resolved the number first
    would answer NAME_NOT_FOUND where mock answers the strategy or geometry sentence -
    the same split round 3 found for the setup and the body.
    """
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(tool_numbers=_mock_document_library())
    params = {"setup_name": "Setup1", "tool_number": 3, **extra}

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(**params)

    from fusion360_mcp.mock import mock_command

    refused = mock_command("cam_create_operation", params)

    assert "tool numbered" not in str(raised.value), "the parameter rule answers first"
    assert refused["error_message"] == str(raised.value)


def test_an_empty_document_library_says_it_is_empty(handler_module):
    """A document with no tool registered: the hint says how to make one."""
    setup, created = _recording_setup(_tool_op())
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "pocket2d", tool_number=1)

    assert "it is empty" in str(raised.value)
    assert any("tool_diameter" in hint for hint in raised.value.hints)
    assert created == []


def _mock_document_library():
    """The numbers mock's fake document holds, so this test cannot drift from it."""
    from fusion360_mcp.mock import DOCUMENT_TOOL_LIBRARY

    return DOCUMENT_TOOL_LIBRARY


def test_mock_and_the_handler_refuse_a_missing_tool_number_alike(handler_module):
    """One number, one list, one sentence - mock declares (1,), so the handler is fed
    the same list rather than a literal."""
    setup, _created = _recording_setup(_tool_op())
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup, tool_numbers=_mock_document_library())

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation("Setup1", "pocket2d", tool_number=3)

    from fusion360_mcp.mock import mock_command

    refused = mock_command(
        "cam_create_operation",
        {"setup_name": "Setup1", "strategy": "pocket2d", "tool_number": 3},
    )

    assert refused["error_kind"] == raised.value.error_kind
    assert refused["error_message"] == str(raised.value)


def test_fusion_refusing_the_tool_object_is_a_refusal(handler_module, monkeypatch):
    """A JSON Fusion will not build is a refusal, never a half-configured operation."""
    operation = _tool_op()
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))

    class RefusingTool:
        @staticmethod
        def createFromJson(_json):
            raise RuntimeError("3 : tool definition is invalid")

    monkeypatch.setattr(adsk.cam, "Tool", RefusingTool)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            "Setup1", "pocket2d", tool_diameter=0.6, coolant=None
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert "tool definition is invalid" in str(raised.value)
    assert operation.deleted == 1, "no refusal leaves a half-built operation"


def test_an_operation_without_a_tool_says_generation_will_fail(handler_module):
    """The operation is still useful: a reply with a warning, not a refusal."""
    operation = _tool_op()
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))

    result = handler.cam_create_operation("Setup1", "pocket2d", coolant=None)

    assert result["tool"] is None
    assert "requires tool to be selected" in result["tool_warning"]
    assert "tool_diameter" in result["tool_warning"]


def test_wait_future_reports_the_operations_error_instead_of_waiting_the_bound(
    handler_module,
):
    """An operation Fusion refuses fails *at once*: the bound must not hide the cause.

    Measured on 2706.1.17: a generation with no tool sets ``hasError`` and a message
    ("Toolpath requires tool to be selected.") while the future never completes, so
    the 25 s bound reported ``TIMEOUT`` for a failure Fusion had already named.
    """
    operation = SimpleNamespace(
        hasError=True, error="Toolpath requires tool to be selected.\n"
    )

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(
            FakeNeverStartedFuture(), timeout=5.0, operations=[operation]
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert str(raised.value) == "Toolpath requires tool to be selected."


def test_wait_future_reports_an_inherited_error_when_the_bound_expires(
    handler_module,
):
    """The retry case: an operation that failed *last* time must generate this time.

    ``hasError`` keeps the previous attempt's sentence until this attempt rewrites it,
    and a refused future answers "Generation not started" for ever - so both cases look
    identical from inside the wait. The baseline taken *before* generating separates
    them: an inherited sentence is not reported as this call's failure, and it is not
    discarded either - when the bound expires it is reported *as inherited*, because a
    retry that fails the same way produces the same sentence.
    """
    stale = SimpleNamespace(
        hasError=True, error="Toolpath requires tool to be selected.\n"
    )
    handler = handler_module.CommandHandler

    with pytest.raises(addon_hints.Refusal) as raised:
        handler._wait_future(
            FakeNeverStartedFuture(),
            timeout=0.01,
            operations=[stale],
            prior_errors=handler._operation_errors([stale]),
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert "Toolpath requires tool to be selected." in str(raised.value)
    assert "recorded this before the call" in str(raised.value)


def test_wait_future_still_times_out_for_a_clean_operation(handler_module):
    """Only a reported error short-circuits; a healthy operation waits the bound."""
    operation = SimpleNamespace(hasError=False, error="")

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(
            FakeGenerationFlagFuture(completed_after=None),
            timeout=0.01,
            operations=[operation],
        )

    assert raised.value.error_kind == "TIMEOUT"


def test_wait_future_names_the_operation_its_error_belongs_to(handler_module):
    """``generate_all`` has no target: a nameless sentence names nothing."""
    operation = SimpleNamespace(
        name="Rough1", hasError=True, error="Toolpath requires tool to be selected.\n"
    )

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(
            FakeGenerationFlagFuture(completed_after=None),
            timeout=5.0,
            operations=[operation],
        )

    assert str(raised.value) == (
        "Operation 'Rough1': Toolpath requires tool to be selected."
    )


def test_wait_future_reports_an_error_that_completes_the_future(handler_module):
    """Completion is checked before the error, and nothing used to run after the loop.

    The measured refusal leaves the future pending; nothing says every failure does. A
    generation that errors *and* completes left the loop clean, and each call site then
    answered ``generated: True`` for an operation Fusion had refused.
    """
    operation = SimpleNamespace(
        name="Rough1", hasError=True, error="3 : toolpath calculation failed"
    )

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(
            FakeGenerationFlagFuture(completed_after=1),
            timeout=5.0,
            operations=[operation],
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert str(raised.value) == ("Operation 'Rough1': 3 : toolpath calculation failed")


def test_wait_future_reports_a_nameless_error_without_a_prefix(handler_module):
    """No name is no prefix: Fusion's own sentence beats a dangling quote."""
    operation = SimpleNamespace(hasError=True, error="3 : generation failed")

    with pytest.raises(addon_hints.Refusal) as raised:
        handler_module.CommandHandler._wait_future(
            FakeGenerationFlagFuture(completed_after=None),
            timeout=5.0,
            operations=[operation],
        )

    assert str(raised.value) == "3 : generation failed"


def test_a_geometry_refusal_never_attaches_the_tool_first(handler_module):
    """Order matters: attaching registers the tool in ``documentToolLibrary``.

    The geometry seam is the only step that removes the operation after it exists, so
    it runs first. Reversing them would leave a tool behind on every refused retry while
    the refusal promised only that the operation was removed - and nothing in the reply
    says a library entry was gained.
    """
    operation, value, _applied = _contour_operation()

    def refuse(selections):
        raise RuntimeError("3 : some input argument is invalid")

    value.applyCurveSelections = refuse
    handler = _creation_handler(handler_module, operation, faces=1)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_operation(
            setup_name="Setup1",
            strategy="contour2d",
            body_name="Body1",
            face_indices=[0],
            tool_diameter=0.6,
        )

    assert raised.value.error_kind == "FUSION_REFUSED"
    assert operation.deleted == 1
    assert not hasattr(operation, "tool"), "the tool was attached before the seam"


def test_wait_future_tells_two_same_named_operations_apart(handler_module):
    """A name is not a key: this add-in refuses duplicates precisely because they exist.

    Keyed by name, the second operation's verdict would overwrite the first's in the
    snapshot - so a fresh failure could be masked by an older one with the same label.
    """
    handler = handler_module.CommandHandler
    stale = SimpleNamespace(name="Rough1", hasError=True, error="old failure")
    clean = SimpleNamespace(name="Rough1", hasError=False, error="")
    fresh = SimpleNamespace(name="Rough1", hasError=True, error="new failure")
    # The fresh failure comes FIRST on purpose: under name keys the later stale entry
    # overwrites it in the snapshot, so the old implementation masked it and stalled to
    # TIMEOUT. Only position keys raise here, which is what the fix claims.
    prior = handler._operation_errors([clean, stale])

    with pytest.raises(addon_hints.Refusal) as raised:
        handler._wait_future(
            FakeNeverStartedFuture(),
            timeout=5.0,
            operations=[fresh, stale],
            prior_errors=prior,
        )

    assert str(raised.value) == "Operation 'Rough1': new failure"


def test_generation_reports_an_error_the_call_itself_caused(handler_module):
    """The snapshot is taken *before* generating, so a brand-new failure is reported.

    Nothing else pins that ordering: with the snapshot moved after the generate call,
    the failure would already be in it and the wait would report an inherited verdict
    instead (or stall to the bound). The stand-in keeps the wait short but keeps the
    snapshot and the comparison, which is what this test is about.
    """
    operation = SimpleNamespace(name="Rough1", hasError=False, error="")
    cam = _cam(_setup_with_operations("Setup1", operation))

    def generate(target):
        target.hasError = True
        target.error = "3 : toolpath calculation failed"
        return FakeNeverStartedFuture()

    cam.generateToolpath = generate
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam
    bounded = handler_module.CommandHandler._wait_future
    handler._wait_future = (
        lambda future, timeout=25.0, operations=(), prior_errors=None: bounded(
            future,
            timeout=0.01,
            operations=operations,
            prior_errors=prior_errors,
        )
    )

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_generate_toolpath(setup_name="Setup1", operation_name="Rough1")

    assert raised.value.error_kind == "FUSION_REFUSED"
    # The whole sentence, not a substring: with the snapshot taken *after* the generate
    # call the failure is inherited, and the reply carries the inherited-branch suffix -
    # so only an equality assertion fails on that mutation.
    assert str(raised.value) == ("Operation 'Rough1': 3 : toolpath calculation failed")


def test_operation_errors_skips_what_it_cannot_read_and_names_a_blank_message(
    handler_module,
):
    """The skip branches and the fallback are the other half of the read-back.

    ``hasError`` is absent on some shapes and may refuse reads on a deleted operation;
    either way that operation is skipped rather than reported. A blank message from
    Fusion is replaced by one that names the operation, so a refusal never carries an
    empty sentence.
    """

    class Deleted:
        """A shape whose reads raise, as a deleted Fusion object's do."""

        name = "Rough3"

        @property
        def hasError(self):
            raise RuntimeError("3 : object deleted")

    handler = handler_module.CommandHandler
    errors = handler._operation_errors(
        [
            SimpleNamespace(name="Rough1", hasError=True, error="   "),
            SimpleNamespace(name="Rough2"),  # no hasError at all
            Deleted(),
            SimpleNamespace(name="Rough4", hasError=True, error="kept"),
        ]
    )

    assert errors[0] == "Fusion reported an error on operation 'Rough1'"
    assert 1 not in errors, "a shape without hasError is skipped"
    assert 2 not in errors, "a read that raises is skipped"
    assert errors[3] == "Operation 'Rough4': kept"


# ── the setup's stock vocabulary ─────────────────────────────────────────────
# Measured on Fusion 2706.1.17 by writing ``job_stockMode`` on a live setup: the ids
# ``default``, ``fixedbox``, ``relativecylinder``, ``fixedcylinder`` and ``solid`` are
# accepted; ``from_body`` (which this schema used to advertise) and a nonsense string
# were both refused with "3 : Invalid enumeration value." - two probes, not a universal.


class _StockParam:
    def __init__(self):
        self.expression = None


class _Setup:
    """A setup that records the CAM parameters written to it.

    *accepted* is the set of parameter names this build knows, or None for "every name".
    A name outside it answers ``None``, which is what Fusion does for a parameter that
    does not exist - a fake that accepts any name would report ``stock_applied`` for a
    misspelled ``job_stockMode`` and keep the suite green.
    """

    def __init__(self, name, accepted=None):
        self.name = name
        self.accepted = accepted
        self.written = {}

    @property
    def parameters(self):
        def item_by_name(name):
            if self.accepted is not None and name not in self.accepted:
                return None
            return self.written.setdefault(name, _StockParam())

        return SimpleNamespace(itemByName=item_by_name)


def _setup_cam(default_name: str = "Setup1", accepted=None):
    """A CAM product whose ``setups.add`` answers a recording setup.

    ``cam.seen`` holds the ``OperationTypes`` member each ``createInput`` was handed, so
    a swapped branch in the handler's map is visible rather than harmless.
    """
    created = []
    seen = []

    def create_input(op_type):
        seen.append(op_type)
        return SimpleNamespace(name=None, models=None)

    def add(setup_input):
        setup = _Setup(setup_input.name or default_name, accepted=accepted)
        created.append(setup)
        return setup

    cam = SimpleNamespace(
        setups=SimpleNamespace(createInput=create_input, add=add), seen=seen
    )
    return cam, created


@pytest.mark.parametrize(
    ("mode", "expected"), sorted(addon_rules.CAM_STOCK_MODES.items())
)
def test_a_stock_mode_reaches_fusion_as_its_own_id(handler_module, mode, expected):
    """The name is ours, the id is Fusion's - and they differ for all five."""
    handler = _handler(handler_module)
    cam, created = _setup_cam()
    handler._get_cam = lambda: cam
    handler._body_by_name = lambda name: SimpleNamespace(name=name)

    result = handler.cam_create_setup("Body1", name="Setup1", stock_mode=mode)

    assert result["stock_applied"]["stock_mode"] == expected
    assert created[0].written["job_stockMode"].expression == f"'{expected}'"
    # One-sided assertions let a handler that always adds the warning stay green.
    assert "stock_failed" not in result
    assert "warning" not in result


def test_an_unknown_stock_mode_is_refused_before_a_setup_exists(handler_module):
    """Nothing is created for a value Fusion would refuse: no stockless setup behind."""
    handler = _handler(handler_module)
    cam, created = _setup_cam()
    handler._get_cam = lambda: cam
    handler._body_by_name = lambda name: SimpleNamespace(name=name)

    with pytest.raises(addon_hints.Refusal) as raised:
        handler.cam_create_setup("Body1", name="Setup1", stock_mode="from_body")

    assert raised.value.error_kind == "INVALID_INPUT"
    assert created == [], "the setup must not exist when the vocabulary is refused"


def test_a_stock_mode_fusion_will_not_take_is_reported_not_claimed(handler_module):
    """``stock_failed`` is the honest answer when the setup lacks the parameter.

    The fake accepts any name by default, so without a build that refuses one this line
    of the reply - and the warning beside it - had no test at all.
    """
    handler = _handler(handler_module)
    cam, _created = _setup_cam(accepted={"job_stockOffset"})
    handler._get_cam = lambda: cam
    handler._body_by_name = lambda name: SimpleNamespace(name=name)

    result = handler.cam_create_setup("Body1", name="Setup1", stock_mode="from_solid")

    assert result["stock_failed"] == {"stock_mode": "solid"}
    assert "stock_applied" not in result
    assert result["warning"]


@pytest.mark.parametrize(
    ("operation_type", "member"),
    [
        ("milling", "MillingOperation"),
        ("turning", "TurningOperation"),
        ("cutting", "JetOperation"),
    ],
)
def test_an_operation_type_reaches_its_own_enum_member(
    handler_module, operation_type, member
):
    """The three names map to three different members, by identity like the handler.

    ``cutting -> JetOperation`` is not a guess a reader would make, and the fake now
    records what it was handed, so swapping a branch fails here.
    """
    handler = _handler(handler_module)
    cam, _created = _setup_cam()
    handler._get_cam = lambda: cam
    handler._body_by_name = lambda name: SimpleNamespace(name=name)

    handler.cam_create_setup("Body1", name="Setup1", operation_type=operation_type)

    assert cam.seen[0] is getattr(adsk.cam.OperationTypes, member)


# ── mock mode's CAM replies ──────────────────────────────────────────────────
# What an agent rehearses here is what it then reads against Fusion. A key
# that exists in one mode and not the other is a KeyError at the worst moment, so the
# two are compared to each other rather than each to a literal - the same shape
# `tests/test_rules.py` uses for refusal sentences.


def _mock_cam(name: str, params: dict):
    from fusion360_mcp.mock import mock_command

    result = mock_command(name, params)
    assert result["ok"] is True, result
    return {key: value for key, value in result.items() if key not in ("ok", "mode")}


def test_mock_and_the_handler_answer_the_same_cam_setup_keys(handler_module):
    handler = _handler(handler_module)
    cam, _created = _setup_cam()
    handler._get_cam = lambda: cam
    handler._body_by_name = lambda name: SimpleNamespace(name=name)

    reply = handler.cam_create_setup("Body1", name="Setup1", stock_mode="from_solid")

    # The same stock mode on both sides, so the *value* mapping is compared and not just
    # the key names.
    mock_reply = _mock_cam(
        "cam_create_setup",
        {"body_name": "Body1", "name": "Setup1", "stock_mode": "from_solid"},
    )

    assert set(reply) == set(mock_reply)
    assert reply["stock_applied"] == mock_reply["stock_applied"]
    assert mock_reply["stock_applied"] == {"stock_mode": "solid"}


def test_mock_and_the_handler_answer_the_same_cam_operation_keys(handler_module):
    operation = _tool_op()
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))

    reply = handler.cam_create_operation(
        "Setup1",
        "adaptive2d",
        name="Rough1",
        tool_diameter=0.6,
        stepdown=0.1,
        coolant="flood",
    )

    mock_reply = _mock_cam(
        "cam_create_operation",
        {
            "setup_name": "Setup1",
            "strategy": "adaptive2d",
            "name": "Rough1",
            "tool_diameter": 0.6,
            "stepdown": 0.1,
            "coolant": "flood",
        },
    )

    assert set(reply) == set(mock_reply)
    # Nested keys too: the handler writes Fusion's parameter names into the operation,
    # so the set it wrote is the set mock must answer.
    assert set(operation.written) == set(mock_reply["parameters_applied"])
    assert reply["parameters_applied"] == mock_reply["parameters_applied"]


@pytest.mark.parametrize(
    ("params", "handler_target"),
    [
        ({"setup_name": "Setup1"}, "setup"),
        ({"operation_name": "Rough1"}, "operation"),
        ({"generate_all": True}, "all"),
    ],
    ids=["setup scope", "operation scope", "all scope"],
)
def test_mock_and_the_handler_answer_the_same_toolpath_keys(
    handler_module, params, handler_target
):
    operation = _operation("Rough1")
    cam = _cam(_setup_with_operations("Setup1", operation))
    generated = []
    cam.generateToolpath = generated.append
    # The all-scope case goes through the other entry point; both are one call, and the
    # wait is stubbed by `_generating_handler`.
    cam.generateAllToolpaths = lambda _errors: None
    handler = _generating_handler(handler_module, cam)

    reply = handler.cam_generate_toolpath(**params)

    mock_reply = _mock_cam("cam_generate_toolpath", params)

    assert set(reply) == set(mock_reply)
    assert reply["scope"] == mock_reply["scope"] == handler_target


def test_mock_and_the_handler_answer_the_same_list_setups_keys(handler_module):
    setup = _setup_with_operations("Setup1", _readable_operation("Rough1"))
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup)

    reply = handler.cam_list_setups()

    mock_reply = _mock_cam("cam_list_setups", {})

    assert set(reply) == set(mock_reply)
    assert set(reply["setups"][0]) == set(mock_reply["setups"][0])


def test_mock_and_the_handler_answer_the_same_list_operations_keys(handler_module):
    setup = _setup_with_operations(
        "Setup1", _readable_operation("Rough1"), _readable_operation("Face1")
    )
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(setup)

    reply = handler.cam_list_operations("Setup1")

    mock_reply = _mock_cam("cam_list_operations", {"setup_name": "Setup1"})

    assert set(reply) == set(mock_reply)
    assert set(reply["operations"][0]) == set(mock_reply["operations"][0])


def test_mock_and_the_handler_answer_the_same_operation_info_keys(handler_module):
    operation = SimpleNamespace(
        name="Rough1",
        isValid=True,
        hasToolpath=True,
        tool=SimpleNamespace(description="6mm flat end mill"),
        parameters=[SimpleNamespace(name="stepdown", expression="2 mm")],
    )
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup_with_operations("Setup1", operation))

    reply = handler.cam_get_operation_info("Setup1", "Rough1")

    mock_reply = _mock_cam(
        "cam_get_operation_info", {"setup_name": "Setup1", "operation_name": "Rough1"}
    )

    assert set(reply) == set(mock_reply)


def test_mock_and_the_handler_answer_the_same_post_process_keys(
    handler_module, tmp_path
):
    operation = _operation("Rough1")
    cam = _cam(_setup_with_operations("Setup1", operation), generic_post=str(tmp_path))
    cam.postProcess = lambda *_args: None
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam
    handler._resolve_post = lambda _name: str(tmp_path / "fanuc.cps")

    reply = handler.cam_post_process(
        "Setup1", operation_name="Rough1", output_folder=str(tmp_path)
    )

    mock_reply = _mock_cam(
        "cam_post_process",
        {
            "setup_name": "Setup1",
            "operation_name": "Rough1",
            "output_folder": str(tmp_path),
        },
    )

    assert set(reply) == set(mock_reply)


def test_a_parameter_fusion_will_not_take_is_reported_not_claimed(handler_module):
    """A strategy that exposes no `tool_coolant` sends it to ``parameters_failed``.

    Real Fusion answers ``None`` from ``itemByName`` for a name the strategy does not
    have, which is what the handler's warning describes. No test reached that path
    before, because the fake answered a parameter for every name.
    """
    operation = _tool_op(accepted={"maximumStepdown"})
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))

    result = handler.cam_create_operation(
        "Setup1", "pocket2d", stepdown=0.1, coolant="flood"
    )

    assert result["parameters_applied"] == {"maximumStepdown": 0.1}
    assert result["parameters_failed"] == {"tool_coolant": "flood"}
    assert result["warning"]


@pytest.mark.parametrize(
    ("argument", "parameter"),
    [
        ("stock_offset_sides", "job_stockOffset"),
        ("stock_offset_top", "job_stockOffsetTop"),
        ("stock_offset_bottom", "job_stockOffsetBottom"),
    ],
)
def test_mock_and_the_handler_report_the_same_offset_names(
    handler_module, argument, parameter
):
    """All three offsets, one at a time, under Fusion's own names."""
    handler = _handler(handler_module)
    cam, _created = _setup_cam()
    handler._get_cam = lambda: cam
    handler._body_by_name = lambda name: SimpleNamespace(name=name)

    reply = handler.cam_create_setup("Body1", name="Setup1", **{argument: 0.5})

    mock_reply = _mock_cam(
        "cam_create_setup", {"body_name": "Body1", "name": "Setup1", argument: 0.5}
    )

    assert reply["stock_applied"] == mock_reply["stock_applied"]
    assert reply["stock_applied"][parameter] == 0.5


@pytest.mark.parametrize(
    ("argument", "parameter"),
    [
        ("stepdown", "maximumStepdown"),
        ("stepover", "maximumStepover"),
        ("feed_rate", "tool_feedCutting"),
        ("spindle_speed", "tool_spindleSpeed"),
    ],
)
def test_mock_and_the_handler_report_the_same_parameter_names(
    handler_module, argument, parameter
):
    """The handler writes Fusion's names into the operation; mock must answer them."""
    operation = _tool_op()
    handler = _handler(handler_module)
    handler._get_cam = lambda: _cam(_setup("Setup1", operation))

    reply = handler.cam_create_operation(
        "Setup1", "adaptive2d", coolant=None, **{argument: 1.0}
    )

    mock_reply = _mock_cam(
        "cam_create_operation",
        {
            "setup_name": "Setup1",
            "strategy": "adaptive2d",
            argument: 1.0,
            "coolant": None,
        },
    )

    assert set(reply["parameters_applied"]) == {parameter}
    assert reply["parameters_applied"] == mock_reply["parameters_applied"]


def test_mock_and_the_handler_resolve_the_same_default_post_folder(handler_module):
    """No ``output_folder`` given: both resolve the home Desktop path, not a literal."""
    cam = _cam(_setup_with_operations("Setup1", _operation("Rough1")))
    cam.postProcess = lambda *_args: None
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam
    handler._resolve_post = lambda _name: "fanuc.cps"

    reply = handler.cam_post_process("Setup1")

    mock_reply = _mock_cam("cam_post_process", {"setup_name": "Setup1"})

    assert reply["output_folder"] == mock_reply["output_folder"]


def test_a_missing_cam_name_reaches_the_caller_as_name_not_found(handler_module):
    """Both CAM raise sites the NAME_NOT_FOUND rule exists for, driven for real.

    Classifying a hand-written copy of the sentence proves only the copy: reword an
    f-string and the rule stops matching, so the caller gets ``UNKNOWN`` with no
    hints — the failure mode AGENTS.md forbids — while the suite stays green. These
    two go through ``_find_setup`` and ``_find_operation`` instead, which is the
    code that actually raises the text the rule matches.
    """
    cam = _cam(_setup_with_operations("Setup1", _operation("Rough1")))
    handler = _handler(handler_module)
    handler._get_cam = lambda: cam

    with pytest.raises(RuntimeError) as setup_missing:
        handler.cam_list_operations("NoSuchSetup")
    with pytest.raises(RuntimeError) as operation_missing:
        handler.cam_get_operation_info("Setup1", "NoSuchOp")

    # The wording is deliberately not pinned: the rule matches ``not found`` or
    # ``does not exist``, so a pin on one spelling would fail on a rename the rule
    # still accepts. The hint proves the rule fired rather than some other refusal —
    # ``_KIND_HINTS`` also names ``cam_list_setups`` now, but only a ``Refusal``
    # reaches it and both lookups raise a plain ``RuntimeError``.
    for raised in (setup_missing, operation_missing):
        kind, hints = addon_hints.classify(raised.value)
        assert kind == "NAME_NOT_FOUND"
        assert any("cam_list_setups" in hint for hint in hints), hints
