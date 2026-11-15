"""Which commands change the model — GENERATED, do not edit.

Rendered by ``scripts/sync_mirrors.py`` from
``addon/server/mutation_commands.py``: the add-in is installed into Fusion's
AddIns folder and cannot import this package, so its copy is canonical.  Edit
that file and run ``uv run python scripts/sync_mirrors.py``; hand edits here are
overwritten.
"""

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
