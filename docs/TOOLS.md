# Tools

All 100 tools this server exposes, grouped by what they do. Every tool returns the same
envelope — `ok`, plus tool-specific fields, plus `deltas` for mutations — and failures come
back as data (`error_kind`, `hints`, `traceback`) rather than exceptions.

A mutation whose snapshot did not move — body count, mass and bounding box all
identical — also carries `warning: "nothing changed in the snapshot: …"`, because
`ok: true` alone reads as success to a caller that stops there. It is information, never
a refusal: clipping nothing can be exactly what was asked. Commands whose success the
snapshot cannot judge (`set_parameter`, `suppress_feature`, `unsuppress_feature`, `undo`,
`move_body`, `delete_all`, `set_color`, `create_ucs`, `auto_constrain`, `split_face`,
`create_thread`) never carry it, each for a reason recorded beside it in
`addon/server/mutation_commands.py`. A command that sets a `warning` of its own keeps it
— the CAM handlers use one for a partial failure — because that sentence describes the
call that was just made, and this key never replaces it. A `mass_g_before`,
`mass_g_after` or `mass_g_delta` of `null` means the mass could not be read, and the
warning is never raised on one.

Units are **centimetres** throughout: Fusion's internal unit, not millimetres. Tools
marked **(2026+)** use APIs that need a Fusion build from 2026 or later; the rest were
checked against **Fusion 2706.1.17**'s API.

## Reading a row

`Proven` is the `app.version` the tool has answered a real Fusion on, or an em dash
where nothing has succeeded yet. It is **generated** from the `Evidence` cell and never
typed: `uv run python scripts/sync_proven_column.py` rewrites it, `--check` reports a
stale one, and `tests/test_proven.py` fails while the two disagree.

`Evidence` is the record, one line per row, and the only part written by hand:

- ``proven — YYYY-MM-DD, `version`, #pr: what was measured`` — the version is the
  running `app.version` and the PR is the one whose body carries the envelope. A trailing
  `(#157)` names a *different* PR whose body carries the envelope — the measurement's
  own, when the row cites it.
- `unproven — <why>`, one line. "Only a refusal is exercised" is a reason; "not yet" is
  not, and `scripts/check_proven.py` refuses one.

Nothing here is aspirational: an `unproven` row is where the next unknown defect
lives. `uv run python scripts/check_proven.py` validates this table against
`src/fusion360_mcp/tools.py` without needing Fusion. `--live` sends the read-only tools
it chooses to send — twelve of the nineteen — and reports a row whose reply contradicts
its state, in either direction; a *proven* row it sends no call to is reported as not
probed, never as passing. Two of those twelve touch the session: `cam_list_setups`
activates the Manufacture workspace, and `render_view` repositions the camera for its
capture and restores it before returning.

## Scene & Query

