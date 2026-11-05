# Roadmap

What is likely to happen next, in the order it is likely to happen. This is not a promise
and it carries no dates: it exists so a reader - and the agent filling in the OpenSSF
questionnaire - can see where the project is going, and so a known gap is visibly known
rather than merely absent.

Nothing here is a criterion of its own; [BADGE.md](BADGE.md) is the map from criteria to
evidence, and only `warnings_strict` below comes from that map.

## 1. The OpenSSF Best Practices badge

- Register the project at <https://www.bestpractices.dev/> (GitHub OAuth) and answer the
  questionnaire from [BADGE.md](BADGE.md). Four MUST criteria there are answers only the
  maintainer has: `report_responses`, `vulnerability_report_response`,
  `know_secure_design`, `know_common_errors`.
- Widen the ruff selection in `pyproject.toml` beyond `E`, `F`, `I` - `warnings_strict`
  is SUGGESTED, so it does not block Passing, and it is the one gap in BADGE.md that is
  work in this repository rather than a questionnaire answer.
- Add the badge markup to `README.md` once a project id exists - that is the only
  step left outside the code. The Scorecard `Signed-Releases` asset is done:
  `release.yml` attaches the attestation bundle as `provenance.sigstore.json`, the
  name the check reads; the score reaches 8/10 once five releases carry it.

## 2. The test refactor

The add-in's tests still reach the Fusion API through `ast` guards in places, which assert
on source text rather than on behaviour. Three parcels, in order, each one PR:

1. **`tests/test_addon_joints.py`** - convert the behavioural guards (argument counts,
   motion per `joint_type`, as-built joints, "never calls `computeAll`") and keep the data
   tables static. Needs the fake runtime to gain `JointGeometry.createByPoint`,
   `JointInput`'s per-motion methods, `root.joints.add`,
   `createAsBuiltJointInput`, a driveable `joint.jointMotion`, and a `computeAll` counter.
2. **The `create_hole` call-site guards** in `tests/test_hole_geometry.py`; the pure-module
   tests there are already direct and stay as they are. Needs faces carrying
   `maxPoint`/`minPoint`/`pointOnFace`, a sketch created on a face, `sketchPoints.add`,
   `HoleFeatures.createSimpleInput` and `participantBodies`.
3. **Make the add-in importable.** One adapter (e.g. `addon/server/fusion_api.py`) so
   `command_handler` resolves `adsk` through a single import site, then add
   `addon/server` to `[tool.coverage.run] source` and re-base the coverage floor - the
   total will drop a long way. This is the only parcel that can break the daily workflow,
   so it does not merge on CI alone: the add-in has to be loaded in Fusion and exercised
   by hand first.

`tests/fakes/` is over its soft size cap in exchange for retiring the guards wholesale;
the two conversion parcels above are deliberately not free, and a file that keeps its
guards says why in its docstring.
