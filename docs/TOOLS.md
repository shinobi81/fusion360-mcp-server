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
| `shell`               | Hollow out a body                     |
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

- `edge_selection` — the coarse filter (`all`, `top`, `bottom`, `vertical`);
  `top` means the highest edges of the body's bounding box.
- `edge_indices` — exact edges, numbered as `list_edges` reports them. Indices are positional
  and move when the body changes, so re-list before relying on them.
- `edge_points` + `edge_tolerance` (cm, default 0.1) — each point snaps to its nearest edge;
  a point too far away, or one equally close to two edges, is refused with the measurement.

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
