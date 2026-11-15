# AGENTS.md

## Overview

An MCP server (97 tools) connecting AI coding agents to Autodesk Fusion 360 for CAD
automation. Two pieces:

1. **MCP server** (this repo) — speaks MCP over stdio, forwards commands over TCP
2. **Fusion 360 add-in** — runs inside Fusion, executes commands on the main thread

```text
MCP client ──stdio──> MCP Server ──TCP :9876──> Fusion Add-in ──CustomEvent──> Main Thread
  (Claude Code,                  <──JSON──                  <──result──
   Codex, Cursor, …)
```

Fusion's API is not thread-safe, so the add-in dispatches every call to the main thread
through a CustomEvent work queue: a socket thread submits a work item and blocks on a
per-item `threading.Event` until the main thread completes it. Details: `ARCHITECTURE.md`.

## Commands

```bash
uv sync --locked               # install deps into .venv; refuses a stale lock
uv run pytest -q               # suite runs without Fusion
uv run pytest -q --no-cov tests/test_tools.py   # subset: the coverage floor
                                                # applies to the whole suite
uv run ruff check src/ tests/ fuzz/ addon/ scripts/  # lint (this is what CI runs)
uv run ruff format --check src/ tests/ fuzz/ scripts/    # format gate (what CI runs)
uv run ruff format src/ tests/ fuzz/ scripts/  # apply it; addon/ is exempt
uv run mypy src                # type gate (what CI runs); addon/ is excluded
npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"
```

`addon/` is linted but not format-gated: it runs on Fusion's own interpreter, which
`requires-python` does not govern, so a rewrite legal for this package is not safe there.
Ruff's one drift into it is PEP 758 (`except A, B:`), which
`tests/test_addon_sources.py` fails the suite on.

`uv run` **rebuilds the package** when `pyproject.toml` changes, and Windows will not let
it replace `.venv/Scripts/fusion360-mcp-server.exe` while a running MCP server holds it
(`os error 32`). Use `uv run --no-sync …`, or stop the server first.

Coverage is two gates: `pytest` floors the combined `src/` + `addon/server` total at 59
(low on purpose — the add-in's CAM, view-sheet and viewport families only run inside
Fusion), and CI separately requires 95 on `src/`. The lazy `adsk` adapter, the fake runtime
and the atheris targets: `docs/TESTING.md`.

## Adding a tool

1. Handler method in the module that owns the domain — one of the `handler_*.py` modules
   `COMMAND_MODULES` lists, not `command_handler.py`, which composes them and declares
   nothing — and its name in `HandlerBase._COMMAND_NAMES`
   — `__init__` builds `self._commands` from that set, so a name with no method cannot be
   listed and a method with no name is unreachable
2. Tool definition in `src/fusion360_mcp/tools.py` (`name` must match the command exactly)
3. Mock handler in `src/fusion360_mcp/mock.py` + `_DISPATCH` entry
4. Mutations also go in `addon/server/mutation_commands.py`, the one canonical set, then
   `uv run python scripts/sync_mirrors.py` regenerates the `src/` mirror that mock mode
   and the connection read; `tests/test_addon_sync.py` fails while any mirror is stale
5. Annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`
6. A row in `docs/TOOLS.md` and the name in the index in this file — the index is
   guarded, the description is not
7. A behavioural mock test (`tests/test_mock.py`); the tool count and each tool's argument
   count are pinned in `tests/test_tools.py`

The MCP server forwards tool calls 1:1 — there is no mapping layer to touch.

## Conventions

- Tool names are `snake_case` and must match the add-in command names.
- **All lengths are centimetres** — Fusion's internal unit. Not millimetres.
- Wire format is newline-delimited JSON over TCP; `ping` never touches the Fusion API.
- Errors are data (`ok: false`, `error_kind`, `hints`), never raised across the wire. A
  new failure mode gets a rule in `addon/server/hints.py` — the canonical table — then
  `uv run python scripts/sync_mirrors.py` regenerates `src/fusion360_mcp/hints.py`.
- A parameter the add-in can refuse from the parameters alone belongs in
  `addon/server/rules.py`, which the handler raises from and mock mode answers with: one
  message, one `error_kind`, both sides. `tests/test_rules.py` compares the two answers.
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
- Do not "fix" `addon/` type errors by adding ignores; `adsk` cannot resolve outside
  Fusion and the directory is excluded on purpose.
- Do not edit `build/`, `.venv/`, or `uv.lock` by hand (`uv lock` regenerates it).

## Merging

`main` takes PRs only, and merging needs an approving review a solo author cannot give
themselves, so the merge is `gh pr merge <pr> --squash --admin`. **`--admin` bypasses the
entire ruleset**, including `required_review_thread_resolution`, so the check is yours:

```bash
python scripts/check_review_threads.py <pr>   # exit 0 = mergeable, 1 = threads open
gh pr view <pr> --json reviews --jq '.reviews[] | "\(.author.login) [\(.state)]\n\(.body)"'
gh pr merge <pr> --squash --admin             # only after the two commands above are clean
```

The `threads` CI job runs the same script, so open threads show up as a failing check. A
red `threads` check is never "fine, merge anyway", and failing to _query_ threads is a
failure too: an unchecked merge is not a clean merge. Bot findings are review threads
too — fix each one, or record in the thread why it does not apply.

## Available tools (97)

Grouped by area; `docs/TOOLS.md` has the argument-level description of each tool and
`src/fusion360_mcp/tools.py` is the schema. A name not in this table is not a tool:
list_tools returns exactly these, and the add-in dispatches on the same strings.

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

Success is `ok: true` plus the tool's own fields and, on mutations, `deltas`
(`body_count_*`, `mass_g_*`, `bbox_before`/`bbox_after`). Failure is data, never an
exception: `ok: false`, `error_kind`, `error_message`, `hints`, `traceback`.

`error_kind` is a stable tag to branch on — `PROFILE_NOT_CLOSED`, `SKETCH_NOT_FOUND`,
`BODY_NOT_FOUND`, `SELF_INTERSECTION`, `REGEN_FAILED`, `BOOLEAN_NO_OP`, `AXIS_OUT_OF_PLANE`,
`INVALID_INPUT`, `NO_ACTIVE_DESIGN`, `DESIGN_TYPE_MISMATCH`, `NOT_ENTITLED`, `TIMEOUT`,
`UNKNOWN_COMMAND`, `UNKNOWN`. `NOT_ENTITLED` is Fusion refusing the API for this account
(seen on `auto_constrain`: "not available since user is restricted") — not a parameter
problem, so use an approach that does not need that API.

Four measured behaviours, worth reading instead of guessing:

- **Sketch draw tools report where the geometry landed, not where you asked.** Measured
  on Fusion 2706: curve points are read in the sketch's _own_ frame, so a `z` is projected
  onto the sketch plane rather than added to its offset, and repeating the plane's
  `z_offset` doubles it. The result carries
  `model_center`/`model_origin`/`model_start`/`model_end`/`model_points` (cm, model space),
  plus `ignored_z` and a `note` when a non-zero `z` was discarded. To move geometry, move
  the plane: `create_sketch(z_offset=...)`.
- **`revolve`'s axis is model space and must be coplanar with the profile.** Measured on
  Fusion 2706.1.17: `axis_origin_*` and `axis_direction_*` are model-space centimetres,
  a direction is normalised so its magnitude does not matter, and an axis leaving the
  sketch plane is refused as `AXIS_OUT_OF_PLANE`. Read
  `axis_model_start`/`axis_model_end` to confirm where it ran; an origin off the plane
  also carries `axis_snapped_to_sketch_plane: true`.
- **On `extrude`/`revolve`/`sweep`/`loft`, a `cut`, `join` or `intersect` hits every body
  the profile reaches — name `target_body` unless that is what you want.** Left out, the
  choice is Fusion's own inference (`participantBodies` empty); `target_body` sets that
  property and copies nothing. Measured on Fusion 2706: a loft whose sections spanned the
  seam between two touching blocks cut **both**. A body that does not exist is
  `BODY_NOT_FOUND`; naming one with `operation="new_body"` is `INVALID_INPUT`, since a
  new body is the feature's output, and a mistyped `operation` is refused before any of
  that — it invalidates the whole call.
- **`undo` steps the timeline back and says whether it could verify that.** Measured on
  Fusion 2706: on a parametric design the marker moves back one step synchronously and the
  reply is `{undone: true, verified: true, marker_position: n, timeline_count: m}` — the
  feature is suppressed, not deleted, so `timeline_count` does not drop. `{undone: false,
  verified: true, reason: ...}` means nothing was left to undo. Direct designs have no
  timeline, so the undo is asynchronous: `{undone: "issued", verified: false}`, to be
  confirmed with `get_scene_info`.

Read the deltas before rendering. `body_count_delta: 0, mass_g_delta: 0` means the
operation did nothing — check interference before retrying; with `keep_tool=True` the body
count does not drop even when the cut worked, so read `mass_g_delta`. `render_view` costs
200KB–2MB of base64, so render at a checkpoint rather than after every mutation: deltas
say whether a feature did _something_, a render whether it did the _right_ thing.

## MCP protocol features

- **Tool annotations** — `readOnlyHint`, `destructiveHint`, `idempotentHint` on every tool.
  Untrusted behavioural hints, not authorization. See the
  [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).
- **Resources** — `fusion360://status`, `fusion360://design`, `fusion360://parameters`
- **Resource templates** — `fusion360://body/{name}`, `fusion360://component/{name}`
- **Prompts** — `create-box`, `model-threaded-bolt`, `sheet-metal-enclosure`
- **Structured errors** — `isError=True` when the add-in reports a failure, carrying
  `error_kind`, `hints` and a traceback so an agent can branch on the failure mode.
- **Mock mode** — `--mode mock` returns test data without Fusion running

## Important constraints

- **One operation per tool call.** Fusion's API is not thread-safe and complex scripts
  crash the add-in.
- **No loops inside execute_code** — three similar features are three tool calls.
- **Keep execute_code under ~15 lines.** Prefer the dedicated tools.
- **Units are centimetres** — Fusion's internal API, not millimetres.
- **30-second timeout.** A slower command returns a timeout error.
- **body_name preferred over body_index**, so a lookup survives a rebuild.
- **Verify after each step** with `get_scene_info` or `get_object_info`.
- **Name everything** so later steps can reference it reliably.

## Troubleshooting

- "Not connected" means the add-in is not running: Fusion → Shift+S → Add-Ins → Run.
- A timeout means the main thread is blocked (modal dialog, heavy computation).
- If a merge looks live but Fusion behaves as before, the add-in is running the class it
  loaded at start-up: `uv run python scripts/reload_addin.py` reloads it and then proves
  the running class answers exactly the methods the command modules declare (see
  `docs/TESTING.md`).
- After any error, call `get_scene_info` to check whether the operation partially applied.
- Logs are written to `~/fusion360mcp.log` by the add-in.
