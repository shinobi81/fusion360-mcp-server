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

import ast
import pathlib

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


def test_the_name_not_found_fallback_names_the_cam_enumeration():
    """A CAM name is not in the scene, so the generic advice cannot list it.

    No current refusal reaches this entry - every ``Refusal("NAME_NOT_FOUND", ...)``
    in ``addon/server`` passes hints of its own, and ``_hints_for`` returns those
    first - so this pins the data rather than a behaviour. It is pinned because
    ``AGENTS.md`` states the same next move, and two documents that must agree are
    exactly the pair that drifts.
    """
    kind, hints = addon_hints.classify(
        addon_hints.Refusal("NAME_NOT_FOUND", "nothing in the table reads like this")
    )

    assert kind == "NAME_NOT_FOUND"
    assert hints == list(addon_hints._KIND_HINTS["NAME_NOT_FOUND"])
    assert any("cam_list_setups" in hint for hint in hints)


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
    ``no profiles? in sketch`` — two of the add-in's own sentences were UNKNOWN."""
    assert addon_hints.classify(message)[0] == kind


def test_the_adapter_wording_classifies_as_internal():
    """``addon/server/fusion_api.py`` must keep raising AttributeError — getattr,
    hasattr and monkeypatch all catch only that — so the kind comes from here."""
    for message in (
        "module 'addon.server.fusion_api' has no attribute 'corex'",
        "module 'addon.server.fusion_api' cannot resolve 'corex': adsk is not "
        "importable",
    ):
        kind, hints = addon_hints.classify(AttributeError(message))
        assert kind == "INTERNAL_ERROR"
        assert any("check_fusion_api" in hint for hint in hints)


def test_a_fusion_message_using_cannot_resolve_is_not_an_internal_error():
    """The adapter's shape is anchored; the phrase alone is ordinary Fusion text."""
    assert addon_hints.classify("Fusion cannot resolve this profile")[0] != (
        "INTERNAL_ERROR"
    )


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


# ── the dispatch guard: a direct-wire caller gets a typed refusal ──


def test_an_undeclared_argument_is_refused_by_the_dispatch(bound_handler):
    """Live: ``create_box(name=...)`` raised ``TypeError`` and the wire said UNKNOWN.

    A client can reach :9876 directly and skip the server's schema gate (D12), so
    ``execute_command`` binds the handler's own signature and refuses the mismatch
    as INVALID_INPUT, naming the argument.
    """
    handler = bound_handler(FakeDesign(bodies=[]))

    out = handler.execute_command(
        {
            "type": "create_box",
            "params": {"length": 1.0, "width": 1.0, "height": 1.0, "name": "x"},
        }
    )

    result = out["result"]
    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert "name" in result["error_message"]
    assert result["hints"]


def test_a_declared_argument_set_still_dispatches(bound_handler):
    """The guard must not refuse a call the schema admits: ``ping`` has no params."""
    handler = bound_handler(FakeDesign(bodies=[]))

    out = handler.execute_command({"type": "ping", "params": {}})

    assert out["result"] == {"pong": True, "ok": True}


# ── the guard: no raise reaches a caller as UNKNOWN ──────────────────

# Both walks assert the kind a typed refusal states; neither asserts that it yields
# hints, because `_hints_for` cannot return nothing — `_GENERIC_HINTS` is its last
# resort — so such an assertion could never fail.  The advice a converted site carries
# is authored with the site (D9); the kind is what has to be mechanical.

#: Raises that still reach a caller as ``UNKNOWN``: empty since Task 8 typed the last
#: eleven.  A row here is a debt, not an exemption; a new row is a regression.
_UNCLASSIFIED_BASELINE: frozenset[tuple[str, str]] = frozenset()

