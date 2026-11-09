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
- Widen the ruff selection in `pyproject.toml` beyond `E`, `F`, `I`, `RUF` - `warnings_strict`
  is SUGGESTED, so it does not block Passing, and it is the one gap in BADGE.md that is
  work in this repository rather than a questionnaire answer.
- Add the badge markup to `README.md` once a project id exists - that is the only
  step left outside the code. The Scorecard `Signed-Releases` asset is done:
  `release.yml` attaches the attestation bundle as `provenance.sigstore.json`, the
  name the check reads; the score reaches 8/10 once five releases carry it.

## 2. The test refactor - done

The add-in's tests used to reach the Fusion API through `ast` guards, which assert on
source text rather than on behaviour. Three parcels, one PR each, all merged:

1. **`tests/test_addon_joints.py`** - *done (#63).* Fifteen of its sixteen tests parsed
   `command_handler.py`; the eight behavioural ones now run the handler against fakes that
   model the seven motion setters, a driveable value per joint type and `asBuiltJoints`.
   The nine tests left are table-against-schema checks, which no test can observe any
   other way.
2. **The `create_hole` call-site guards** - *done (#65).* The five guards in
   `tests/test_hole_geometry.py` are replaced by six tests in `tests/test_addon_hole.py`,
   which drive the handler against a hole-feature model: a planar face carrying its own
   surface, a sketch created on that face, `sketchPoints.add`,
   `HoleFeatures.createSimpleInput` and `participantBodies`. The sixth pins the
   planar-face skip the scans never covered; the pure-module tests stay as they are.
3. **Make the add-in importable.** - *done (#68).* One adapter
   (`addon/server/fusion_api.py`) resolves `adsk` lazily, so nothing under `addon/` imports
   it at module scope; `addon/server` is in `[tool.coverage.run] source` and the floor is
   re-based from the measurement (59 combined, with `src/` keeping its own 95 gate in CI).
   The new code is exercised in Fusion 2706 before merge - the adapter's four names and
   the bridge's handler class, driven against the real API; the reload-and-drive through
   the socket is done immediately after, since the add-in is registered against `main`.

`tests/fakes/` is over its soft size cap in exchange for retiring the guards wholesale;
the three parcels above are deliberately not free, and a file that keeps its guards says
why in its docstring. Two source readers stay on purpose, and neither is a behavioural
claim: `test_addon_sync.py`'s table-against-schema check, which is a property of the
source rather than of running it, and `test_addon_joints.py`'s `_class_assign`, which
reads the two `CommandHandler` tables the tests compare against the schemas.

Nothing else is queued behind this section. What is left is section 1, and there the
badge markup is the only step outside a form.
