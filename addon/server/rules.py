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

from .hints import Refusal

#: The four edge selectors ``fillet`` and ``chamfer`` accept.  ``tools.py`` advertises
#: this tuple as the schema enum and refuses nothing itself, so the validator owns the
#: set: a fifth selector is one edit here plus the branch that handles it.
EDGE_SELECTIONS = ("all", "top", "bottom", "vertical")


def edge_selector_refusal(params: Mapping[str, Any]) -> Refusal | None:
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
        return Refusal(
            "INVALID_INPUT",
            "Pass only one of edge_indices and edge_points — they name the same "
            "edges two ways, so one would be ignored",
        )
    if (indices is not None or points is not None) and selection != "all":
        return Refusal(
            "INVALID_INPUT",
            f"edge_selection '{selection}' cannot be combined with edge_indices "
            "or edge_points — pass one selector, not two",
        )
    if indices is not None and not indices:
        return Refusal(
            "INVALID_INPUT",
            "edge_indices was empty — name at least one edge, or omit it to use "
            "edge_selection",
        )
    if points is not None and not points:
        return Refusal(
            "INVALID_INPUT",
            "edge_points was empty — name at least one point, or omit it to use "
            "edge_selection",
        )
    for index in indices or []:
        if isinstance(index, bool) or not isinstance(index, int):
            return Refusal(
                "INVALID_INPUT",
                f"Edge index {index!r} is out of range — indices are whole numbers "
                "from list_edges",
            )
    for point in points or []:
        coordinates = len(point) if isinstance(point, (list, tuple)) else point
        if coordinates != 3:
            return Refusal(
                "INVALID_INPUT",
                f"Each edge point needs three coordinates, got {coordinates}",
            )
    if selection not in EDGE_SELECTIONS:
        return Refusal(
            "INVALID_INPUT",
            f"Unknown edge_selection '{selection}' — use all/top/bottom/vertical",
        )
    return None


def target_body_refusal(params: Mapping[str, Any], operation: str) -> Refusal | None:
    """The refusal a ``target_body`` beside a new body earns, or None.

    ``operation`` decides it, not the body: a new body is the feature's output, so
    there is nothing to target, and Fusion is never asked.  An unknown *name* is not
    judged here — that takes the design, which mock mode does not have.
    """
    if params.get("target_body") is None or operation != "new_body":
        return None
    return Refusal(
        "INVALID_INPUT",
        "Invalid input: target_body applies only to cut, join or intersect — "
        "new_body builds a body of its own, so there is nothing to target",
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
