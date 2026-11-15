# AGENTS.md

## Overview

This is an MCP server (97 tools) that connects AI coding agents to Autodesk Fusion 360
for CAD automation. It consists of two pieces:

1. **MCP Server** (this repo) — speaks MCP protocol over stdio, forwards commands to
   Fusion via TCP
2. **Fusion 360 Add-in** — runs inside Fusion, executes commands on the main thread via
   CustomEvent bridge

## How the system works

```text
MCP client ──stdio──> MCP Server ──TCP :9876──> Fusion Add-in ──CustomEvent──> Main Thread
  (Claude Code,                  <──JSON──                  <──result──
   Codex, Cursor, …)
```

The add-in uses a CustomEvent + work queue pattern to safely dispatch all Fusion API
calls to the main thread. Socket threads submit work items and block on a per-item
`threading.Event` until the main thread completes execution.

## Commands

```bash
uv sync --locked               # install deps into .venv; refuses a stale lock
uv run pytest -q               # suite runs without Fusion
uv run pytest -q --no-cov tests/test_tools.py   # subset: the coverage floor
                                                # applies to the whole suite
uv run ruff check src/ tests/ fuzz/ addon/ scripts/  # lint (this is what CI runs)
uv run ruff format --check src/ tests/ fuzz/ scripts/    # format gate (what CI runs)
uv run ruff format src/ tests/ fuzz/ scripts/  # apply it; addon/ is exempt
npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"
```

`addon/` is linted but not format-gated, and this file used to say to format
`addon/server/command_handler.py` by hand — don't. The add-in runs on Fusion's own
interpreter, which `requires-python` does not govern, so a rewrite that is legal for
this package is not safe to apply there. The directory's sole remaining drift is
exactly that: ruff turns `except (TypeError, ValueError):` into
`except TypeError, ValueError:`, PEP 758 syntax, because the target it infers is
3.14. `tests/test_addon_sources.py` reads the add-in's tokens and fails the suite if
that form appears, so a formatter you did not ask for cannot reach `main`.

`uv run` **rebuilds the package** when `pyproject.toml` changes, and Windows will not let
it replace `.venv/Scripts/fusion360-mcp-server.exe` while a running MCP server holds it
(`os error 32`). When that bites, use `uv run --no-sync …`, or stop the server first.

**Coverage is two gates, not one.** `pytest` measures `src/fusion360_mcp` _and_
`addon/server`, and the floor in `addopts` (59) is set just under the combined total —
the add-in's CAM, view-sheet export and viewport families only run inside Fusion (body
STL/STEP and f3d export are covered offline), so its own number
is low on purpose. The server keeps its own gate: CI runs
`uv run coverage report --include="src/fusion360_mcp/*" --fail-under=95` after pytest, so
an add-in regression cannot buy slack for `src/`. Run both before opening a PR that
touches either.

The add-in is importable under pytest: nothing under `addon/` imports `adsk` at module
scope — it resolves Autodesk's API through the lazy adapter in
`addon/server/fusion_api.py`. The `handler_module` fixture in `tests/conftest.py` injects
the fake API into that adapter for a whole test module (`tests/fakes/runtime.py` for the
surface, `sketch.py` and `design.py` for geometry and the document tree) and restores it
afterwards, and `tests/test_addon_importable.py` asserts the import works in a subprocess
where no `adsk` exists at all. Neither pyright nor mypy can resolve `adsk`; `addon/` is
therefore still excluded from both in `pyproject.toml`.

`fuzz/` is the other test surface: four atheris targets whose `check(data)` functions are
also driven by `tests/test_fuzz_targets.py`, so their invariants run in the ordinary
suite on every platform while atheris itself stays Linux-only and CI-only. Running them
by hand, and what the job needs, is in `docs/TESTING.md`.

## Adding a tool

1. Handler method in `addon/server/command_handler.py`, registered in `_COMMANDS`
2. Tool definition in `src/fusion360_mcp/tools.py` (`name` must match the command exactly)
3. Mock handler in `src/fusion360_mcp/mock.py` + `_DISPATCH` entry — `test_addon_sync.py`
   fails if the two lists drift