| Tool               | Proven      | Description                                                                                                                                            | Evidence                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ping`             | `2706.1.17` | Health check (instant, no Fusion API)                                                                                                                  | proven — 2026-11-26, `2706.1.17`, #158: answered `{status: pong}` — from the socket fast path, never from the handler                                                                                                                                                                                                                                                                                 |
| `health`           | `2706.1.17` | Health check on Fusion's main thread: `app_version`, `active_document`, `queue_depth`; times out when the thread is wedged, where `ping` still answers | proven — 2026-11-28, `2706.1.17`, #164: answered `app_version` `2706.1.17`, `active_document` and `queue_depth: 0` from the main thread after the add-in was restarted, and failed at the 3 s `--timeout` while the thread was blocked (#161); the hand-off and the depth it reads are pinned by `tests/test_addon_bridge.py`, `tests/test_addon_importable.py` and `tests/test_addon_scene_reads.py` |
| `get_scene_info`   | `2706.1.17` | Design name, bodies, sketches, features, camera                                                                                                        | proven — 2026-11-26, `2706.1.17`, #158: reported a one-body parametric design's bodies, counts and camera                                                                                                                                                                                                                                                                                             |
| `get_object_info`  | `2706.1.17` | Detailed info about a named body or sketch                                                                                                             | proven — 2026-11-26, `2706.1.17`, #158: answered a body's face/edge/vertex counts, volume and bbox                                                                                                                                                                                                                                                                                                    |
| `list_edges`       | `2706.1.17` | A body's edges: index, endpoints, midpoint, length, curve type                                                                                         | proven — 2026-11-26, `2706.1.17`, #158: answered a box's twelve edges with index and midpoint                                                                                                                                                                                                                                                                                                         |
| `list_faces`       | `2706.1.17` | A body's faces: index, surface type, planarity, area, centroid, and normal when planar                                                                 | proven — 2026-11-26, `2706.1.17`, #158: answered a box's six faces with index, surface_type and normal (#147)                                                                                                                                                                                                                                                                                         |
| `get_bounding_box` | `2706.1.17` | Axis-aligned bbox (min/max/size/center) for body or component; unions all bodies when called on a component                                            | proven — 2026-11-26, `2706.1.17`, #158: answered a box's min/max/size/center                                                                                                                                                                                                                                                                                                                          |
| `list_components`  | `2706.1.17` | List all components in the design                                                                                                                      | proven — 2026-11-26, `2706.1.17`, #158: answered `Component1` with `count`                                                                                                                                                                                                                                                                                                                            |

## Document

| Tool              | Proven      | Description                                                                                                                                                                                                                                                                                    | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `new_document`    | `2706.1.17` | Create a design document and make it active — the way in from a cold start                                                                                                                                                                                                                     | proven — 2026-11-26, `2706.1.17`, #158: created an active parametric design document                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `save_document`   | `2706.1.17` | Save the active document in place, or an untitled one by name into Fusion's active data folder (no local-file save exists in this API); answers `saved`, `name`, `folder`, `saved_as` and `is_modified`; a `name` passed for an already-saved document is ignored and echoed as `name_ignored` | proven — 2026-11-27, `2706.1.17`, #162: refused an untitled document with no name (nothing written), saved it by name into the active data folder (`saved_as: true`, `is_modified: false`), then — after `create_box` modified it, `isSaved: True`/`isModified: True` — saved in place (`saved_as: false`, `is_modified: false`, read back as `True False`); `checkpoint=True` reported `saved_before: true` on `execute_code` and `cam_create_operation`; saving an *unmodified* document twice answered `saved: true` both times with no version added |
| `get_design_type` | `2706.1.17` | Check if the design is parametric or direct                                                                                                                                                                                                                                                    | proven — 2026-11-26, `2706.1.17`, #158: answered `parametric` with `design_type_id`                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `set_design_type` | `2706.1.17` | Switch design type (parametric/direct recovery)                                                                                                                                                                                                                                                | proven — 2026-11-28, `2706.1.17`, #164: switched parametric -> direct -> parametric: `changed: true` both ways                                                                                                                                                                                                                                                                                                                                                                                                                                           |

## Sketching

| Tool               | Proven      | Description                                                                                                              | Evidence                                                                                                                                                                    |
| ------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_sketch`    | `2706.1.17` | New sketch on xy/yz/xz plane, optional offset                                                                            | proven — 2026-11-26, `2706.1.17`, #158: created `Sketch1` on xy with a z offset                                                                                             |
| `draw_rectangle`   | `2706.1.17` | Rectangle in most recent sketch, or in `sketch_name`                                                                     | proven — 2026-11-26, `2706.1.17`, #158: reported `model_origin` for a 10x10 rectangle                                                                                       |
| `draw_circle`      | `2706.1.17` | Circle in most recent sketch, or in `sketch_name`                                                                        | proven — 2026-11-28, `2706.1.17`, #164: drew a R1.5 cm circle at (5,3) and reported `model_center`                                                                          |
| `draw_line`        | `2706.1.17` | Line in most recent sketch, or in `sketch_name`                                                                          | proven — 2026-11-28, `2706.1.17`, #164: drew (-5,8)->(5,8.4) and reported `model_start`/`model_end` in model space                                                          |
| `draw_arc`         | `2706.1.17` | Arc (center + start + sweep angle)                                                                                       | proven — 2026-11-28, `2706.1.17`, #164: drew a 90 deg arc of radius 2 centred (15,3), reporting `model_center`                                                              |
| `draw_spline`      | `2706.1.17` | Fit-point or control-point spline                                                                                        | proven — 2026-11-28, `2706.1.17`, #164: a four-point `fit_points` spline through (20,0)..(26,2), with `model_points` reported                                               |
| `create_polygon`   | `2706.1.17` | Regular polygon (3–64 sides)                                                                                             | proven — 2026-11-28, `2706.1.17`, #164: added a 6-sided R2 cm polygon at (-8,3), as six `SketchLine`s                                                                       |
| `draw_circles`     | `2706.1.17` | Several equally spaced circles in one solve — far faster than one call per circle                                        | proven — 2026-11-28, `2706.1.17`, #164: three R0.5 circles at 2 cm spacing in one deferred solve: `added: 3`, `total_curves: 17`                                            |
| `add_constraint`   | `2706.1.17` | Geometric constraint (coincident, parallel, tangent, etc.)                                                               | proven — 2026-11-28, `2706.1.17`, #164: applied `horizontal` to a sloped `SketchLine` by index                                                                              |
| `auto_constrain`   | —           | **(2026+)** Auto-constrain a sketch via the AutoConstrain API — 3 result options (thorough / fast / tolerance-adjusting) | unproven — only a refusal is exercised: `NOT_ENTITLED`, `3 : AutoConstrain is not available since user is restricted` (2026-11-28, `2706.1.17`) — the account, not the call |
| `add_dimension`    | `2706.1.17` | Driving dimension (distance, angle, radial, diameter)                                                                    | proven — 2026-11-28, `2706.1.17`, #164: applied a `distance` of 10 between two rectangle edges and a `radial` of 2 to a circle, both by index                               |
| `offset_curve`     | `2706.1.17` | Offset connected sketch curves                                                                                           | proven — 2026-11-28, `2706.1.17`, #164: offset a spline by 1 cm                                                                                                             |
| `trim_curve`       | `2706.1.17` | Trim at intersections                                                                                                    | proven — 2026-11-28, `2706.1.17`, #164: trimmed a 20 cm line at its crossing, keeping (0,0)-(10,0)                                                                          |
| `extend_curve`     | `2706.1.17` | Extend to nearest intersection                                                                                           | proven — 2026-11-28, `2706.1.17`, #164: extended a line past its end                                                                                                        |
| `project_geometry` | `2706.1.17` | Project edges/bodies onto sketch plane                                                                                   | proven — 2026-11-28, `2706.1.17`, #164: projected a body's 30 edges into a new sketch: `projected_curves: 30`, linked                                                       |

The `draw_*` tools and `create_polygon` take an optional `sketch_name`; without it
the geometry goes into the most recent sketch. Naming it lets you add to an older
sketch without relying on creation order.

