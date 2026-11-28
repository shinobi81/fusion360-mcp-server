# Proven against Fusion

One row per tool, and the evidence behind it. A tool whose row says **proven** has
been called against a real Fusion and answered what the row claims. **Unproven**
means no successful answer exists — nobody called it, or it was only ever refused —
and the row says which. Nothing here is aspirational: an `unproven` row is where the
next unknown defect lives. *Mutation* in a row means a call that changes the design,
not membership of `addon/server/mutation_commands.py`, which is the narrower set
that also reports `deltas`.

The convention, checked by `scripts/check_proven.py` and `tests/test_proven.py`:

- `proven — YYYY-MM-DD, version, #pr: what was measured`, where the version is the
  running `app.version` in backticks and the PR is the one that added the row, whose
  body carries the envelope. A trailing `(#157)` names a *different* PR whose body
  carries the envelope — the measurement's own, when the row cites it.
- `unproven — <why>`, one line. "Only a refusal is exercised" is a reason; "not yet"
  is not.

`uv run python scripts/check_proven.py` validates this table against
`src/fusion360_mcp/tools.py` without needing Fusion. `--live` sends the read-only
tools it chooses to send — twelve of the nineteen — and reports a row whose reply
contradicts its state, in either direction; a *proven* row it sends no call to is
reported as not probed, never as passing. Two of those twelve touch the session:
`cam_list_setups` activates the Manufacture workspace, and `render_view` repositions
the camera for its capture and restores it before returning.

