"""
Error classification for Fusion API failures (mirror of addon copy).

This module is used in mock mode and in tests.  The canonical table lives
in ``addon/server/hints.py`` because the addon is installed into Fusion's
AddIns folder and cannot import from this package.  Keep them in sync.
"""

import re

# Each entry: (regex applied to str(exc), error_kind, hints)
# First match wins. Patterns use re.IGNORECASE.
_RULES: list[tuple[str, str, list[str]]] = [
    (
        r"no active design",
        "NO_ACTIVE_DESIGN",
        [
            "Open or create a design in Fusion before calling mutation tools.",
            "Use get_design_type to confirm the active product is a design.",
        ],
    ),
    (
        r"no profiles? in sketch",
        "PROFILE_NOT_CLOSED",
        [
            "The sketch has no closed profile to extrude/revolve.",
            "Check that your curves form a closed loop — draw_line segments "
            "must share endpoints exactly (use add_constraint coincident).",
            "Inspect the sketch with get_scene_info — a sketch with 0 profiles "
            "is never extrudable.",
        ],
    ),
    # BODY is matched before SKETCH, and both anchor on the quoted name. The
    # obvious "keyword .* not found" pattern spans the whole message, so a body
    # named "Sketch1" was reported as SKETCH_NOT_FOUND. The distance-capped
    # fallback still catches Fusion's own unquoted wording.
    (
        r"no body\b"
        r"|body\s+['\"][^'\"]*['\"]\s+(?:not found|does not exist)"
        r"|body\b[^.\n]{0,25}?\bnot found",
        "BODY_NOT_FOUND",
        [
            "The named body does not exist in the active design.",
            "Use list_components or get_scene_info to see available bodies.",
        ],
    ),
    (
        r"no sketch\b"
        r"|sketch\s+['\"][^'\"]*['\"]\s+(?:not found|does not exist)"
        r"|sketch\b[^.\n]{0,25}?\bnot found",
        "SKETCH_NOT_FOUND",
        [
            "The named sketch does not exist in the active design.",
            "List sketches via get_scene_info before referencing one by name.",
        ],
    ),
    (
        r"self[- ]?intersect",
        "SELF_INTERSECTION",
        [
            "The resulting geometry self-intersects — Fusion cannot resolve it.",
            "For sweeps: check the path curvature vs. the profile size.",
            "For lofts: ensure profiles are oriented consistently.",
            "Try reducing the feature size, or split into smaller operations.",
        ],
    ),
    (
        r"regenerat(e|ion) fail|feature\s+fail(ed|ure)|rebuild fail",
        "REGEN_FAILED",
        [
            "Fusion could not regenerate the feature with these inputs.",
            "Check for references to deleted geometry upstream in the timeline.",
            "Try undo, then attempt the mutation with different parameters.",
        ],
    ),
    (
        r"boolean.*(empty|no[- ]?op|no result|failed)|subtract.*empty",
        "BOOLEAN_NO_OP",
        [
            "Boolean operation produced no change — tool and target do not "
            "intersect, or the result would be identical to the target.",
            "Verify the tool body actually overlaps the target — use "
            "check_interference.",
            "For subtract: confirm the tool body is inside or crosses the target.",
            "Consider move_body to reposition before retrying.",
        ],
    ),
    (
        r"revolve axis .{0,40}?sketch plane",
        "AXIS_OUT_OF_PLANE",
        [
            "The axis is a construction line in the profile's sketch.",
            "So it must be coplanar with the profile: one sketch plane.",
            "axis_origin/axis_direction are model space (cm).",
            "World directions x/y/z use the model axes, no coplanarity.",
        ],
    ),
    (
        # Ahead of the generic INVALID_INPUT rule below, whose pattern
        # ("invalid parameter") also matches this message. Fusion never saw the
        # value -- the add-in refused it -- so that rule's units and enum hints
        # would point the caller at the wrong cause.
        r"is not finite",
        "INVALID_INPUT",
        [
            # One line each: a wrapped pair in a list trips CodeQL's
            # implicit-concatenation query, which cannot tell a deliberate wrap
            # from a missing comma.
            "inf, -inf and nan are not numbers Fusion can store; nothing was written.",
            "Send a finite number, or set the real value later with set_parameter.",
        ],
    ),
    (
        # The add-in refuses this itself, before any CAM object exists: tool
        # geometry belongs to the tool library, so there is no diameter to set
        # on an operation. Without a rule it classified as UNKNOWN with no
        # hints, and the caller had no way to learn where the diameter lives.
        r"tool_diameter cannot be set",
        "INVALID_INPUT",
        [
            "An operation takes a tool, not a diameter; nothing was written.",
            "Set the diameter on the tool itself, then pass tool_number.",
        ],
    ),
    (
        # The CAM entry point refuses this itself, before an operation exists.
        # Without the rule it was UNKNOWN with no hints, so the caller could not
        # learn the three words Fusion accepts.
        r"unknown operation_type",
        "INVALID_INPUT",
        [
            "That CAM operation type does not exist; nothing was written.",
            "Use operation_type milling, turning or cutting.",
        ],
    ),
    (
        # Our CAM lookups quote the name they could not find.  Anchored on the
        # quoted name so the BODY/SKETCH rules above keep their own wording.
        r"(?:setup|operation)\s+['\"][^'\"]*['\"]\s+(?:not found|does not exist)",
        "INVALID_INPUT",
        [
            "No CAM setup or operation in this design has that name.",
            "cam_list_setups (then cam_list_operations) lists the real names.",
        ],
    ),
    (
        # Every feature tool raises this itself for a mistyped ``operation``.
        # Without a rule it classified as UNKNOWN with no hints, so a caller that
        # wrote ``union`` was told nothing at all. Anchored on the quoted name so
        # the CAM rule above keeps its own wording for ``operation_type``.
        r"unknown (?:boolean )?(?:operation|op)\s+'",
        "INVALID_INPUT",
        [
            "Fusion has no operation by that name; nothing was written.",
            "Features take new_body/join/cut/intersect, booleans join/cut/intersect.",
        ],
    ),
    (
        # Fusion's own refusal ("A loft needs at least two sections") classified
        # as UNKNOWN with no hints. The add-in checks first so the caller is told
        # what a loft actually needs.
        r"a loft needs at least two",
        "INVALID_INPUT",
        [
            "A loft interpolates between sections; nothing was written.",
            "Pass two or more profile_sketch_names, in loft order.",
        ],
    ),
    (
        # A caller who passes two selectors has not decided which edges to round;
        # picking one silently would round whatever the other happened to match.
        r"only one of edge_indices|cannot be combined with edge_indices",
        "INVALID_INPUT",
        [
            "Only one edge selector applies at a time; nothing was written.",
            "Pass edge_indices, or edge_points, or edge_selection — not two.",
        ],
    ),
    (
        # Indices are positional: a stale one and an empty list are both caller
        # mistakes that Fusion cannot detect, so the refusal has to explain them.
        r"edge index \S+ is out of range|edge_indices was empty|edge_points was empty",
        "INVALID_INPUT",
        [
            "Edge indices are positional and come from list_edges.",
            "Re-run list_edges after the body changes — an index can move.",
        ],
    ),
    (
        # A body whose edges all reported a dead parameter range cannot be probed
        # by point.  Without a rule this classified as UNKNOWN with no hints — the
        # failure mode AGENTS.md says must never ship.
        r"no usable parameter range",
        "INVALID_INPUT",
        [
            "No edge on that body could be measured; nothing was written.",
            "Call list_edges and choose with edge_indices instead.",
        ],
    ),
    (
        # Point selection can fail three ways, and every one of them names the
        # measurement the caller needs to fix it rather than "no edges matched".
        r"no edge within .* cm of|equally close to edges|has no edges, so no point"
        r"|edge point needs three coordinates",
        "INVALID_INPUT",
        [
            "No single edge matched that point; nothing was written.",
            "Call list_edges and select by edge_indices, or raise edge_tolerance.",
        ],
    ),
    (
        # Two causes, two messages, and the hint has to fit both: a body with no
        # edges has nothing to list, so pointing such a caller at list_edges would
        # send them to an empty answer.
        r"has no edges to select from|has no edges that can be rounded",
        "INVALID_INPUT",
        [
            "That body has nothing a fillet can round; nothing was written.",
            "A degenerate edge (a cone's apex) has no geometry. Check the body and "
            "its edges with list_edges before choosing a selector.",
        ],
    ),
    (
        # The coarse selectors take the highest / lowest plane that holds an
        # *edge*.  Nothing matching is a real answer — a body whose top is a
        # curved surface has no edge in a top plane — and live it classified as
        # UNKNOWN with no hints, which AGENTS.md says must never ship.
        r"no edges matched selection",
        "INVALID_INPUT",
        [
            "No edge of that body lies in the selected plane; nothing was written.",
            "Call list_edges and pick with edge_indices or edge_points: top and "
            "bottom take the highest/lowest edges, which is empty when the body's "
            "extreme is a curved surface.",
        ],
    ),
    (
        # The message already lists the four it accepts; without a rule the
        # caller got UNKNOWN and a traceback for a one-word typo.
        r"unknown edge_selection",
        "INVALID_INPUT",
        [
            "edge_selection is one of all / top / bottom / vertical.",
            "Pass edge_indices or edge_points to name edges exactly.",
        ],
    ),
    (
        # Fusion's own refusal when a cut reaches no body — found live on a sweep
        # whose profile sat outside every block. It classified as UNKNOWN with no
        # hints, so the caller learned nothing about why nothing was cut.
        r"no intersecting target body|NO_TARGET_SWEEP_BODY",
        "INVALID_INPUT",
        [
            "The feature reaches no body, so there is nothing to cut.",
            "Move the profile until it overlaps a body, then retry.",
        ],
    ),
    (
        # The add-in refuses this itself, before a feature input exists: a new
        # body is the feature's output, so there is nothing to target. Without a
        # rule the generic "invalid input" hints pointed at units and enums for
        # a parameter whose only mistake was its operation.
        r"target_body applies only to",
        "INVALID_INPUT",
        [
            "A new body is the feature's output, so there is nothing to target.",
            "Pass target_body only with operation cut, join or intersect.",
        ],
    ),
    (
        r"invalid (argument|input|parameter)|bad (argument|input|value)",
        "INVALID_INPUT",
        [
            "Fusion rejected one of the parameters.",
            "Check units (all Fusion API values are in cm), enum values, and "
            "that referenced entities still exist.",
        ],
    ),
    (
        r"unknown command",
        "UNKNOWN_COMMAND",
        [
            "The add-in does not know this command — typo or version skew.",
            "Restart the addon (via reload_handler) if you recently added tools.",
        ],
    ),
    (
        r"profile.*(open|not closed|unclosed)",
        "PROFILE_NOT_CLOSED",
        [
            "The profile is open — extrude/revolve need a closed loop.",
            "Draw the missing segment or add coincident constraints at endpoints.",
        ],
    ),
    (
        r"timeout",
        "TIMEOUT",
        [
            "The operation exceeded the 30s bridge timeout.",
            "If a long operation is expected (CAM toolpath, complex fillet), "
            "split it into smaller steps.",
        ],
    ),
    (
        r"requires (?:parametric|direct[- ]edit)|"
        r"not (?:supported|permitted|allowed) in (?:parametric|direct[- ]edit)|"
        r"switch to (?:parametric|direct[- ]edit)",
        "DESIGN_TYPE_MISMATCH",
        [
            "This operation is not permitted in the current design type.",
            "Check get_design_type; some operations (like undo after direct "
            "edits) require parametric mode.",
        ],
    ),
    (
        r"not available since user is restricted|user is restricted"
        r"|not entitled|entitlement"
        r"|requires? an? (?:active |paid )?subscription",
        "NOT_ENTITLED",
        [
            "Fusion refused this API for this account — an entitlement gate, "
            "not a parameter problem.",
            "Do not retry: the identical call keeps being refused until "
            "the account's entitlement changes.",
            "Use an approach that does not need this API, or run it under a "
            "Fusion subscription that includes it.",
        ],
    ),
]


def classify(exc: BaseException | str) -> tuple[str, list[str]]:
    """Return ``(error_kind, hints)`` for *exc*.

    Accepts either an exception or a message string.  Falls back to
    ``("UNKNOWN", [])`` if no rule matches.
    """
    if isinstance(exc, BaseException):
        msg = str(exc) or exc.__class__.__name__
    else:
        msg = str(exc)
    for pattern, kind, hints in _RULES:
        if re.search(pattern, msg, re.IGNORECASE):
            return kind, list(hints)
    return "UNKNOWN", []
