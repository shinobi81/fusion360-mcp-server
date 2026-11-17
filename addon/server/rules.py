"""
Validation both the add-in and mock mode apply before Fusion sees a parameter.

The handler refuses an input it can judge from the parameters alone — two edge
selectors at once, an index that is not a whole number, a ``target_body`` on a call
that builds a new body — and mock mode has no Fusion to refuse anything, so it has to
apply the same checks to answer with what the add-in would.  The messages live here
once, with the ``error_kind`` each one already carried.

Pure by design: no ``adsk``, no I/O, no import of the handler or of mock mode, so the
server package can import its copy.

This file is canonical — the addon is installed into Fusion's AddIns folder at deploy
time and cannot import from the MCP server package, so ``src/fusion360_mcp/_rules.py``
is generated from it.  Edit here, then run ``uv run python scripts/sync_mirrors.py``; a
hand edit in the ``src`` copy is overwritten.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# ``_hints.Refusal``, not ``from .hints import Refusal``: the add-in reloads these
# modules in place, and a by-name import would keep the class object that was
# imported first.  ``hints.classify`` tests ``isinstance(exc, Refusal)`` against the
# fresh class, so every refusal built here would fall back to the regex table - and
# that table answers the same today, so nothing would report the drift.
from . import hints as _hints

#: The four edge selectors ``fillet`` and ``chamfer`` accept.  ``tools.py`` advertises
#: this tuple as the schema enum and refuses nothing itself, so the validator owns the
#: set: a fifth selector is one edit here plus the branch that handles it.
EDGE_SELECTIONS = ("all", "top", "bottom", "vertical")


def edge_selector_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an edge selector's parameters earn, or None when they are usable.

    ``params`` carries ``edge_selection``, ``edge_indices`` and ``edge_points`` as the
    caller sent them, ``None`` meaning unset.  Only the parameters are judged: whether
    the body has any edges, and which edges a selection matches, needs Fusion.

    One selector at a time.  A caller that passes two has not decided which edges it
    means, and picking one would silently round whatever the other happened to match.
    ``all`` is the default, so it is the one selection that means "unset".  Indices are
    positional, so a stale one and an empty list are both caller mistakes Fusion cannot
    detect — the message names the selector to use instead.
    """
    indices = params.get("edge_indices")
    points = params.get("edge_points")
    selection = params.get("edge_selection", "all")

    if indices is not None and points is not None:
        return _hints.Refusal(
            "INVALID_INPUT",
            "Pass only one of edge_indices and edge_points — they name the same "
            "edges two ways, so one would be ignored",
        )
    if (indices is not None or points is not None) and selection != "all":
        return _hints.Refusal(
            "INVALID_INPUT",
            f"edge_selection '{selection}' cannot be combined with edge_indices "
            "or edge_points — pass one selector, not two",
        )
    if indices is not None and not isinstance(indices, (list, tuple)):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"edge_indices needs a list of whole numbers, got {indices!r}",
        )
    if points is not None and not isinstance(points, (list, tuple)):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"edge_points needs a list of three-number points, got {points!r}",
        )
    if indices is not None and not indices:
        return _hints.Refusal(
            "INVALID_INPUT",
            "edge_indices was empty — name at least one edge, or omit it to use "
            "edge_selection",
        )
    if points is not None and not points:
        return _hints.Refusal(
            "INVALID_INPUT",
            "edge_points was empty — name at least one point, or omit it to use "
            "edge_selection",
        )
    for index in indices or []:
        if isinstance(index, bool) or not isinstance(index, int):
            return _hints.Refusal(
                "INVALID_INPUT",
                f"Edge index {index!r} is out of range — indices are whole numbers "
                "from list_edges",
            )
    for point in points or []:
        # Shape before count: a bare number is not a point, and ``len`` of one is a
        # TypeError — so ``3`` must not read as "three coordinates".
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            got = len(point) if isinstance(point, (list, tuple)) else repr(point)
            return _hints.Refusal(
                "INVALID_INPUT",
                f"Each edge point needs three coordinates, got {got}",
            )
    if selection not in EDGE_SELECTIONS:
        return _hints.Refusal(
            "INVALID_INPUT",
            f"Unknown edge_selection '{selection}' — use all/top/bottom/vertical",
        )
    return None


def target_body_refusal(
    params: Mapping[str, Any], operation: str
) -> _hints.Refusal | None:
    """The refusal a ``target_body`` beside a new body earns, or None.

    ``operation`` decides it, not the body: a new body is the feature's output, so
    there is nothing to target, and Fusion is never asked.  An unknown *name* is not
    judged here — that takes the design, which mock mode does not have.
    """
    if params.get("target_body") is None or operation != "new_body":
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Invalid input: target_body applies only to cut, join or intersect — "
        "new_body builds a body of its own, so there is nothing to target",
    )


