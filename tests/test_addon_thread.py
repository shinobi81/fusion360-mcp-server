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

import pytest

from tests.fakes.bodies import FakeBody, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign
from tests.fakes.features import FakeThreadInfo


def _thread_diameter(designation: str, is_internal: bool = False) -> float:
    """The diameter the face must have for *designation*, per the fake's table."""
    info = FakeThreadInfo.create(
        False,
        is_internal,
        "ISO Metric profile",
        designation,
        "6H" if is_internal else "6g",
        True,
    )
    return info.minorDiameter if is_internal else info.majorDiameter


def _design_with_a_bore(
    designation: str = "M6x1", is_internal: bool = False
) -> tuple[FakeDesign, FakeFace]:
    """One body with one cylindrical face, sized to the thread about to be cut.

    The face's diameter is the thread's own - ``create_thread`` refuses a designation
    that does not match it, so a fixture with a fixed radius would only pass for one
    designation and quietly test nothing for the rest.
    """
    diameter = _thread_diameter(designation, is_internal)
    bore = FakeFace(normal=(0.0, 0.0, 1.0), planar=False, radius=diameter / 2)
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
    design, _ = _design_with_a_bore("M10x1.5", is_internal=True)
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0, is_internal=True)

    info = design.rootComponent.features.threadFeatures.inputs[0].threadInfo
    assert info.isInternal is True


def test_cosmetic_is_the_default_and_modelled_is_opt_in(bound_handler):
    """The two flags the tool has always had, still reaching the feature input."""
    design, _ = _design_with_a_bore("M10x1.5")
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0)

    created = design.rootComponent.features.threadFeatures.inputs[0]
    assert created.isModeled is False
    assert created.isFullLength is True


def test_a_partial_length_is_a_value_input_in_centimetres(bound_handler):
    design, _ = _design_with_a_bore("M10x1.5")
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
    internal, _ = _design_with_a_bore("M10x1.5", is_internal=True)
    bound_handler(internal).create_thread("Body1", face_index=0, is_internal=True)
    threads = internal.rootComponent.features.threadFeatures

    assert threads.inputs[0].threadInfo.threadClass == "6H"

    external, _ = _design_with_a_bore("M10x1.5")
    bound_handler(external).create_thread("Body1", face_index=0)
    external_threads = external.rootComponent.features.threadFeatures
    assert external_threads.inputs[0].threadInfo.threadClass == "6g"


def test_an_explicit_class_wins_over_the_default(bound_handler):
    design, _ = _design_with_a_bore("M10x1.5", is_internal=True)
    handler = bound_handler(design)

    handler.create_thread("Body1", face_index=0, is_internal=True, thread_class="6G")

    info = design.rootComponent.features.threadFeatures.inputs[0].threadInfo
    assert info.threadClass == "6G"


class TestSizeMatching:
    """A designation that does not match the face is refused, unless told otherwise.

    Fusion sizes the body to the thread - an ``M6x1`` cosmetic thread on a Ø20 mm
    shaft left a Ø5.88 mm one, measured - so a caller who mistyped a designation would
    silently lose the geometry they asked for.
    """

    def _large_face(self):
        return _design_with_a_bore("M20x2.5")

    def test_a_mismatched_designation_is_refused(self, bound_handler):
        design, _ = self._large_face()

        with pytest.raises(RuntimeError) as raised:
            bound_handler(design).create_thread(
                "Body1", face_index=0, thread_designation="M6x1"
            )

        # The numbers come from the fake's measured table, not from this test: a
        # hard-coded 20.00 mm was wrong the moment the table stopped rounding
        # (M20x2.5's major diameter is 19.79 mm).
        face_mm = _thread_diameter("M20x2.5") * 10
        thread_mm = _thread_diameter("M6x1") * 10
        message = str(raised.value)
        assert f"{face_mm:.2f} mm" in message, message
        assert f"{thread_mm:.2f} mm" in message, message
        assert "allow_resize" in message, message

    def test_the_refusal_names_the_thread_fusion_recommends(self, bound_handler):
        """``recommendThreadData`` answers for the diameter - no table lives here."""
        design, _ = self._large_face()

        with pytest.raises(RuntimeError, match=r"M20x2\.5"):
            bound_handler(design).create_thread(
                "Body1", face_index=0, thread_designation="M6x1"
            )

    def test_allow_resize_accepts_fusions_resize_and_reports_the_diameters(
        self, bound_handler
    ):
        design, _ = self._large_face()

        out = bound_handler(design).create_thread(
            "Body1", face_index=0, thread_designation="M6x1", allow_resize=True
        )

        assert out["face_diameter_cm"] == pytest.approx(_thread_diameter("M20x2.5"))
        assert out["thread_diameter_cm"] == pytest.approx(_thread_diameter("M6x1"))

    def test_a_face_that_is_not_cylindrical_is_refused(self, bound_handler):
        """A plane cannot be threaded, and Fusion's word for it is a cast that fails."""
        face = FakeFace(normal=(0.0, 0.0, 1.0))
        design = FakeDesign(bodies=[FakeBody("Body1", faces=FakeCollection([face]))])

        with pytest.raises(RuntimeError, match="not cylindrical"):
            bound_handler(design).create_thread("Body1", face_index=0)
