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
checked against **Fusion 2706.1.17**'s API — whether each has been *called* is
`docs/PROVEN.md`, not this paragraph.

The **Proven** column is the build each tool has answered a real Fusion on, or an em
dash where nothing has succeeded yet. It is generated from the table below and never
written by hand: `uv run python scripts/sync_proven_column.py` rewrites it, `--check`
reports a stale one, and `tests/test_proven.py` fails while they disagree.

Which of these has been *called* against a real Fusion — and what it answered — is
`docs/PROVEN.md`, one row per tool, with the date, the PR holding the envelope and, for
an unproven tool, why. A row that says `unproven` is where the next defect
nobody has looked for is. `uv run python scripts/check_proven.py --live` re-probes the
read-only tools it chooses to send — twelve of the nineteen — and reports a row whose
reply contradicts its state, in either direction. Two of those twelve touch the session:
`cam_list_setups` activates the Manufacture workspace, and `render_view` repositions the
camera for its capture and restores it before returning.

## Scene & Query

| Tool               | Proven      | Description                                                                                                                                            |
| ------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ping`             | `2706.1.17` | Health check (instant, no Fusion API)                                                                                                                  |
| `health`           | `2706.1.17` | Health check on Fusion's main thread: `app_version`, `active_document`, `queue_depth`; times out when the thread is wedged, where `ping` still answers |
| `get_scene_info`   | `2706.1.17` | Design name, bodies, sketches, features, camera                                                                                                        |
| `get_object_info`  | `2706.1.17` | Detailed info about a named body or sketch                                                                                                             |
| `list_edges`       | `2706.1.17` | A body's edges: index, endpoints, midpoint, length, curve type                                                                                         |
| `list_faces`       | `2706.1.17` | A body's faces: index, surface type, planarity, area, centroid, and normal when planar                                                                 |
| `get_bounding_box` | `2706.1.17` | Axis-aligned bbox (min/max/size/center) for body or component; unions all bodies when called on a component                                            |
| `list_components`  | `2706.1.17` | List all components in the design                                                                                                                      |

## Document

| Tool              | Proven      | Description                                                                                                                                                                                                                                                                                    |
| ----------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `new_document`    | `2706.1.17` | Create a design document and make it active — the way in from a cold start                                                                                                                                                                                                                     |
| `save_document`   | `2706.1.17` | Save the active document in place, or an untitled one by name into Fusion's active data folder (no local-file save exists in this API); answers `saved`, `name`, `folder`, `saved_as` and `is_modified`; a `name` passed for an already-saved document is ignored and echoed as `name_ignored` |
| `get_design_type` | `2706.1.17` | Check if the design is parametric or direct                                                                                                                                                                                                                                                    |
| `set_design_type` | `2706.1.17` | Switch design type (parametric/direct recovery)                                                                                                                                                                                                                                                |

## Sketching

| Tool               | Proven      | Description                                                                                                              |
| ------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------ |
| `create_sketch`    | `2706.1.17` | New sketch on xy/yz/xz plane, optional offset                                                                            |
| `draw_rectangle`   | `2706.1.17` | Rectangle in most recent sketch, or in `sketch_name`                                                                     |
| `draw_circle`      | `2706.1.17` | Circle in most recent sketch, or in `sketch_name`                                                                        |
| `draw_line`        | `2706.1.17` | Line in most recent sketch, or in `sketch_name`                                                                          |
| `draw_arc`         | `2706.1.17` | Arc (center + start + sweep angle)                                                                                       |
| `draw_spline`      | `2706.1.17` | Fit-point or control-point spline                                                                                        |
| `create_polygon`   | `2706.1.17` | Regular polygon (3–64 sides)                                                                                             |
| `draw_circles`     | `2706.1.17` | Several equally spaced circles in one solve — far faster than one call per circle                                        |
| `add_constraint`   | `2706.1.17` | Geometric constraint (coincident, parallel, tangent, etc.)                                                               |
| `auto_constrain`   | —           | **(2026+)** Auto-constrain a sketch via the AutoConstrain API — 3 result options (thorough / fast / tolerance-adjusting) |
| `add_dimension`    | `2706.1.17` | Driving dimension (distance, angle, radial, diameter)                                                                    |
| `offset_curve`     | `2706.1.17` | Offset connected sketch curves                                                                                           |
| `trim_curve`       | `2706.1.17` | Trim at intersections                                                                                                    |
| `extend_curve`     | `2706.1.17` | Extend to nearest intersection                                                                                           |
| `project_geometry` | `2706.1.17` | Project edges/bodies onto sketch plane                                                                                   |

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

| Tool                  | Proven      | Description                                                                                                                                                                                                                                                                                                                      |
| --------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extrude`             | `2706.1.17` | Extrude a sketch profile; `target_body` limits a cut/join/intersect                                                                                                                                                                                                                                                              |
| `revolve`             | `2706.1.17` | Revolve about a model-space axis (must be coplanar with the profile); `target_body` limits a cut/join/intersect                                                                                                                                                                                                                  |
| `sweep`               | `2706.1.17` | Sweep a profile along a path; `target_body` limits a cut/join/intersect                                                                                                                                                                                                                                                          |
| `loft`                | `2706.1.17` | Loft between two or more profiles; `target_body` limits a cut/join/intersect                                                                                                                                                                                                                                                     |
| `fillet`              | `2706.1.17` | Round edges: all/top/bottom/vertical, or `edge_indices` / `edge_points`                                                                                                                                                                                                                                                          |
| `chamfer`             | `2706.1.17` | Chamfer edges: same three selectors as `fillet`                                                                                                                                                                                                                                                                                  |
| `shell`               | `2706.1.17` | Hollow out a body; `face_selection` (top/bottom) is the face left **open**                                                                                                                                                                                                                                                       |
| `mirror`              | `2706.1.17` | Mirror a body across a plane                                                                                                                                                                                                                                                                                                     |
| `create_hole`         | `2706.1.17` | Hole feature on a body face                                                                                                                                                                                                                                                                                                      |
| `rectangular_pattern` | `2706.1.17` | Pattern in rows and columns                                                                                                                                                                                                                                                                                                      |
| `circular_pattern`    | `2706.1.17` | Pattern around an axis                                                                                                                                                                                                                                                                                                           |
| `create_thread`       | `2706.1.17` | Add threads (cosmetic or modeled). **Refuses** a designation that does not match the face - Fusion would resize the body to it (an `M6x1` thread on a 20 mm shaft leaves a 5.88 mm one) - and names the thread that fits; `allow_resize=true` accepts the resize. `thread_class` defaults to 6H internal / 6g external (ISO 965) |
| `draft_faces`         | `2706.1.17` | Draft/taper faces for mold release                                                                                                                                                                                                                                                                                               |
| `split_body`          | `2706.1.17` | Split a body using a plane                                                                                                                                                                                                                                                                                                       |
| `split_face`          | `2706.1.17` | Split faces of a body                                                                                                                                                                                                                                                                                                            |
| `offset_faces`        | `2706.1.17` | Push/pull faces by a distance                                                                                                                                                                                                                                                                                                    |
| `scale_body`          | `2706.1.17` | Scale uniformly or non-uniformly about `anchor_*`. The anchor is a *reference*: it becomes a sketch point in a hidden reference sketch (named in the reply), because Fusion refuses a bare coordinate with `3 : invalid ref point`                                                                                               |
| `suppress_feature`    | `2706.1.17` | Suppress a timeline feature                                                                                                                                                                                                                                                                                                      |
| `unsuppress_feature`  | `2706.1.17` | Re-enable a suppressed feature                                                                                                                                                                                                                                                                                                   |

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

