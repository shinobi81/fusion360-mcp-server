"""A refusal carries the classification it already knew.

``classify`` recovered ``error_kind`` by matching ``str(exc)`` against ``_RULES``, so
the raiser threw away which input was wrong and a regex guessed it back.  ``Refusal``
keeps it.  The table stays for Fusion's own messages, which arrive as plain exceptions
and plain strings and have no kind to state.

These import the canonical module (``addon.server.hints``) rather than the generated
mirror: this is the one the add-in raises from, and ``fusion360_mcp.hints`` is a copy
holding its own classes.  Reached through the module object, not by name, because
``reload_handler`` re-executes that module and replaces the class — a by-name import
kept pointing at the generation the test module happened to import first.
"""

from __future__ import annotations

import pytest

from addon.server import hints as addon_hints
from fusion360_mcp import hints as mirror
from tests.fakes.bodies import body_with_edges
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import PARAMETRIC
from tests.fakes.sketch import FakeSketch

# ── the class ─────────────────────────────────────────────────────────


def test_a_refusal_classifies_as_its_own_kind():
    kind, hints = addon_hints.classify(
        addon_hints.Refusal(
            "AXIS_OUT_OF_PLANE",
            "axis leaves the sketch",
            ("pick a coplanar axis",),
        )
    )
    assert kind == "AXIS_OUT_OF_PLANE"
    assert hints == ["pick a coplanar axis"]


def test_a_refusal_with_an_unlisted_kind_still_classifies():
    """A caller that adds a kind the table never heard of still gets advice.

    Without a fallback this is the mode AGENTS.md forbids: an error with no hints.
    """
    kind, hints = addon_hints.classify(
        addon_hints.Refusal("NOT_A_DOCUMENTED_KIND", "boom")
    )
    assert kind == "NOT_A_DOCUMENTED_KIND"
    assert hints


def test_a_refusal_is_a_runtime_error_whose_message_is_the_human_text():
    """Every existing ``pytest.raises(RuntimeError)`` and wire message keeps working."""
    refusal = addon_hints.Refusal("INVALID_INPUT", "name the field")
    assert isinstance(refusal, RuntimeError)
    assert str(refusal) == "name the field"


def test_a_refusal_holds_its_hints_as_a_tuple():
    assert addon_hints.Refusal("INVALID_INPUT", "m", ("one", "two")).hints == (
        "one",
        "two",
    )
    assert addon_hints.Refusal("INVALID_INPUT", "m").hints == ()


def test_the_kind_a_refusal_carries_wins_over_the_table():
    """The message matches Fusion's generic argument rule; the raiser knew better.

    This is the whole point of the class: text that *reads* like one kind is
    still whatever the code that refused it says it is.
    """
    kind, _hints = addon_hints.classify(
        addon_hints.Refusal("BODY_NOT_FOUND", "Some input argument is invalid")
    )
    assert kind == "BODY_NOT_FOUND"


# ── the wire contract: a converted message classifies as it did ───────

#: The seven messages converted to ``Refusal``, verbatim from ``addon/server/rules.py``.
#: The seven handler tests below compare the message they catch against these
#: entries, so a message edited at its source fails here instead of silently
#: re-routing to another rule's hints.  Each entry is one string: the wrapped ones are
#: joined with ``+`` so a continuation cannot read as a missing comma.
CONVERTED = [
    "Pass only one of edge_indices and edge_points — they name the same edges "
    + "two ways, so one would be ignored",
    "edge_selection 'top' cannot be combined with edge_indices or edge_points — "
    + "pass one selector, not two",
    "edge_indices was empty — name at least one edge, or omit it to use edge_selection",
    "edge_points was empty — name at least one point, or omit it to use edge_selection",
    "Unknown edge_selection 'diagonal' — use all/top/bottom/vertical",
    "Invalid input: target_body applies only to cut, join or intersect — "
    + "new_body builds a body of its own, so there is nothing to target",
    "Unknown rule_type 'Tangent' - use 'normal' or 'tangent'",
]


@pytest.mark.parametrize("message", CONVERTED)
def test_a_converted_message_classifies_exactly_as_it_did(message):
    """Kind *and* hints, so the fallback chain reproduces the table exactly.

    Each of these messages has its own rule, which is where its advice comes from.
    A per-kind fallback alone would hand every one of them the same generic hints.
    """
    assert addon_hints.classify(
        addon_hints.Refusal("INVALID_INPUT", message)
    ) == addon_hints.classify(message)


def test_a_fusion_message_still_comes_from_the_table():
    """Fusion's own errors are untyped — no Refusal, so the regex table answers."""
    kind, hints = addon_hints.classify(RuntimeError("3 : invalid free edge"))
    assert kind == "INVALID_INPUT"
    assert any("free edge" in hint for hint in hints), hints