| Tool | Evidence |
| --- | --- |
| `get_scene_info` | proven — 2026-11-26, `2706.1.17`, #158: reported a one-body parametric design's bodies, counts and camera |
| `get_object_info` | proven — 2026-11-26, `2706.1.17`, #158: answered a body's face/edge/vertex counts, volume and bbox |
| `get_bounding_box` | proven — 2026-11-26, `2706.1.17`, #158: answered a box's min/max/size/center |
| `create_sketch` | proven — 2026-11-26, `2706.1.17`, #158: created `Sketch1` on xy with a z offset |
| `draw_rectangle` | proven — 2026-11-26, `2706.1.17`, #158: reported `model_origin` for a 10x10 rectangle |
| `draw_circle` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `draw_line` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `extrude` | proven — 2026-11-26, `2706.1.17`, #158: cut a 15.7 g void from a box; a cut whose profile reached nothing was refused by Fusion (`3 : No target body found to cut or intersect!`) |
| `revolve` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `fillet` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `chamfer` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `shell` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `mirror` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `rename_body` | proven — 2026-11-26, `2706.1.17`, #158: renamed a body, reporting `old_name` and `new_name` (#157) |
| `move_body` | proven — 2026-11-26, `2706.1.17`, #158: moved a body and the root bbox followed, measured (#157) |
| `export_stl` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `boolean_operation` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `delete_all` | proven — 2026-11-26, `2706.1.17`, #158: swept a sketch-only design and reported what it removed (#157) |
| `undo` | proven — 2026-11-26, `2706.1.17`, #158: stepped a parametric timeline back, `verified: true` (#157) |
| `execute_code` | proven — 2026-11-26, `2706.1.17`, #158: ran a script; a no-op script carries the snapshot warning (#157) |
| `sweep` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `loft` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_polygon` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `draw_arc` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_hole` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `rectangular_pattern` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `circular_pattern` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `save_document` | proven — 2026-11-27, `2706.1.17`, #162: refused an untitled document with no name (nothing written), saved it by name into the active data folder (`saved_as: true`, `is_modified: false`), then — after `create_box` modified it, `isSaved: True`/`isModified: True` — saved in place (`saved_as: false`, `is_modified: false`, read back as `True False`); `checkpoint=True` reported `saved_before: true` on `execute_code` and `cam_create_operation` |
| `new_document` | proven — 2026-11-26, `2706.1.17`, #158: created an active parametric design document |
| `create_component` | proven — 2026-11-26, `2706.1.17`, #158: created `C1`; a body added to it is counted in the snapshot |
| `add_joint` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `set_joint_value` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `list_edges` | proven — 2026-11-26, `2706.1.17`, #158: answered a box's twelve edges with index and midpoint |
| `list_faces` | proven — 2026-11-26, `2706.1.17`, #158: answered a box's six faces with index, surface_type and normal (#147) |
| `list_components` | proven — 2026-11-26, `2706.1.17`, #158: answered `Component1` with `count` |
| `export_step` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `export_f3d` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `export_view_sheet` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `export` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `import_mesh` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `get_parameters` | proven — 2026-11-26, `2706.1.17`, #158: answered `count: 0` and an empty parameter list |
| `create_parameter` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `set_parameter` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `delete_parameter` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `draw_circles` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `add_constraint` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `auto_constrain` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `add_dimension` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_construction_plane` | proven — 2026-11-27, `2706.1.17`, #160: built a plane (`Plane1`, then `Plane2` for `edge_name="Y"`); refused `edge_name="w"` with the axis sentence, and a missing angle with `3 : invalid expression` before this PR's rule (#160) |
| `create_construction_axis` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_ucs` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `draw_spline` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `offset_curve` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `trim_curve` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `extend_curve` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_thread` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `draft_faces` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `split_body` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `split_face` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `offset_faces` | proven — 2026-11-26, `2706.1.17`, #158: ran with distance 0 and its `deltas` counted the surface body it created |
| `scale_body` | unproven — only a refusal is exercised: `3 : invalid ref point` on every call (#157) |
| `create_box` | proven — 2026-11-26, `2706.1.17`, #158: reported `deltas` body_count 0 -> 1 and 502.4 g |
| `create_box_parametric` | proven — 2026-11-26, `2706.1.17`, #158: reported `deltas` body_count 0 -> 1 and 62.8 g (#157) |
| `create_cylinder` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_sphere` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_torus` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_as_built_joint` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_rigid_group` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `measure_distance` | proven — 2026-11-26, `2706.1.17`, #158: measured 1.0 cm between two points given as `x,y,z` strings |
| `measure_angle` | proven — 2026-11-26, `2706.1.17`, #158: answered `angle_degrees` for one body's face 0 against itself — the call shape, not two distinct entities |
| `get_physical_properties` | proven — 2026-11-26, `2706.1.17`, #158: answered mass, volume, area, density and center of mass |
| `create_section_analysis` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `check_interference` | unproven — only a refusal is exercised: `GEOMETRY_UNSUPPORTED` with one component |
| `compare_meshes` | unproven — only a live refusal was observed; the comparison itself is exercised against fakes (`tests/test_addon_document.py`) |
| `set_appearance` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `set_color` | proven — 2026-11-26, `2706.1.17`, #158: answered `ok` with identical deltas and no no-op warning (#157) |
| `project_geometry` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `suppress_feature` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `unsuppress_feature` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `patch_surface` | proven — 2026-11-26, `2706.1.17`, #158: created a surface body, body_count +1 (#157) |
| `stitch_surfaces` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `thicken_surface` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `ruled_surface` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `trim_surface` | proven — 2026-11-26, `2706.1.17`, #158: trimmed a surface with a plane and shrank the bbox (#157) |
| `create_flange` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `create_bend` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `flat_pattern` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `unfold` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `cam_create_setup` | proven — 2026-11-27, `2706.1.17`, #159: created `Setup1` over a body with relative-box stock offsets |
| `cam_create_operation` | proven — 2026-11-27, `2706.1.17`, #159: aimed a `face` operation through its `stockContours` boundary (`useStockContours` measured `true`), then generated it |
| `cam_generate_toolpath` | proven — 2026-11-27, `2706.1.17`, #159: answered `generated: true` for a `face` operation with no face selection |
| `cam_post_process` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `cam_list_setups` | proven — 2026-11-26, `2706.1.17`, #158: answered `count: 0` on a design with no CAM setups |
| `cam_list_operations` | unproven — only a refusal is exercised: `NAME_NOT_FOUND` with no setups |
| `cam_get_operation_info` | proven — 2026-11-27, `2706.1.17`, #159: answered `is_valid: true` and `has_toolpath: true` after generating the aimed operation |
| `health` | proven — 2026-11-27, `2706.1.17`, #161: answered `app_version` `2706.1.17` and `active_document` from the main thread, and failed at the 3 s `--timeout` the probe passed while the thread was blocked; `queue_depth` is null live because the running `EventBridge` predates this change (the reload does not cover that module); the bridge hands itself to the handler, and that hand-off plus the depth it reads is pinned by `tests/test_addon_bridge.py` (construction), `tests/test_addon_importable.py` (reload) and `tests/test_addon_scene_reads.py` (the depth) |
| `ping` | proven — 2026-11-26, `2706.1.17`, #158: answered `{status: pong}` — from the socket fast path, never from the handler |
| `get_design_type` | proven — 2026-11-26, `2706.1.17`, #158: answered `parametric` with `design_type_id` |
| `set_design_type` | unproven — mutation; no live call made — the suite covers its handler against fakes only |
| `render_view` | proven — 2026-11-26, `2706.1.17`, #158: returned a PNG: `bytes`, `width`, `height`, `image_format` |
