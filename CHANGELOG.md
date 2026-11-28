# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions before 0.3.0 use the shared date 2026-11-01, the day this project was tagged
and published; they are the fork history.

## [0.10.0] - 2026-11-25

This release is about what the tools can *do*. Eight changes since 0.9.0, and every one
that could be was measured against a running Fusion 2706.1.17 rather than inferred from
the binding - which mattered, because three of them contradicted what the documentation
said and one took a live probe to discover at all. The exception is
`create_construction_axis`'s `face_index`, whose two arguments come from the shipped stub:
the tool builds through the documented call, but no live envelope proves it yet.

*Correction, 2026-11-27 (#163).* It does now: on Fusion 2706.1.17,
`create_construction_axis(method="perpendicular_at_point", body_name="Body2",
face_index=0, point_one=[0, 0, 2])` answered `created: true` with `name: "Axis1"`, and
`rootComponent.constructionAxes` held that axis. Nothing in the shipped behaviour changed;
the sentence above is left as the tag shipped it, and this paragraph is the correction.

### Added

- **`list_faces`** - a body's faces with their index, `surface_type`, planarity, area
  and centroid, plus the outward normal on a planar face, and `count`/`truncated` like
  `list_edges`. The indices `face_indices` takes could previously only be learned
  through `execute_code`. Measured: `geometry.normal` is **not** the outward normal - on
  a box the bottom and all four sides carry `isParamReversed`, so the tool negates where
  it is set, and six faces report six distinct directions. 98 tools now.
- **A tool on a CAM operation**, so its toolpath can generate. `cam_create_operation`
  takes `tool_diameter` (cm), `tool_length`, `tool_flutes` and `tool_number` and builds
  a complete flat end mill, or `tool_json` for a tool object used verbatim. A *partial*
  tool object is not refused: measured, it **crashed Fusion**, taking the document's
  unsaved state with it - which is why the builder emits the whole shape.
- **`tool_number` on its own selects a tool the document library already holds.** The
  reply says `from_library`, and a number nothing holds is `NAME_NOT_FOUND` naming the
  numbers that would work. `DocumentToolLibrary` has no by-number lookup, so the
  measured route is `count` plus `item(i)` and each tool's own `tool_number` parameter.
- **`create_construction_plane(method="tangent")` builds a plane.** It was advertised in
  the schema and refused by a rule - the last enum value a caller could send and never
  satisfy. It takes `body_name` and `face_index`, and two forms: `angle` + `plane` for a
  cylindrical face (`setByTangent`), or `point_one` for any face
  (`setByTangentAtPoint`).

### Changed

**Breaking:** the first two change what a caller sends or branches on.

- **`cam_create_setup`'s `stock_mode` is one measured table.** Fusion accepts `default`,
  `fixedbox`, `relativecylinder`, `fixedcylinder` and `solid`; the advertised
  `from_body` never worked and is refused as `3 : Invalid enumeration value.` The
  schema, the handler and mock mode all read one table, so `from_solid` is its name.
- **Five `hints.py` rules retagged**, to the taxonomy the rest of the add-in speaks: the
  CAM `setup/operation not found` rule is now `NAME_NOT_FOUND`, and `no faces matched`,
  `no edges matched selection`, `has no edges to select from` /
  `has no edges that can be rounded`, and the `no usable parameter range` rule are
  `GEOMETRY_UNSUPPORTED`. A client that branches on the old `INVALID_INPUT` for those
  will see the difference; `docs/ROADMAP.md` records the judgement calls that were
  deliberately *not* retagged.
- **`create_construction_axis("perpendicular_at_point")` takes `face_index`** (with
  `body_name`) and builds through `setByPerpendicularAtPoint(face, point)`. Its blanket
  refusal became one that names the arguments that are missing.
- **Hints stopped sending callers to `execute_code` for a face.** `list_faces` exists, so
  the hints and schema descriptions that named `execute_code` as the way to learn a face
  index name the tool instead.
- **The schema gained three arguments**: `body_name` + `face_index` on
  `create_construction_plane` (10 → 12) and `face_index` on `create_construction_axis`.

### Fixed

- **A CAM operation can generate a toolpath**, and a generation Fusion refuses now
  reports Fusion's own sentence instead of `TIMEOUT` after 25 s: a refused future never
  completes, so the bound belonged to the wrong cause.
- **A CAM operation created without a tool says so up front**, with `tool: null` and a
  warning, instead of leaving it to the next call's generation to fail.
- **Mock mode answers the CAM handlers' keys** across seven commands. It used to answer
  `toolpath_count` where the handler answers `generated` and `scope`, `output_file` where
  the live key is `output_folder`, and a `strategy` per operation the handler never sends
  - so an agent that rehearsed against mock got a `KeyError` against Fusion, after the
  expensive half of a sequence had already run.
- **Two construction-plane refusals name what Fusion does not**: a reference plane whose
  normal is parallel to the face's axis is refused here, because Fusion answers
  `2 : InternalValidationError : data_->execute(&obj, apiName)` and names neither the
  argument nor the fix; and a cone is refused on the angle form, because - measured - the
  binding documents "cylindrical or conical" and **every** reference plane is refused for
  a cone, while the at-a-point form works on it.

### Under the hood

- `handler_export` went from 44% to 93% coverage, and the combined figure from 94.10% to
  96.75%: the view sheet, the viewport capture, both `import_mesh` import paths and
  `export`'s `stl` dispatch are covered offline now. The fake runtime gained
  `adsk.core.CameraTypes`, and the viewport fake hands the camera out as a **copy** -
  Fusion's documented contract - so a dropped assignment fails instead of passing.
- `scripts/check_fusion_api.py` covers 197 `adsk` references, none missing.

## [0.9.0] - 2026-11-23

This release is mostly about what a caller is told when something goes wrong. Every
add-in refusal now reaches a caller with an `error_kind` and advice, the tool schemas are
enforced before Fusion is touched, and two CAM commands stopped inventing what Fusion
accepts. Three repaired sheet-metal/surface commands changed arguments, which is where a
script written against 0.8.5's schema will see the difference.

### Added

- **Six `error_kind` values**, chosen by the caller's next move rather than by which API
  failed: `NAME_NOT_FOUND`, `GEOMETRY_UNSUPPORTED`, `FUSION_REFUSED`,
  `WORKSPACE_UNAVAILABLE`, `SCRIPT_ERROR`, `INTERNAL_ERROR`. `INVALID_INPUT` keeps its
  meaning (an unusable parameter) and `BODY_NOT_FOUND`/`SKETCH_NOT_FOUND` stay because a
  client may already branch on them. 88 of 134 literal-message raises answered `UNKNOWN`
  with no hints before this; none do now, pinned by a test that fails on a new untyped
  one.
- **The tool schema is enforced in one place.** `_send` refuses an undeclared argument,
  a value outside a declared enum or bound, or a missing `required` field, so real and
  mock mode answer alike before Fusion sees the call. The 63 enum properties, 78 bounds
  and every `additionalProperties: false` were declared and unread before.
- **`scripts/check_fusion_api.py`** asks the running Fusion whether every
  `adsk.<dotted.path>` under `addon/server` exists - 190 references today. It is the
  check that would have caught the three invented names this repo shipped.
- **`cam_create_operation` takes `body_name` and `face_indices`** and applies a
  `FaceContourSelection` to the strategy's own geometry parameter (`contours`, `pockets`,
  `machiningBoundarySel`), discovered at run time, so the handler needs no map
  entry to find it. `CAM_GEOMETRY_PARAMETERS` in `rules.py` is still what mock
  mode answers from and what the refusal names the five strategies from.

### Changed