The same applies to the profile side of the features: `extrude`, `revolve` and `sweep` take
`sketch_name` for the sketch that holds the profile, so a part whose profiles live in two
sketches need not be built in creation order. `sweep` also names its path sketch, separately.

### Choosing which body a cut touches

An `extrude`, `revolve`, `sweep` or `loft` with `operation` of `cut`, `join` or `intersect`
applies to **every body the profile reaches** unless `target_body` names one. A loft across
the seam between two touching blocks cuts both; on a part with several bodies that is rarely
what was meant. `target_body` sets Fusion's own `participantBodies`, so nothing is copied
or recreated. Left out, the choice stays Fusion's, which is the behaviour without the
parameter. With `join` that is more than a shape change: measured on 2706, a `join` whose
new material crossed the seam merged the *second* body into the target — two bodies became
one — while naming `target_body` left the other body intact.
Naming a body the profile never reaches is not an error: Fusion builds the feature and
changes nothing, so the call reports `ok: true` with `mass_g_delta: 0`. Read the delta,
not the status, when a cut looks like it did nothing. A profile that reaches **no** body
at all is refused instead — `INVALID_INPUT`, where Fusion's own message is
`NO_TARGET_SWEEP_BODY` — because Fusion then has no target to infer.

## Features

| Tool                  | Proven      | Description                                                                                                                                                                                                                                                                                                                      | Evidence                                                                                                                                                                                                        |
| --------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extrude`             | `2706.1.17` | Extrude a sketch profile; `target_body` limits a cut/join/intersect                                                                                                                                                                                                                                                              | proven — 2026-11-26, `2706.1.17`, #158: cut a 15.7 g void from a box; a cut whose profile reached nothing was refused by Fusion (`3 : No target body found to cut or intersect!`)                               |
| `revolve`             | `2706.1.17` | Revolve about a model-space axis (must be coplanar with the profile); `target_body` limits a cut/join/intersect                                                                                                                                                                                                                  | proven — 2026-11-28, `2706.1.17`, #164: revolved a 2x4 cm rectangle 360 deg about the vertical model axis at x=10: `body_count` 1 -> 2, `axis_model_start` (10,0,0), `axis_model_end` (10,10,0)                 |
| `sweep`               | `2706.1.17` | Sweep a profile along a path; `target_body` limits a cut/join/intersect                                                                                                                                                                                                                                                          | proven — 2026-11-28, `2706.1.17`, #164: swept a circle on xz along a line on xy: `body_count` 2 -> 3, `Sweep1`                                                                                                  |
| `loft`                | `2706.1.17` | Loft between two or more profiles; `target_body` limits a cut/join/intersect                                                                                                                                                                                                                                                     | proven — 2026-11-28, `2706.1.17`, #164: lofted a square at z=0 to a circle at z=10: `body_count` 3 -> 4, `Loft1`                                                                                                |
| `fillet`              | `2706.1.17` | Round edges: all/top/bottom/vertical, or `edge_indices` / `edge_points`                                                                                                                                                                                                                                                          | proven — 2026-11-28, `2706.1.17`, #164: filleted the four top edges at r=0.3: mass 625.49 -> 623.14 g                                                                                                           |
| `chamfer`             | `2706.1.17` | Chamfer edges: same three selectors as `fillet`                                                                                                                                                                                                                                                                                  | proven — 2026-11-28, `2706.1.17`, #164: chamfered edge 0 at 0.4: mass 628.0 -> 625.49 g                                                                                                                         |
| `shell`               | `2706.1.17` | Hollow out a body; `face_selection` (top/bottom) is the face left **open**                                                                                                                                                                                                                                                       | proven — 2026-11-28, `2706.1.17`, #164: removed the top face at a 0.25 cm wall: mass 623.14 -> 168.67 g, `faces_removed: 1`                                                                                     |
| `mirror`              | `2706.1.17` | Mirror a body across a plane                                                                                                                                                                                                                                                                                                     | proven — 2026-11-28, `2706.1.17`, #164: mirrored a body across yz: `body_count` 5 -> 6                                                                                                                          |
| `create_hole`         | `2706.1.17` | Hole feature on a body face                                                                                                                                                                                                                                                                                                      | proven — 2026-11-28, `2706.1.17`, #164: cut a 1 cm hole 3 cm deep into a box's top face: `actual_diameter: 1.0`                                                                                                 |
| `rectangular_pattern` | `2706.1.17` | Pattern in rows and columns                                                                                                                                                                                                                                                                                                      | proven — 2026-11-28, `2706.1.17`, #164: copied a body 2x1 at 8 cm X spacing: `body_count` 2 -> 3, `R-Pattern1`                                                                                                  |
| `circular_pattern`    | `2706.1.17` | Pattern around an axis                                                                                                                                                                                                                                                                                                           | proven — 2026-11-28, `2706.1.17`, #164: three copies about z: `body_count` 3 -> 5, `C-Pattern1`                                                                                                                 |
| `create_thread`       | `2706.1.17` | Add threads (cosmetic or modeled). **Refuses** a designation that does not match the face - Fusion would resize the body to it (an `M6x1` thread on a 20 mm shaft leaves a 5.88 mm one) - and names the thread that fits; `allow_resize=true` accepts the resize. `thread_class` defaults to 6H internal / 6g external (ISO 965) | proven — 2026-11-28, `2706.1.17`, #164: cut an M10x1.5 6g thread on a Ø10 mm cylinder's lateral face: `face_diameter_cm` 1.0, `thread_diameter_cm` 0.9997, `is_modeled` true                                    |
| `draft_faces`         | `2706.1.17` | Draft/taper faces for mold release                                                                                                                                                                                                                                                                                               | proven — 2026-11-28, `2706.1.17`, #164: drafted a body's vertical faces by 2 deg, `face_count` reported                                                                                                         |
| `split_body`          | `2706.1.17` | Split a body using a plane                                                                                                                                                                                                                                                                                                       | proven — 2026-11-28, `2706.1.17`, #164: split a body across xz: `body_count` 7 -> 8, `Split1`                                                                                                                   |
| `split_face`          | `2706.1.17` | Split faces of a body                                                                                                                                                                                                                                                                                                            | proven — 2026-11-28, `2706.1.17`, #164: split face 0 with the yz plane: `SplitFace1`                                                                                                                            |
| `offset_faces`        | `2706.1.17` | Push/pull faces by a distance                                                                                                                                                                                                                                                                                                    | proven — 2026-11-26, `2706.1.17`, #158: ran with distance 0 and its `deltas` counted the surface body it created                                                                                                |
| `scale_body`          | `2706.1.17` | Scale uniformly or non-uniformly about `anchor_*`. The anchor is a *reference*: it becomes a sketch point in a hidden reference sketch (named in the reply), because Fusion refuses a bare coordinate with `3 : invalid ref point`                                                                                               | proven — 2026-11-28, `2706.1.17`, #164: `Scale1` about (1,2,3) at 1.5x: mass 502.4 -> 1695.6 g with `reference_sketch` named; the anchor is a sketch point, because a raw point answers `3 : invalid ref point` |
| `suppress_feature`    | `2706.1.17` | Suppress a timeline feature                                                                                                                                                                                                                                                                                                      | proven — 2026-11-28, `2706.1.17`, #164: suppressed `Hole1`: `body_count` 7 -> 6                                                                                                                                 |
| `unsuppress_feature`  | `2706.1.17` | Re-enable a suppressed feature                                                                                                                                                                                                                                                                                                   | proven — 2026-11-28, `2706.1.17`, #164: restored `Hole1`: `body_count` 6 -> 7                                                                                                                                   |

### Choosing edges

`fillet` and `chamfer` accept exactly one selector:

- `edge_selection` — the coarse filter (`all`, `top`, `bottom`, `vertical`). `top`
  and `bottom` take the edges lying in the highest / lowest plane that holds *any*
  edge, and the plane is measured from the edges, not from the body's bounding
  box: on a body whose top is a curved surface (a dome joined onto a plate) the
  extreme carries no edge, and the plate's own edges are what come back. An edge
  counts only when its whole extent lies in that plane — one that merely reaches
  the top does not — and `vertical` means an edge with no extent in x or y,
  which a closed circular edge is not merely because its two vertices are the
  same point.
- `edge_indices` — exact edges, numbered as `list_edges` reports them. Indices are positional
  and move when the body changes, so re-list before relying on them.
- `edge_points` + `edge_tolerance` (cm, default 0.1) — each point snaps to its nearest edge;
  a point too far away, or one equally close to two edges, is refused with the measurement.

Every selector skips **degenerate** edges — the ones Fusion flags with
`isDegenerate`, which have no geometry at all (a cone's apex produces them) and
which no fillet can round. `list_edges` still reports them, so a `count` can exceed
what a selection returns.

## Body Operations

| Tool                | Proven      | Description                                               | Evidence                                                                                               |
| ------------------- | ----------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `move_body`         | `2706.1.17` | Translate a body by (x, y, z)                             | proven — 2026-11-26, `2706.1.17`, #158: moved a body and the root bbox followed, measured (#157)       |
| `rename_body`       | `2706.1.17` | Rename a body (searches root and all components)          | proven — 2026-11-26, `2706.1.17`, #158: renamed a body, reporting `old_name` and `new_name` (#157)     |
| `boolean_operation` | `2706.1.17` | Join/cut/intersect two bodies; `keep_tool` keeps the tool | proven — 2026-11-28, `2706.1.17`, #164: joined `ParaBox` into `Body1`: `body_count` 4 -> 3, `Combine1` |
| `delete_all`        | `2706.1.17` | Clear the design                                          | proven — 2026-11-26, `2706.1.17`, #158: swept a sketch-only design and reported what it removed (#157) |
| `undo`              | `2706.1.17` | Step back one timeline feature (verified; see note)       | proven — 2026-11-26, `2706.1.17`, #158: stepped a parametric timeline back, `verified: true` (#157)    |

## Direct Primitives

| Tool                    | Proven      | Description                                                                                                                                                                                       | Evidence                                                                                      |
| ----------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `create_box`            | `2706.1.17` | Box (via TemporaryBRepManager, history-less), centred on `center_x`/`center_y`/`center_z`: it spans half its size either side of that point on every axis                                         | proven — 2026-11-26, `2706.1.17`, #158: reported `deltas` body_count 0 -> 1 and 502.4 g       |
| `create_box_parametric` | `2706.1.17` | History-based box: sketch rectangle + dimensions + extrude. `length`/`width`/`height` accept numbers (cm) or string expressions referencing User Parameters (e.g. `"boxL"`, `"outer - 2*wall_t"`) | proven — 2026-11-26, `2706.1.17`, #158: reported `deltas` body_count 0 -> 1 and 62.8 g (#157) |
| `create_cylinder`       | `2706.1.17` | Cylinder                                                                                                                                                                                          | proven — 2026-11-28, `2706.1.17`, #164: `body_count` 1 -> 2 for R0.5 x 3 cm at (10,0,0)       |
| `create_sphere`         | `2706.1.17` | Sphere                                                                                                                                                                                            | proven — 2026-11-28, `2706.1.17`, #164: `body_count` 1 -> 2 for R3 at (30,0,0)                |
| `create_torus`          | `2706.1.17` | Torus                                                                                                                                                                                             | proven — 2026-11-28, `2706.1.17`, #164: `body_count` 2 -> 3 for major 4 / minor 1 at (50,0,0) |

## Surface Operations

| Tool              | Proven      | Description                                                                                                                                                                                                                                                                                 | Evidence                                                                                                          |
| ----------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `patch_surface`   | `2706.1.17` | Create a patch surface from a sketch profile. `continuity` applies to B-Rep edge boundaries and is ignored for sketch curves, which is this tool's only accepted boundary                                                                                                                   | proven — 2026-11-26, `2706.1.17`, #158: created a surface body, body_count +1 (#157)                              |
| `stitch_surfaces` | `2706.1.17` | Stitch surface bodies into one                                                                                                                                                                                                                                                              | proven — 2026-11-28, `2706.1.17`, #164: stitched a patch with the surface ruled off its edge: `body_count` 2 -> 1 |
| `thicken_surface` | `2706.1.17` | Thicken a surface into a solid                                                                                                                                                                                                                                                              | proven — 2026-11-28, `2706.1.17`, #164: thickened the stitched surface by 0.2 cm: `body_count` 1 -> 2             |
| `ruled_surface`   | `2706.1.17` | Ruled surface from a **free** edge — a sheet body's boundary. A solid's edge is shared by two faces and Fusion refuses it (`invalid free edge`); patch or stitch to a surface body first                                                                                                    | proven — 2026-11-28, `2706.1.17`, #164: ruled 1 cm off a patch's edge: `body_count` 1 -> 2                        |
| `trim_surface`    | `2706.1.17` | Trim a surface with a body or a base plane. `keep_cells` lists the cells that survive; every other cell is removed. Fusion offers no side to name - a trimmed patch's cells all report a zero centroid - so the indices are the caller's choice, and the refusal reports how many there are | proven — 2026-11-26, `2706.1.17`, #158: trimmed a surface with a plane and shrank the bbox (#157)                 |

## Sheet Metal

| Tool            | Proven      | Description                                                                                                                                                                         | Evidence                                                                                                                                                                                                                                   |
| --------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `create_flange` | `2706.1.17` | Create an edge flange. `distance` is the flange length; `bend_radius_override` applies to this flange only                                                                          | proven — 2026-11-28, `2706.1.17`, #164: a 2 cm, 90 deg edge flange on a sheet-metal body: `EdgeFlange2`                                                                                                                                    |
| `create_bend`   | `2706.1.17` | Fold along a sketch line. `stationary_face_index` is the face that stays fixed - a wrong one bends the part the wrong way; `line_position` is where the line sits in the flat state | proven — 2026-11-28, `2706.1.17`, #164: a 90 deg fold along a sketch line on the bottom face: `Fold1`, mass +0.46 g; faces 0 and 12 were refused `FOLD_GENERIC_FEATURE_FAILURE`, so the stationary face has to be the one the line lies on |
| `flat_pattern`  | `2706.1.17` | Create flat pattern, pinned on the body's largest planar face (its top or bottom)                                                                                                   | proven — 2026-11-28, `2706.1.17`, #164: `FlatPattern1` from the largest planar face; the first planar face of a 10x10x0.25 cm flange is a 0.37 cm2 side wall, which Fusion refuses with `a side face may have been selected`               |
| `unfold`        | `2706.1.17` | Unfold specific bends, or every one; pinned on the same largest planar face                                                                                                         | proven — 2026-11-28, `2706.1.17`, #164: `Unfold1` over every bend: mass 196.71 -> 196.25 g, the flange unfolded                                                                                                                            |

## Construction Geometry

| Tool                        | Proven      | Description                                                                                               | Evidence                                                                                                                                                                                                                                                                                                                                                                                |
| --------------------------- | ----------- | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_construction_plane` | `2706.1.17` | Offset, angle, midplane, 3-point, tangent (`body_name` + `face_index`; `angle` + `plane`, or `point_one`) | proven — 2026-11-27, `2706.1.17`, #160: built a plane (`Plane1`, then `Plane2` for `edge_name="Y"`); refused `edge_name="w"` with the axis sentence, and a missing angle with `3 : invalid expression` before this PR's rule (#160)                                                                                                                                                     |
| `create_construction_axis`  | `2706.1.17` | Two-point, intersection, edge, perpendicular (`face_index` + `point_one`)                                 | proven — 2026-11-27, `2706.1.17`, #163: `perpendicular_at_point` on face 0 of a box answered `created: true`, `name: "Axis1"`; `list_faces` reported that face as `surface_type: "Plane"` before the call, and the axis was read back through `execute_code` from `rootComponent.constructionAxes` — `get_scene_info` reports bodies, sketches and counts, and no construction geometry |
| `create_ucs`                | `2706.1.17` | **(2026+, preview API)** User Coordinate System at a point with optional rotation                         | proven — 2026-11-28, `2706.1.17`, #164: built `UCS1` at (3,2,1) with 30 deg about z, reporting the hidden `UCS_UCS1_ref` sketch it anchors on                                                                                                                                                                                                                                           |