def components_differ_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a joint between one component and itself earns, or None.

    Two occurrences of the same component have no relative motion, so Fusion is
    never asked.  The names are compared, not the occurrences: a handler has
    already resolved them, and mock mode has no design to resolve them in.
    """
    component_one = params.get("component_one")
    component_two = params.get("component_two")
    if component_one is None or component_two is None or component_one != component_two:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "component_one and component_two must differ",
        hints=("Pass two different components; a joint needs two.",),
    )


def joint_geometry_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an ``add_joint`` without a face pair earns, or None.

    A joint cannot be built from the components' origin points: a bare point
    carries no component association, so ``JointGeometry.createByPoint`` rejects
    it.  Whether the named face exists needs Fusion; that it was named does not.
    """
    if params.get("face_one") is not None and params.get("face_two") is not None:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "add_joint needs joint geometry: pass face_one/face_two "
        "(and body_one/body_two when a component holds more than one body). "
        "Component origin points are not valid joint geometry.",
        hints=(
            "Pass face_one and face_two.",
            "Add body_one/body_two when the component holds more than one body.",
        ),
    )


def as_built_geometry_refusal(
    params: Mapping[str, Any],
) -> _hints.Refusal | None:
    """The refusal a non-rigid as-built joint without a face pair earns, or None.

    Fusion refuses the input with "Geometry should not be null if joint motion is
    not rigid", so only ``rigid`` works without geometry.  ``joint_type`` decides
    it, and an omitted one is the handler's ``rigid`` default.
    """
    joint_type = params.get("joint_type", "rigid")
    if joint_type == "rigid":
        return None
    if params.get("face_one") is not None and params.get("face_two") is not None:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"A {joint_type} as-built joint needs geometry: pass face_one/face_two "
        "(and body_one/body_two when a component holds more than one body). "
        "Only 'rigid' works without it.",
        hints=("Pass face_one and face_two, or use joint_type='rigid'.",),
    )


def rigid_group_size_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a rigid group of fewer than two components earns, or None.

    ``params`` carries the names that resolved to occurrences, so this is what the
    add-in checks before ``rigidGroups.add``; mock mode judges the names it was
    given, which is all it has.  A group of one holds nothing together.
    """
    names = params.get("component_names") or ()
    if len(names) >= 2:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Need at least 2 components for rigid group",
        hints=("Pass at least two component names.",),
    )


def construction_method_refusal(
    params: Mapping[str, Any],
) -> _hints.Refusal | None:
    """The refusal a tangent construction plane earns, or None.

    A tangent plane needs a face to be tangent to, and the tool has no face
    parameter, so the call cannot be built.  The method stays in the schema for
    wire compatibility, where ``execute_code`` is the route that works.
    """
    if params.get("method") != "tangent":
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Tangent plane needs face selection—use execute_code",
        hints=(
            "create_construction_plane has no face parameter; build this plane "
            "with execute_code.",
        ),
    )


def perpendicular_axis_refusal(
    params: Mapping[str, Any],
) -> _hints.Refusal | None:
    """The refusal a perpendicular construction axis earns, or None.

    ``setByPerpendicularAtPoint(face, pointEntity)`` needs a B-Rep face, which
    this tool has no parameter for, so the call cannot be built; the method stays
    in the schema for wire compatibility.
    """
    if params.get("method") != "perpendicular_at_point":
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Perpendicular axis needs a B-Rep face, which this tool has no "
        "parameter for — use execute_code; the method stays in the "
        "schema for wire compatibility",
        hints=(
            "The schema advertises this method for wire compatibility; "
            "use execute_code.",
        ),
    )


def rule_type_refusal(rule_type: str) -> _hints.Refusal | None:
    """The refusal a ``ruled_surface`` ``rule_type`` earns, or None when it is usable.

    The schema's enum is advisory: a socket caller is not the schema, so an unknown
    value reaches the handler, and a bare ``KeyError`` classified as ``UNKNOWN`` tells
    it nothing.  Judged from the parameter alone, so mock mode refuses it too instead
    of rehearsing a call Fusion rejects.
    """
    if rule_type in ("normal", "tangent"):
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"Unknown rule_type {rule_type!r} - use 'normal' or 'tangent'",
    )


def sketch_plane_z_note() -> str:
    """What the caller is told when a ``z`` was projected away onto the sketch plane.

    A success note, never a refusal: the geometry exists, in the sketch plane, and the
    note is the only thing that says the ``z`` did not move it.  Mock mode reports it
    too, so it is one sentence rather than two copies of one.
    """
    return (
        "Sketch curves lie in the sketch plane, so the z component was "
        "dropped instead of being added to the plane's own offset. "
        "Use create_sketch(z_offset=...) to move the plane itself."
    )
