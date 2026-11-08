# Tools

All 97 tools this server exposes, grouped by what they do. Every tool returns the same
envelope — `ok`, plus tool-specific fields, plus `deltas` for mutations — and failures come
back as data (`error_kind`, `hints`, `traceback`) rather than exceptions.

Units are **centimetres** throughout: Fusion's internal unit, not millimetres. Tools
marked **(2026+)** use APIs that need a Fusion build from 2026 or later; the rest were
verified on **Fusion 2706.1.17**.

## Scene & Query

| Tool               | Description                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------------- |
| `ping`             | Health check (instant, no Fusion API)                                                                       |
| `get_scene_info`   | Design name, bodies, sketches, features, camera                                                             |
| `get_object_info`  | Detailed info about a named body or sketch                                                                  |
| `list_edges`      | A body's edges: index, endpoints, midpoint, length, curve type                      |
| `get_bounding_box` | Axis-aligned bbox (min/max/size/center) for body or component; unions all bodies when called on a component |
| `list_components`  | List all components in the design                                                                           |

## Document

| Tool              | Description                                                                            |
| ----------------- | -------------------------------------------------------------------------------------- |
| `new_document`    | Create a design document and make it active — the way in from a cold start             |
| `get_design_type` | Check if the design is parametric or direct                                            |
| `set_design_type` | Switch design type (parametric/direct recovery)                                        |

## Sketching

| Tool               | Description                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `create_sketch`    | New sketch on xy/yz/xz plane, optional offset                                                                            |
| `draw_rectangle`   | Rectangle in most recent sketch, or in `sketch_name`                                                                     |
| `draw_circle`      | Circle in most recent sketch, or in `sketch_name`                                                                        |
| `draw_line`        | Line in most recent sketch, or in `sketch_name`                                                                          |
| `draw_arc`         | Arc (center + start + sweep angle)                                                                                       |
| `draw_spline`      | Fit-point or control-point spline                                                                                        |
| `create_polygon`   | Regular polygon (3–64 sides)                                                                                             |
| `draw_circles`    | Several equally spaced circles in one solve — far faster than one call per circle         |
| `add_constraint`   | Geometric constraint (coincident, parallel, tangent, etc.)                                                               |
| `auto_constrain`   | **(2026+)** Auto-constrain a sketch via the AutoConstrain API — 3 result options (thorough / fast / tolerance-adjusting) |
| `add_dimension`    | Driving dimension (distance, angle, radial, diameter)                                                                    |
| `offset_curve`     | Offset connected sketch curves                                                                                           |
| `trim_curve`       | Trim at intersections                                                                                                    |
| `extend_curve`     | Extend to nearest intersection                                                                                           |
| `project_geometry` | Project edges/bodies onto sketch plane                                                                                   |

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

| Tool                  | Description                           |
| --------------------- | ------------------------------------- |
| `extrude`             | Extrude a sketch profile; `target_body` limits a cut/join/intersect |
| `revolve`             | Revolve about a model-space axis (must be coplanar with the profile); `target_body` limits a cut/join/intersect |
| `sweep`               | Sweep a profile along a path; `target_body` limits a cut/join/intersect |
| `loft`                | Loft between two or more profiles; `target_body` limits a cut/join/intersect |
| `fillet`              | Round edges: all/top/bottom/vertical, or `edge_indices` / `edge_points` |
| `chamfer`             | Chamfer edges: same three selectors as `fillet` |
| `shell`               | Hollow out a body; `face_selection` (top/bottom) is the face left **open** |
| `mirror`              | Mirror a body across a plane          |
| `create_hole`         | Hole feature on a body face           |
| `rectangular_pattern` | Pattern in rows and columns           |
| `circular_pattern`    | Pattern around an axis                |
| `create_thread`       | Add threads (cosmetic or modeled)     |
| `draft_faces`         | Draft/taper faces for mold release    |
| `split_body`          | Split a body using a plane            |
| `split_face`          | Split faces of a body                 |
| `offset_faces`        | Push/pull faces by a distance         |
| `scale_body`          | Scale uniformly or non-uniformly      |
| `suppress_feature`    | Suppress a timeline feature           |
| `unsuppress_feature`  | Re-enable a suppressed feature        |

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

| Tool                | Description                                         |
| ------------------- | --------------------------------------------------- |
| `move_body`         | Translate a body by (x, y, z)                       |
| `rename_body`       | Rename a body (searches root and all components)    |
| `boolean_operation` | Join/cut/intersect two bodies; `keep_tool` keeps the tool |
| `delete_all`        | Clear the design                                    |
| `undo`              | Step back one timeline feature (verified; see note) |

## Direct Primitives