### What a `tangent` construction plane takes

Fusion ships two definitions behind the one value, and the arguments decide which runs:

- **`angle` + `plane`, with `body_name` + `face_index`** — `setByTangent(face, angle,
  referencePlane)`. The face must be **cylindrical**; `angle` is in degrees and defaults
  to 0, and `plane` is the reference it is measured from and is required, because an
  angle has no zero without one.

  Two measured constraints. The first is refused here, before Fusion sees the call; the
  second is refused here too, because Fusion's own answer names nothing:

  - a reference plane whose **normal is parallel to the face's axis** is refused —
    `xy` on a Z cylinder fails in Fusion, `yz` and `xz` build, at 0° and at 45°. The
    angle is measured *around* the axis. A face whose axis is oblique is not judged:
    the call goes to Fusion, which answers `FUSION_REFUSED` if it cannot build it.
  - the face must be a **cylinder**. The binding's docstring says "cylindrical or
    conical", and measured on 2706.1.17 a cone is refused whichever reference plane is
    used; the route that works for a cone is `point_one` below.
- **`point_one`, with `body_name` + `face_index`** — `setByTangentAtPoint(face, point)`.
  Any face, and the point need not lie on it.

Passing both is refused from the parameters alone, so real and mock mode answer alike.

## Assembly