4. Mutation commands go in `_MUTATION_COMMANDS` (add-in) and `_MUTATION_MOCKS` (mock)
5. Annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`
6. A row in `docs/TOOLS.md` and the name in the index above — the index is guarded,
   the description is not
7. Add a behavioural mock test (`tests/test_mock.py`); the tool count and each
   tool's argument count are pinned in `tests/test_tools.py`

The MCP server forwards tool calls 1:1 — there is no mapping layer to touch.

## Conventions

- Tool names are `snake_case` and must match the add-in command names.
- **All lengths are centimetres** — Fusion's internal unit. Not millimetres.
- Wire format is newline-delimited JSON over TCP; `ping` never touches the Fusion API.
- Errors are returned as data (`ok: false`, `error_kind`, `hints`), not raised across the
  wire. New failure modes get a rule in `addon/server/hints.py` — the canonical table —
  then `uv run python scripts/sync_mirrors.py` regenerates `src/fusion360_mcp/hints.py`.
- Every tool has a mock handler, so `--mode mock` works without Fusion.

## Boundaries

- **Never push to `main`.** The ruleset requires a reviewed PR, a green CI run and
  resolved review threads; direct pushes and force-pushes are rejected. This applies to
the maintainer too.
- **Never merge a PR that still has unresolved review threads.** Inline comments — the
  CodeQL/Dependabot findings especially — are review threads. Resolve every one first,
  by fixing it or by replying with why it does not apply. See _Merging_ below.
- Never commit secrets. `.env` is gitignored — keep it that way.
- Never edit `.venv/` by hand, and do not run `uv sync` while an MCP server is running.
- Never call `close()` on the active Fusion document from `execute_code` — it crashed
  Fusion 2705.
- Do not "fix" `addon/` type errors by adding ignores; `adsk` genuinely cannot resolve
  outside Fusion and the directory is excluded on purpose.
- Do not edit `build/`, `.venv/`, or `uv.lock` by hand (`uv lock` regenerates it).

## Merging

`main` takes PRs only, and merging needs an approving review that a solo author cannot
give themselves, so the merge is `gh pr merge <n> --squash --admin`. **`--admin` bypasses
the entire ruleset**, including `required_review_thread_resolution` — the setting that is
supposed to stop exactly this. GitHub will not save you; the check is yours to run:

```bash
python scripts/check_review_threads.py <pr>   # exit 0 = mergeable, 1 = threads open
gh pr view <pr> --json reviews --jq '.reviews[] | "\(.author.login) [\(.state)]\n\(.body)"'
gh pr merge <pr> --squash --admin            # only after the two commands above are clean
```

The `threads` CI job runs the same script, so a PR with open threads shows a failing
check — that is the copy to look at, and a red `threads` check is never "fine, merge
anyway". A failure to _query_ threads is also a failure: an unchecked merge is not a
clean merge.

Reading the bot findings is not a formality. PR #19 was merged with seven open CodeQL
threads (six `implicit-string-concatenation-in-list` in a new `hints` rule, one
`mixed-returns` in a test fixture) because the threads were never opened. Fix them or
record why not — in the thread — before merging.

## Available tools (97)

Grouped by area (the grouping and order differ from `docs/TOOLS.md`, which has the
argument-level description of each tool; the schema is `src/fusion360_mcp/tools.py`).
A name that is not in this table is not a tool: list_tools returns exactly these and
the add-in dispatches on the same strings.

| Area | Tools |
| --- | --- |
| Document | `new_document`, `get_design_type`, `set_design_type` |
| Scene & Query | `ping`, `get_scene_info`, `get_object_info`, `list_edges`, `list_components`, `get_bounding_box` |
| Sketching | `create_sketch`, `draw_rectangle`, `draw_circle`, `draw_line`, `draw_arc`, `draw_spline`, `create_polygon`, `draw_circles`, `add_constraint`, `auto_constrain`, `add_dimension`, `offset_curve`, `trim_curve`, `extend_curve`, `project_geometry` |
| Features | `extrude`, `revolve`, `sweep`, `loft`, `fillet`, `chamfer`, `shell`, `mirror`, `create_hole`, `rectangular_pattern`, `circular_pattern`, `create_thread`, `draft_faces`, `split_body`, `split_face`, `offset_faces`, `scale_body`, `suppress_feature`, `unsuppress_feature` |
| Body Operations | `move_body`, `rename_body`, `boolean_operation`, `delete_all`, `undo` |
| Direct Primitives | `create_box`, `create_cylinder`, `create_sphere`, `create_torus`, `create_box_parametric` |
| Surface Operations | `patch_surface`, `stitch_surfaces`, `thicken_surface`, `ruled_surface`, `trim_surface` |
| Sheet Metal | `create_flange`, `create_bend`, `flat_pattern`, `unfold` |
| Construction Geometry | `create_construction_plane`, `create_construction_axis`, `create_ucs` |
| Assembly | `create_component`, `add_joint`, `create_as_built_joint`, `create_rigid_group`, `set_joint_value` |
| Inspection & Analysis | `measure_distance`, `measure_angle`, `get_physical_properties`, `create_section_analysis`, `check_interference`, `compare_meshes` |
| Appearance & Parameters | `set_appearance`, `set_color`, `get_parameters`, `create_parameter`, `set_parameter`, `delete_parameter` |
| Import | `import_mesh` |
| Export | `export_stl`, `export_step`, `export_f3d`, `export_view_sheet`, `export` |
| CAM / Manufacturing | `cam_create_setup`, `cam_create_operation`, `cam_generate_toolpath`, `cam_post_process`, `cam_list_setups`, `cam_list_operations`, `cam_get_operation_info` |
| Code Execution | `execute_code` |
| Perception | `render_view` |

## Response shape

Every tool call returns a dict-shaped result with these conventions — read them instead
of guessing whether an operation worked:

**Success:**

```json
{
  "ok": true,
  "body_name": "Body1",   // tool-specific fields
  ...,
  "deltas": {             // present only for mutations
    "body_count_before": 0,
    "body_count_after":  1,
    "body_count_delta":  1,
    "mass_g_before": 0.0,
    "mass_g_after":  7.85,
    "mass_g_delta":  7.85,
    "bbox_before": null,
    "bbox_after":  {"min": [0,0,0], "max": [1,1,1]}
  }
}
```

**Failure (no exception — the error flows back as data):**

```json
{
  "ok": false,
  "error_kind": "PROFILE_NOT_CLOSED", // stable tag you can branch on
  "error_message": "No profiles in sketch", // short human-readable
  "hints": ["close the loop", "..."], // contextual repair suggestions
  "traceback": "..." // full traceback for debugging
}
```

Known `error_kind` values: `PROFILE_NOT_CLOSED`, `SKETCH_NOT_FOUND`, `BODY_NOT_FOUND`,
`SELF_INTERSECTION`, `REGEN_FAILED`, `BOOLEAN_NO_OP`, `AXIS_OUT_OF_PLANE`, `INVALID_INPUT`,
`NO_ACTIVE_DESIGN`, `DESIGN_TYPE_MISMATCH`, `NOT_ENTITLED`, `TIMEOUT`, `UNKNOWN_COMMAND`,
`UNKNOWN`.

`NOT_ENTITLED` means Fusion refused the API for this account (seen on
`auto_constrain`: "not available since user is restricted"). It is not a parameter
problem — do not retry the same call, use an approach that does not need that API.

**Sketch draw tools report where the geometry landed, not where you asked.** Fusion reads
sketch-curve points in the sketch's _own_ frame, so a `z` you pass to `draw_rectangle`,
`draw_circle`, `draw_line`, `draw_arc`, `draw_spline` or `create_polygon` is projected
onto the sketch plane rather than added to its offset — passing the plane's own
`z_offset` again used to double it. The result carries `model_center` / `model_origin` /
`model_start` / `model_end` / `model_points` (model space, cm), plus `ignored_z` and a
`note` whenever a non-zero `z` was discarded. To move geometry, move the plane:
`create_sketch(z_offset=...)`.

**`revolve`'s axis is model space, and must be coplanar with the profile.**
`axis_origin_*` and `axis_direction_*` are model-space centimetres, not sketch
coordinates — a direction is normalised, so its magnitude does not matter. A world axis
through the model origin uses Fusion's own construction axis; anything else becomes a
construction line in the profile's sketch, so an axis leaving the sketch plane is refused
with `AXIS_OUT_OF_PLANE`. Read `axis_model_start` / `axis_model_end` to confirm where it
actually ran; if the origin was off the plane, the result also carries
`axis_snapped_to_sketch_plane: true` and a `note`.

**An `extrude`, `revolve`, `sweep` or `loft` cut hits every body the profile reaches —
name `target_body` unless that is what you want.** Measured on Fusion 2706: a loft whose
sections spanned the seam between two touching blocks cut **both**. Left out, the choice
stays Fusion's own inference (`participantBodies` empty); `target_body` sets that property
and nothing is copied or recreated. Naming a body that does not exist is refused as
`BODY_NOT_FOUND`, and naming one with `operation="new_body"` is refused as `INVALID_INPUT`:
a new body is the feature's output, so there is nothing to target. A mistyped `operation`
is refused before any of that, because it invalidates the whole call.

**`undo` steps the timeline back, and tells you whether it could verify that.** On a
parametric design it moves the timeline marker back one step, which the API performs
synchronously: `{undone: true, verified: true, marker_position: n, timeline_count: m}`.
The feature is **suppressed, not deleted** — `timeline_count` does not drop, and moving
the marker forward brings it back. `{undone: false, verified: true, reason: ...}` means
there was nothing left to undo. Direct designs have no timeline, so Fusion's undo command
is asynchronous and lands only after the call returns: you get `{undone: "issued",
verified: false}` and must confirm with `get_scene_info` before undoing again.

**Use the deltas to sanity-check without a render.** A `boolean_operation` that reports
`body_count_delta: 0, mass_g_delta: 0` did nothing — follow up with `check_interference`
before retrying. With `keep_tool=True` the body count does not drop even when the cut
worked, so read `mass_g_delta` there. An `extrude` that shifts mass by three orders of
magnitude is probably using the wrong units.

**Use `render_view` sparingly** — it returns ~200KB–2MB of base64 image data. Render
after a logical checkpoint (finished a feature, about to commit), not after every
mutation. Deltas already tell you whether the feature _did_ something; `render_view`
tells you whether it did the _right_ something.

## MCP protocol features

- **Tool annotations:** Every tool has `readOnlyHint`, `destructiveHint`, and
  `idempotentHint` metadata. These are untrusted behavioral hints unless supplied by a
  trusted server, not authorization or proof of safe execution. See the
  [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).
- **Resources** — `fusion360://status`, `fusion360://design`, `fusion360://parameters`
- **Resource templates** — `fusion360://body/{name}`, `fusion360://component/{name}`
- **Prompts** — `create-box`, `model-threaded-bolt`, `sheet-metal-enclosure` workflow
  templates