- **Breaking for the invented names: `cam_create_operation`'s strategy enum is Fusion's
  own.** Ten of the fifteen it carried were fiction (`2d_contour`, `2d_pocket`,
  `2d_adaptive`, `3d_adaptive`, `3d_pocket`, `3d_contour`, `3d_scallop`, `3d_parallel`,
  `drilling`, `thread_milling`) and Fusion refused them with `3 : Unknown strategy`;
  `face`, `bore`, `slot`, `trace` and `engrave` are kept, and five 2D/3D names are added.
- **Breaking: three repaired commands renamed arguments.** `create_flange`'s `height` is
  now `distance` and `bend_radius` is `bend_radius_override`; `create_bend` takes a
  required `stationary_face_index`; `trim_surface` requires `keep_cells` and accepts
  `tool_plane`. None of them worked before, so no working script breaks.
- **`InternalValidationError` answers `FUSION_REFUSED`**, not `INVALID_INPUT` - Fusion
  rejected the state, not the argument, and the rule's own hint always said so.
- **An unknown `joint_type`, `quadrant` or `key_point`** answers `INVALID_INPUT` naming
  the accepted set instead of `UNKNOWN`; so does an unknown CAM strategy, and a geometry
  selection on a strategy that has no parameter for one.
- **`cam_generate_toolpath(operation_name=…)` works without `setup_name`**, as its
  schema and message have always advertised, and a name a setup holds twice is refused by
  all three commands that resolve one.
- Hints stop naming `get_object_info` as a way to enumerate faces - it answers counts and
  no tool lists faces. The advice is `execute_code` with `body.faces.item(i)`.

### Fixed

- CAM generation: `GenerateToolpathFuture.wait()` does not exist on 2706, and the
  completion flag raises until generation begins - both made every generation call fail
  with `UNKNOWN` instead of a typed refusal.
- Nine repairs, each covered by a test written against Fusion's shipped API, and the
  `create_flange`/`create_bend`/`trim_surface` trio additionally proven live:
  `unfold`, `flat_pattern`, `thicken_surface`, `scale_body`, that trio,
  `patch_surface`'s continuity
  (now `groupContinuity`; still inert for sketch boundaries until the tool takes
  edges), and `create_construction_axis(perpendicular_at_point)`, which now refuses
  and names the face argument the tool does not have instead of failing inside
  Fusion.

### Removed

- Three unreachable helpers in `handler_surface.py` and the fake seams that existed only
  for them.

The suite went from 1245 to 1624 tests, combined coverage from 69.97% to 92.33%, and
`handler_cam` from 17% to 75%.

## [0.8.5] - 2026-11-15

Three merged PRs that remove duplication rather than add features, plus the
release-review work they forced. Two things a caller can observe: `render_view` accepts
three camera presets it was already handling, and mock mode's malformed-edge-point
refusal now uses the add-in's wording. Everything else is internal or tooling.

### Added

- **`uv run mypy src` is a required check** in the `test` CI job - `src/` only, because
  `addon/` reaches Fusion's `adsk`, which no checker can resolve. `[tool.mypy]` had been
  configured since 0.7 with nothing invoking it: a checker nothing runs reports nothing.
  Zero errors when it was wired up, and no `# type: ignore` was needed.
  `check_untyped_defs` stays off, so the result is a floor, not a claim about
  unannotated bodies.

- **`render_view`'s `view` enum gains `iso_ne`, `iso_nw` and `iso_sw`** - `_VIEW_DIRS`
  had handled all three since the presets were written, so the schema was refusing calls
  the add-in answered.

### Changed

- **`addon/server/command_handler.py` is a 32-line shell.** The 5,639-line class (97
  commands and 61 helpers) is now nine modules: a `HandlerBase` holding dispatch, the
  command tables and the helpers two domains call, plus one mixin per domain
  (`handler_sketch`, `handler_features`, `handler_primitives`, `handler_scene`,
  `handler_assembly`, `handler_surface`, `handler_export`, `handler_cam`). Bodies moved
  verbatim. The add-in's reload proof was reworked **before** any move, because it
  compared `vars(cls)` - deliberately, so an inherited method would not read as drift -
  which is exactly what a mixin split changes: it now walks `cls.__mro__` and reads a
  module list, and the string Fusion executes is itself executed in the suite.

- **`render_view`'s `view` enum reorders `left`/`right`** to `_VIEW_DIRS` key order. No
  handler behaviour depends on the order; a client reading the enum positionally would
  notice.

- **mock mode's malformed-edge-point refusal uses the add-in's wording** - "Each edge
  point needs three coordinates, got N" rather than "edge point needs three
  coordinates". The two copies had drifted and one shared function can only say one;
  `error_kind` and `hints` are unchanged.

- **`scripts/reload_addin.py` asks which add-in it is talking to before it reloads**,
  and refuses when the loaded path is not this checkout's. It used to send the reload
  first and report the path afterwards, on stdout, with a success exit - so a bare run
  from the wrong checkout re-executed another tree's modules and mentioned it later.

- **`scripts/sync_mirrors.py` and `scripts/reload_addin.py` survive `python -OO`.** Two
  separate bugs: a `__doc__` subscript, and `ast.parse` dropping docstrings so the
  mirror guard read a canonical's docstring as code above its cut and refused it. The
  guard now parses with `optimize=0` - it asks about the file, not the interpreter.

### Fixed

- **a non-list `edge_indices`/`edge_points` is refused, not crashed on.** A bare number
  raised `TypeError` out of the add-in's validator, so it reached the agent as `UNKNOWN`
  with no hints, and mock mode raised through `mock_command` with no envelope at all.
  Both answer `INVALID_INPUT` naming the field, and `hints.py` has a rule for it in both
  mirrors.

- **pyright can resolve `src/`** (`extraPaths`), so the editor stops reporting roughly
  200 false "unresolved import" errors over five real ones. The five are fixed, not
  silenced.

### Removed

- **`CommandHandler._COMMANDS`**, the lazily-built class attribute. It cached the
  *first* instance's bound methods for every later instance, which is why `event_bridge`
  had to reset it on reload. Dispatch is now built per instance from `_COMMAND_NAMES`.

- **`scripts/reload_addin.py --file`**, undocumented and unused.

## [0.8.4] - 2026-11-15

Three merged PRs, and the review of them. The behaviour change is in `create_thread`:
it refuses a thread whose designation does not match the face instead of letting Fusion
quietly resize the body to it. Everything here was checked against Fusion 2706.

### Added

- **`scripts/reload_addin.py`** - the add-in keeps `command_handler` in memory, so a
  `git pull` changes what is on disk and nothing about what Fusion executes, and
  `inspect.getsource` reads the *file*, so a stale class describes itself with the new
  code. The script sends `reload_handler` and compares the running class's method names
  with the methods the file declares, exiting 1 on drift in either direction. `--check`
  verifies without reloading. It says what it does not prove: bodies are not compared,
  and `event_bridge.py`/`socket_server.py` are not reloaded by it.

### Changed

- **`create_thread` refuses a designation that would resize the body.** An `M6x1`
  cosmetic thread on a Ø20 mm shaft left a **Ø5.88 mm** one - Fusion sizes the body to
  the thread - so a mistyped designation silently destroyed the geometry. It now
  compares the face's diameter with the thread's (major externally, minor in a tapped
  hole, read from the `ThreadInfo` Fusion builds) and refuses beyond `max(2%, 0.12 mm)`,
  naming the thread Fusion recommends for that diameter and diagnosing a wrong
  `is_internal` when the other polarity fits. `allow_resize=true` opts in. Either way
  the result reports `face_diameter_cm` and `thread_diameter_cm`.

### Fixed