| Tool                    | Proven      | Description                                                         | Evidence                                                                                                                        |
| ----------------------- | ----------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `create_component`      | `2706.1.17` | Create a sub-assembly component                                     | proven — 2026-11-26, `2706.1.17`, #158: created `C1`; a body added to it is counted in the snapshot                             |
| `add_joint`             | `2706.1.17` | Joint between two components                                        | proven — 2026-11-28, `2706.1.17`, #164: a revolute joint from two Ø10 mm cylindrical faces: `Revolute 1`, `RevoluteJointMotion` |
| `set_joint_value`       | `2706.1.17` | Drive a joint and read the value back (angles in deg, slides in cm) | proven — 2026-11-28, `2706.1.17`, #164: drove `Revolute 1` to 45 deg: `read_back` 0.785398 rad, `applied: true`                 |
| `create_as_built_joint` | `2706.1.17` | Joint from current positions                                        | proven — 2026-11-28, `2706.1.17`, #164: a rigid as-built joint between two components: `Rigid 1`, `kept_current_positions`      |
| `create_rigid_group`    | `2706.1.17` | Lock components together                                            | proven — 2026-11-28, `2706.1.17`, #164: grouped two components: `created: true`, `component_count: 2`                           |

### What `add_joint` reports, and what `axis` means