| Tool                | Proven      | Description                                               |
| ------------------- | ----------- | --------------------------------------------------------- |
| `move_body`         | `2706.1.17` | Translate a body by (x, y, z)                             |
| `rename_body`       | `2706.1.17` | Rename a body (searches root and all components)          |
| `boolean_operation` | `2706.1.17` | Join/cut/intersect two bodies; `keep_tool` keeps the tool |
| `delete_all`        | `2706.1.17` | Clear the design                                          |
| `undo`              | `2706.1.17` | Step back one timeline feature (verified; see note)       |

## Direct Primitives

| Tool                    | Proven      | Description                                                                                                                                                                                       |
| ----------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_box`            | `2706.1.17` | Box (via TemporaryBRepManager, history-less), centred on `center_x`/`center_y`/`center_z`: it spans half its size either side of that point on every axis                                         |
| `create_box_parametric` | `2706.1.17` | History-based box: sketch rectangle + dimensions + extrude. `length`/`width`/`height` accept numbers (cm) or string expressions referencing User Parameters (e.g. `"boxL"`, `"outer - 2*wall_t"`) |
| `create_cylinder`       | `2706.1.17` | Cylinder                                                                                                                                                                                          |
| `create_sphere`         | `2706.1.17` | Sphere                                                                                                                                                                                            |
| `create_torus`          | `2706.1.17` | Torus                                                                                                                                                                                             |

## Surface Operations

| Tool              | Proven      | Description                                                                                                                                                                                                                                                                                 |
| ----------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `patch_surface`   | `2706.1.17` | Create a patch surface from a sketch profile. `continuity` applies to B-Rep edge boundaries and is ignored for sketch curves, which is this tool's only accepted boundary                                                                                                                   |
| `stitch_surfaces` | `2706.1.17` | Stitch surface bodies into one                                                                                                                                                                                                                                                              |
| `thicken_surface` | `2706.1.17` | Thicken a surface into a solid                                                                                                                                                                                                                                                              |
| `ruled_surface`   | `2706.1.17` | Ruled surface from a **free** edge — a sheet body's boundary. A solid's edge is shared by two faces and Fusion refuses it (`invalid free edge`); patch or stitch to a surface body first                                                                                                    |
| `trim_surface`    | `2706.1.17` | Trim a surface with a body or a base plane. `keep_cells` lists the cells that survive; every other cell is removed. Fusion offers no side to name - a trimmed patch's cells all report a zero centroid - so the indices are the caller's choice, and the refusal reports how many there are |

## Sheet Metal

| Tool            | Proven      | Description                                                                                                                                                                         |
| --------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_flange` | `2706.1.17` | Create an edge flange. `distance` is the flange length; `bend_radius_override` applies to this flange only                                                                          |
| `create_bend`   | `2706.1.17` | Fold along a sketch line. `stationary_face_index` is the face that stays fixed - a wrong one bends the part the wrong way; `line_position` is where the line sits in the flat state |
| `flat_pattern`  | `2706.1.17` | Create flat pattern, pinned on the body's largest planar face (its top or bottom)                                                                                                   |
| `unfold`        | `2706.1.17` | Unfold specific bends, or every one; pinned on the same largest planar face                                                                                                         |

