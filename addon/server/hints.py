"""
Error classification for Fusion API failures.

Maps exception messages from the Fusion API (and our handler code) to a
stable ``error_kind`` tag plus a small list of contextual repair hints.

This file is canonical — the addon is installed into Fusion's AddIns folder
at deploy time and cannot import from the MCP server package, so
``src/fusion360_mcp/hints.py`` is generated from it.  Edit here, then run
``uv run python scripts/sync_mirrors.py``; a hand edit in the ``src`` copy is
overwritten.
"""

import re

# Each entry: (regex applied to str(exc), error_kind, hints)
# First match wins. Patterns use re.IGNORECASE.
_RULES: list[tuple[str, str, list[str]]] = [
    # ``fusion_api.__getattr__`` is an adapter contract, not a tool refusal: it must
    # raise AttributeError or getattr/hasattr/monkeypatch stop working.  The kind is
    # recovered here instead, and the advice points at the script that checks names.
    (
        r"module .* (has no attribute|cannot resolve)",
        "INTERNAL_ERROR",
        [
            "This is an add-in defect, not an input problem.",
            "Run `scripts/check_fusion_api.py` to see which adsk name is missing.",
        ],
    ),
    (
        r"no active design",
        "NO_ACTIVE_DESIGN",
        [
            "Open or create a design in Fusion before calling mutation tools.",
            "Use get_design_type to confirm the active product is a design.",
        ],
    ),
    (
        r"no profiles? in sketch|produced no profile",
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
        r"(?:is not|must be) finite",
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
        # Fusion's own CAM generation failure ("3 : generation failed").
        # ``_wait_future`` re-raises it for the handler to classify and nothing
        # did, so it reached the caller as UNKNOWN with no hints.  REGEN_FAILED
        # comes earlier and keeps "Regeneration failed": that is a feature
        # rebuild, not a toolpath.
        r"generation fail",
        "FUSION_REFUSED",
        [
            "Fusion failed to generate the toolpath.",
            "cam_list_operations reports what happened: check has_toolpath.",
            "Fix the operation's parameters or tool, then generate it again.",
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
        # A selector that is not a list used to raise ``TypeError`` out of the
        # validator: the add-in answered UNKNOWN with no hints and mock mode raised
        # through ``mock_command``.  Without a rule the shape check fell back to the
        # first ``INVALID_INPUT`` entry and advised about inf and nan.
        r"edge_indices needs a list|edge_points needs a list",
        "INVALID_INPUT",
        [
            "An edge selector is a list; nothing was written.",
            "Pass edge_indices as whole numbers, or edge_points as [x, y, z] triples.",
        ],
    ),
    (
        # The face selectors mean "the faces lying in the top/bottom PLANE", so a
        # body whose top is a curved surface has none there.
        r"no faces matched",
        "INVALID_INPUT",
        [
            "No face of that body lies in the selected plane; nothing was written.",
            "top and bottom take the faces in the highest or lowest flat plane.",
            "For anything else, name the faces from execute_code.",
        ],
    ),
    (
        # Fusion's own refusal when it can find no edge it can round among those
        # given - measured on a revolved cone, whose apex produces degenerate
        # edges (isDegenerate true, no geometry). It classified UNKNOWN with no
        # hints, so the caller learned nothing about why nothing was rounded.
        r"fillet_no_edge_found|no fillet edge found",
        "INVALID_INPUT",
        [
            "Fusion found no edge it can round among those given; nothing was written.",
            "Check list_edges for is_degenerate.",
            "Use a smaller radius: an edge shorter than the radius cannot take it.",
        ],
    ),
    (
        # Mirrors the edge_selection rule: without it this classified as UNKNOWN
        # and the caller got a traceback for a one-word typo.
        r"unknown face_selection",
        "INVALID_INPUT",
        [
            "face_selection is one of top / bottom.",
            "Those mean the faces lying in the top or bottom plane of the body.",
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
            "A degenerate edge (a cone's apex) has no geometry.",
            "Check the body with list_edges before choosing a selector.",
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
            "top and bottom take the highest/lowest edges a body has.",
            "Call list_edges and pick with edge_indices or edge_points.",
        ],
    ),
    (
        # ruled_surface's rule_type takes the same shape as edge_selection below:
        # the handler names both accepted values, so the hints repeat them.
        r"unknown rule_type",
        "INVALID_INPUT",
        [
            "rule_type is one of normal or tangent; nothing was written.",
            "The error message names the full set.",
        ],
    ),
    (
        # The message already lists the four it accepts; this keeps a one-word
        # typo from becoming UNKNOWN.
        r"unknown edge_selection",
        "INVALID_INPUT",
        [
            "edge_selection is one of all / top / bottom / vertical.",
            "Pass edge_indices or edge_points to name edges exactly.",
        ],
    ),
    (
        # A face index that names a plane, an edge or a wrong face. Before the size
        # check existed Fusion refused this itself with "some input argument is
        # invalid"; the handler now says it first, so it needs its own rule.
        r"not cylindrical",
        "INVALID_INPUT",
        [
            # One literal per hint: two adjacent ones read as a missing comma to
            # CodeQL, and it cannot tell a wrapped sentence from a bug.
            "A thread needs a cylindrical face; nothing was written.",
            "Use list_faces (body_name=...) to list the body's faces.",
            "Then pass a cylindrical face_index.",
        ],
    ),
    (
        # Found live on 2706: Fusion sizes the body to the thread's designation, so a
        # caller who mistyped one silently loses the geometry they asked for. The
        # handler refuses that by default and names the thread that would fit.
        r"would resize the body",
        "INVALID_INPUT",
        [
            "The face's diameter has to match the thread designation.",
            "Pass allow_resize=true to accept Fusion resizing the body.",
            "Or use the thread designation the message names.",
        ],
    ),
    (
        # Found live on 2706: a ruled surface needs a FREE (open) edge, and every
        # edge of a solid is shared by two faces, so Fusion answers "3 : invalid
        # free edge". Unclassified it reached the caller as UNKNOWN with no hints.
        r"invalid free edge",
        "INVALID_INPUT",
        [
            # One literal per hint, never two adjacent ones: CodeQL reads the
            # latter as a possibly missing comma, and it cannot tell a wrapped
            # sentence from a bug.
            "A ruled surface extends a free edge, not a solid's shared one.",
            "A sheet body's boundary edge is free; patch or stitch first.",
            "Then rule one of its boundary edges with that edge_index.",
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
        # A field the type needs is missing.  These messages contain "a curve
        # index", so without a rule above the curve-index one they inherit its
        # advice ("a negative index is refused, never wrapped") - which answers a
        # question the caller did not ask.  Anchored on "needs entity_..." only.
        r"needs entity_(one|two)",
        "INVALID_INPUT",
        [
            "Pass the field the type needs: it is missing, not invalid.",
            "radial and diameter measure one curve, so they take entity_one only.",
            "distance, horizontal, vertical and angular take both entity indices.",
            "Constraints follow the same shape: fix/horizontal/vertical take one.",
        ],
    ),
    (
        # An unknown type would otherwise fall through to UNKNOWN with no hints,
        # which is the failure mode every rule here exists to prevent.
        r"unknown (?:dimension|constraint) type",
        "INVALID_INPUT",
        [
            "Use one of the types the error message lists - it is the full set.",
            "The same list is the tool's inputSchema enum.",
        ],
    ),
    (
        # Fusion's generic argument refusal - "3 : Some input argument is invalid".
        # Measured on 2706 for a shell wall of zero or less, and for a sketch
        # dimension label at a point Fusion will not accept; both reached the caller
        # as UNKNOWN with no hints.
        r"Some input argument is invalid",
        "INVALID_INPUT",
        [
            "Fusion rejected one of the arguments: check its range and its unit.",
            "For shell, the wall thickness must be a positive distance in cm.",
            "For a dimension, the curve must be one that sketch can measure.",
        ],
    ),
    (
        # Fusion's own "N : InternalValidationError": the API refused the input's
        # STATE (a property unset, or a value it will not accept) rather than the
        # call's arguments.  The first hint below already says so, which is why the
        # kind is FUSION_REFUSED: a caller told the arguments are fine must not be
        # handed INVALID_INPUT's advice to fix them.  Unclassified it reaches the
        # caller as UNKNOWN with no hints, which is the failure mode every rule here
        # exists to stop.
        r"InternalValidationError",
        "FUSION_REFUSED",
        [
            "Fusion rejected the input's state, not its arguments.",
            "A required property may be unset, or a value it will not accept.",
            "For shell, the wall thickness must be a positive distance in cm.",
            "Check the entity exists and belongs to the body the feature acts on.",
        ],
    ),
    (
        # A shell wall Fusion cannot honour.  The schema says minimum 0.001, but the
        # socket takes what a client sends, and json.loads accepts NaN and Infinity.
        r"thickness must be (?:a )?positive",
        "INVALID_INPUT",
        [
            "thickness is a distance in cm and must be greater than zero.",
            "A typical wall is 0.1-0.3 cm; the schema floor is 0.001.",
            "A shell removes material, so it cannot add a negative wall.",
        ],
    ),
    (
        # ``midpoint``'s first entity is a sketch POINT, and it was resolved against
        # the curve list: a point index inside the curve list named the wrong item,
        # and a refusal spoke about curves.  Placed ABOVE the curve-index rule so
        # "is outside sketch" cannot steal these and answer with curve advice.
        r"point index|has no points|point\(s\), indexed",
        "INVALID_INPUT",
        [
            "Point indices are 0-based: a sketch with N points offers 0 to N-1.",
            "A negative index is refused, never wrapped: -1 is not the last point.",
            "midpoint takes a POINT for entity_one and a CURVE for entity_two.",
        ],
    ),
    (
        # A curve index past the end would reach the caller as UNKNOWN with no
        # hints.  The three messages the handler raises each carry one of these
        # phrases: a non-integer index, an empty sketch, and an index out of
        # range.  Placed above the generic INVALID_INPUT rule so it wins.
        r"curve index|has no curves, so|is outside sketch",
        "INVALID_INPUT",
        [
            "Curve indices are 0-based: a sketch with N curves offers 0 to N-1.",
            "A negative index is refused, never wrapped: -1 is not the last curve.",
            "Count the curves first: get_object_info reports the sketch's curve_count.",
        ],
    ),
    (
        # The joint frame's axes are what `axis` is resolved against. A zero-length
        # one has no direction to report, and before this rule it reached the
        # caller as `axis_world: [0, 0, 0]` and picked an arbitrary JointDirections
        # member. Anchored on "geometry's ... axis is zero-length" so it does NOT
        # capture the revolve message ("revolve axis direction is zero-length"),
        # which is a caller error with its own generic hints.
        r"geometry's .* axis is zero-length",
        "INVALID_INPUT",
        [
            "The face reports no usable axis, so no direction can be resolved.",
            "Build the joint from a different face: the geometry is the problem.",
            "Use list_faces to find another face whose surface_type is Cylinder.",
        ],
    ),
    (
        # Found live on 2706: create_flange on a body whose component carries no
        # sheet-metal rule answers "3 : component has no sheet metal rule", and
        # unclassified it reached the caller as UNKNOWN with no hints.  The fix is
        # a different body, not a different argument, so the kind is
        # GEOMETRY_UNSUPPORTED - and it sits above the generic INVALID_INPUT rule
        # below so that rule's units-and-enums advice cannot shadow it.
        r"\bcomponent has no sheet[- ]metal rule\b",
        "GEOMETRY_UNSUPPORTED",
        [
            # One literal per hint, never two adjacent ones: CodeQL reads the
            # latter as a possibly missing comma.
            "The component has no sheet-metal rule, so Fusion cannot flange it.",
            "Pick a body in a component with a sheet-metal rule, or convert it.",
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
        r"timeout|did not finish within",
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
    (
        # Fusion prefixes most of its own failures with an error number: "3 :
        # invalid free edge", "2 : InternalValidationError ...".  The specific
        # rules above own the numbered messages they recognise; a numbered
        # message none of them claims is still Fusion refusing the call, not an
        # add-in defect, and used to fall through to UNKNOWN with no hints.
        # Last in the table so every specific rule wins by first match.
        r"^\d+\s*:",
        "FUSION_REFUSED",
        [
            "Fusion refused the call and gave no cause this server recognises.",
            "Check the design's state and the arguments, then retry or change it.",
        ],
    ),
]

#: Every ``error_kind`` this module can return, spelled out rather than derived from
#: ``_RULES``: a literal is what makes a typo in a new rule's kind a red target.
#:
#: Twenty entries: the thirteen kinds ``_RULES`` returned before the six were added,
#: plus ``UNKNOWN``, plus the six new ones.  ``FUSION_REFUSED`` is the easy one to
#: drop - the first draft of this plan did, and the guard's ``kind in _KNOWN_KINDS``
#: assertion would have failed on every ``FUSION_REFUSED`` refusal until someone
#: noticed.
_KNOWN_KINDS: frozenset[str] = frozenset(
    {
        "AXIS_OUT_OF_PLANE",
        "BODY_NOT_FOUND",
        "BOOLEAN_NO_OP",
        "DESIGN_TYPE_MISMATCH",
        "FUSION_REFUSED",
        "GEOMETRY_UNSUPPORTED",
        "INTERNAL_ERROR",
        "INVALID_INPUT",
        "NAME_NOT_FOUND",
        "NOT_ENTITLED",
        "NO_ACTIVE_DESIGN",
        "PROFILE_NOT_CLOSED",
        "REGEN_FAILED",
        "SCRIPT_ERROR",
        "SELF_INTERSECTION",
        "SKETCH_NOT_FOUND",
        "TIMEOUT",
        "UNKNOWN",
        "UNKNOWN_COMMAND",
        "WORKSPACE_UNAVAILABLE",
    }
)

#: The advice a ``Refusal`` gets when it carries none of its own and its message matches
#: no rule.  One entry per kind the add-in types itself; a kind absent here falls
#: through to ``_GENERIC_HINTS``, which is honest about knowing nothing.
_KIND_HINTS: dict[str, tuple[str, ...]] = {
    "INVALID_INPUT": (
        "Fix the field error_message names; nothing was written.",
        "It names the field, and the values when the accepted set is fixed.",
    ),
    "NAME_NOT_FOUND": (
        "The name does not exist in the active design.",
        "Enumerate with get_scene_info or list_components, then retry with a name "
        "from that list.",
    ),
    "GEOMETRY_UNSUPPORTED": (
        "The body does not have the geometry this call needs.",
        "Inspect it with list_faces (body_name=...) and choose a face it has.",
    ),
    "FUSION_REFUSED": (
        "Fusion did not complete the operation.",
        "Check what was written with get_scene_info, then retry or change the "
        "approach.",
    ),
    "WORKSPACE_UNAVAILABLE": (
        "The workspace this call needs has not been opened in this Fusion session.",
        "Open it once (the Manufacturing workspace, or a viewport) and retry.",
    ),
    "SCRIPT_ERROR": (
        "execute_code ran a script that did not compile or run.",
        "Fix the script and resend; the namespace is rebuilt on every call.",
    ),
    "INTERNAL_ERROR": (
        "This is an add-in defect, not an input problem.",
        "Report it with the traceback; get_scene_info shows what was written.",
    ),
}

#: Advice for a refusal whose kind no rule mentions — an empty hint list is the
#: failure mode every rule above exists to stop, and a later kind must not revive it.
_GENERIC_HINTS: list[str] = [
    "The add-in refused this input; nothing was written.",
    "error_message names the field it rejected, when the refusal has one.",
]


class Refusal(RuntimeError):
    """An input the add-in refused, carrying the classification it already knew.

    ``classify`` recovered ``error_kind`` by matching the message against
    ``_RULES``, so the code that refused an input — the one place that knows which
    field was wrong — discarded that and let a regex guess it back.  A ``Refusal``
    states it.  Fusion's own refusals stay untyped, and the table stays theirs.
    """

    def __init__(
        self,
        error_kind: str,
        message: str,
        hints: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        self.hints = tuple(hints)


def _hints_for(exc: Refusal) -> list[str]:
    """The hints for a ``Refusal`` that carries none of its own.

    The table is read for hints but never for the kind: the kind is what the raiser
    already knew, while the message-shaped rules are what know the advice, one rule
    per refusal.  A per-kind lookup alone would give every refusal of that kind the
    same hints, whichever input it actually refused.
    """
    if exc.hints:
        return list(exc.hints)
    msg = str(exc)
    for pattern, _kind, hints in _RULES:
        if re.search(pattern, msg, re.IGNORECASE):
            return list(hints)
    return list(_KIND_HINTS.get(exc.error_kind, _GENERIC_HINTS))


def classify(exc: BaseException | str) -> tuple[str, list[str]]:
    """Return ``(error_kind, hints)`` for *exc*.

    Accepts either an exception or a message string.  A ``Refusal`` names its own
    kind, so the rules are consulted for its hints and never for that; any other
    exception — Fusion's own messages included — is matched against ``_RULES``,
    falling back to ``("UNKNOWN", [])``.
    """
    if isinstance(exc, Refusal):
        return exc.error_kind, _hints_for(exc)
    if isinstance(exc, BaseException):
        msg = str(exc) or exc.__class__.__name__
    else:
        msg = str(exc)
    for pattern, kind, hints in _RULES:
        if re.search(pattern, msg, re.IGNORECASE):
            return kind, list(hints)
    return "UNKNOWN", []