`axis` (and `second_axis`) name a **model** axis — `x`, `y`, `z` in world terms.
Fusion's `JointDirections` enum names a **joint** axis, and the two frames are not the
same: the joint's axes come from the face's parametric frame, so they move with
`quadrant`. The handler resolves the request against the geometry's own axes and passes
whichever is closest.

For a cylinder whose bore is world Z with `quadrant="middle"` the joint frame is
X = −Y, Y = +Z, Z = −X, so:

| requested | slides along |
| --------- | ------------ |
| `x`       | −X           |
| `y`       | −Y           |
| `z`       | +Z (the bore)|

When the bore lies along a model axis, the chosen member matches the request exactly in
magnitude; the **sign** may not, because no member of that frame points along +X. When the
bore is off-axis (a 45° bore, say) the nearest member is 0.707 off at best — the closest
available, not an exact answer. Read `axis_world` rather than assuming either.

Measured, so worth not retrying: setting `JointInput.isFlipped` does **not** reverse a
slider, and a created joint's motion cannot be edited ("Cannot be edited before rolling
back"), so there is no flip and no probe-then-pick.

Every `add_joint` result carries the measurements behind that:

- `joint_origin` — where the origin landed. For cylinder/cone geometry Fusion puts it on
  the **surface** at the bore's radius (every valid quadrant/height combination was
  measured to), never on the axis, so a revolute joint rotates about a line offset from
  the bore by that radius. A hinge that must lock two halves together wants a joint built
  from the bore axis instead.
- `primary_axis` — the geometry's `primaryAxisVector`, as Fusion reports it. It is not
  always the bore: for the cylinder above the bore is `thirdAxisVector`, and `primary` is
  one of the two perpendicular directions.
- `axis_world` — the model-space vector the motion was given, i.e. what the resolution
  above chose.
- `directions` — every direction vector Fusion reports for the resulting joint,
  keyed by its own attribute names minus `Vector`:
  - `slideDirection` — slider, pin_slot
  - `rotationAxis` — revolute, cylindrical, pin_slot
  - `normalDirection`, `primarySlideDirection`, `secondarySlideDirection` — planar,
    which *does* slide: do not read a missing `slideDirection` as "no slide"
  - `pitchDirection`, `yawDirection`, `rollDirection` — ball

  This is Fusion's own account of the joint that came out. If the two faces' frames
  disagree it is the truth and `axis_world` is the inference.

## Inspection & Analysis