#: Raises the static walk cannot judge, each with why.  Never silently skipped.
_UNJUDGEABLE: frozenset[tuple[str, int, str]] = frozenset(
    {
        (
            "event_bridge.py",
            101,
            "raise NotImplementedError: no Refusal bound to it",
        ),
        (
            "handler_assembly.py",
            181,
            "raise refusal: kind comes from _rules.construction_plane_angle_refusal",
        ),
        (
            "handler_assembly.py",
            188,
            "raise refusal: kind comes from _rules.construction_plane_angle_refusal",
        ),
        (
            "handler_assembly.py",
            307,
            "raise refusal: kind comes from _rules.perpendicular_axis_refusal",
        ),
        (
            "handler_assembly.py",
            467,
            "raise selector_refusal: kind comes from _rules.joint_selector_refusal",
        ),
        (
            "handler_assembly.py",
            483,
            "raise component_refusal: kind comes from _rules.components_differ_refusal",
        ),
        (
            "handler_assembly.py",
            488,
            "raise geometry_refusal: kind comes from _rules.joint_geometry_refusal",
        ),
        (
            "handler_assembly.py",
            754,
            "raise selector_refusal: kind comes from _rules.joint_selector_refusal",
        ),
        (
            "handler_assembly.py",
            769,
            "raise component_refusal: kind comes from _rules.components_differ_refusal",
        ),
        (
            "handler_assembly.py",
            780,
            "raise geometry_refusal: kind comes from _rules.as_built_geometry_refusal",
        ),
        (
            "handler_assembly.py",
            956,
            "raise refusal: kind comes from _rules.rigid_group_size_refusal",
        ),
        (
            "handler_base.py",
            338,
            "raise refusal: kind comes from _rules.point3d_refusal",
        ),
        (
            "handler_base.py",
            343,
            "raise refusal: kind comes from _rules.body_name_required_refusal",
        ),
        (
            "handler_base.py",
            439,
            "raise refusal: kind comes from _rules.construction_plane_name_refusal",
        ),
        (
            "handler_base.py",
            454,
            "raise refusal: kind comes from _rules.construction_axis_name_refusal",
        ),
        (
            "handler_base.py",
            727,
            "message is not a literal",
        ),
        (
            "handler_base.py",
            768,
            "message is not a literal",
        ),
        (
            "handler_cam.py",
            144,
            "message is not a literal",
        ),
        (
            "handler_cam.py",
            243,
            "raise stock_refusal: kind comes from _rules.cam_stock_mode_refusal",
        ),
        (
            "handler_cam.py",
            590,
            "raise strategy_refusal: kind comes from _rules.cam_strategy_refusal",
        ),
        (
            "handler_cam.py",
            598,
            "raise geometry_refusal: kind comes from _rules.cam_geometry_refusal",
        ),
        (
            "handler_cam.py",
            608,
            "raise tool_refusal: kind comes from _rules.cam_tool_refusal",
        ),
        (
            "handler_cam.py",
            645,
            "raise library_refusal: kind comes from _rules.cam_library_tool_refusal",
        ),
        (
            "handler_cam.py",
            748,
            "raise refusal: kind comes from _rules.cam_target_refusal",
        ),
        (
            "handler_cam.py",
            832,
            "message is not a literal",
        ),
        (
            "handler_cam.py",
            906,
            "raise number_refusal: kind comes from _rules.cam_program_number_refusal",
        ),
        (
            "handler_export.py",
            358,
            "raise target_refusal: kind comes from _rules.export_target_refusal",
        ),
        (
            "handler_export.py",
            366,
            "raise body_refusal: kind comes from _rules.export_body_refusal",
        ),
        (
            "handler_features.py",
            49,
            "raise refusal: kind comes from _rules.target_body_refusal",
        ),
        (
            "handler_features.py",
            101,
            "raise refusal: kind comes from _rules.edge_selector_refusal",
        ),
        (
            "handler_features.py",
            994,
            "message is not a literal",
        ),
        (
            "handler_scene.py",
            763,
            "message is not a literal",
        ),
        (
            "handler_sketch.py",
            317,
            "raise refusal: kind comes from _rules.symmetry_line_refusal",
        ),
        (
            "handler_sketch.py",
            325,
            "message is not a literal",
        ),
        (
            "handler_sketch.py",
            461,
            "message is not a literal",
        ),
        (
            "handler_surface.py",
            121,
            "raise refusal: kind comes from _rules.rule_type_refusal",
        ),
        (
            "handler_surface.py",
            171,
            "raise tool_refusal: kind comes from _rules.surface_tool_refusal",
        ),
        (
            "handler_surface.py",
            173,
            "raise cells_refusal: kind comes from _rules.keep_cells_refusal",
        ),
    }
)

_RENDER = "…"  # what a FormattedValue collapses to; every rule anchors on literals


def _message_of(node: ast.Raise, *, refusal: bool = False) -> str | None:
    """The message a raise would carry, with interpolated parts collapsed.

    A ``Refusal`` call puts the kind in ``args[0]`` and the message in ``args[1]``;
    every other raise puts its message first.
    """
    exc = node.exc
    if not isinstance(exc, ast.Call) or not exc.args:
        return None
    index = 1 if refusal else 0
    if len(exc.args) <= index:
        return None
    arg = exc.args[index]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr):
        return "".join(
            str(p.value) if isinstance(p, ast.Constant) else _RENDER for p in arg.values
        )
    return None


