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
| `draw_circle` | proven — 2026-11-28, `2706.1.17`, #164: drew a R1.5 cm circle at (5,3) and reported `model_center` |
| `draw_line` | proven — 2026-11-28, `2706.1.17`, #164: drew (-5,8)->(5,8.4) and reported `model_start`/`model_end` in model space |
| `extrude` | proven — 2026-11-26, `2706.1.17`, #158: cut a 15.7 g void from a box; a cut whose profile reached nothing was refused by Fusion (`3 : No target body found to cut or intersect!`) |
| `revolve` | proven — 2026-11-28, `2706.1.17`, #164: revolved a 2x4 cm rectangle 360 deg about the vertical model axis at x=10: `body_count` 1 -> 2, `axis_model_start` (10,0,0), `axis_model_end` (10,10,0) |
| `fillet` | proven — 2026-11-28, `2706.1.17`, #164: filleted the four top edges at r=0.3: mass 625.49 -> 623.14 g |
| `chamfer` | proven — 2026-11-28, `2706.1.17`, #164: chamfered edge 0 at 0.4: mass 628.0 -> 625.49 g |
| `shell` | proven — 2026-11-28, `2706.1.17`, #164: removed the top face at a 0.25 cm wall: mass 623.14 -> 168.67 g, `faces_removed: 1` |
| `mirror` | proven — 2026-11-28, `2706.1.17`, #164: mirrored a body across yz: `body_count` 5 -> 6 |
| `rename_body` | proven — 2026-11-26, `2706.1.17`, #158: renamed a body, reporting `old_name` and `new_name` (#157) |
| `move_body` | proven — 2026-11-26, `2706.1.17`, #158: moved a body and the root bbox followed, measured (#157) |
| `export_stl` | proven — 2026-11-28, `2706.1.17`, #164: wrote a 10x10x10 cm body to `block.stl`: `exported: true` with the path echoed |
| `boolean_operation` | proven — 2026-11-28, `2706.1.17`, #164: joined `ParaBox` into `Body1`: `body_count` 4 -> 3, `Combine1` |
| `delete_all` | proven — 2026-11-26, `2706.1.17`, #158: swept a sketch-only design and reported what it removed (#157) |
| `undo` | proven — 2026-11-26, `2706.1.17`, #158: stepped a parametric timeline back, `verified: true` (#157) |
| `execute_code` | proven — 2026-11-26, `2706.1.17`, #158: ran a script; a no-op script carries the snapshot warning (#157) |
| `sweep` | proven — 2026-11-28, `2706.1.17`, #164: swept a circle on xz along a line on xy: `body_count` 2 -> 3, `Sweep1` |
| `loft` | proven — 2026-11-28, `2706.1.17`, #164: lofted a square at z=0 to a circle at z=10: `body_count` 3 -> 4, `Loft1` |
| `create_polygon` | proven — 2026-11-28, `2706.1.17`, #164: added a 6-sided R2 cm polygon at (-8,3), as six `SketchLine`s |
| `draw_arc` | proven — 2026-11-28, `2706.1.17`, #164: drew a 90 deg arc of radius 2 centred (15,3), reporting `model_center` |
| `create_hole` | proven — 2026-11-28, `2706.1.17`, #164: cut a 1 cm hole 3 cm deep into a box's top face: `actual_diameter: 1.0` |
| `rectangular_pattern` | proven — 2026-11-28, `2706.1.17`, #164: copied a body 2x1 at 8 cm X spacing: `body_count` 2 -> 3, `R-Pattern1` |
| `circular_pattern` | proven — 2026-11-28, `2706.1.17`, #164: three copies about z: `body_count` 3 -> 5, `C-Pattern1` |
| `save_document` | proven — 2026-11-27, `2706.1.17`, #162: refused an untitled document with no name (nothing written), saved it by name into the active data folder (`saved_as: true`, `is_modified: false`), then — after `create_box` modified it, `isSaved: True`/`isModified: True` — saved in place (`saved_as: false`, `is_modified: false`, read back as `True False`); `checkpoint=True` reported `saved_before: true` on `execute_code` and `cam_create_operation`; saving an *unmodified* document twice answered `saved: true` both times with no version added |
| `new_document` | proven — 2026-11-26, `2706.1.17`, #158: created an active parametric design document |
| `create_component` | proven — 2026-11-26, `2706.1.17`, #158: created `C1`; a body added to it is counted in the snapshot |
| `add_joint` | proven — 2026-11-28, `2706.1.17`, #164: a revolute joint from two Ø10 mm cylindrical faces: `Revolute 1`, `RevoluteJointMotion` |
| `set_joint_value` | proven — 2026-11-28, `2706.1.17`, #164: drove `Revolute 1` to 45 deg: `read_back` 0.785398 rad, `applied: true` |
| `list_edges` | proven — 2026-11-26, `2706.1.17`, #158: answered a box's twelve edges with index and midpoint |
| `list_faces` | proven — 2026-11-26, `2706.1.17`, #158: answered a box's six faces with index, surface_type and normal (#147) |
| `list_components` | proven — 2026-11-26, `2706.1.17`, #158: answered `Component1` with `count` |
| `export_step` | proven — 2026-11-28, `2706.1.17`, #165: wrote `one.step` (8,941 bytes) for a single-body component and said so — `scope: component`, `bodies_in_component: 1`; with a second body it wrote both (14,479 bytes) and carried the note. Fusion's `createSTEPExportOptions` takes a Component, so the unit is the component that owns the body, never the body |
| `export_f3d` | proven — 2026-11-28, `2706.1.17`, #164: wrote the design to `design.f3d`: `exported: true` |
| `export_view_sheet` | proven — 2026-11-28, `2706.1.17`, #164: wrote an HTML sheet and the `iso`+`front` PNGs to the Desktop default: `html_path` returned |
| `export` | proven — 2026-11-28, `2706.1.17`, #165: `format: stl` exported a body (`exported: true`, body and path echoed) and `format: step` wrote the component that owns it (`scope: component`, `bodies_in_component: 2`, 14,486 bytes), as `export_step` alone does |
| `import_mesh` | proven — 2026-11-28, `2706.1.17`, #164: imported `block.stl` twice as mesh bodies `block` and `block (1)`, each with a bounding box |
| `get_parameters` | proven — 2026-11-26, `2706.1.17`, #158: answered `count: 0` and an empty parameter list |
| `create_parameter` | proven — 2026-11-28, `2706.1.17`, #164: created `plate_width` at 42 mm: `unit` `mm`, `expression` `42 mm` |
| `set_parameter` | proven — 2026-11-28, `2706.1.17`, #164: drove `plate_width` 42 -> 55: `expression` `55 mm`, and the body mass followed |
| `delete_parameter` | proven — 2026-11-28, `2706.1.17`, #164: deleted `plate_width`; `get_parameters` went 1 -> 0 |
| `draw_circles` | proven — 2026-11-28, `2706.1.17`, #164: three R0.5 circles at 2 cm spacing in one deferred solve: `added: 3`, `total_curves: 17` |
| `add_constraint` | proven — 2026-11-28, `2706.1.17`, #164: applied `horizontal` to a sloped `SketchLine` by index |
| `auto_constrain` | unproven — only a refusal is exercised: `NOT_ENTITLED`, `3 : AutoConstrain is not available since user is restricted` (2026-11-28, `2706.1.17`) — the account, not the call |
| `add_dimension` | proven — 2026-11-28, `2706.1.17`, #164: applied a `distance` of 10 between two rectangle edges and a `radial` of 2 to a circle, both by index |
| `create_construction_plane` | proven — 2026-11-27, `2706.1.17`, #160: built a plane (`Plane1`, then `Plane2` for `edge_name="Y"`); refused `edge_name="w"` with the axis sentence, and a missing angle with `3 : invalid expression` before this PR's rule (#160) |
| `create_construction_axis` | proven — 2026-11-27, `2706.1.17`, #163: `perpendicular_at_point` on face 0 of a box answered `created: true`, `name: "Axis1"`; `list_faces` reported that face as `surface_type: "Plane"` before the call, and the axis was read back through `execute_code` from `rootComponent.constructionAxes` — `get_scene_info` reports bodies, sketches and counts, and no construction geometry |
| `create_ucs` | proven — 2026-11-28, `2706.1.17`, #164: built `UCS1` at (3,2,1) with 30 deg about z, reporting the hidden `UCS_UCS1_ref` sketch it anchors on |
| `draw_spline` | proven — 2026-11-28, `2706.1.17`, #164: a four-point `fit_points` spline through (20,0)..(26,2), with `model_points` reported |
| `offset_curve` | proven — 2026-11-28, `2706.1.17`, #164: offset a spline by 1 cm |
| `trim_curve` | proven — 2026-11-28, `2706.1.17`, #164: trimmed a 20 cm line at its crossing, keeping (0,0)-(10,0) |
| `extend_curve` | proven — 2026-11-28, `2706.1.17`, #164: extended a line past its end |
| `create_thread` | proven — 2026-11-28, `2706.1.17`, #164: cut an M10x1.5 6g thread on a Ø10 mm cylinder's lateral face: `face_diameter_cm` 1.0, `thread_diameter_cm` 0.9997, `is_modeled` true |
| `draft_faces` | proven — 2026-11-28, `2706.1.17`, #164: drafted a body's vertical faces by 2 deg, `face_count` reported |
| `split_body` | proven — 2026-11-28, `2706.1.17`, #164: split a body across xz: `body_count` 7 -> 8, `Split1` |
| `split_face` | proven — 2026-11-28, `2706.1.17`, #164: split face 0 with the yz plane: `SplitFace1` |
| `offset_faces` | proven — 2026-11-26, `2706.1.17`, #158: ran with distance 0 and its `deltas` counted the surface body it created |
| `scale_body` | proven — 2026-11-28, `2706.1.17`, #164: `Scale1` about (1,2,3) at 1.5x: mass 502.4 -> 1695.6 g with `reference_sketch` named; the anchor is a sketch point, because a raw point answers `3 : invalid ref point` |
| `create_box` | proven — 2026-11-26, `2706.1.17`, #158: reported `deltas` body_count 0 -> 1 and 502.4 g |
| `create_box_parametric` | proven — 2026-11-26, `2706.1.17`, #158: reported `deltas` body_count 0 -> 1 and 62.8 g (#157) |
| `create_cylinder` | proven — 2026-11-28, `2706.1.17`, #164: `body_count` 1 -> 2 for R0.5 x 3 cm at (10,0,0) |
| `create_sphere` | proven — 2026-11-28, `2706.1.17`, #164: `body_count` 1 -> 2 for R3 at (30,0,0) |
| `create_torus` | proven — 2026-11-28, `2706.1.17`, #164: `body_count` 2 -> 3 for major 4 / minor 1 at (50,0,0) |
| `create_as_built_joint` | proven — 2026-11-28, `2706.1.17`, #164: a rigid as-built joint between two components: `Rigid 1`, `kept_current_positions` |
| `create_rigid_group` | proven — 2026-11-28, `2706.1.17`, #164: grouped two components: `created: true`, `component_count: 2` |
| `measure_distance` | proven — 2026-11-26, `2706.1.17`, #158: measured 1.0 cm between two points given as `x,y,z` strings |
| `measure_angle` | proven — 2026-11-28, `2706.1.17`, #164: answered 90.0 deg between face 0 of two boxes; a box against a sphere is refused `3 : measurement failed`, so both faces have to be planar |
| `get_physical_properties` | proven — 2026-11-26, `2706.1.17`, #158: answered mass, volume, area, density and center of mass |
| `create_section_analysis` | proven — 2026-11-28, `2706.1.17`, #164: `Section1` on xz at offset 2 through `design.analyses.sectionAnalyses`; a Component has no `analyses` live |
| `check_interference` | proven — 2026-11-28, `2706.1.17`, #164: reported one interference of 32.0 cm3 between two components whose 4 cm boxes overlap by 2 cm |
| `compare_meshes` | proven — 2026-11-28, `2706.1.17`, #164: compared `block` with `block (1)`, the same STL imported twice: 20 nodes, every deviation 0.0 |
| `set_appearance` | proven — 2026-11-28, `2706.1.17`, #164: applied `Steel - Satin` to a body: `applied: true` |
| `set_color` | proven — 2026-11-26, `2706.1.17`, #158: answered `ok` with identical deltas and no no-op warning (#157) |
| `project_geometry` | proven — 2026-11-28, `2706.1.17`, #164: projected a body's 30 edges into a new sketch: `projected_curves: 30`, linked |
| `suppress_feature` | proven — 2026-11-28, `2706.1.17`, #164: suppressed `Hole1`: `body_count` 7 -> 6 |
| `unsuppress_feature` | proven — 2026-11-28, `2706.1.17`, #164: restored `Hole1`: `body_count` 6 -> 7 |
| `patch_surface` | proven — 2026-11-26, `2706.1.17`, #158: created a surface body, body_count +1 (#157) |
| `stitch_surfaces` | proven — 2026-11-28, `2706.1.17`, #164: stitched a patch with the surface ruled off its edge: `body_count` 2 -> 1 |
| `thicken_surface` | proven — 2026-11-28, `2706.1.17`, #164: thickened the stitched surface by 0.2 cm: `body_count` 1 -> 2 |
| `ruled_surface` | proven — 2026-11-28, `2706.1.17`, #164: ruled 1 cm off a patch's edge: `body_count` 1 -> 2 |
| `trim_surface` | proven — 2026-11-26, `2706.1.17`, #158: trimmed a surface with a plane and shrank the bbox (#157) |
| `create_flange` | proven — 2026-11-28, `2706.1.17`, #164: a 2 cm, 90 deg edge flange on a sheet-metal body: `EdgeFlange2` |
| `create_bend` | proven — 2026-11-28, `2706.1.17`, #164: a 90 deg fold along a sketch line on the bottom face: `Fold1`, mass +0.46 g; faces 0 and 12 were refused `FOLD_GENERIC_FEATURE_FAILURE`, so the stationary face has to be the one the line lies on |
| `flat_pattern` | proven — 2026-11-28, `2706.1.17`, #164: `FlatPattern1` from the largest planar face; the first planar face of a 10x10x0.25 cm flange is a 0.37 cm2 side wall, which Fusion refuses with `a side face may have been selected` |
| `unfold` | proven — 2026-11-28, `2706.1.17`, #164: `Unfold1` over every bend: mass 196.71 -> 196.25 g, the flange unfolded |
| `cam_create_setup` | proven — 2026-11-27, `2706.1.17`, #159: created `Setup1` over a body with relative-box stock offsets |
| `cam_create_operation` | proven — 2026-11-27, `2706.1.17`, #159: aimed a `face` operation through its `stockContours` boundary (`useStockContours` measured `true`), then generated it |
| `cam_generate_toolpath` | proven — 2026-11-27, `2706.1.17`, #159: answered `generated: true` for a `face` operation with no face selection |
| `cam_post_process` | proven — 2026-11-28, `2706.1.17`, #165: posted the `face` operation `Face1` through Fusion's own `fanuc.cps`, producing `1001.nc` whose first line is `O1001`, and again at `program_number` 2048 (`2048.nc`, `O2048`). The setup's name used to be passed as the program name, which a post that sets `programNameIsInteger` reads as `NaN` |
| `cam_list_setups` | proven — 2026-11-26, `2706.1.17`, #158: answered `count: 0` on a design with no CAM setups |
| `cam_list_operations` | proven — 2026-11-28, `2706.1.17`, #164: answered the one `Face1` operation with `has_toolpath: true` and `is_valid: true` |
| `cam_get_operation_info` | proven — 2026-11-27, `2706.1.17`, #159: answered `is_valid: true` and `has_toolpath: true` after generating the aimed operation |
| `health` | proven — 2026-11-28, `2706.1.17`, #164: answered `app_version` `2706.1.17`, `active_document` and `queue_depth: 0` from the main thread after the add-in was restarted, and failed at the 3 s `--timeout` while the thread was blocked (#161); the hand-off and the depth it reads are pinned by `tests/test_addon_bridge.py`, `tests/test_addon_importable.py` and `tests/test_addon_scene_reads.py` |
| `ping` | proven — 2026-11-26, `2706.1.17`, #158: answered `{status: pong}` — from the socket fast path, never from the handler |
| `get_design_type` | proven — 2026-11-26, `2706.1.17`, #158: answered `parametric` with `design_type_id` |
| `set_design_type` | proven — 2026-11-28, `2706.1.17`, #164: switched parametric -> direct -> parametric: `changed: true` both ways |
| `render_view` | proven — 2026-11-26, `2706.1.17`, #158: returned a PNG: `bytes`, `width`, `height`, `image_format` |