## Construction Geometry

| Tool                        | Proven      | Description                                                                                               |
| --------------------------- | ----------- | --------------------------------------------------------------------------------------------------------- |
| `create_construction_plane` | `2706.1.17` | Offset, angle, midplane, 3-point, tangent (`body_name` + `face_index`; `angle` + `plane`, or `point_one`) |
| `create_construction_axis`  | `2706.1.17` | Two-point, intersection, edge, perpendicular (`face_index` + `point_one`)                                 |
| `create_ucs`                | `2706.1.17` | **(2026+, preview API)** User Coordinate System at a point with optional rotation                         |

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

| Tool                    | Proven      | Description                                                         |
| ----------------------- | ----------- | ------------------------------------------------------------------- |
| `create_component`      | `2706.1.17` | Create a sub-assembly component                                     |
| `add_joint`             | `2706.1.17` | Joint between two components                                        |
| `set_joint_value`       | `2706.1.17` | Drive a joint and read the value back (angles in deg, slides in cm) |
| `create_as_built_joint` | `2706.1.17` | Joint from current positions                                        |
| `create_rigid_group`    | `2706.1.17` | Lock components together                                            |

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

| Tool                      | Proven      | Description                                                                                                             |
| ------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------- |
| `measure_distance`        | `2706.1.17` | Minimum distance between entities                                                                                       |
| `measure_angle`           | `2706.1.17` | Angle between entities                                                                                                  |
| `get_physical_properties` | `2706.1.17` | Mass, volume, area, center of mass                                                                                      |
| `create_section_analysis` | `2706.1.17` | Section plane through model                                                                                             |
| `check_interference`      | `2706.1.17` | Detect collisions between components                                                                                    |
| `compare_meshes`          | `2706.1.17` | **(2026+)** Deviation statistics between two mesh bodies (min/max/mean/RMS, cm) — e.g. validate against a reference STL |

