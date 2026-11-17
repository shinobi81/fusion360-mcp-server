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

**Measured on 0.8.5, before the work:**

| Module | Then | Now | What the missing lines reached |
| --- | --- | --- | --- |
| `handler_cam` | 17% | 17% | setups, operations, toolpaths, post-processing |
| `handler_surface` | 22% | 69% | patch, stitch, thicken, ruled, trim, sheet metal |
| `handler_export` | 23% | 23% | STL/STEP/F3D, view sheets, the generic `export` |
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
a fake must declare Fusion's arity, not the handler's - turned up seven commands that
could never have worked:

| Command | What was wrong | State |
| --- | --- | --- |
| `unfold` | `createInput(bends, stationary)`; the shipped signature takes the stationary face alone and the bends go on the input | fixed (#130) |
| `flat_pattern` | `root.features.flatPatternFeatures` does not exist; a component creates a flat pattern | fixed (#130) |
| `thicken_surface` | `isSymmetric` and `isChainSelection` were swapped, so `direction` never made anything symmetric | fixed (#130) |
| `scale_body` | per-axis branch passed five arguments to a three-argument `createInput`; non-uniform is `setToNonUniform` | fixed (#131) |
| `create_construction_axis("perpendicular_at_point")` | handed a `ConstructionPlane` to a `BRepFace` parameter; now refuses and names the missing argument | fixed (#131) |
| `patch_surface` | wrote a property Fusion does not ship, so `continuity` was a silent no-op | fixed to `groupContinuity`; the argument is inert for sketch curves until the tool takes edges (#131) |
| `create_flange`, `create_bend`, `trim_surface` | `FlangeFeatures` has no `createInput`; there is no `bendFeatures` at all; `TrimFeatures.createInput` takes the tool alone | **fixed and proven live (#134)** |

### What is left

Zero invented names remain, and that is now checked rather than hoped for:
`scripts/check_fusion_api.py` walks every `adsk.<dotted.path>` under `addon/server`
and asks the running Fusion whether it exists - 193 references, none missing on
2706.1.17 (#135).

1. **`hints.py` rules** for the refusals that still classify `UNKNOWN` — its own PR, with
   `scripts/sync_mirrors.py`, because the table is canonical and mirrored.
2. **`handler_cam` (17%) and `handler_export` (23%)** remain where they were: a CAM
   `Product` and an `exportManager`/`viewport` are the two largest fakes in the tree, and
   the behaviour they would cover is the behaviour a fake cannot settle - a view sheet
   either renders or it does not. Those belong in a Fusion session, not in a fake.
3. **`create_construction_axis("perpendicular_at_point")`** refuses by design: it
   needs a `BRepFace`, which the tool has no argument for. Making it work means adding a
   face parameter, a schema decision rather than a repair.

Settled, so a later session does not re-open them: the four call sites that pass a raw
`Point3D` where the headers say "a construction point, sketch point or vertex" are fine.
`setByThreePoints`, `setByTwoPoints` and `ScaleFeatures.createInput` all accept a
`Point3D` on 2706.1.17. The documentation is advice, not enforcement.

Not part of this: moving the 59 floor. Raising it to whatever the new figure becomes is
a number chasing its own measurement; the reason to write these tests is the refusals
and return values nobody has looked at. The floor moves afterwards only if that is what
someone decides to guard.