def _refusal_call(node: ast.AST | None) -> ast.Call | None:
    """The ``Refusal(...)`` construction *node* spells, under either import style.

    ``addon/server/rules.py`` explains why the add-in writes ``_hints.Refusal`` and
    cannot import the name — a reload replaces the class — so a walk that knew only the
    bare spelling would miss every site the domain tasks convert.
    """
    if not isinstance(node, ast.Call):
        return None
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    return node if name == "Refusal" else None


def _literal_kind(call: ast.Call) -> str | None:
    """The ``error_kind`` a ``Refusal(...)`` call states, when it is written down."""
    first = call.args[0] if call.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _judged(module: ast.Module) -> dict[tuple[str, str], str]:
    """``{(kind, message): why}`` for every raise whose kind the walk can read.

    A ``Refusal`` is judged as typed under either spelling: the kind it states is what
    reaches the caller, so no regex is involved.  A raise the walk cannot read — a
    computed message, a kind that is not written down — is left out here and listed by
    ``_unresolved_raises`` with its line and its reason.
    """
    found: dict[tuple[str, str], str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        call = _refusal_call(node.exc)
        if call is not None:
            kind = _literal_kind(call)
            if kind is not None:
                found[(kind, _message_of(node, refusal=True) or "")] = "typed"
            continue
        msg = _message_of(node)
        if msg is not None:
            found[(addon_hints.classify(msg)[0], msg)] = "classified"
    return found


def _bindings(func: ast.AST) -> dict[str, ast.expr]:
    """The names *func* binds, for the one-level ``raise <name>`` resolution."""
    bound: dict[str, ast.expr] = {}
    for inner in ast.walk(func):
        if isinstance(inner, ast.Assign):
            for target in inner.targets:
                if isinstance(target, ast.Name):
                    bound[target.id] = inner.value
        elif isinstance(inner, ast.NamedExpr) and isinstance(inner.target, ast.Name):
            bound[inner.target.id] = inner.value
    return bound


def _name_reason(name: str, expr: ast.expr | None) -> str:
    """Why a ``raise <name>`` could not be judged, in terms a reader can act on."""
    if expr is None:
        return f"raise {name}: no Refusal bound to it"
    if _refusal_call(expr) is not None:
        return f"raise {name}: kind is not a string literal"
    if isinstance(expr, ast.Call):
        return f"raise {name}: kind comes from {ast.unparse(expr.func)}"
    return f"raise {name}: local binding is not a Refusal call"


def _unresolved_raises(module: ast.Module, name: str) -> set[tuple[str, int, str]]:
    """Raises the static walk cannot judge, each with its line and its reason.

    One level of binding is resolved — ``refusal = ...`` or ``refusal := ...`` in the
    enclosing function — which is the shape spec D8 anticipates.  **No site in the tree
    binds it to a literal ``Refusal``**: every ``raise refusal`` site takes its kind
    from ``_rules.*_refusal(...)``, which this walk cannot read, and ``event_bridge``'s
    raise is a ``Protocol`` body.  A binding the walk cannot resolve is listed with its
    reason rather than passing quietly, as is a raise whose kind or message is computed
    rather than written down (D8).
    """
    rows: set[tuple[str, int, str]] = set()
    for func in ast.walk(module):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = _bindings(func)
        for inner in ast.walk(func):
            if not isinstance(inner, ast.Raise):
                continue
            # A bare `raise` re-raises what was caught: its kind was judged where it
            # was raised, so there is nothing new here to list.
            if inner.exc is None:
                continue
            call = _refusal_call(inner.exc)
            if call is not None:
                kind = _literal_kind(call)
                if kind is None:
                    rows.add((name, inner.lineno, "kind is not a string literal"))
                else:
                    assert kind in addon_hints._KNOWN_KINDS, (name, inner.lineno, kind)
                continue
            if isinstance(inner.exc, ast.Call):
                if _message_of(inner) is None:
                    rows.add((name, inner.lineno, "message is not a literal"))
                continue
            if not isinstance(inner.exc, ast.Name):
                continue
            expr = bound.get(inner.exc.id)
            call = _refusal_call(expr)
            kind = _literal_kind(call) if call is not None else None
            if kind is not None:
                assert kind in addon_hints._KNOWN_KINDS, (name, inner.lineno, kind)
                continue
            rows.add((name, inner.lineno, _name_reason(inner.exc.id, expr)))
    return rows


def test_every_raise_site_carries_a_named_kind():
    """The automated form of the audit: no literal-message raise reaches a caller
    UNKNOWN.

    Fails two ways on purpose — a new unclassified site (a regression) and a baseline
    row that no longer matches a site (a stale row) — so each domain PR must delete its
    own rows and the last one empties the baseline.  A raise the walk cannot read at all
    is pinned by ``_UNJUDGEABLE``, also by equality.
    """
    addon_dir = pathlib.Path(__file__).resolve().parent.parent / "addon" / "server"
    unknown: set[tuple[str, str]] = set()
    unjudgeable: set[tuple[str, int, str]] = set()
    for path in sorted(addon_dir.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        unjudgeable |= _unresolved_raises(module, path.name)
        for kind, msg in _judged(module):
            if kind == "UNKNOWN":
                unknown.add((path.name, msg))
            else:
                assert kind in addon_hints._KNOWN_KINDS, (path.name, kind, msg)

    new = unknown - _UNCLASSIFIED_BASELINE
    stale = _UNCLASSIFIED_BASELINE - unknown
    assert not new, f"unclassified raises with no baseline row:\n{sorted(new)}"
    assert not stale, f"baseline rows that no longer match a site:\n{sorted(stale)}"
    assert unjudgeable == _UNJUDGEABLE, sorted(unjudgeable ^ _UNJUDGEABLE)


def test_a_typed_raise_is_judged_by_the_kind_it_states():
    """Both spellings: the kind reaches the caller, so no regex is involved.

    ``rules.py`` bans the by-name spelling inside the add-in, so every site the domain
    tasks convert writes ``_hints.Refusal``.  Read as a bare name only, such a raise
    was treated as a message, and the *kind string* was looked up in the rules — which
    is how ``classify("BODY_NOT_FOUND")`` became an ``UNKNOWN`` row named after a kind.
    """
    for source in (
        'raise Refusal("BODY_NOT_FOUND", "x")',
        'raise _hints.Refusal("BODY_NOT_FOUND", "x")',
        'raise _hints.Refusal("BODY_NOT_FOUND", "x", hints=("h",))',
    ):
        assert _judged(ast.parse(source)) == {("BODY_NOT_FOUND", "x"): "typed"}


def test_a_raise_the_walk_cannot_read_is_listed_with_its_reason():
    """A computed kind or message is named, never skipped and never guessed."""
    module = ast.parse(
        "def f(kind, flag):\n"
        "    if flag:\n"
        '        raise _hints.Refusal(kind, "boom")\n'
        "    if refusal := _rules.x_refusal(flag):\n"
        "        raise refusal\n"
        "    raise RuntimeError(compute())\n"
    )
    assert _judged(module) == {}
    assert _unresolved_raises(module, "snippet.py") == {
        ("snippet.py", 3, "kind is not a string literal"),
        ("snippet.py", 5, "raise refusal: kind comes from _rules.x_refusal"),
        ("snippet.py", 6, "message is not a literal"),
    }


def test_a_refusal_raised_through_a_name_is_judged_from_its_binding():
    """The one-level resolve D8 anticipates; no site in the tree has the shape yet."""
    module = ast.parse(
        "def f():\n"
        '    refusal = Refusal("BODY_NOT_FOUND", "no body")\n'
        "    raise refusal\n"
    )
    assert _unresolved_raises(module, "snippet.py") == set()
    typo = ast.parse(
        "def f():\n"
        '    refusal = Refusal("BODY_NOT_FOUNDX", "no body")\n'
        "    raise refusal\n"
    )
    with pytest.raises(AssertionError):
        _unresolved_raises(typo, "snippet.py")


def test_every_refusal_built_in_rules_names_a_known_kind():
    """``rules.py`` is the only place a validator's kind is written down.

    A handler raises what a validator returned, so the walk above records the site and
    never sees the kind.  ``tests/test_rules.py`` compares the add-in with the *mirror*
    of that same file, so a mistyped kind agrees on both sides and parity stays green —
    this is the one assertion that reads the literal.
    """
    addon_dir = pathlib.Path(__file__).resolve().parent.parent / "addon" / "server"
    module = ast.parse((addon_dir / "rules.py").read_text(encoding="utf-8"))
    built = 0
    for node in ast.walk(module):
        call = _refusal_call(node)
        if call is None:
            continue
        built += 1
        kind = _literal_kind(call)
        assert kind is not None, (call.lineno, "kind is not a string literal")
        assert kind in addon_hints._KNOWN_KINDS, (call.lineno, kind)
    assert built, "no Refusal construction found in addon/server/rules.py"
