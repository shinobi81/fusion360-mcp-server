# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions before 0.3.0 use the shared date 2026-11-01, the day this project was tagged
and published; they are the fork history.

## [0.6.3] - 2026-11-08

The release where `shell` opens the face it was told to open, and a curve index that names
nothing is refused instead of silently naming another curve. Nothing was removed, so this
is a patch.

### Fixed

- **`shell` now opens the face `face_selection` names.** 0.6.2 fixed *which* faces were
  chosen; the feature still built a closed cavity around them. `ShellFeatureInput` has
  no `facesToRemove` property — assigning one attaches a plain Python attribute to the
  API wrapper, which reads back as stored, reports `faces.count == 1`, leaves `isValid`
  true and never reaches Fusion. The faces now travel in the collection `createInput`
  documents for them. Measured on 2706: a 10x10x2 box with `face_selection="top"` goes
  from 200 cm³ to **34.112 cm³**, with a 7.84 cm² rim where the top was and no inner
  ceiling, on both a history-less and a parametric body. Closes the known issue in
  0.6.2. (#58)
- **A curve index that names no curve is refused.** `add_constraint`, `add_dimension`,
  `offset_curve`, `trim_curve`, `extend_curve` and `sweep` indexed the sketch's curve
  list with no guard, so an index past the end was `UNKNOWN` with no hints, a
  **negative** index wrapped to the end of the list and returned `ok: true` having
  touched a curve nobody named, and `True` indexed as 1. All nine sites now refuse with
  the field, the index, the sketch and the valid range, classify `INVALID_INPUT` with
  hints, and mock mode refuses the two checks that need no geometry. (#59)

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

- **`shell` does not open a face.** With the selection now correct, the geometry can be
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

[0.6.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/shinobi81/fusion360-mcp-server/releases/tag/v0.2.0
