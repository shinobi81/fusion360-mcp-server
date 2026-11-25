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
| `create_construction_axis("perpendicular_at_point")` | handed a `ConstructionPlane` to a `BRepFace` parameter; refused and named the missing argument until #149 made it build | fixed (#131), built (#149) |
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
2. ~~**Retag the rules that already carry a kind**~~ - **closed (#150).** The work above
   changed the tag of the 88 with none; a rule that already answered with a kind kept
   it, even where the new taxonomy disagreed.

   **The five that disagreed answer the taxonomy now**, and the two review rounds found
   four of them - the item named two:

   - the CAM `setup/operation not found` rule -> `NAME_NOT_FOUND`;
   - `no faces matched` -> `GEOMETRY_UNSUPPORTED`, and its twin `no edges matched
     selection` with it, which the first pass left behind: a domed body answered
     `INVALID_INPUT` for `fillet(edge_selection="top")` and `GEOMETRY_UNSUPPORTED` for
     `shell(face_selection="top")` - the same selector mechanism, the same fault;
   - `has no edges to select from|has no edges that can be rounded` ->
     `GEOMETRY_UNSUPPORTED`, because `_select_edges` already typed the *identical*
     absence that way when it was reached through `points=`; the route taken decided
     the answer;
   - the `no usable parameter range` table rule, whose only raise site was already a
     typed `GEOMETRY_UNSUPPORTED` `Refusal` - the table contradicted production from a
     branch nothing reaches. A test had hidden that for a year: it classified the
     add-on's `Refusal` with the *package mirror's* `classify`, two distinct classes,
     so the `isinstance` check missed and the message was re-matched by regex into
     `INVALID_INPUT`. `tests/test_addon_edge_selection.py` now calls
     `addon_hints.classify`, and asserts the kind production actually answers.

   No message and no hint moved: the tag is the only thing a client sees differently,
   which is why the item asked for its own release note rather than a ride-along. Pins
   flipped or added in five files - `tests/test_feedback.py`,
   `tests/test_addon_face_selection.py`, `tests/test_addon_feature_edits.py`,
   `tests/test_addon_edge_selection.py`, `tests/test_addon_cam.py` - and one docstring's
   reasoning went with them (it argued for `INVALID_INPUT` on the grounds that the body
   was found and the *selector* did not apply; the tie-break is that the selector was
   applied correctly and the body has no such face, which is geometry, not a
   parameter).

   **The remaining judgement calls, named one by one so the boundary is a decision.**
   The criterion is AGENTS.md's: `GEOMETRY_UNSUPPORTED` means "pick a different face or
   edge; the body does not have that geometry". These stay `INVALID_INPUT` for reasons
   rather than inertia:

   - `geometry's … axis is zero-length` - a degenerate face wants a different face, in
     the taxonomy's own words; it is deferred because a joint-geometry refusal wants
     its own evidence and its own release-note line, not a fifth ride-along tag.
   - `not cylindrical` and `invalid free edge` - the entity exists and lacks a
     property, so the argument/geometry line is genuinely ambiguous.
   - `no edge within … cm of`, `equally close to edges`, and the index rules - the
     point or the index was wrong, which is an unusable argument.
   - `no intersecting target body|NO_TARGET_SWEEP_BODY` - the fix is moving the
     profile, again an argument.

   The `NAME_NOT_FOUND` tag ends an asymmetry the item recorded rather than lost:
   `cam_generate_toolpath(operation_name=…)` raises its own typed `NAME_NOT_FOUND` for
   a search that finds nothing, while the lookup rule answered `INVALID_INPUT` for the
   same fault. One fault, one kind, whichever command met it - pinned by
   `test_a_missing_cam_name_answers_one_kind_whichever_way_it_is_raised`.
   `InternalValidationError` had already retagged to `FUSION_REFUSED` on the same
   grounds (measured on Fusion 2706.1.17: `2 : InternalValidationError …`).
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

4. ~~`create_construction_axis("perpendicular_at_point")` refuses by design~~ -
   **closed (#149).** It needed a `BRepFace`, and the tool had no argument that could
   supply one: the method was advertised in the schema and refused by a rule, so it was
   one of two enum values a caller could send and never satisfy (`create_construction_
   plane`'s `tangent` still is). The tool takes
   `face_index` (with `body_name`) now, and the axis is built through
   `setByPerpendicularAtPoint(face, point)`, whose two arguments are the stub's.

   The refusal moved with it: instead of a blanket refusal, the rule names the
   arguments that are missing (`body_name`, `face_index`, `point_one`) from the
   parameters alone, so mock mode refuses the same call with the same sentence. A face
   index is judged against the body's face count before the call, so a wrong one names
   the range rather than raising out of the API with no advice - and `list_faces` is
   where a caller gets the indices.

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

   Key *presence* is the wrong thing to police on the way in, and this was measured
   rather than assumed: across Fusion's own 15 sample libraries (807 tools), 257 carry no
   `holder`, 75 no `geometry` and 72 no `start-values` preset. Requiring those blocks
   would refuse tools Fusion ships, so `_tool_json_shape_refusal` stays structural (a
   string, valid JSON, one non-empty object) and the advice points at `tool_diameter`,
   whose builder is the shape measured to work.

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

7. ~~No tool enumerates a body's faces~~ - **closed (#147).** `get_object_info` answered
   `faces_count`/`edges_count`/`vertices_count` and a bounding box; `list_edges` had
   existed all along and the face equivalent did not, so the indices `face_indices`
   takes could only be learned through `execute_code` (`body.faces.item(i)`) - and a
   wrong-but-in-range index was accepted silently. `list_faces` now reports, per face,
   its index, `surface_type`, planarity, area and centroid, plus the outward normal on a
   planar face; it keeps `list_edges`' contract (`count` is the real total, `truncated`
   says whether `limit` clipped the list).

   Two measurements from 2706.1.17 shaped the reply. The planar test is Fusion's own
   `SurfaceTypes.PlaneSurfaceType` member, not an integer copied from it. And
   **`geometry.normal` is not the outward normal**: with a centred box, the bottom face
   and all four sides report the surface normal with `isParamReversed` true, so the raw
   property gives `+Z` for a face that points down and a box's top and bottom claim one
   direction - the tool negates where the flag is set, and the six faces then report six
   distinct outward normals. The hints that sent a caller to `execute_code` for a face
   selection it could supply (`hints.py` x4, `handler_assembly`, `handler_cam`, plus the
   descriptions of `add_joint` and `cam_create_operation.face_indices`) name the tool
   now; the two that remain are for tools with no face-index argument at all, where
   `list_faces` has nowhere to send the indices.

8. ~~Mock's CAM replies differ from the handlers' key names~~ - **closed (#148).** The
   divergence was real and caller-facing: mock answered `{setup_name, operation_name,
   strategy}` where the handler answers `{name, setup, strategy}`, `{setup_name,
   body_name, operation_type, stock_mode}` where the handler answers `{name, body,
   operation_type, stock_applied}`, and `{setup_name, operation_name, generated,
   toolpath_count}` where the handler answers `{generated, scope, setup, operation}`.
   `toolpath_count` was never a handler key at all. The same defect ran through four more
   commands the item had not named: `cam_post_process` (`output_file`/`output_units` vs
   `output_folder`/`units`), `cam_get_operation_info` (`operation_name`/`strategy`/
   `tool_diameter` vs `name`/`is_valid`/`tool`/`parameters`), `cam_list_operations`
   (`setup_name`, a `strategy` per operation) and `cam_list_setups` (no `count`, no
   `is_valid`). An agent that rehearsed any of those keys got a `KeyError` against Fusion
   - after the expensive half of a sequence had already run.

   Mock now answers the handlers' keys and values across all seven commands:
   `parameters_applied` under Fusion's own parameter names (`maximumStepdown`,
   `tool_feedCutting`, `tool_coolant`, ...), `stock_applied.stock_mode` with Fusion's
   *id* rather than the caller's name, `stock_applied`'s three offsets under
   `job_stockOffset*`, `generated` plus `scope`, and the handler's shapes for the four
   list/info commands.

   The guard is a comparison of the two modes to each other - `test_mock_and_the_handler_
   answer_the_same_*` in `tests/test_addon_cam.py`, one per command - rather than each to
   a literal, so a **top-level** key added to one side alone fails the suite. Nested keys
   are covered where they are compared as well: `parameters_applied` against the
   parameter names the handler actually wrote, and `stock_applied` value-for-value.

   Deliberately still divergent, and recorded as a decision rather than left to be
   rediscovered: mock cannot model a parameter Fusion *refuses* (`parameters_failed`), and
   it cannot model the tool description Fusion normalises, so those stay placeholders.
9. ~~`cam_create_setup`'s `stock_mode` vocabulary does not match the handler's map~~
   - **closed, and measured.** The mismatch was real: the schema advertised
   `relative_box`/`fixed_box`/`from_body`, the handler mapped five names - three of
   them never offered by the schema - and an unmapped value was passed through
   verbatim.

   Measured on 2706.1.17 by writing `job_stockMode` on a live setup, one candidate at a
   time: `default`, `fixedbox`, `relativecylinder`, `fixedcylinder` and `solid` are
   accepted and read back as themselves, while `from_body` - the value the schema
   advertised - and a nonsense string (`bogus`) are both refused with
   `3 : Invalid enumeration value.` Two refusals do not prove *every* other string is
   refused, and this says only what was probed. So `from_body` never worked, three
   working ids were unreachable, and the failure surfaced as `stock_failed` rather than
   as a refusal.

   One pairing rests on fused evidence rather than on this probe: `relative_box` ->
   `default`. The write proves Fusion accepts `default` and returns it; that `default`
   *is* the relative-size box comes from the handler's older note about Fusion 2705, and
   the parameter exposes only `title: 'Mode'` - no human label - so 2706 could not
   confirm it without comparing stock geometry. The other four pairings are
   self-describing.

   What shipped: one table, `rules.CAM_STOCK_MODES`, is now the only source - the schema
   enum is `list(CAM_STOCK_MODES)` (pinned by reading the source, since equal values
   cannot show where they came from), the handler indexes the table its own refusal just
   validated, and `rules.cam_stock_mode_refusal` refuses an unknown name from the
   parameters alone, so `mock_command` and a direct-wire caller answer the same
   sentence, and nothing is created for a value Fusion would reject. That the two modes
   order their refusals alike is pinned by a call carrying both faults at once.

   An **MCP** caller never reaches that rule: the schema gate refuses the value first,
   with its own sentence, exactly as it does for `set_design_type` - so the migration
   advice for
   `from_body` reaches MCP clients through the schema description instead, and
   `test_schema_gate.py` pins the sentence such a caller actually gets. `from_body`
   is named in the refusal's hint as the old spelling of `from_solid`, and the schema's
   description says so too. The first tests to name `stock_mode` at all cover the five
   ids, the refusal, and that the setup does not exist when the vocabulary is refused.

Settled, so a later session does not re-open them: the four call sites that pass a raw
`Point3D` where the headers say "a construction point, sketch point or vertex" are fine.
`setByThreePoints`, `setByTwoPoints` and `ScaleFeatures.createInput` all accept a
`Point3D` on 2706.1.17. The documentation is advice, not enforcement.

Not part of this: moving the 59 floor. Raising it to whatever the new figure becomes is
a number chasing its own measurement; the reason to write these tests is the refusals
and return values nobody has looked at. The floor moves afterwards only if that is what
someone decides to guard.
