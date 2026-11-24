# Roadmap

What is likely to happen next, in the order it is likely to happen. This is not a promise
and it carries no dates: it exists so a reader can see where the project is going, and so
a known gap is visibly known rather than merely absent.

## 1. A stricter lint selection - done

`pyproject.toml` sets `select = ["E", "F", "I", "RUF", "B", "SIM"]`. The first four
were a linter configuration rather than a strict one: `B` (bugbear) reports constructs
that are almost always a mistake, and `SIM` (simplify) reports code that says at more
length what it could say at less. Both are in now, across the four trees the change
touched (`src/`, `tests/`, `fuzz/`, `addon/`), and the tree is clean with no `ignore`,
no `per-file-ignores` and no new `noqa`: a rule that is on everywhere either passes or
gets fixed. `scripts/` joined both gates in a later change, and stays: the add-in
installer and the artifact check are exercised by tests, `check_review_threads.py` by the
`threads` CI job, and `smoke_envelope.py` is a hand-run helper.

The first pass was 16 findings, so it went in as one change rather than one per rule
family. The dispositions are the whole story of it:

| Rule | n | Disposition |
| --- | --- | --- |
| `B010` | 5 | plain attribute assignment instead of `setattr` |
| `B905` | 3 | `zip(..., strict=True)` |
| `B018` | 3 | `_ = <expr>`: the access is the assertion, inside `pytest.raises` |
| `SIM105` | 2 | `with contextlib.suppress(Exception):` |
| `B904` | 1 | `raise ... from None`, so the message is not chained to the parser's |
| `SIM102` | 1 | one condition instead of two nested `if`s |
| `B033` | 1 | a stale duplicate set member |

`addon/` executes on Fusion's own interpreter, so the two rewrites there were judged
against that rather than against CPython 3.14 alone: both use the `contextlib.suppress`
each module already imported, and neither changes the class of exception caught.

Nothing else about the configuration changed. `line-length = 88` matches the prose gates,
and `target-version` stays inferred from `requires-python`, so the support window is
stated once.

## 2. The test refactor - done

The add-in's tests used to reach the Fusion API through `ast` guards, which assert on
source text rather than on behaviour. Three parcels, one PR each, all merged:

1. **`tests/test_addon_joints.py`** - *done (#63).* Fifteen of its tests parsed the
   handler's source. Eight are gone: the behavioural ones now drive the handler from
   `test_addon_joint_values.py` and `test_addon_joint_frame.py`, the `createByPoint`
   arity is pinned by a fake that declares Fusion's real one-argument signature, and the
   two as-built scans were already covered by #61. The nine left read tables: eight that
   survived, plus the `required` schema read the review restored - because a table is
   data, and a table asserting itself proves nothing.
2. **The `create_hole` call-site guards** - *done (#65).* The five guards in
   `tests/test_hole_geometry.py` are replaced by six tests in `tests/test_addon_hole.py`,
   which drive the handler against a hole-feature model: a planar face carrying its own
   surface, a sketch created on that face, `sketchPoints.add`,
   `HoleFeatures.createSimpleInput` and `participantBodies`. The sixth pins the
   planar-face skip the scans never covered; the pure-module tests there stay as they
   are.
3. **Make the add-in importable.** - *done (#68).* One adapter
   (`addon/server/fusion_api.py`) resolves `adsk` lazily, so nothing under `addon/` imports
   it at module scope; `addon/server` is in `[tool.coverage.run] source` and the floor is
   re-based from the measurement (59 combined, with `src/` keeping its own 95 gate in CI).
   The new code is exercised in Fusion 2706 before merge - the adapter's four names and
   the bridge's handler class, driven against the real API; the reload-and-drive through
   the socket is done immediately after, since the add-in is registered against `main`.

`tests/fakes/` is over its soft size cap in exchange for retiring the guards wholesale;
the two conversion parcels above are deliberately not free, and a file that keeps its
guards says why in its docstring.

Three table reads stay, and none of them is a behavioural claim: `test_addon_sync.py`
compares `CommandHandler._COMMAND_NAMES` and the canonical `MUTATION_COMMANDS` against
`tools.py`'s names and each other, `test_addon_joints.py` compares the joint tables against
the schemas (through the imported `CommandHandler`, since the add-in became importable),
and `test_addon_sources.py` reads the add-in's tokens because both PEP 758 spellings parse
the same. Each asserts on data rather than on behaviour.

Nothing else is queued behind this section; sections 1 and 2 are both closed.

## 3. The add-in's untested half - in progress, and the audit paid for itself

The combined coverage floor is 59 and `addon/server` sat at 60, so the floor was not the
problem the number described: it was set low on purpose, because the add-in's CAM, view
sheet and viewport families only run inside Fusion. The cost was that a large share of the
add-in had never been executed by anything, and a module nobody runs is a module where a
renamed API call sits unnoticed.

**Measured on 0.8.5, then after the coverage parcels:**

| Module | Then | After the coverage parcels | What the missing lines reached |
| --- | --- | --- | --- |
| `handler_cam` | 17% | 17% | setups, operations, toolpaths, post-processing |
| `handler_surface` | 22% | 69% | patch, stitch, thicken, ruled, trim, sheet metal |
| `handler_export` | 23% | 23% | view sheets, `render_view` past its refusals, `import_mesh`'s success path, `export`'s `stl` branch |
| `handler_scene` | 41% | 92% | scene description, measurement, bounding box, object info |
| `socket_server` | 48% | 100% | framing, malformed input, timeouts, disconnects |
| `handler_assembly` | 62% | 90% | joints, components, rigid groups |
| `handler_features` | 81% | 98% | features, and the eight edit commands |
| `handler_primitives` | 71% | 96% | the direct primitives and the parametric box |
| `addon/server` total | 60% | 80% | |

Suite 1245 -> 1379 passing tests; the combined figure 69.97% -> 85.22%. The 59 floor did
not move, which was the point.

### What the audit found

The tests were the cheap part. Reading each handler against the shipped binding - because
a fake must declare Fusion's arity, not the handler's - turned up nine commands that never
worked, across the seven rows below:

| Command | What was wrong | State |
| --- | --- | --- |
| `unfold` | `createInput(bends, stationary)`; the shipped signature takes the stationary face alone and the bends go on the input | fixed (#130) |
| `flat_pattern` | `root.features.flatPatternFeatures` does not exist; a component creates a flat pattern | fixed (#130) |
| `thicken_surface` | `isSymmetric` and `isChainSelection` were swapped, so `direction` never made anything symmetric | fixed (#130) |
| `scale_body` | per-axis branch passed five arguments to a three-argument `createInput`; non-uniform is `setToNonUniform` | fixed (#131) |
| `create_construction_axis("perpendicular_at_point")` | handed a `ConstructionPlane` to a `BRepFace` parameter; now refuses and names the missing argument | fixed (#131) |
| `patch_surface` | wrote a property Fusion does not ship, so `continuity` was a silent no-op | fixed to `groupContinuity`; the argument is inert for sketch curves until the tool takes edges (#131) |
| `create_flange`, `create_bend`, `trim_surface` | `FlangeFeatures` has no `createInput`; there is no `bendFeatures` at all; `TrimFeatures.createInput` takes the tool alone | **fixed and proven live (#134)** |

### What the refusal work found - done, on `typed-refusals`, not merged

The roadmap's first item here - `hints.py` rules for the refusals that classify
`UNKNOWN` - is done on the `typed-refusals` branch, which starts at `0bb4545`. The record
is here rather than in the design document, because `docs/superpowers/` is git-ignored
and the numbers are the durable half.

The roadmap asked for one rules table, and the measurement is what rejected that shape:
an AST walk of every `raise` in `addon/server` found **134** carrying a literal
message, and pushing each message through the real `classify()` gave the before column.

| | Before | After |
| --- | --- | --- |
| raises reaching a caller as `UNKNOWN` with no hints | **88** | **0** |
| typed `Refusal` sites | 11, all in `rules.py` | 74, in 11 modules |
| raises the walk cannot judge from source | 7 | 28, each pinned with its reason |

The suite was green over all 88, and that is the part worth keeping: `classify()` ran
**11 times** across 1393 tests, and every handler test asserted on the refusal it raised,
never on the envelope a caller receives.

Three instruments, chosen at the raise site by what the raiser can know - which is why a
table was the wrong answer, since a table can only read a string:

- **the schema gate** for what `tools.py` already declared and nothing read: 63 enum
  properties and 78 minimum/maximum bounds, enforced in `_send` so real and mock mode
  refuse alike before Fusion is touched. Roughly 20 of the 88 needed no new code - the
  constraint was written down and unenforced.
- **`rules.py`** for what the parameters alone decide: 20 validators, 18 site rows in
  `tests/test_rules.py` that compare the handler's refusal with mock mode's envelope
  sentence for sentence and hint for hint.
- **`Refusal` at the site** for what needs live state - an index against a real face count,
  a component with no planar face. 47 of the 88.

The last 2 were existing rules whose pattern never matched the sentence the add-in
actually raised; the third pattern widened in the same commit was defensive, because the
live message already ended in `is not finite`. Six kinds came out of the work, chosen by
the caller's next move rather than by which API failed: `NAME_NOT_FOUND`,
`GEOMETRY_UNSUPPORTED`, `FUSION_REFUSED`, `WORKSPACE_UNAVAILABLE`, `SCRIPT_ERROR`,
`INTERNAL_ERROR`. `INVALID_INPUT` stays for an unusable parameter, and
`BODY_NOT_FOUND`/`SKETCH_NOT_FOUND` stay although `NAME_NOT_FOUND` covers them,
because a client may already branch on them.

`tests/test_addon_refusals.py` makes it a ratchet rather than a one-off audit. It
fails on a raise that would reach a caller `UNKNOWN`, on a baseline row that no longer
matches a site, and on any change to the 28 unjudgeable rows - a computed message, a
`Protocol` body, or a kind that comes from a `rules.py` validator call, each with its
reason written down. That count rose from 7 by design: the validators are what let mock
mode answer the same sentence, and a kind returned from a function is not readable in the
file that raises it.

### What is left

Zero invented names remain, and that is now checked rather than hoped for:
`scripts/check_fusion_api.py` walks every `adsk.<dotted.path>` under `addon/server`
and asks the running Fusion whether it exists - 190 references, none missing on
2706.1.17 (#135 and #142, which deleted three).

1. ~~The 0.9.0 release note is unwritten~~ - **written with the 0.9.0 tag**; the entry
   covers every PR below. For the next release, `CHANGELOG.md` cannot tell you: the file
   opens at the release being cut (`[0.9.0]` now) because the packaging guard fails an
   entry written ahead of the version, so entries are written once, at release. This
   entry covers the PRs merged since `v0.8.5` (`#125`-`#143`): the six new kinds, the
   schema gate, the refusals that moved from `UNKNOWN` to a kind, the
   `InternalValidationError` retag
   from `INVALID_INPUT` to `FUSION_REFUSED`, the gate's own sentences for the rows it
   answers, the three sheet-metal/surface repairs whose arguments were renamed
   (`#134`), and `#143`'s caller-visible schema change - `cam_create_operation`'s
   strategy enum replaced with ten measured names and two new arguments (`body_name`,
   `face_indices`).
2. **Retag the rules that already carry a kind** - deferred, and named here so the
   inconsistency reads as a decision rather than an oversight. The work above changed the
   tag of the 88 with none; a rule that already answered with a kind kept it, even where
   the new taxonomy disagrees: the CAM `setup/operation not found` rule is still
   `INVALID_INPUT`, and so is `no faces matched`. Those tags are what a client may
   already branch on, so changing them is a client-visible change with its own evidence
   and release note, not a ride-along. One new path is deliberately asymmetric:
   `cam_generate_toolpath(operation_name=…)` answers `NAME_NOT_FOUND`, because its hint
   names the list to enumerate, while the CAM `setup/operation not found` rule still
   answers `INVALID_INPUT`; the two coexist because retagging that rule is the deferred
   change above, and the new search raises its own typed refusal rather than that
   message. One retag did ship with this work, because the rule's own hint already said
   so: `InternalValidationError` used to answer `INVALID_INPUT` and now reports
   `FUSION_REFUSED` (measured on Fusion 2706.1.17: `2 : InternalValidationError …`),
   pinned by `test_an_internal_validation_error_is_a_fusion_refusal` in
   `tests/test_feedback.py`.
3. **`handler_cam` (65%) and `handler_export` (44%)** - measured after #141 - are the
   two modules the coverage parcels above left where they were. The refusal work
   drove their refusal paths (that is the 23% -> 44% on `handler_export`: its refusals
   are what `tests/test_addon_export.py` exercises), and #141's fake
   `PostProcessInput` reached the post-process lines no test could enter. What is left
   is four things: the view sheet, `render_view`'s successful capture (both its tests
   are refusals - no viewport, and `saveAsImageFile` answering false),
   `import_mesh`'s success path (its tests are the missing file and the empty mesh),
   and `export`'s `stl` dispatch (every `export` test names step or f3d, so the branch
   is unreachable from the suite). Which of them needs Fusion is the reverse of what
   it looks like: `render_view`'s capture needs only a `saveAsImageFile` that writes
   bytes - the lines after it are `tempfile`, a read and a base64 encode - while
   `export_view_sheet` needs `adsk.core.CameraTypes`, which the fake runtime does not
   declare, plus a camera carrying `eye`/`target`/`upVector`. Only the render itself
   has to be confirmed in Fusion. `handler_cam`'s remainder is no longer that kind at
   all: an operation is a `SimpleNamespace` with the fields the command reads, which
   is what #141's read-path tests use.

4. **`create_construction_axis("perpendicular_at_point")`** refuses by design: it
   needs a `BRepFace`, which the tool has no argument for. Making it work means adding a
   face parameter, a schema decision rather than a repair.
5. ~~`_find_operation` still picks the first same-named operation~~ - **closed (#141)**.
   The first-match scan resolved `operation_name` inside one setup for
   `cam_post_process` and `cam_get_operation_info`, so a name the setup held twice
   picked the first: G-code for an operation the caller had not named, and a
   description of the wrong one. `_find_operation` now refuses with the sentence
   `cam_generate_toolpath` already raised, from one helper, so all three commands
   answer alike. The evidence is the same as the generate path's, and as thin: Fusion
   *suffixes* a rename that would duplicate a name inside a setup (`Face11` renamed to
   `Face10` produced `Face101`, measured on 2706.1.17), so the shape needs the create
   path and has no live envelope. The tests for `cam_post_process` and
   `cam_get_operation_info`, plus the generate path's own, are the proof that all three
   treat it one way; nothing proves Fusion can produce it.

6. ~~A CAM operation still cannot generate, because it has no tool~~ - **closed.** #143
   fixed the two causes in front of it (ten invented strategy names, and a geometry
   parameter left empty on every strategy), so `cam_create_operation` created an
   operation with its faces selected; generation then answered `hasError == True,
   error == "Toolpath requires tool to be selected."` because the operation had no tool.

   The measurement that closed it, on Fusion 2706.1.17: `Tool.createFromJson` accepts a
   **complete** tool object - every key a shipped library entry carries, including
   `holder` and one `start-values.presets` entry - and `Operation.tool` takes the result.
   Fusion registers it in `documentToolLibrary` itself (`count` 0 → 1), so no explicit
   `add` is needed, and `generateToolpath` then finishes: `has_toolpath: true`,
   `isToolpathValid: true`, with the parameters reporting `tool_diameter: 6.`,
   `tool_unit: 'millimeters'`, `tool_numberOfFlutes: 2`, `tool_vendor:
   'fusion360-mcp-server'`.

   **A partial object is not refused, it crashes Fusion.** An entry with no `holder` and
   an empty `start-values` neither raised nor refused: Fusion 360 exited during
   `createFromJson`, taking the document's unsaved state with it. That is why
   `addon/server/cam_tool.py` emits the whole shape from one function instead of patching
   the keys a caller passed, and why its test pins the key sets by name.

   What shipped: `cam_create_operation` takes `tool_diameter` (cm, converted to the
   library's millimetres), `tool_length`, `tool_flutes` and `tool_number`, or `tool_json`
   for a complete object it uses verbatim; a reply without a tool says generation will
   fail rather than leaving it to the next call. Only the flat end mill is measured end
   to end. `_wait_future` also reports the operation's own error now: a generation Fusion
   refuses sets `hasError` at once while the future never completes, so the 25 s bound
   used to answer `TIMEOUT` for a cause already named.

   Still open from this thread: `tool_number` cannot select an existing library tool -
   `DocumentToolLibrary` exposes `item`/`createQuery`/`toolsBySetupOrFolder` and no
   by-number lookup has been measured, so a number on its own is refused rather than
   silently ignored.

7. **No tool enumerates a body's faces.** `get_object_info` answers
   `faces_count`/`edges_count`/`vertices_count` and a bounding box; `list_edges` exists
   and a face equivalent does not. #143's `face_indices` therefore has to be discovered
   through `execute_code` (`body.faces.item(i)`), which is what its hints now say. A
   `list_faces` tool is a schema decision, not a repair, and the wrong-but-in-range index
   it would prevent is accepted silently today. `Operation.deleteMe()` - the recovery
   path's one call the name audit cannot see (`op` is a local) - was verified by hand on
   2706.1.17: a scratch `face` operation was created, `deleteMe()` answered `True`, and
   `setup.operations.count` returned to its previous value.
8. **Mock's `cam_create_operation` and `cam_create_setup` replies still differ from the
   handlers' key names.** `cam_create_operation`: handler `{name, setup, strategy}` plus
   `parameters_applied`/`parameters_failed`/`warning` (a live success carries
   `parameters_applied` whenever the strategy exposes `tool_coolant`), mock
   `{setup_name, operation_name, strategy}` plus the same `geometry` echo the handler
   returns (`{parameter, face_indices}`).
   `cam_create_setup`: handler `{name, body, operation_type, stock_applied|stock_failed,
   warning}`, mock `{setup_name, body_name, operation_type, stock_mode}`. An agent that
   rehearses a key in mock mode then reads it against Fusion and gets a `KeyError`.
   Pre-existing and pinned by `tests/test_mock.py`; left as a decision rather than a
   ride-along on #143.

   Two things this section used to record are no longer true, both because the tool work
   closed them: the **fault ordering** now agrees (the tool sentence is judged from the
   parameters, so the handler answers it third - before `WORKSPACE_UNAVAILABLE` and the
   setup lookup - exactly as mock does), and the **`tool`/`tool_warning` keys agree**,
   including mock declining to invent a tool description it cannot read back. The
   remaining divergence is the key *names* above.

9. **`cam_create_setup`'s `stock_mode` vocabulary does not match the handler's map.**
   The schema advertises `relative_box`/`fixed_box`/`from_body`; `handler_cam.py` maps
   `relative_box`/`fixed_box`/`relative_cylinder`/`fixed_cylinder`/`from_solid` and
   passes an unmapped value through verbatim, so a schema-legal `from_body` reaches
   Fusion as `from_body` and is reported as `stock_failed`. Read from the two files on
   2026-11-23, not measured against Fusion; no test names `stock_mode` at all.

Settled, so a later session does not re-open them: the four call sites that pass a raw
`Point3D` where the headers say "a construction point, sketch point or vertex" are fine.
`setByThreePoints`, `setByTwoPoints` and `ScaleFeatures.createInput` all accept a
`Point3D` on 2706.1.17. The documentation is advice, not enforcement.

Not part of this: moving the 59 floor. Raising it to whatever the new figure becomes is
a number chasing its own measurement; the reason to write these tests is the refusals
and return values nobody has looked at. The floor moves afterwards only if that is what
someone decides to guard.