## Appearance

| Tool             | Proven      | Description                                               |
| ---------------- | ----------- | --------------------------------------------------------- |
| `set_appearance` | `2706.1.17` | Assign material appearance from library                   |
| `set_color`      | `2706.1.17` | **(2026+)** Assign a flat RGB color (+ opacity) to a body |

## Parameters

| Tool               | Proven      | Description              |
| ------------------ | ----------- | ------------------------ |
| `get_parameters`   | `2706.1.17` | List all user parameters |
| `create_parameter` | `2706.1.17` | Create a new parameter   |
| `set_parameter`    | `2706.1.17` | Update a parameter value |
| `delete_parameter` | `2706.1.17` | Remove a parameter       |

## Import / Export

| Tool                | Proven      | Description                                                                                                                                                                                                                                                                                                                         |
| ------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `import_mesh`       | `2706.1.17` | Import STL/OBJ/3MF as mesh body via `MeshBodies.add()`. Unit-aware (`mm`/`cm`/`m`/`in`/`ft`). Returns the mesh name and bounding box                                                                                                                                                                                                |
| `export_stl`        | `2706.1.17` | Export body as STL (supports bodies inside components)                                                                                                                                                                                                                                                                              |
| `export_step`       | `2706.1.17` | Export as STEP. Fusion's factory takes a **Component**, not a body (`3 : invlid argument geometry`), so this writes the component that owns the named body and the reply says `scope: component`, names it and counts `bodies_in_component`; a component holding more than one body carries a `note`. Use `export_stl` for one body |
| `export_f3d`        | `2706.1.17` | Export design as Fusion archive                                                                                                                                                                                                                                                                                                     |
| `export_view_sheet` | `2706.1.17` | Export multi-view PNG sheet (iso/front/top/right) for visual inspection, plus a shareable HTML sheet                                                                                                                                                                                                                                |
| `export`            | `2706.1.17` | Unified dispatcher — routes to `export_stl`/`export_step`/`export_f3d` based on explicit `format` or file-extension inference                                                                                                                                                                                                       |

## CAM / Manufacturing

| Tool                     | Proven      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cam_create_setup`       | `2706.1.17` | Create a manufacturing setup (milling/turning/cutting); applies stock mode/offsets                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `cam_create_operation`   | `2706.1.17` | Add a machining operation (Fusion's strategy names only); applies stepdown/feed/speed/coolant, `face_indices` selects geometry for the six strategies a selection can be applied to, and `tool_diameter` (cm) attaches a flat end mill so the operation can generate — `tool_json` takes a complete tool object instead, and `tool_number` alone reuses one the document library already holds; `checkpoint=True` saves the document first where it can and reports `saved_before` (`checkpoint_skipped` says why not) |
| `cam_generate_toolpath`  | `2706.1.17` | Generate toolpaths for operations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `cam_post_process`       | `2706.1.17` | Post-process to G-code — pass a full `.cps` path (cloud-post builds don't ship local posts). `program_number` (default 1001) is what the post reads as its program name: a post that sets `programNameIsInteger` parses it, and the setup's name parsed to `NaN`, failing every post of the setup                                                                                                                                                                                                                      |
| `cam_list_setups`        | `2706.1.17` | List all manufacturing setups                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `cam_list_operations`    | `2706.1.17` | List operations in a setup                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `cam_get_operation_info` | `2706.1.17` | Get operation details (strategy, tool, parameters)                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

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

| Tool           | Proven      | Description                                                                                                                                                         |
| -------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute_code` | `2706.1.17` | Run arbitrary Python in Fusion (REPL-style); `checkpoint=True` saves the document first where it can and reports `saved_before` (`checkpoint_skipped` says why not) |

## Perception

| Tool          | Proven      | Description                                                                                                                    |
| ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `render_view` | `2706.1.17` | Capture the active viewport as PNG (optional camera preset: iso/front/top/...). Returns an image block for visual verification |