| Tool                      | Proven      | Description                                                                                                             | Evidence                                                                                                                                                                           |
| ------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `measure_distance`        | `2706.1.17` | Minimum distance between entities                                                                                       | proven — 2026-11-26, `2706.1.17`, #158: measured 1.0 cm between two points given as `x,y,z` strings                                                                                |
| `measure_angle`           | `2706.1.17` | Angle between entities                                                                                                  | proven — 2026-11-28, `2706.1.17`, #164: answered 90.0 deg between face 0 of two boxes; a box against a sphere is refused `3 : measurement failed`, so both faces have to be planar |
| `get_physical_properties` | `2706.1.17` | Mass, volume, area, center of mass                                                                                      | proven — 2026-11-26, `2706.1.17`, #158: answered mass, volume, area, density and center of mass                                                                                    |
| `create_section_analysis` | `2706.1.17` | Section plane through model                                                                                             | proven — 2026-11-28, `2706.1.17`, #164: `Section1` on xz at offset 2 through `design.analyses.sectionAnalyses`; a Component has no `analyses` live                                 |
| `check_interference`      | `2706.1.17` | Detect collisions between components                                                                                    | proven — 2026-11-28, `2706.1.17`, #164: reported one interference of 32.0 cm3 between two components whose 4 cm boxes overlap by 2 cm                                              |
| `compare_meshes`          | `2706.1.17` | **(2026+)** Deviation statistics between two mesh bodies (min/max/mean/RMS, cm) — e.g. validate against a reference STL | proven — 2026-11-28, `2706.1.17`, #164: compared `block` with `block (1)`, the same STL imported twice: 20 nodes, every deviation 0.0                                              |

## Appearance

| Tool             | Proven      | Description                                               | Evidence                                                                                                |
| ---------------- | ----------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `set_appearance` | `2706.1.17` | Assign material appearance from library                   | proven — 2026-11-28, `2706.1.17`, #164: applied `Steel - Satin` to a body: `applied: true`              |
| `set_color`      | `2706.1.17` | **(2026+)** Assign a flat RGB color (+ opacity) to a body | proven — 2026-11-26, `2706.1.17`, #158: answered `ok` with identical deltas and no no-op warning (#157) |

## Parameters

| Tool               | Proven      | Description              | Evidence                                                                                                               |
| ------------------ | ----------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `get_parameters`   | `2706.1.17` | List all user parameters | proven — 2026-11-26, `2706.1.17`, #158: answered `count: 0` and an empty parameter list                                |
| `create_parameter` | `2706.1.17` | Create a new parameter   | proven — 2026-11-28, `2706.1.17`, #164: created `plate_width` at 42 mm: `unit` `mm`, `expression` `42 mm`              |
| `set_parameter`    | `2706.1.17` | Update a parameter value | proven — 2026-11-28, `2706.1.17`, #164: drove `plate_width` 42 -> 55: `expression` `55 mm`, and the body mass followed |
| `delete_parameter` | `2706.1.17` | Remove a parameter       | proven — 2026-11-28, `2706.1.17`, #164: deleted `plate_width`; `get_parameters` went 1 -> 0                            |

## Import / Export

| Tool                | Proven      | Description                                                                                                                                                                                                                                                                                                                         | Evidence                                                                                                                                                                                                                                                                                                                                                   |
| ------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `import_mesh`       | `2706.1.17` | Import STL/OBJ/3MF as mesh body via `MeshBodies.add()`. Unit-aware (`mm`/`cm`/`m`/`in`/`ft`). Returns the mesh name and bounding box                                                                                                                                                                                                | proven — 2026-11-28, `2706.1.17`, #164: imported `block.stl` twice as mesh bodies `block` and `block (1)`, each with a bounding box                                                                                                                                                                                                                        |
| `export_stl`        | `2706.1.17` | Export body as STL (supports bodies inside components)                                                                                                                                                                                                                                                                              | proven — 2026-11-28, `2706.1.17`, #164: wrote a 10x10x10 cm body to `block.stl`: `exported: true` with the path echoed                                                                                                                                                                                                                                     |
| `export_step`       | `2706.1.17` | Export as STEP. Fusion's factory takes a **Component**, not a body (`3 : invlid argument geometry`), so this writes the component that owns the named body and the reply says `scope: component`, names it and counts `bodies_in_component`; a component holding more than one body carries a `note`. Use `export_stl` for one body | proven — 2026-11-28, `2706.1.17`, #165: wrote `one.step` (8,941 bytes) for a single-body component and said so — `scope: component`, `bodies_in_component: 1`; with a second body it wrote both (14,479 bytes) and carried the note. Fusion's `createSTEPExportOptions` takes a Component, so the unit is the component that owns the body, never the body |
| `export_f3d`        | `2706.1.17` | Export design as Fusion archive                                                                                                                                                                                                                                                                                                     | proven — 2026-11-28, `2706.1.17`, #164: wrote the design to `design.f3d`: `exported: true`                                                                                                                                                                                                                                                                 |
| `export_view_sheet` | `2706.1.17` | Export multi-view PNG sheet (iso/front/top/right) for visual inspection, plus a shareable HTML sheet                                                                                                                                                                                                                                | proven — 2026-11-28, `2706.1.17`, #164: wrote an HTML sheet and the `iso`+`front` PNGs to the Desktop default: `html_path` returned                                                                                                                                                                                                                        |
| `export`            | `2706.1.17` | Unified dispatcher — routes to `export_stl`/`export_step`/`export_f3d` based on explicit `format` or file-extension inference                                                                                                                                                                                                       | proven — 2026-11-28, `2706.1.17`, #165: `format: stl` exported a body (`exported: true`, body and path echoed) and `format: step` wrote the component that owns it (`scope: component`, `bodies_in_component: 2`, 14,486 bytes), as `export_step` alone does                                                                                               |

## CAM / Manufacturing