- **the size check's first tolerance refused the canonical small-thread call.** A
  relative-only 2 % band tightened as the thread shrank and refused Ø3.00 mm stock
  against M3x0.5, while accepting a larger resize on an M6 - and then recommended the
  designation it had just refused. It has an absolute floor now, and the message never
  names the refused designation as the fix.
- **the "not cylindrical" refusal reached the caller as `UNKNOWN` with no hints** - a
  regression, since Fusion used to refuse it with a classified error. Both mirrors have
  the rule, and picking a non-cylindrical `face_index` is the likeliest mistake with
  this tool.
- **`scripts/smoke_envelope.py` could not run on a Windows console**: it printed `→`
  from the delta formatter to cp1252 and died with `UnicodeEncodeError`.
- **the reload script's first version read a reply shape that does not exist**
  (`reload_handler` answers flat; only `execute_code` nests under `result`), and its
  success line read as "everything is current" when it compares names only.
- **the add-in's fake thread table was derived, not measured**, and thread diameters
  differ by class: `M3x0.5` is 2.927 mm major externally and 3.086 mm internally. It is
  keyed by `(designation, is_internal)` with values measured on 2706, and
  `ThreadInfo.create` refuses a null class the way Fusion does.

## [0.8.3] - 2026-11-15

Three tools that had never worked now do, and the rest of the release is the dedupe
that was hiding them. Everything below was checked against Fusion 2706 in a scratch
document, emptied again afterwards; no tool was renamed and no response field was
removed, so a caller reading the old keys is unaffected.

### Fixed

- **`create_thread` never created a thread.** It handed a `ThreadDataQuery` to
  `ThreadFeatures.createInput`, which takes a `ThreadInfo` - measured on 2706 as
  "argument 3 of type `ThreadInfo`" - so every call returned an error envelope and
  mock mode was the only mode it worked in. It builds the `ThreadInfo` now, so
  `is_internal`, `thread_type`, `thread_designation` and `thread_class` reach the
  feature: verified live as `6g` for an external thread and `6H` for an internal one,
  which is what ISO 965 assigns. Fusion sizes the body to the designation - an `M6x1`
  cosmetic thread on a Ø20 mm shaft leaves a Ø5.88 mm one - and the tool says so.
- **`ruled_surface` could not call the API it documented.** It passed a raw edge and
  two arguments to `createInput`, whose shipped signature is
  `createInput(profile, distance, angle, type)` with a **Profile** first; every call
  raised. It builds the profile with `createBRepEdgeProfile` now and maps `rule_type`
  to `RuledSurfaceTypes`. Verified live on a sheet body's boundary edge: the surface
  appeared and the bounding box grew by exactly the distance asked for.
- **`project_geometry` called the retired `Sketch.project`,** which cannot express
  linkage, so its `is_linked` argument did nothing. It calls `project2` now; verified
  live, the projected curves carry `isLinked = False` and `True` on the sketch
  entities themselves.
- **Every mutation in the Manufacture workspace silently lost its `deltas`.**
  `_snapshot` read `app.activeProduct`, which is the CAM product there and has no
  `rootComponent`, so the snapshot returned nothing and no delta was attached - the
  signal this project tells agents to rely on. It goes through `_design()`, and so
  does `_orient_camera`, which had the same read one method away and made
  `render_view(view=...)` raise there.
- **`create_section_analysis` reported no name**, discarding the analysis `add()`
  returned, so the section it had just made could not be referenced. It reports
  `analysis_name`.
- **`AGENTS.md` said "Available tools (97)" and listed 96** - `list_edges` was absent,
  and nothing read the page. A guard now pins both directions against the registry.
- **`FUSION_MCP_PORT` had two parsers with two failure modes.** The server warns and
  falls back to 9876, the CLI default raised at start-up, and the add-in raised too.
  All three tolerate a typo now, and the add-in logs the fallback.
- **A ruled surface on a solid's edge returned `UNKNOWN` with no hints.** Fusion
  answers "invalid free edge" (every edge of a solid is shared by two faces) and no
  rule matched it; a rule in both mirrors says what a free edge is and how to
  get one.
- **Exporting to a bare filename raised.** `os.makedirs(os.path.dirname(path))` fails
  on an empty dirname, in the STL/STEP path and in the f3d one.

### Changed

- **`tools.py` 3,101 -> 2,479 lines.** fillet/chamfer, the two joint tools and the four
  profile-based features had hand-copied schema blocks; they share them now, and every
  entry is a `_tool(...)` call instead of a five-level dict literal. The wire format is
  unchanged: all 97 `(name, title, description, inputSchema, annotations)` tuples were
  compared with `json.dumps(sort_keys=True)` before and after.
- **`server.py`'s resource reads have one failure boundary** instead of five copies of
  it, and the resource templates are advertised from the table that renders them. The
  prompt texts are unchanged and still asserted through a real client session.
- **The add-in has one extreme-plane rule, one `_sketch()` resolver, one `_sweep`,**
  and one `_export_body` for STL and STEP - which is now tested (export had no test
  that could reach it before) rather than merged on trust.
- **`AGENTS.md`'s tool catalogue is an index** (448 -> 296 lines) pointing at
  `docs/TOOLS.md`, which is now the single place a tool's description lives.
- **Tests and prose:** 1,072 -> 1,119 tests, combined coverage 64% -> 68% (`src/`
  99%), and comments that narrated past incidents now state the constraint. Ten
  comments cited section numbers of files that are git-excluded or gitignored.

## [0.8.2] - 2026-11-15

A patch release whose payload is documentation and the guards that keep it honest. No
tool, parameter, response field or `error_kind` changed, and no line of the add-in's
code changed: the only code that moved is in `tests/`.

### Fixed