| Tool                    | Description                                                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_box`            | Box (via TemporaryBRepManager, history-less)                                                                                                                                                      |
| `create_box_parametric` | History-based box: sketch rectangle + dimensions + extrude. `length`/`width`/`height` accept numbers (cm) or string expressions referencing User Parameters (e.g. `"boxL"`, `"outer - 2*wall_t"`) |
| `create_cylinder`       | Cylinder                                                                                                                                                                                          |
| `create_sphere`         | Sphere                                                                                                                                                                                            |
| `create_torus`          | Torus                                                                                                                                                                                             |

## Surface Operations

| Tool              | Description                                |
| ----------------- | ------------------------------------------ |
| `patch_surface`   | Create a patch surface from boundary edges |
| `stitch_surfaces` | Stitch surface bodies into one             |
| `thicken_surface` | Thicken a surface into a solid             |
| `ruled_surface`   | Ruled surface from an edge                 |
| `trim_surface`    | Trim a surface with another body           |

## Sheet Metal

| Tool            | Description                |
| --------------- | -------------------------- |
| `create_flange` | Create a flange on an edge |
| `create_bend`   | Add a bend                 |
| `flat_pattern`  | Create flat pattern        |
| `unfold`        | Unfold specific bends      |

## Construction Geometry

| Tool                        | Description                                                                       |
| --------------------------- | --------------------------------------------------------------------------------- |
| `create_construction_plane` | Offset, angle, midplane, 3-point, tangent                                         |
| `create_construction_axis`  | Two-point, intersection, edge, perpendicular                                      |
| `create_ucs`                | **(2026+, preview API)** User Coordinate System at a point with optional rotation |

## Assembly

| Tool                    | Description                     |
| ----------------------- | ------------------------------- |
| `create_component`      | Create a sub-assembly component |
| `add_joint`             | Joint between two components    |
| `set_joint_value`       | Drive a joint and read the value back (angles in deg, slides in cm) |
| `create_as_built_joint` | Joint from current positions    |
| `create_rigid_group`    | Lock components together        |

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

| Tool                      | Description                                                                                                             |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `measure_distance`        | Minimum distance between entities                                                                                       |
| `measure_angle`           | Angle between entities                                                                                                  |
| `get_physical_properties` | Mass, volume, area, center of mass                                                                                      |
| `create_section_analysis` | Section plane through model                                                                                             |
| `check_interference`      | Detect collisions between components                                                                                    |
| `compare_meshes`          | **(2026+)** Deviation statistics between two mesh bodies (min/max/mean/RMS, cm) — e.g. validate against a reference STL |

## Appearance

| Tool             | Description                                               |
| ---------------- | --------------------------------------------------------- |
| `set_appearance` | Assign material appearance from library                   |
| `set_color`      | **(2026+)** Assign a flat RGB color (+ opacity) to a body |

## Parameters

| Tool               | Description              |
| ------------------ | ------------------------ |
| `get_parameters`   | List all user parameters |
| `create_parameter` | Create a new parameter   |
| `set_parameter`    | Update a parameter value |
| `delete_parameter` | Remove a parameter       |

## Import / Export

| Tool                | Description                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `import_mesh`       | Import STL/OBJ/3MF as mesh body via `MeshBodies.add()`. Unit-aware (`mm`/`cm`/`m`/`in`/`ft`). Returns the mesh name and bounding box |
| `export_stl`        | Export body as STL (supports bodies inside components)                                                                               |
| `export_step`       | Export body as STEP (supports bodies inside components)                                                                              |
| `export_f3d`        | Export design as Fusion archive                                                                                                      |
| `export_view_sheet` | Export multi-view PNG sheet (iso/front/top/right) for visual inspection                                                              |
| `export`            | Unified dispatcher — routes to `export_stl`/`export_step`/`export_f3d` based on explicit `format` or file-extension inference        |

## CAM / Manufacturing

| Tool                     | Description                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `cam_create_setup`       | Create a manufacturing setup (milling/turning/cutting); applies stock mode/offsets                                  |
| `cam_create_operation`   | Add a machining operation (face, contour, adaptive, drilling, etc.); applies stepdown/feed/speed/coolant parameters |
| `cam_generate_toolpath`  | Generate toolpaths for operations                                                                                   |
| `cam_post_process`       | Post-process to G-code — pass a full `.cps` path (cloud-post builds don't ship local posts)                         |
| `cam_list_setups`        | List all manufacturing setups                                                                                       |
| `cam_list_operations`    | List operations in a setup                                                                                          |
| `cam_get_operation_info` | Get operation details (strategy, tool, parameters)                                                                  |

## Code Execution

| Tool           | Description                                 |
| -------------- | ------------------------------------------- |
| `execute_code` | Run arbitrary Python in Fusion (REPL-style) |

## Perception

| Tool          | Description                                                                                                                    |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `render_view` | Capture the active viewport as PNG (optional camera preset: iso/front/top/...). Returns an image block for visual verification |
