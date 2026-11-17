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


# ── the guard: no raise reaches a caller as UNKNOWN ──────────────────

#: Raises that still reach a caller as ``UNKNOWN``.  PRs 4a-8 delete their own rows;
#: the last one empties this set.  A row here is a debt, not an exemption.
_UNCLASSIFIED_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        (
            "handler_assembly.py",
            "'…' has motion …, which this command cannot drive; known types: …",
        ),
        ("handler_assembly.py", "'…' is a rigid joint; it has no value to drive"),
        (
            "handler_assembly.py",
            "A joint frame is required to place axis '…' — internal error",
        ),
        (
            "handler_assembly.py",
            "A … as-built joint needs geometry: pass face_one/face_two (and "
            + "body_one/body_two when a component holds more than one body). Only "
            + "'rigid' works without it.",
        ),
        (
            "handler_assembly.py",
            "Component '…' has … bodies; pass '…' to choose which body carries the "
            + "joint geometry",
        ),
        (
            "handler_assembly.py",
            "Face index … is out of range for body '…' (… faces). Enumerate them "
            + "with get_object_info and pick a cylindrical face.",
        ),
        (
            "handler_assembly.py",
            "Fusion did not keep the requested value on '…' (set … …, read back …). "
            + "A design.computeAll() after setting a joint value resets it to zero.",
        ),
        ("handler_assembly.py", "Need at least 2 components for rigid group"),
        (
            "handler_assembly.py",
            "No as-built joints in the design; pass as_built=False for regular "
            + "joints or create one first",
        ),
        ("handler_assembly.py", "One or both components not found"),
        (
            "handler_assembly.py",
            "Perpendicular axis needs a B-Rep face, which this tool has no "
            + "parameter for — use execute_code; the method stays in the schema for "
            + "wire compatibility",
        ),
        ("handler_assembly.py", "Tangent plane needs face selection—use execute_code"),
        ("handler_assembly.py", "Unknown axis: …. Use one of …"),
        ("handler_assembly.py", "Unknown joint type: …. Use one of …"),
        ("handler_assembly.py", "Unknown key_point: …. Use one of …"),
        ("handler_assembly.py", "Unknown method: …"),
        ("handler_assembly.py", "Unknown quadrant/key_point: …/…"),
        ("handler_assembly.py", "Unknown quadrant: …. Use one of …"),
        (
            "handler_assembly.py",
            "add_joint needs joint geometry: pass face_one/face_two (and "
            + "body_one/body_two when a component holds more than one body). "
            + "Component origin points are not valid joint geometry.",
        ),
        ("handler_assembly.py", "component_one and component_two must differ"),
        ("handler_assembly.py", "value_kind '…' does not apply to …; use one of …"),
        ("handler_assembly.py", "…joint '…' not found (… …joints in the design)"),
        ("handler_base.py", "A body name is required"),
        ("handler_base.py", "Component '…' not found"),
        ("handler_base.py", "Feature '…' not found in timeline"),
        ("handler_base.py", "Unknown axis '…' — use x, y, or z"),
        ("handler_base.py", "Unknown plane … — use xy, yz, or xz"),
        ("handler_base.py", "… must be [x, y, z] in centimetres"),
        ("handler_cam.py", "Fusion rejected strategy '…' for setup '…'"),
        (
            "handler_cam.py",
            "No CAM workspace found. Open the Manufacturing workspace in Fusion 360 "
            + "at least once to initialise it.",
        ),
        ("handler_cam.py", "Post processor not found: …"),
        ("handler_cam.py", "Provide setup_name, operation_name, or generate_all=true"),
        (
            "handler_cam.py",
            "This Fusion build has no local generic post folder (posts are "
            + "cloud-library based). Pass the full path to the .cps file in "
            + "'post_processor' instead of a short name.",
        ),
        ("handler_export.py", "Mesh file not found: …"),
        ("handler_export.py", "No active viewport"),
        ("handler_export.py", "No mesh bodies imported from …"),
        ("handler_export.py", "No mesh body imported from …"),
        (
            "handler_export.py",
            "Specify format (stl/step/f3d) or file_path with extension",
        ),
        ("handler_export.py", "Unknown format: …. Expected: stl, step, f3d"),
        ("handler_export.py", "Unknown units '…'. Expected one of: …"),
        ("handler_export.py", "Unknown view '…'. Expected: current, …"),
        ("handler_export.py", "Unknown views: …. Valid: …"),
        ("handler_export.py", "body_name required for STEP export"),
        ("handler_export.py", "body_name required for STL export"),
        ("handler_export.py", "saveAsImageFile returned false"),
        ("handler_features.py", "Body '…' …, so no point can select an edge"),
        ("handler_features.py", "No near-horizontal …-facing planar face on '…'"),
        (
            "handler_primitives.py",
            "Undo aborted: stepping the timeline back to … changed the design type "
            + "from … to …. The marker was restored. If the design is stuck in direct "
            + "mode, call set_design_type('parametric') to capture history again, "
            + "then delete the failed feature explicitly.",
        ),
        (
            "handler_primitives.py",
            "Undo command is not available in the current workspace. The design was "
            + "NOT modified — delete the failed feature explicitly instead.",
        ),
        (
            "handler_primitives.py",
            "delete_all did not clear the design — remaining: …. Deleted: …. "
            + "Failures: …",
        ),
        ("handler_scene.py", "Appearance '…' not found"),
        ("handler_scene.py", "Could not copy appearance '…' into the design"),
        ("handler_scene.py", "Could not obtain polygon mesh data"),
        ("handler_scene.py", "Entity '…' not found"),
        ("handler_scene.py", "Invalid design_type '…'. Use 'parametric' or 'direct'."),
        ("handler_scene.py", "Need at least 2 components with bodies"),
        ("handler_scene.py", "New document has no design product"),
        ("handler_scene.py", "No appearance library found"),
        ("handler_scene.py", "Parameter '…' not found"),
        ("handler_scene.py", "SyntaxError: …\n…"),
        ("handler_scene.py", "compareWith returned no deviation data"),
        (
            "handler_sketch.py",
            "Invalid result_option … — use 1 (thorough), 2 (fast), or 3 (may adjust "
            + "geometry within tolerance).",
        ),
        ("handler_sketch.py", "Unknown axis: … - use x or y"),
        (
            "handler_sketch.py",
            "autoConstrain returned no result — the sketch is not eligible for "
            + "geometry adjustment. Retry with result_option 1 or 2.",
        ),
        ("handler_sketch.py", "count must be at least 1"),
        (
            "handler_sketch.py",
            "symmetry needs symmetry_line — the index of the sketch line the two "
            + "entities are mirrored about",
        ),
        ("handler_surface.py", "No planar face found for stationary face"),
        (
            "handler_surface.py",
            "keep … does not apply to a body tool - use one of …; a plane tool "
            + "takes …",
        ),
        (
            "handler_surface.py",
            "keep … does not apply to a plane tool - use one of …; a body tool "
            + "takes …",
        ),
        ("handler_surface.py", "keep_cells takes cell indices, not …"),
        (
            "handler_surface.py",
            "keep_cells … is out of range - this trim produced … cell(s), indexed "
            + "from 0",
        ),
        ("handler_surface.py", "line_position … is not one of …"),
        (
            "handler_surface.py",
            "trim_surface needs exactly one of tool_name (a body) or tool_plane "
            + "(xy, xz or yz)",
        ),
        ("handler_surface.py", "… has no line to bend along"),
        ("handler_surface.py", "… has no planar face to take a side from"),
        ("handler_surface.py", "… is not planar"),
        ("hole_geometry.py", "plane is vertical: no unique Z above (x, y)"),
    }
)

