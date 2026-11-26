"""Which commands change the model — GENERATED, do not edit.

Rendered by ``scripts/sync_mirrors.py`` from
``addon/server/mutation_commands.py``: the add-in is installed into Fusion's
AddIns folder and cannot import this package, so its copy is canonical.  Edit
that file and run ``uv run python scripts/sync_mirrors.py``; hand edits here are
overwritten.
"""

# fmt: off
# `src/` is format-gated and `addon/` is not, so this rendered body is exempt:
# reformatting it here would edit a file the gate does not own.

from __future__ import annotations

# Commands that can change body mass / bbox / body count.  Only these
# get before/after snapshots so agents can sanity-check without a render.
MUTATION_COMMANDS: frozenset[str] = frozenset(
    {
        # feature ops
        "extrude",
        "revolve",
        "sweep",
        "loft",
        "fillet",
        "chamfer",
        "shell",
        "mirror",
        "create_hole",
        "rectangular_pattern",
        "circular_pattern",
        "create_thread",
        "draft_faces",
        "split_body",
        "split_face",
        "offset_faces",
        "scale_body",
        "suppress_feature",
        "unsuppress_feature",
        # body ops
        "move_body",
        "boolean_operation",
        # primitives
        "create_box",
        "create_box_parametric",
        "create_cylinder",
        "create_sphere",
        "create_torus",
        # surface / sheet metal (can produce / thicken bodies)
        "thicken_surface",
        "patch_surface",
        "stitch_surfaces",
        "ruled_surface",
        "trim_surface",
        "create_flange",
        "create_bend",
        "flat_pattern",
        "unfold",
        # scene-wide
        "delete_all",
        "undo",
        # parametric & agent-authored changes
        "set_parameter",
        "execute_code",
        # sketch constraint mutation
        "auto_constrain",
        # construction geometry / appearance
        "create_ucs",
        "set_color",
    }
)

# Commands whose success the snapshot cannot judge, and the reason each is here.
#
# A mutation whose three measures all come back identical did nothing *measurable*, and
# ``no_op_warning`` says so - except for these, where an unchanged snapshot is either
# the normal outcome or a change the snapshot has no field for.  One reason per entry:
# an exemption without one is indistinguishable from a forgotten case.
NO_OP_EXEMPT: dict[str, str] = {
    "auto_constrain": (
        "sketch constraints are not bodies: mass, count and bbox cannot see them"
    ),
    "create_thread": (
        "a thread is cosmetic unless is_modeled=True, and a cosmetic one adds no mass"
    ),
    "create_ucs": (
        "a user coordinate system is construction geometry, invisible to the snapshot"
    ),
    "delete_all": (
        "it removes sketches, joints, construction geometry and timeline entries - a "
        "design with no bodies has nothing left that the snapshot counts, so a sweep "
        "of a sketch-only design measured nothing"
    ),
    "move_body": (
        "a successful move always translates a body - Fusion refuses a zero "
        "translation with '3 : invalid transform', measured on 2706.1.17 - while the "
        "root box is a union, so a body moved inside another's extents changes none "
        "of the three measures (measured: a 1 cm move that answered 'nothing changed')"
    ),
    "set_color": "an appearance changes no body's mass, count or bounding box",
    "set_parameter": (
        "a parameter's value is not one of the three measures, and the design can "
        "regenerate identically - or the value can be the one it already held"
    ),
    "split_face": (
        "splitting a face changes topology, not the body's mass, count or box"
    ),
    "suppress_feature": (
        "suppression is timeline state, and a suppressed feature may already have "
        "contributed nothing measurable"
    ),
    "undo": (
        "a timeline step back is reported as undone/verified, and a suppressed feature "
        "stays in the timeline, so the snapshot can be untouched"
    ),
    "unsuppress_feature": (
        "the mirror of suppress_feature: the snapshot need not move for the feature to "
        "return"
    ),
}

# Mass is compared with a tolerance: a no-op still re-evaluates the design, and Fusion's
# two evaluations of the same body need not agree in the last bit.  1e-6 g is far below
# anything a feature removes, and far above the float noise it can add.
_MASS_TOLERANCE_G = 1e-6


def no_op_warning(command: str, deltas: dict) -> str | None:
    """The ``nothing changed`` warning for *command*'s deltas, or None.

    A mutation whose body count, mass and bounding box all came back identical moved
    nothing measurable, and ``ok: true`` alone reads as success to a caller that stops
    there.  The three are judged together: ``move_body`` and ``unfold`` change neither
    count nor mass, so a rule built on those two would accuse a real change of being a
    no-op.

    Nothing unmeasured is read as unchanged.  A design with bodies whose mass could not
    be read answers ``None`` for it (``_snapshot`` says why), and a box that was never
    read is ``None`` too, so both refuse the judgement instead of supplying a zero -
    "unknown is not zero" is the whole point of the key.

    Never a refusal - clipping nothing can be exactly what was asked - and never a claim
    about the design: the wording names the snapshot, because a topology-only command
    (``split_face``) changes the body without moving any of these three numbers.  The
    arrow is ASCII on purpose: this string is built in the add-in and travels on the
    wire, where only the MCP renderer's own prose uses a real arrow.
    """
    if command in NO_OP_EXEMPT:
        return None
    count_before = deltas.get("body_count_before")
    count_after = deltas.get("body_count_after")
    count_delta = deltas.get("body_count_delta")
    mass_before = deltas.get("mass_g_before")
    mass_after = deltas.get("mass_g_after")
    mass_delta = deltas.get("mass_g_delta")
    if (
        count_before is None
        or count_after is None
        or count_delta is None
        or mass_before is None
        or mass_after is None
        or mass_delta is None
    ):
        # Unknown is not zero: a measure this snapshot does not carry cannot be judged.
        return None
    if count_delta != 0 or abs(mass_delta) > _MASS_TOLERANCE_G:
        return None
    box_before = deltas.get("bbox_before")
    box_after = deltas.get("bbox_after")
    if count_before and box_before is None:
        # Bodies but no box: the read failed, so "identical" is unproven.  Measured on
        # 2706.1.17: moving a body inside a component moved root.boundingBox with it,
        # so the two measures agree there - but get_bounding_box unions occurrences by
        # hand, so a *transformed* occurrence is one probe this does not cover, and the
        # guard keeps that case silent rather than wrong.
        return None
    if box_before != box_after:
        return None
    return (
        f"nothing changed in the snapshot: body_count {count_before} -> "
        f"{count_after}, mass_g "
        f"{mass_before:.3f} -> {mass_after:.3f}, and the bounding box is identical. "
        "The call succeeded, but every measure came back the same - check that the "
        "script, profile, target or name reached a body."
    )
