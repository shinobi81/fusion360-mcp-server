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

#: Commands whose success the snapshot cannot judge, and the reason each is here.
#:
#: A mutation whose three measures all come back identical did nothing *measurable*, and
#: ``no_op_warning`` says so - except for these, where an unchanged snapshot is either
#: the normal outcome or a change the snapshot has no field for.  One reason per entry:
#: an exemption without one is indistinguishable from a forgotten case.
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

#: Mass is compared with a tolerance: a no-op repeats Fusion's own evaluation, and only
#: the snapshot's kg -> g conversion could move the last bit.
_MASS_TOLERANCE_G = 1e-6


def no_op_warning(command: str, deltas: dict) -> str | None:
    """The ``nothing changed`` warning for *command*'s deltas, or None.

    A mutation whose body count, mass and bounding box all came back identical moved
    nothing measurable, and ``ok: true`` alone reads as success to a caller that stops
    there.  The three are judged together: ``move_body`` and ``unfold`` change neither
    count nor mass, so a rule built on those two would accuse a real change of being a
    no-op.

    Never a refusal - clipping nothing can be exactly what was asked - and never a claim
    about the design: the wording names the snapshot, because a topology-only command
    (``split_face``) changes the body without moving any of these three numbers.
    """
    if command in NO_OP_EXEMPT:
        return None
    count_delta = deltas.get("body_count_delta")
    mass_delta = deltas.get("mass_g_delta")
    if count_delta is None or mass_delta is None:
        # Unknown is not zero: a deltas dict without a measure cannot be judged.
        return None
    if count_delta != 0 or abs(mass_delta) > _MASS_TOLERANCE_G:
        return None
    if deltas.get("bbox_before") != deltas.get("bbox_after"):
        return None
    return (
        f"nothing changed: body_count {deltas.get('body_count_before')} -> "
        f"{deltas.get('body_count_after')}, mass_g "
        f"{deltas.get('mass_g_before', 0.0):.3f} -> "
        f"{deltas.get('mass_g_after', 0.0):.3f}, and the bounding box is identical. "
        "The command reported success but nothing measurable moved - check that the "
        "profile, target or name reached a body."
    )