@pytest.mark.parametrize(
    ("kind", "message", "hints"),
    [
        # No rule mentions this kind, so the generic fallback answers.
        ("NOT_A_DOCUMENTED_KIND", "boom", ()),
        # The refusal carries its own hints, which win over every rule.
        ("AXIS_OUT_OF_PLANE", "axis leaves the sketch", ("pick a coplanar axis",)),
        # No rule matches and BODY_NOT_FOUND has no ``_KIND_HINTS`` entry, so the
        # last fallback answers and both modules return ``_GENERIC_HINTS``.  This
        # variant runs the mirror's copy of that branch; the per-kind branch is
        # pinned on the canonical module by
        # test_a_refusal_with_no_matching_rule_takes_its_kind_default.
        ("BODY_NOT_FOUND", "nothing to match here", ()),
        # A rule matches the message, and its hints are the ones returned.
        ("INVALID_INPUT", "3 : invalid free edge", ()),
    ],
)
def test_the_generated_mirror_refuses_identically(kind, message, hints):
    """Two modules, two ``Refusal`` classes, one behaviour.

    ``src/fusion360_mcp/hints.py`` is generated from the canonical file and so holds a
    class object of its own.  The server only classifies the strings that cross the
    wire, so a drift in the copied body would surface nowhere else.
    """
    expected = addon_hints.classify(addon_hints.Refusal(kind, message, hints))
    assert mirror.classify(mirror.Refusal(kind, message, hints)) == expected


def test_a_refusal_with_no_matching_rule_takes_its_kind_default():
    """D4: the fallback is a per-kind entry, never the first rule of that kind.

    The old behaviour borrowed the inf/NaN rule's hints for any unmatched
    ``INVALID_INPUT``, which told a caller with a bad ``count`` about ``nan``.
    """
    kind, hints = addon_hints.classify(
        addon_hints.Refusal("INVALID_INPUT", "nothing in the table reads like this")
    )
    assert kind == "INVALID_INPUT"
    assert hints == list(addon_hints._KIND_HINTS["INVALID_INPUT"])
    assert "inf, -inf and nan" not in " ".join(hints)


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        (
            "Toolpath generation did not finish within 30s. The operation may still "
            "complete in the background — check with cam_list_operations before "
            "regenerating.",
            "TIMEOUT",
        ),
        ("thickness must be finite, in cm: inf", "INVALID_INPUT"),
        ("Rectangle sketch produced no profile", "PROFILE_NOT_CLOSED"),
    ],
)
def test_the_three_wordings_that_never_matched(message, kind):
    """Rule 43 said only ``timeout``, rule 9 only ``is not finite``, rule 2 only
    ``no profiles? in sketch`` — so the add-in's own three sentences were UNKNOWN."""
    assert addon_hints.classify(message)[0] == kind


def test_the_adapter_wording_classifies_as_internal():
    """``addon/server/fusion_api.py`` must keep raising AttributeError — getattr,
    hasattr and monkeypatch all catch only that — so the kind comes from here."""
    kind, hints = addon_hints.classify(
        AttributeError("module 'addon.server.fusion_api' has no attribute 'corex'")
    )
    assert kind == "INTERNAL_ERROR"
    assert any("check_fusion_api" in hint for hint in hints)


# ── the converted call sites ─────────────────────────────────────────


@pytest.fixture
def plate(bound_handler):
    body = body_with_edges("Plate", [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1))])
    return bound_handler(FakeDesign(bodies=[body])), body


def test_two_edge_selectors_at_once_is_refused_as_a_refusal(plate):
    handler, body = plate
    with pytest.raises(addon_hints.Refusal) as raised:
        handler._select_edges(body, "all", indices=[0], points=[[0.0, 0.0, 0.0]])
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[0]


def test_a_named_selection_beside_an_index_selector_is_refused_as_a_refusal(plate):
    handler, body = plate
    with pytest.raises(addon_hints.Refusal) as raised:
        handler._select_edges(body, "top", indices=[0])
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[1]


def test_an_empty_index_list_is_refused_as_a_refusal(plate):
    handler, body = plate
    with pytest.raises(addon_hints.Refusal) as raised:
        handler._select_edges(body, "all", indices=[])
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[2]


def test_an_empty_point_list_is_refused_as_a_refusal(plate):
    handler, body = plate
    with pytest.raises(addon_hints.Refusal) as raised:
        handler._select_edges(body, "all", points=[])
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[3]


def test_an_unknown_edge_selection_is_refused_as_a_refusal(plate):
    handler, body = plate
    with pytest.raises(addon_hints.Refusal) as raised:
        handler._select_edges(body, "diagonal")
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[4]


def test_target_body_on_a_new_body_is_refused_as_a_refusal(bound_handler):
    handler = bound_handler(FakeDesign(bodies=[]))
    with pytest.raises(addon_hints.Refusal) as raised:
        handler._resolve_target_body("Body1", "new_body")
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[5]


def test_an_unknown_rule_type_is_refused_as_a_refusal(bound_handler):
    sketch = FakeSketch(name="Sketch1")
    body = body_with_edges(
        "Body1",
        [((0.0, 0.0, 0.0), (0.0, 10.0, 0.0)), ((0.0, 10.0, 0.0), (10.0, 10.0, 0.0))],
    )
    handler = bound_handler(
        FakeDesign(bodies=[body], sketches=[sketch], design_type=PARAMETRIC)
    )
    with pytest.raises(addon_hints.Refusal) as raised:
        handler.ruled_surface("Body1", edge_index=0, rule_type="Tangent")
    assert raised.value.error_kind == "INVALID_INPUT"
    assert str(raised.value) == CONVERTED[6]