- **Structured errors** — `isError=True` when the add-in reports failures. Error results
  carry `error_kind`, `hints`, and a traceback so the agent can branch on failure mode
  rather than parsing prose (see _Response shape_ above).
- **Mock mode** — `--mode mock` returns test data without Fusion running

## Important constraints

- **One operation per tool call.** Never batch multiple operations — Fusion's API is not
  thread-safe and complex scripts crash the add-in.
- **No loops inside execute_code.** If you need to create 3 similar features, make 3
  separate tool calls.
- **Keep execute_code under ~15 lines.** Prefer the dedicated tools over execute_code
  whenever possible.
- **Units are centimeters.** Fusion's internal API uses cm, not mm.
- **30-second timeout.** Commands that take longer than 30s will return a timeout error.
- **body_name preferred over body_index.** Use named lookups when possible.
- **Verify after each step.** Call `get_scene_info` or `get_object_info` to confirm
  success — don't assume from lack of error.
- **Name everything.** Name every body and sketch explicitly so they can be referenced
  reliably in later steps.

## Troubleshooting

- If commands fail with "Not connected", the Fusion add-in isn't running. The user needs
  to start it in Fusion (Shift+S > Add-Ins > Run).
- If commands time out, the Fusion main thread may be blocked (modal dialog, heavy
  computation).
- If a merge looks live but Fusion behaves as it did before, the add-in is running the
  class it loaded at start-up: `uv run python scripts/reload_addin.py` reloads it and
  proves the running class matches the file (see `docs/TESTING.md`).
- After any error, call `get_scene_info` to check if the operation partially applied
  before retrying.
- Logs are written to `~/fusion360mcp.log` by the add-in.