#: Raises the static walk cannot judge, each with why.  Never silently skipped.
_UNJUDGEABLE: frozenset[tuple[str, int, str]] = frozenset(
    {
        ("event_bridge.py", 98, "raise <name> unresolved"),
        ("handler_features.py", 41, "raise <name> unresolved"),
        ("handler_features.py", 93, "raise <name> unresolved"),
        ("handler_surface.py", 120, "raise <name> unresolved"),
    }
)

_RENDER = "…"  # what a FormattedValue collapses to; every rule anchors on literals


def _rendered(arg: ast.expr) -> str | None:
    """A literal message with interpolated parts collapsed, or None for a value.

    Every rule anchors on literals, so a ``FormattedValue`` becomes ``_RENDER`` and
    the site is judged by the fixed text it does say.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr):
        return "".join(
            str(p.value) if isinstance(p, ast.Constant) else _RENDER for p in arg.values
        )
    return None


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
    return _rendered(exc.args[index])


def _judged(module: ast.Module) -> dict[tuple[str, str], str]:
    """``{(kind_or_'?', message): why}`` for every raise this test can judge."""
    found: dict[tuple[str, str], str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        if isinstance(exc, ast.Call) and getattr(exc.func, "id", None) == "Refusal":
            first = exc.args[0] if exc.args else None
            kind = first.value if isinstance(first, ast.Constant) else "?"
            found[(str(kind), _message_of(node, refusal=True) or "")] = "typed"
            continue
        msg = _message_of(node)
        if msg is not None:
            found[(addon_hints.classify(msg)[0], msg)] = "classified"
    return found


def test_every_raise_site_carries_a_named_kind():
    """The automated form of the audit: no literal-message raise reaches a caller
    UNKNOWN.

    Fails two ways on purpose — a new unclassified site (a regression) and a baseline
    row that no longer matches a site (a stale row), so each domain PR must delete its
    own rows and the last one empties the baseline.
    """
    addon_dir = pathlib.Path(__file__).resolve().parent.parent / "addon" / "server"
    unknown: set[tuple[str, str]] = set()
    unjudgeable: set[tuple[str, int, str]] = set()
    for path in sorted(addon_dir.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(module):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # `refusal = Refusal(kind, ...)` then `raise refusal`: resolve one level,
            # which is what every current site does. A binding this cannot resolve is
            # listed with its reason rather than passing quietly (spec D8).
            bound: dict[str, str] = {}
            for inner in ast.walk(func):
                if not (
                    isinstance(inner, ast.Assign) and isinstance(inner.value, ast.Call)
                ):
                    continue
                call = inner.value
                if getattr(call.func, "id", None) != "Refusal" or not call.args:
                    continue
                first = call.args[0]
                if not isinstance(first, ast.Constant):
                    continue
                for target in inner.targets:
                    if isinstance(target, ast.Name):
                        bound[target.id] = str(first.value)
            for inner in ast.walk(func):
                if not isinstance(inner, ast.Raise):
                    continue
                if not isinstance(inner.exc, ast.Name):
                    continue
                kind = bound.get(inner.exc.id)
                if kind is None:
                    unjudgeable.add(
                        (path.name, inner.lineno, "raise <name> unresolved")
                    )
                else:
                    assert kind in addon_hints._KNOWN_KINDS, (
                        path.name,
                        inner.lineno,
                        kind,
                    )
                    assert addon_hints._hints_for(
                        addon_hints.Refusal(kind, "raised through a name")
                    ), (path.name, inner.lineno, "no hints")
        for kind, msg in _judged(module):
            if kind == "?":
                continue
            if kind == "UNKNOWN":
                unknown.add((path.name, msg))
            else:
                assert kind in addon_hints._KNOWN_KINDS, (path.name, kind, msg)
                assert addon_hints._hints_for(addon_hints.Refusal(kind, msg or "x")), (
                    path.name,
                    kind,
                    "no hints",
                )

    new = unknown - _UNCLASSIFIED_BASELINE
    stale = _UNCLASSIFIED_BASELINE - unknown
    assert not new, f"unclassified raises with no baseline row:\n{sorted(new)}"
    assert not stale, f"baseline rows that no longer match a site:\n{sorted(stale)}"
    assert unjudgeable == _UNJUDGEABLE, sorted(unjudgeable ^ _UNJUDGEABLE)


def _refusal_call(node: ast.AST) -> ast.Call | None:
    """The ``Refusal(...)`` construction *node* spells, under either import style."""
    if not isinstance(node, ast.Call):
        return None
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    return node if name == "Refusal" else None


def _hint_literals(call: ast.Call) -> tuple[str, ...]:
    """The literal hints a ``Refusal(...)`` passes, positionally or as ``hints=``."""
    node = call.args[2] if len(call.args) > 2 else None
    for keyword in call.keywords:
        if keyword.arg == "hints":
            node = keyword.value
    if not isinstance(node, ast.Tuple):
        return ()
    return tuple(
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )


def test_every_refusal_built_in_rules_names_a_known_kind():
    """``rules.py`` is the only place a validator's kind is written down.

    A handler raises what a validator returned, so the walk above records the site as
    unjudgeable and never sees the kind.  ``tests/test_rules.py`` compares the add-in
    with the *mirror* of that same file, so a mistyped kind agrees on both sides and
    parity stays green — this is the one assertion that reads the literal.
    """
    addon_dir = pathlib.Path(__file__).resolve().parent.parent / "addon" / "server"
    module = ast.parse((addon_dir / "rules.py").read_text(encoding="utf-8"))
    built = 0
    for node in ast.walk(module):
        call = _refusal_call(node)
        if call is None:
            continue
        built += 1
        assert len(call.args) > 1, (call.lineno, "kind and message are positional")
        kind_arg = call.args[0]
        assert isinstance(kind_arg, ast.Constant) and isinstance(kind_arg.value, str), (
            call.lineno,
            "kind is not a string literal",
        )
        kind = kind_arg.value
        assert kind in addon_hints._KNOWN_KINDS, (call.lineno, kind)
        assert addon_hints._hints_for(
            addon_hints.Refusal(
                kind, _rendered(call.args[1]) or "x", _hint_literals(call)
            )
        ), (call.lineno, kind, "no hints")
    assert built, "no Refusal construction found in addon/server/rules.py"