- **`SECURITY.md` answered "is my version supported?" with a series nobody was on.** It
  said `0.3.x` from 0.4.0 through 0.8.1 - five minors of telling every reader of the
  current release that their own version was unsupported, in the file `llms.txt` routes
  that question to. It says `0.8.x` now, and a test reads both rows against the series
  `pyproject.toml` states, so the Yes row must be that series and the No row everything
  below it. (#101)
- **`SECURITY.md`'s three design notes rendered as one bullet.** The `-` markers sat
  inside the paragraph - the shape the file had since it arrived in #5 - and
  markdownlint parses that as a single well-formed item, so no gate saw it. Three
  bullets again. (#102)

### Changed

- **Every command-shaped `uv sync` passes `--locked`** - four in CI (`ci.yml` three
  times, `fuzz.yml`'s group-only one) and five in the documents that tell someone to run
  it (`AGENTS.md`, `CONTRIBUTING.md`, `README.md`, `docs/TESTING.md` twice), plus the
  comment beside `pyproject.toml`'s dependency groups. `--frozen` installs whatever the
  lock says and never compares it with `pyproject.toml`, so a release PR that moved the
  version and forgot `uv lock` would have installed cleanly and stayed green. (#101)
- **`tests/test_packaging.py`'s docstring names the claims it guards again** - the four
  build-shape tests #94 added (the add-in's mapping into the wheel, `src/`'s package
  list, the add-on subpackages, `include-package-data`) and the quick-start half of the
  pin claim. (#102)

### Testing

- **Three records that could drift from the release are now read**: `SECURITY.md`'s
  supported-versions rows, the sync flag on every documented command, and the
  changelog's first heading, its date shape and its compare link. The sync flag is the
  sweep - every tracked markdown page but the changelog, plus every workflow, with
  `SYNC_DOCUMENTS` naming the four pages that must keep showing the command, so a reflow
  cannot empty it. The other two read their one file each, and fail rather than pass
  when the row, heading or link they look for is gone. (#101)

## [0.8.1] - 2026-11-14

A patch release for refusal and output behaviour. No tool, parameter, response field or
`error_kind` changed, and the add-in's own code is untouched: what moved is what
`--install-addon` refuses, how the installer and the artifact check print, and the exit
code the check answers when it cannot check.

### Fixed

- **`--install-addon` no longer installs an add-in Fusion cannot load.** It named the
  install from a `*.manifest` the shell installer would never have chosen: a dot-prefixed
  name (`AddIns/.Hidden`, a hidden folder whose `.Hidden.py` entry module does not exist)
  and, on Windows, a name whose suffix is only case-variant, which the case-sensitive copy
  rule then refused to copy. Both are refused now, as the development path already does.
  (#97)
- **A blank `version` is refused.** The check was truthiness, so `" "` passed and printed
  an empty `Version:` line from an install that went ahead anyway — the outcome that
  refusal exists to prevent. It is now "no non-whitespace character". (#99)
- **One printed value cannot become two lines.** Refusals, the success banner and the
  artifact check's findings all embed names, paths or the manifest's `version`; and a
  newline is legal in a POSIX filename, while a manifest's `version` is JSON text that
  may carry one. A single crafted manifest installed successfully and split the banner,
  and a tracked path carrying a newline split one finding into two. Each value is
  collapsed to one line, while the two-manifest refusal keeps its deliberate
  one-candidate-per-line listing. (#99)
- **`scripts/check_artifacts_ship_addon.py` answers a tracked-but-deleted add-on file
  with exit 2, not 1.** `git ls-files` names the index rather than the working tree, so
  deleting a tracked file without `git rm` produced a traceback and the exit code a real
  finding uses. It is cannot-check now, one line on stderr, as absent git and an
  unreadable artifact already were. (#97)

### Testing

- **`tests/test_addon_socket.py` and `fuzz/fuzz_socket_framing.py` tolerate a peer that
  closed first**, with `tests/test_fuzz_targets.py` and the socket test pinning each
  site. On darwin, `shutdown(SHUT_WR)` after the handler replied and closed raised
  `ENOTCONN`, which surfaced through both, so the `macos` job could fail on timing
  alone. Tests only, no shipped behaviour changed. (#98)

## [0.8.0] - 2026-11-14

A minor release, because two user-visible surfaces are added: both artifacts now carry
the Fusion add-in, and `fusion360-mcp-server` gains two options. No tool, parameter,
response field or `error_kind` changed, and no line of the add-in's code changed; only
the version in its manifest moved.

### Added

- **The release ships the add-in.** Before this, the wheel held only
  `src/fusion360_mcp/*` and its dist-info, and the sdist held `tests/` but not `addon/`,
  so a tag install could not reach Fusion without a clone: `uvx --from ...@vX.Y.Z`
  installed a server and left the user to run `scripts/install-addon.sh` from a
  checkout. Both artifacts now carry the ten tracked files under `addon/` - the wheel as
  `fusion360_mcp/addon/`, the sdist as `addon/` under its distribution directory - and
  the repository still keeps one copy. (#94)
- **`fusion360-mcp-server --install-addon [--addin-dir PATH]`** copies them into
  Fusion's AddIns folder and exits before any MCP work. `API/AddIns` is created when
  Fusion's own data folder exists. It refuses each of these, with a message on stderr
  and exit status 1: a source checkout; an `addon/` with no manifest, two manifests, or
  a manifest that is not a regular file; a manifest that is not JSON, or whose `version`
  is missing, empty or not a string; a missing Fusion data folder, or one that cannot be
  written to; a platform that is neither Windows nor macOS; a target that is a symlink
  **or a Windows junction**; a target that is a regular file; and a copy that did not
  land complete. A symlinked development install must be removed first, because
  re-running `scripts/install-addon.sh` recreates the link. (#94)
- **A pre-publish check that the artifacts really carry it.**
  `scripts/check_artifacts_ship_addon.py` reads the `.whl` and the `.tar.gz` back,
  compares `addon/**` byte-for-byte with `git ls-files addon`, applies the same copy
  rule the installer uses, and exits 0 clean / 1 finding / 2 cannot check. `release.yml`
  runs it after `uv build` and before the SBOM, the attestation and the publish; a
  directory argument expands itself, so the same command works on bash, PowerShell and
  cmd. (#94)
- **README Quick start installs from the release.** The clone and
  `./scripts/install-addon.sh` symlink path moved, unchanged in substance, to *Working
  on the add-in*. (#94)

### Changed

- `pyproject.toml` maps `addon/` into the package with `package-dir` entries and
  `package-data` for `*.manifest`, and lists `packages` explicitly: a find directive and
  an explicit list cannot coexist, so a new top-level package under `src/` ships in no
  artifact until it is listed, and a test derives the expected list from the tree. (#94)
- **No document states the measured coverage total any more.** It changed three times
  while #94 was built (61.47 -> 62.80 -> 62.84 -> 62.89), each change needing a
  full-suite run and edits to `docs/TESTING.md` and the `addopts` comment; the figure
  and `scripts/check_coverage_figures.py` are deleted together, along with the CI step
  that ran it and `scripts/__init__.py`, whose only importer was the deleted test. The
  floors (59 combined, 95 for `src/`) are enforced by the tools that read them, and
  nothing machine-checks a stale figure in prose any more. (#95)

## [0.7.3] - 2026-11-12

A documentation-and-tooling patch. Nothing in `src/` changed and no add-in code
changed: the range touches one file under `src/` or `addon/`, the manifest's version.
So nothing a caller of the server or the add-in can observe is different, which is
why this is a patch and not a minor: no tool, parameter, response field or
`error_kind` moved, and the Python floor is unchanged.

### Fixed

- **The README's install snippets pointed at `v0.3.1`.** All five of them — the two
  `claude mcp add` lines, the bare `uvx` invocation, and the Cursor and VS Code JSON
  configs — pinned a release four minors old, so a reader who followed the README
  installed 0.3.1 while 0.7.2 was current. They now name the release being cut, and a test
  fails when a documented pin stops matching `pyproject.toml`. (#85)
- **`scripts/install-addon.sh` derives the add-in's name from its manifest** instead of
  spelling it four times, so the folder it installs and the instructions it prints cannot
  disagree. That substitution is also why the script now refuses three states it used to
  pass through: with the name read from a glob, an `addon/` holding no manifest would
  compute an empty target and `rm -rf` the whole AddIns directory, taking every installed
  add-in with it; two manifests leave `basename` two operands and no name; and a match
  that is not a regular file would name the add-in after a file Fusion cannot load. Repo
  tooling only: `scripts/` is not in the sdist, verified with `tar tzf` on the 0.7.2
  build. (#89)

  **Corrected after release (#92).** The middle clause above is wrong: `basename`
  receives the first match and its suffix, so it does produce a name, and two manifests
  are not an error — without the count check the script installs silently under whichever
  manifest the glob lists first. The script's own comment said the same, and was fixed in
  #91.

### Changed

- **`addon/Fusion360MCP.manifest` states the released version.** It said `0.1.0` from the
  commit that created it until 0.7.2, sixteen tagged releases, and now tracks
  `pyproject.toml`, with a test that fails when the two disagree. This tag is the first
  whose tree carries the corrected value: the `v0.7.2` tag itself still says `0.1.0`.
  Fusion parses the manifest with strict JSON rules and does not validate the version, so
  nothing about the add-in's behaviour changes — only what a reader of that field sees.
  (#84)
- **`CONTRIBUTING.md`'s release steps put the changelog entry in the release PR.** It used
  to ask for the entry after the tag, which is not what 0.7.0 through 0.7.3 did — all four
  entries went in with their release PR. The step order and the PR title example now match
  the practice.

### Testing

- Three drift guards joined the suite: the manifest's add-in id, so a GUID change is a
  deliberate act; the lint and format commands the documents quote, so a documented command
  cannot stop being the one CI runs; and the add-in's name across its five copies.
  (#86, #87, #88)

## [0.7.2] - 2026-11-10

A lint-and-CI release with two add-in changes inside it. No tool, parameter or
response field was removed and no documented parameter changed meaning, so this is a
patch.

**Both changes live in the add-in**, so pull and reload it (`reload_handler` over the
socket, or Shift+S > Add-Ins > Run) to pick them up. Nothing breaks if you do not: the
dimension path hands Fusion the same arguments it already did. The wire protocol is
untouched, and the wheel carries only `src/`, so installing 0.7.2 on its own changes
nothing in real mode.

### Changed

- **`execute_code`'s syntax-error refusal is rendered once.** The parse used to be
  printed twice - in the message and again as the chained cause. The chained block is
  suppressed, and the parser's own rendering - file, line, the offending line and its
  caret - now travels in the message, which is what the agent reads, so suppressing the
  block loses nothing. (#76)
- **`add_dimension` narrows its entities where the lambda table reads them.** Seven
  `reportAttributeAccessIssue` findings were narrowing-loss rather than noise: the
  asserts that guarantee an entity is present are conditional on the type table, so the
  merged type was `Any | None` again by the time the table read `.boundingBox` and
  `.startSketchPoint`. The entities are narrowed into `first`/`second` inside each branch
  that already knows the answer. The arguments Fusion receives are unchanged, verified
  live on 2706 for a radial dimension and a distance between two lines. (#78)
- **`ruff`'s selection is `["E", "F", "I", "RUF", "B", "SIM"]`, and the tree is clean.**
  The 16 findings `B` and `SIM` reported are fixed in code: no `ignore`, no
  `per-file-ignores` and no new `noqa`. `scripts/` was added to both the lint and the
  format gate, which had covered four trees and skipped the directory the suite itself
  imports. (#76, #80)
- **CI checks that the coverage percentage the docs quote is the one the run measured.**
  `scripts/check_coverage_figures.py` runs after pytest and fails naming `file:line`; a
  document that stops quoting the figure fails as vacuous rather than passing nothing.
  The figure moved three times inside the lint parcel - 60.73, 61.27, 61.44 - and no gate
  saw it. (#77)

### Testing

- `tests/test_addon_joints.py` reads the joint tables from the imported `CommandHandler`
  instead of parsing the add-in with `ast`: the reason for the parse (an add-in that
  could not be imported) stopped being true when the lazy adapter landed. (#82)
- `add_dimension`'s second point, its three orientation enums and `angular`'s argument
  order are pinned, so a per-branch regression in the narrowed table cannot stay green.
  (#81)
- The bridge's failing-fire pin now proves the command still runs, and a second test pins
  that a fire that never works surfaces as `TIMEOUT` rather than propagating. (#76)
- The `execute_code` syntax-error test pins that the offending line and its caret reach
  the agent. (#76)

## [0.7.1] - 2026-11-09

The release where a dimension can name the curve it measures. No tool, parameter or
response field was removed and no documented parameter changed meaning, so this is a
patch: a schema-legal radial dimension now works, a `midpoint` constraint resolves the
point it was given, and refusals that used to arrive as `UNKNOWN` with no hints now
carry their `error_kind` and hints - a missing entity field, an unknown dimension or
constraint type, a point index that names no point, and Fusion's two opaque shell
messages.

**The behaviour lives in the add-in**, so pull and reload it (`reload_handler` over the
socket, or Shift+S > Add-Ins > Run). The wire protocol is untouched, so this server
still talks to an older add-in - but that add-in keeps classifying those refusals
`UNKNOWN`, and the wheel carries only `src/`, so installing 0.7.1 on its own changes
nothing in real mode.

### Fixed

- **`add_dimension` creates a radial or diameter dimension.** The guard demanded
  `entity_two` for every type, so `add_dimension("radial", 2.0, entity_one=0)` - legal
  under the schema - could not be created at all, and the refusal classified `UNKNOWN`
  with no hints. A table now says which entities each type needs, and the refusal names
  the field that is missing instead of both. Measured on 2706: a radial dimension on a
  sketch offset to z=5 applies, value 3.0. (#71)
- **`add_constraint("midpoint")` resolves its first entity against sketch points.** It
  was validated against `sketchCurves`, so a point index that also fell inside the curve
  list named the wrong item, and one past it was refused with advice about curves. The
  index is checked as a whole-number point index against `sketchPoints` now, and a
  missing first entity is refused instead of being reported as `entity_one: 0`. (#71)
- **`shell` refuses a wall Fusion cannot honour.** A non-finite, non-positive or
  non-numeric `thickness` reached Fusion and came back as `UNKNOWN` with no hints: the
  schema's `minimum` is enforced by the MCP layer, but the socket takes what a client
  sends and `json.loads` accepts `NaN` and `Infinity`. The wall is judged before the
  body lookup, a `bool` is not a distance, and mock mode refuses the same shapes.
  Measured on 2706: `0`, `-1` and `NaN` are each refused by name and the shell-feature
  count is unchanged, so nothing reaches Fusion. (#72)
- **Two Fusion shell refusals are classified.** Reading `insideThickness` before setting
  it returns `2 : InternalValidationError : res`, and an impossible wall returns
  `3 : Some input argument is invalid.` Each family has a rule in both hints mirrors, so
  neither arrives as `UNKNOWN`. (#72)

### Changed

- **`add_dimension`'s and `add_constraint`'s descriptions say what their parameters
  mean.** `entity_one` is a sketch point for `midpoint` and a curve for every other
  type. `add_dimension`'s `entity_two` is needed by distance, horizontal, vertical and
  angular only; `add_constraint`'s says it is not needed for fix, horizontal or
  vertical. No `required` entry changed, so every call that worked before still works.
  (#71)
- **`docs/ROADMAP.md`'s test-refactor section is closed**, naming the three parcels that
  retired the source scans and the three source reads that stay. (#73)

### Removed

- **`docs/BADGE.md`, and the plan to earn the OpenSSF Best Practices badge.** The badge
  is not being pursued, so the passing-criteria map and ROADMAP's registration section
  are gone with it; the evidence it cited was already where a reader looks - coverage
  floors in `docs/TESTING.md` and `pyproject.toml`, the local-trust design notes in
  `SECURITY.md`. The roadmap now carries one open item, a stricter lint selection. (#74)

### Testing

- **The rule-set drift guard reads both spellings.** It matched `select = [...]` only,
  which `CONTRIBUTING.md`'s prose form - `` rules `E`, `F`, ... `` - never had, so the
  copy a past sweep had to repair was the copy nothing guarded. Each document must now
  still quote the set, and a missing one fails loudly rather than passing vacuously.
  (#74)
- **940 tests**, coverage **60.73%** over `src/fusion360_mcp` and `addon/server`, with
  `src/` keeping its own 95 floor in CI. (#71, #72, #73, #74)

## [0.7.0] - 2026-11-09

The release where a box is centred on the point it is given, and the add-in becomes
importable. Minor rather than patch because `create_box` moves geometry: a box asked for
at `center_z=1` with height 2 used to span z 1..3 and now spans 0..2. No parameter was
renamed or removed and no tool changed shape, so every existing call still runs — but a
box lands half its height lower, and that is visible in any design built with the old
placement.

### Changed

- **`create_box` centres the box on `center_z`.** The orientation matrix was built at
  `center_z + height / 2`, so X and Y were centred on the caller's point while Z *started*
  there. The schema now says which it means, which it previously did not: `center_x`,
  `center_y` and `center_z` carry descriptions, and the three sizes name the axis they
  bound. Measured on Fusion 2706, `create_box(length=10, width=6, height=2, center_z=1)`
  returns a body spanning z 0.0..2.0. (#66)
- **The add-in is importable under pytest.** Nothing under `addon/` imports `adsk` at
  module scope any more: it resolves Autodesk's API through one lazy adapter
  (`addon/server/fusion_api.py`), and the log handlers are attached by an explicit
  `configure()` rather than at import. The suite therefore measures `addon/server` and
  injects its fakes through a single seam instead of writing `sys.modules`. No tool
  behaviour changes and the wire protocol is untouched, so an older add-in still talks to
  this server. (#68)

### Testing

- **Coverage measures the add-in, and `src/` keeps its own floor.** The combined floor is
  59 over both packages, because the add-in's CAM, export and viewport paths only run
  inside Fusion; CI adds
  `coverage report --include="src/fusion360_mcp/*" --fail-under=95` as a second gate, so
  a server regression cannot hide behind the add-in's number. 888 tests. (#68)
- **`create_hole`'s call-site guards are behavioural tests.** Five source scans became six
  tests that drive the handler against a hole-feature model; the sixth pins the planar-face
  skip the scans never covered. (#65)
- **Six documents that still said the add-in could not be imported are corrected**, and
  the three that said it in different words were found by the review. (#69)

## [0.6.4] - 2026-11-08

The release where a joint frame with no usable axis is refused instead of answered with
zeros. Nothing was removed, so this is a patch.

### Fixed

- **`add_joint` and `create_as_built_joint` refuse a degenerate joint frame.** The frame's
  three axes are ranked by `|dot|` against the requested world axis, so a zero-length
  vector ties with everything and wins arbitrarily: the caller was told `axis_world` was
  `[0, 0, 0]`, and the joint was built around whichever `JointDirections` member the tie
  happened to produce. The refusal names the offending axis, carries the whole frame, and
  classifies `INVALID_INPUT` with hints. Measured on 2706: a cylinder's joint frame reports
  exactly 1.0 for the squared length of all three axes, so the 1e-12 threshold cannot
  refuse real geometry. (#61)
- **`add_joint` no longer builds the frame for a rigid joint.** `rigid` is the default
  `joint_type` and resolves no direction, so a frame-wide guard would have refused a
  working default call because of an axis nothing asked for. (#61)

### Changed

- **The joints test suite no longer reads the add-in's source to check behaviour.** Fifteen
  of its sixteen tests parsed `command_handler.py` with `ast`; the eight behavioural ones
  now run the handler against the fakes, which model the seven motion setters, a driveable
  motion per joint type with the value attributes Fusion actually exposes, and
  `asBuiltJoints`. What remains is table-against-schema checking, which a test cannot
  observe any other way. No user-facing behaviour changes. (#63)

## [0.6.3] - 2026-11-08

The release where `shell` opens the face it was told to open, and a curve index past
the end or below zero is refused with its range and hints — instead of an
unclassified error or a silently wrapped index. Nothing was removed, so this is a
patch.

### Fixed

- **`shell` now opens the face `face_selection` names.** 0.6.2 fixed *which* faces were
  chosen; the feature still built a closed cavity around them. `ShellFeatureInput` has
  no `facesToRemove` property — assigning one attaches a plain Python attribute to the
  API wrapper. It reads back as stored (`inp.facesToRemove.count == 1`,
  `inp.isValid == True`) and never reaches Fusion. The faces now travel in the collection
  `createInput` documents for them. Measured on 2706: a 10x10x2 box shelled at
  `thickness=0.2` with `face_selection="top"` goes from 200 cm³ to **34.112 cm³**,
  with a 7.84 cm² rim where the top was and no inner ceiling, on both a history-less
  and a parametric body. Closes the known issue in 0.6.2. (#58)
- **A curve index that names no curve is refused.** `add_constraint`, `add_dimension`,
  `offset_curve`, `trim_curve`, `extend_curve` and `sweep` indexed the sketch's curve
  list with no guard, so an index past the end was `UNKNOWN` with no hints, a
  **negative** index wrapped to the end of the list and returned `ok: true` having
  touched a curve nobody named, and `True` indexed as 1. All nine sites now refuse with
  the field, the index and the sketch — plus, for an out-of-range index, the valid
  range — classify `INVALID_INPUT` with hints, and mock mode refuses the two checks
  that need no geometry. (#59)

### Changed

- **The add-in's entry points are annotated**, so `mypy` checks their bodies instead of
  skipping them. Annotating `drain_queue` immediately found a real error: `WorkItem.error`
  was inferred as `None` from its initialiser while the handler assigned a formatted
  traceback to it. That field is now `str | None`. (#57)

## [0.6.2] - 2026-11-08

The release where the joint and face tools say what Fusion actually did. Nothing was
removed; one field was added to `list_edges`, so this is a patch.

### Added

- **`list_edges` reports `is_degenerate`.** A degenerate edge has no geometry at all (a
  revolved cone's apex produces two), and no fillet can round it. Every selector skips
  them, so a selection can legitimately return fewer edges than `count` — the flag is
  what makes that difference visible, and it is the field `fillet`'s new refusal tells a
  caller to look for. (#55)

### Fixed

- **`pin_slot` joints took their directions in the wrong order.** `axis` is documented as
  the primary direction — the slot — but Fusion reads the first argument as the
  *rotation*, so the slot stayed on the perpendicular default and never slid where it was
  told. Measured on 2706; `pin_slot` joins `ball` in the reversed set. Found because
  `add_joint` now reports the directions Fusion returns. (#51)
- **`shell`, `draft_faces` and `offset_faces` with `face_selection="top"` matched the body's
  side walls.** The threshold came from the body's bounding box, so any face that merely
  *reached* the top matched: `shell` on a plain 10x10x2 box reported five faces removed.
  "Top" and "bottom" now mean the faces lying in that plane, the rule
  `edge_selection` got in 0.6.1, and `shell` shares it instead of duplicating the
  threshold. (#54)
- **`FILLET_NO_EDGE_FOUND` classified as `UNKNOWN` with no hints.** Fusion's refusal
  is now `INVALID_INPUT`, naming the two ways an edge is unroundable: degenerate, or
  shorter than the radius. (#55)
- **`execute_code` reported a failure when the script had closed its own document.** The
  close succeeded and the post-execute design-type check raised
  `4 : An API Object refers to a deleted Object`, so the envelope said the call failed.
  It now returns `document_closed: true`. (#52)

### Changed

- **The add-in type-checks clean.** Its 32 standing `mypy` errors are fixed with real
  guards and corrected signatures rather than ignores, and several now name the parameter
  that is missing instead of raising `'NoneType' object has no attribute ...`. (#53)

### Known issue

- **`shell` did not open a face (fixed in 0.6.3).** With the selection now correct,
  the geometry can be
  measured: `shell(top)` on a box still produces a closed hollow body, top face intact.
  Fusion is not honouring the removed-face list, so this release fixes *which* faces are
  chosen, not what Fusion then does with them. **Fixed in 0.6.3** — the face list never
  reached Fusion at all. On 0.6.2, do not read `faces_removed` as proof that a face opened;
  the geometry is the evidence, and 0.6.2 has none.

## [0.6.1] - 2026-11-08

The release that makes `edge_selection` mean what it says on bodies that are not
boxes. No API was removed: every parameter and response field is unchanged, which is
why this is a patch.

### Fixed

- **`fillet` / `chamfer` with `edge_selection="top"` or `"bottom"` refused on bodies
  whose top is a curved surface.** The threshold came from `body.boundingBox`, so a
  dome apex or sphere belly — a surface with no edge on it — put the plane where
  nothing can match. Measured live on 2706 with a plate and a spheroid joined on top
  (body spans z −2…4, all fourteen edges at z=0 or z=1): both selectors returned
  `No edges matched` and refused. They now return 5 edges each, and the plane comes
  from the edges: the highest / lowest one that *holds* an edge. A raking or curved
  edge can no longer invent a plane that holds nothing. (#46)
- **`edge_selection="vertical"` selected every closed edge.** The test compared an
  edge's two vertices, and a `Circle3D`'s vertices are the same point (measured), so
  the four corner lines came back with two rings on the body above. It reads the
  edge's own bounding box now. (#46)
- **Degenerate edges are no longer offered to a fillet.** A revolved cone has two
  edges flagged `isDegenerate` with no geometry at all, and `fillet` given one fails
  inside Fusion with `FILLET_NO_EDGE_FOUND`. Every selector skips them; `all` on that
  cone now rounds 3 of its 5 edges and succeeds instead of failing on all five.
  `list_edges` still reports them. (#46)
- **"No edges matched" and "Unknown edge_selection" classified as `UNKNOWN` with no
  hints.** Both now return `INVALID_INPUT` with a next step, and a body with no edges
  at all (a `create_sphere` body has none) says so instead of reporting that nothing
  matched — its hint would otherwise have sent the caller to `list_edges` on a body
  with nothing to list. (#46)

### Changed

- **`top` and `bottom` are defined by the edges, not by the body.** On a plain box the
  result is unchanged (four edges each). On a body where the two disagree — a flat top
  ring below a slanted edge, a domed top — the flat ring is what comes back, and a
  caller who wants an edge that merely reaches the top names it by index or point.
- **Mock mode refuses an edge-selector combination real mode refuses**: two selectors
  at once, a selector combined with an index list, an empty list, a non-integer index,
  a two-coordinate point, and an unknown `edge_selection`. Mock mode is where a
  sequence gets developed; it should not accept a call Fusion rejects. (#46)

## [0.6.0] - 2026-11-07

The release that lets a caller say **which body a feature touches**, and stops the API
reporting a result it had only echoed back.

### Added

- **`target_body` on `extrude`, `revolve`, `sweep` and `loft`.** Without it Fusion
  applies a `cut`/`join`/`intersect` to *every* body the profile reaches. It sets
  Fusion's own `participantBodies`; nothing is copied or recreated. Measured on 2706: a
  loft across the seam between two touching blocks cut both, a `join` with no target
  merged the second body into the first (two bodies became one), and naming the target
  prevented both. (#41, #42)
- **`keep_tool` on `boolean_operation`**, so a boolean can leave the tool body alone
  instead of consuming it. (#39)
- **`list_edges`**, and `edge_indices` / `edge_points` / `edge_tolerance` on `fillet`
  and `chamfer`, replacing the coarse `all`/`top`/`bottom`/`vertical` selector as the
  only option. Points snap to the nearest edge; a point too far away, or equally close
  to two edges, is refused with the measurement. (#36)
- **`sketch_name` on the seven `draw_*` tools and `create_polygon`**, so geometry can be
  added to an older sketch without relying on creation order, and on `extrude`,
  `revolve` and `sweep` for the profile side of a feature. (#35, #38)

### Changed

- **A mistyped `operation` is reported first**, before a bad body or sketch. It
  invalidates the whole call, so any other error was sending the caller to fix the
  wrong thing. It also no longer leaves a construction line behind on a non-zero
  revolve axis. (#41, #42)
- **The add-in's refusal messages are classified, not `UNKNOWN`**: the profile that
  reaches no body (`NO_TARGET_SWEEP_BODY`), a loft with fewer than two profiles, and a
  mistyped `operation` on every feature tool now return `INVALID_INPUT` with a next
  step. (#41, #42)
- **The add-in's CAM refusals are mirrored in mock mode**, including non-finite stock
  offsets and `tool_diameter`, so the development surface refuses what Fusion refuses.
  (#34)
- **`ruff format --check` is a CI gate** over `src/`, `tests/` and `fuzz/`; `addon/`
  stays linted but not format-gated, because it runs on Fusion's own interpreter.
  (#33)
- **`pyright` is one surface**: `pyrightconfig.json` is gone, `[tool.pyright]` in
  `pyproject.toml` is the only copy, and `uvx pyright` now reports **0 errors**
  repo-wide. (#32, #43)

### Fixed

- **`fillet` / `chamfer` edge selection** samples each edge over its own parameter
  range and checks tolerance before ambiguity; both were wrong against real geometry
  and right only against the fake. (#40)
- **`build_value_input`'s unitless path** handed a huge int to `createByReal`, which
  raised `OverflowError` and surfaced as `UNKNOWN` with no hints. (#34)

### Removed

- **`create_hole` no longer reports `cut_bodies`.** `Feature.bodies` reports the
  participants the call set, not what was cut — measured: a cut naming a body it never
  reaches still reports that body — so the field echoed its own input dressed as a
  result, and a caller could read it as proof the hole landed. The envelope's `deltas`
  are the measured answer. **This is a response-shape break**, which is why it is a
  minor release. (#44)

### Tests and CI

- The suite fails if the add-in gains PEP 758 syntax, which a formatter would otherwise
  write into code that runs on Fusion's interpreter. (#37)

## [0.5.0] - 2026-11-05

### Added

- `tests/test_packaging.py`, a drift guard for the Python support window. It compares
  `requires-python` against the `Programming Language :: Python :: 3.x` classifiers in
  both directions, rejects a re-introduced ruff `target-version`, and fails when
  `pyrightconfig.json` pins an interpreter below the floor. That last check was written
  after pyright was found reading `tomllib` through a stale 3.10 lens and reporting
  `Import "tomllib" could not be resolved` on the new test file.

### Changed

- **The project requires Python 3.14+ and is tested on 3.14 and 3.15.** CI runs both on
  Ubuntu; the `windows` and `macos` jobs now name Python 3.15 and pass `--python` to
  `uv sync` instead of floating on whatever the runner image ships, and the matrix leg
  does the same, so a job cannot report a version's check name while running a different
  interpreter.
- **ruff's `target-version` is gone.** ruff infers its target from
  `project.requires-python`, so the window is stated once. That second copy is what
  drifted: it still said `py310` long after 3.10 was end-of-life.
- `pyrightconfig.json` moves from `pythonVersion` 3.10 to 3.14, the last hand-maintained
  copy of the floor.
- The fuzz job runs Python **3.14**. `atheris==3.1.0` publishes cp312/cp313/cp314 wheels
  and no sdist, so with a `>=3.14` floor that is the only interpreter the group can be
  synced with; `uv lock` narrows it to the single cp314 wheel.
- `README.md`, `ARCHITECTURE.md`, `docs/BADGE.md` and `docs/TESTING.md` state the new
  window.

### Removed

- **Support for Python 3.10, 3.11, 3.12 and 3.13.** 3.10 reached end-of-life on
  2026-10-01, and 3.11 and 3.12 are already security-only, so the old floor promised
  support for interpreters nobody upstream can fix. A `pip install` on any of them now
  refuses at `Requires-Python` with a version message, rather than installing a server
  that fails at import. `uvx` users are unaffected — uv installs 3.14 for them.
- `tomli` and `exceptiongroup` from the lock. They existed only below 3.11, so raising
  the floor removes them, along with the per-interpreter fork entries that made the lock
  four times its current size.

## [0.4.1] - 2026-11-01

### Added

- `scripts/check_review_threads.py` and a `threads` CI job: a pull request with unresolved
  review threads now fails, listing each one. The branch ruleset already required
  `required_review_thread_resolution`, but the code owner's `gh pr merge --admin` bypasses
  the whole ruleset — which is how the revolve change below merged with seven open CodeQL
  findings. `AGENTS.md` (a new **Merging** section) and `CONTRIBUTING.md` state the rule.

### Fixed

- **`revolve` now turns the profile about the axis the caller asked for.** Two defects,
  both measured in Fusion 2706.1.17 against a profile on a sketch offset to model
  `z=-2` with `axis_origin=(0, 0, 0)`:
  - The axis line was built in the **sketch's** frame, so it landed at model `z=-2`
    instead of `z=0` — displaced by exactly the plane offset — and a direction given in
    model space was left unrotated on a `yz`/`xz` sketch. `axis_origin_*` and
    `axis_direction_*` are now documented and treated as **model space (cm)**, converted
    through `modelToSketchSpace`. The result reports `axis_model_start` /
    `axis_model_end`, and an origin off the sketch plane is snapped into it with
    `axis_snapped_to_sketch_plane` plus a `note` rather than silently displaced.
  - The profile proxy was fetched **before** the axis line was added to the same sketch,
    and Fusion invalidates a proxy when the sketch changes: every non-world axis failed
    with `3 : invalid profile(s) for Revolve Feature`. Held geometry and the axis fixed
    and varied only that order — fetched-before fails, fetched-after builds the feature.
- `axis_origin` is honoured for world-aligned directions too. Asking for a line parallel
  to model X through `(0, 5, 0)` used to return the X axis through the model origin, the
  origin argument silently dropped.
- A revolve axis that cannot lie in the profile's sketch plane is refused with the new
  `AXIS_OUT_OF_PLANE` error kind and hints, instead of being projected onto a different
  axis.
- The seven CodeQL findings raised against that change are fixed rather than dismissed:
  the `AXIS_OUT_OF_PLANE` hints no longer rely on implicit string concatenation, and a
  module-scoped test fixture no longer mixes `return` with `yield`.

### Changed

- A direction is normalised, so its magnitude no longer changes the axis.
- A world-aligned direction **with a non-zero `axis_origin`** now builds the axis the
  caller asked for instead of falling back to the axis through the model origin. When
  that offset axis cannot lie in the sketch plane — `axis_direction_z` on an `xy` sketch
  with `axis_origin=(3, 4, 0)`, say — it reports `AXIS_OUT_OF_PLANE` rather than silently
  revolving about a different line.

## [0.4.0] - 2026-11-01

### Changed

- **`undo` no longer trusts Fusion's asynchronous undo.** It steps the timeline marker
  back one feature — synchronous, so the result is verified in the same call — and
  reports `verified: true` with the new marker. The feature is suppressed, not
  deleted. On a direct-mode design it issues Fusion's command and reports
  `undone: "issued"`, `verified: false`, with a hint to confirm via `get_scene_info`.
- The project is licensed **AGPL-3.0-or-later**, single expression. Upstream MIT
  attribution moved to `THIRD-PARTY-NOTICES.md` rather than shipping a parallel
  licence file.
- Dependencies upgraded to their first patched releases: `mcp` 1.26 → 1.30,
  `cryptography` 46 → 50, `starlette` 0.52 → 1.10, `anyio` 4.12 → 4.16, `certifi`,
  `pyjwt`, `uvicorn`, `pytest` 9. Clears 50 open advisories (3 critical, 16 high).
  The declared floors moved with them, because a tag install resolves from
  `pyproject.toml`, not from `uv.lock`.

### Added

- `NOT_ENTITLED` error kind for APIs Fusion refuses for entitlement reasons (seen on
  `auto_constrain`), with hints that say not to retry.
- `ignored_z`, `note` and model-space positions (`model_center`, `model_origin`,
  `model_start`/`model_end`, `model_points`) on sketch draw tools, and `hints`
  rendered on successful results as well as failures.
- `docs/TOOLS.md` — all 96 tools, grouped. The README is a landing page now.
- CodeQL, dependency review and OpenSSF Scorecard workflows; release workflow with
  CycloneDX SBOM and build provenance attestation.

### Fixed

- Drawing on a sketch created with `z_offset` no longer places geometry at double the
  offset. Fusion reads sketch-curve points in the sketch's own frame, so the caller's
  `z` composed with the plane transform.
- `get_scene_info` no longer fails with "this is not a parametric design" on a
  direct-mode design — the tool `undo`'s own hint points at.
- A dead connection returns a `FusionError` with a hint instead of `AttributeError`.
- Resource URIs use pydantic's `AnyUrl` and are no longer bare strings.
- The README claimed 93 tools (three were missing from the catalogue), cited Fusion
  2705, and told you to install from PyPI while explaining elsewhere that the PyPI
  build is broken.
- A body *named* after the other kind was misclassified: `Body 'Sketch1' not found` came
  back as `SKETCH_NOT_FOUND`, because that rule spanned the whole message and was matched
  first. Both `hints.py` mirrors anchor on the quoted name, and `BODY_NOT_FOUND` is
  matched before `SKETCH_NOT_FOUND`.

### Docs / project

- Property-based tests over `hints.classify` (the bug above came from them), coverage
  measured on every run and floored at 80%, and a macOS CI leg.
- `ARCHITECTURE.md` (main-thread boundary, error envelope, sketch/undo semantics),
  `examples/model-a-bracket.md` (a worked session), `SUPPORT.md`.
- `AGENTS.md` gained commands-first, how-to-add-a-tool, conventions and an explicit
  Boundaries section; the model-specific `.claude/CLAUDE.md` is gone.
- `CODEOWNERS`, issue templates, a PR template, Dependabot (with security updates),
  `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `llms.txt`.
- Line endings normalised to LF with `.gitattributes`; workflows linted with
  `yamllint` in CI.

## [0.3.1] - 2026-11-01

### Fixed

- **Sketch curves stay in the sketch plane.** On a sketch created with
  `z_offset=-0.65`, drawing with `z=-0.65` used to put the geometry at model −1.30 —
  the offset applied twice — and still report success. The normal component is now
  dropped and reported.

### Changed

- README install command moved to the release tag, and the changelog entries
  backfilled. - `ruff format` applied to the sketch code.

## [0.3.0] - 2026-11-01

### Changed

- Licence change: the work added in this repository became AGPL-3.0-or-later, with the
  inherited upstream code remaining MIT. Superseded by the AGPL-only licence above.

## [0.2.2] - 2026-11-01

### Fixed

- The add-in socket closes the connection on malformed input instead of hanging; a
  browser request line is never valid JSON. - `execute_code` is annotated as
  destructive, so clients can prompt for it.

### Docs

- `AGENTS.md` documents all 96 tools; a Markdown standard was adopted and applied.

## [0.2.1] - 2026-11-01

### Added

- `new_document` — create a design from a cold start, through the API, so components
  and joints are possible. - `draw_circles` — insert many circles in one solve (100
  circles: 912 ms → 98 ms).

### Fixed

- `measure_distance` reads `positionOne`/`positionTwo` from `MeasureResults`. - The
  client dials `127.0.0.1` instead of `localhost`, avoiding a ~2 s IPv6-first connect
  on Windows.

## [0.2.0] - 2026-11-01

### Added

- First tagged release: the MCP server, the Fusion add-in, 90+ tools, mock mode, and
  the structured error envelope (`ok`, `error_kind`, `hints`, `traceback`).

[0.10.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.8.5...v0.9.0
[0.8.5]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.8.4...v0.8.5
[0.8.4]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.8.3...v0.8.4
[0.8.3]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.8.2...v0.8.3
[0.8.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.7.3...v0.8.0
[0.7.3]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.6.4...v0.7.0
[0.6.4]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/shinobi81/fusion360-mcp-server/releases/tag/v0.2.0
