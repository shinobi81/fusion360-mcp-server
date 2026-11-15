"""``create_thread``: the thread the agent asked for, not the query's default.

``create_thread`` accepted ``is_internal``, ``thread_designation`` and
``thread_class`` and used none of them: it set ``threadType`` on a
``ThreadDataQuery`` and handed *that* to ``ThreadFeatures.createInput``, which
takes a ``ThreadInfo``.  On Fusion 2706 the call raises

    TypeError: in method 'ThreadFeatures_createInput', argument 3 of type
    'adsk::core::Ptr< adsk::fusion::ThreadInfo > const &'

so the tool never created a thread at all — mock mode was the only mode it ever
worked in.  Both halves are pinned here: the fake refuses a non-ThreadInfo the
way Fusion does, and the assertions read the designation, class and
internal/external flag off the ``ThreadInfo`` that reached the input.
"""

from __future__ import annotations

from tests.fakes.bodies import FakeBody, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign


def _design_with_a_bore() -> tuple[FakeDesign, FakeFace]:
    """One body with one cylindrical face — the face ``create_thread`` indexes."""
    bore = FakeFace(normal=(0.0, 0.0, 1.0))
    return FakeDesign(bodies=[FakeBody("Body1", faces=FakeCollection([bore]))]), bore


def test_the_requested_designation_and_class_reach_the_thread_info(bound_handler):
    design, _ = _design_with_a_bore()
    handler = bound_handler(design)

    out = handler.create_thread(
        "Body1",
        face_index=0,
        thread_type="ISO Metric profile",
        thread_designation="M6x1",
        thread_class="6H",
    )

    info = design.rootComponent.features.threadFeatures.inputs[0].threadInfo
    assert (info.threadType, info.threadDesignation, info.threadClass) == (
        "ISO Metric profile",
        "M6x1",
        "6H",
    )
    assert out["thread_designation"] == "M6x1"


def test_an_internal_thread_is_built_as_one(bound_handler):
    design, _ = _design_with_a_bore()
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0, is_internal=True)

    info = design.rootComponent.features.threadFeatures.inputs[0].threadInfo
    assert info.isInternal is True


def test_cosmetic_is_the_default_and_modelled_is_opt_in(bound_handler):
    """The two flags the tool has always had, still reaching the feature input."""
    design, _ = _design_with_a_bore()
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0)

    created = design.rootComponent.features.threadFeatures.inputs[0]
    assert created.isModeled is False
    assert created.isFullLength is True


def test_a_partial_length_is_a_value_input_in_centimetres(bound_handler):
    design, _ = _design_with_a_bore()
    handler = bound_handler(design)

    handler.create_thread(
        "Body1", face_index=0, is_modeled=True, is_full_length=False, thread_length=2.5
    )

    created = design.rootComponent.features.threadFeatures.inputs[0]
    assert created.isFullLength is False
    length = created.threadLength
    assert length is not None, "a partial thread needs a length"
    assert (length.kind, length.value) == ("real", 2.5)


def test_the_default_class_follows_internal_or_external(bound_handler):
    """ISO 965 gives internal threads 6H and external ones 6g.

    The parameter is live for the first time in this PR, so a single ``"6g"``
    default would have asked Fusion for an external tolerance class on every
    internal thread the caller did not spell out.
    """
    design, _ = _design_with_a_bore()
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0, is_internal=True)
    threads = design.rootComponent.features.threadFeatures

    assert threads.inputs[0].threadInfo.threadClass == "6H"

    handler.create_thread("Body1", face_index=0)
    assert threads.inputs[1].threadInfo.threadClass == "6g"


def test_an_explicit_class_wins_over_the_default(bound_handler):
    design, _ = _design_with_a_bore()
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0, is_internal=True, thread_class="6G")

    info = design.rootComponent.features.threadFeatures.inputs[0].threadInfo
    assert info.threadClass == "6G"