| Tool                     | Proven      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Evidence                                                                                                                                                                                                                                                                                                                                     |
| ------------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cam_create_setup`       | `2706.1.17` | Create a manufacturing setup (milling/turning/cutting); applies stock mode/offsets                                                                                                                                                                                                                                                                                                                                                                                                                                     | proven — 2026-11-27, `2706.1.17`, #159: created `Setup1` over a body with relative-box stock offsets                                                                                                                                                                                                                                         |
| `cam_create_operation`   | `2706.1.17` | Add a machining operation (Fusion's strategy names only); applies stepdown/feed/speed/coolant, `face_indices` selects geometry for the six strategies a selection can be applied to, and `tool_diameter` (cm) attaches a flat end mill so the operation can generate — `tool_json` takes a complete tool object instead, and `tool_number` alone reuses one the document library already holds; `checkpoint=True` saves the document first where it can and reports `saved_before` (`checkpoint_skipped` says why not) | proven — 2026-11-27, `2706.1.17`, #159: aimed a `face` operation through its `stockContours` boundary (`useStockContours` measured `true`), then generated it                                                                                                                                                                                |
| `cam_generate_toolpath`  | `2706.1.17` | Generate toolpaths for operations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | proven — 2026-11-27, `2706.1.17`, #159: answered `generated: true` for a `face` operation with no face selection                                                                                                                                                                                                                             |
| `cam_post_process`       | `2706.1.17` | Post-process to G-code — pass a full `.cps` path (cloud-post builds don't ship local posts). `program_number` (default 1001) is what the post reads as its program name: a post that sets `programNameIsInteger` parses it, and the setup's name parsed to `NaN`, failing every post of the setup                                                                                                                                                                                                                      | proven — 2026-11-28, `2706.1.17`, #165: posted the `face` operation `Face1` through Fusion's own `fanuc.cps`, producing `1001.nc` whose first line is `O1001`, and again at `program_number` 2048 (`2048.nc`, `O2048`). The setup's name used to be passed as the program name, which a post that sets `programNameIsInteger` reads as `NaN` |
| `cam_list_setups`        | `2706.1.17` | List all manufacturing setups                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | proven — 2026-11-26, `2706.1.17`, #158: answered `count: 0` on a design with no CAM setups                                                                                                                                                                                                                                                   |
| `cam_list_operations`    | `2706.1.17` | List operations in a setup                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | proven — 2026-11-28, `2706.1.17`, #164: answered the one `Face1` operation with `has_toolpath: true` and `is_valid: true`                                                                                                                                                                                                                    |
| `cam_get_operation_info` | `2706.1.17` | Get operation details (strategy, tool, parameters)                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | proven — 2026-11-27, `2706.1.17`, #159: answered `is_valid: true` and `has_toolpath: true` after generating the aimed operation                                                                                                                                                                                                              |

### Which strategies `face_indices` can aim

Six: `contour2d`, `pocket2d`, `adaptive2d`, `adaptive`, `pocket_clearing` and `face`,
each with the selection parameter `addon/server/rules.py` names for it. The other four
strategies the schema advertises take no selection this tool can write to, and
`face_indices` is refused for them before an operation is created — real and mock mode
answering one sentence that names the six. Which of those four exposes a parameter of
its own is unmeasured (one probe per strategy is its own item), so none is claimed.

`face` is measured (2706.1.17), and it has **no selection parameter of its own**: of its
327 parameters, 26 are `CadObjectParameterValue` (view and heights) and the only
`CadContours2dParameterValue` is `stockContours`. That boundary *is* how a face operation
is aimed — a `FaceContourSelection` written into it is accepted (`isValid: true`,
`hasError: false`), and the operation regenerates with `has_toolpath: true`. Fusion
honours it while `useStockContours` is true, which is its measured default; nothing in
this tool sets that flag, and nothing checks it afterwards, so a document that turned it
off would take the selection without acting on it. Without a selection the operation
still generates: it machines the stock's top.

### How `cam_create_operation` gets a tool

Three ways, one at a time:

- **`tool_diameter`** (cm) — the add-in builds a complete flat end mill, Fusion
  registers it in the document tool library itself, and the reply carries
  `diameter_cm`. `tool_length`, `tool_flutes` and `tool_number` shape that tool.
- **`tool_json`** — a complete tool object taken from a Fusion tool library, used
  verbatim. A *partial* object is not refused: measured on 2706.1.17 it **crashed
  Fusion**, taking the document's unsaved state with it, which is why the builder
  emits the whole shape.
- **`tool_number` on its own** — selects a tool the **document tool library already
  holds**, and the reply says `from_library: true` with no `diameter_cm` (the diameter
  is the library's). A number nothing holds is `NAME_NOT_FOUND`, naming the numbers
  that would work — or saying the library is empty, which is what a new document's is
  until an operation registers a tool.

Measured on 2706.1.17: `DocumentToolLibrary` has no by-number lookup, but `count` plus
`item(i)` and each tool's own `tool_number` parameter answer it (number 7 in, 7 out),
and `Operation.tool` takes the result without the library count changing.

## Code Execution

| Tool           | Proven      | Description                                                                                                                                                         | Evidence                                                                                                 |
| -------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `execute_code` | `2706.1.17` | Run arbitrary Python in Fusion (REPL-style); `checkpoint=True` saves the document first where it can and reports `saved_before` (`checkpoint_skipped` says why not) | proven — 2026-11-26, `2706.1.17`, #158: ran a script; a no-op script carries the snapshot warning (#157) |

## Perception

| Tool          | Proven      | Description                                                                                                                    | Evidence                                                                                           |
| ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `render_view` | `2706.1.17` | Capture the active viewport as PNG (optional camera preset: iso/front/top/...). Returns an image block for visual verification | proven — 2026-11-26, `2706.1.17`, #158: returned a PNG: `bytes`, `width`, `height`, `image_format` |
