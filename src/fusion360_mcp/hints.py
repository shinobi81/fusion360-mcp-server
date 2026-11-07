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
            "Pick the tool with tool_number (or add it to the CAM tool library) "
            "and set the diameter there.",
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
