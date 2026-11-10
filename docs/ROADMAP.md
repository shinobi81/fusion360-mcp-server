# Roadmap

What is likely to happen next, in the order it is likely to happen. This is not a promise
and it carries no dates: it exists so a reader can see where the project is going, and so
a known gap is visibly known rather than merely absent.

## 1. A stricter lint selection - done

`pyproject.toml` sets `select = ["E", "F", "I", "RUF", "B", "SIM"]`. The first four
were a linter configuration rather than a strict one: `B` (bugbear) reports constructs
that are almost always a mistake, and `SIM` (simplify) reports code that says at more
length what it could say at less. Both are in now, across all four linted trees (`src/`,
`tests/`, `fuzz/`, `addon/`), and the tree is clean with no `ignore`, no
`per-file-ignores` and no new `noqa`: a rule that is on everywhere either passes or gets
fixed.

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
against that rather than against CPython 3.14 alone: both reach for `contextlib`, stdlib
since 3.4, and neither changes the class of exception caught.

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

Three source reads stay, and none of them is a behavioural claim: `test_addon_sync.py`
compares `CommandHandler._COMMANDS` and `_MUTATION_COMMANDS` against `mock.py`'s tables,
`test_addon_joints.py` compares the joint tables against the schemas, and
`test_addon_sources.py` reads the add-in's tokens because both PEP 758 spellings parse
the same. Each is a property of the source rather than of running it.

Nothing else is queued behind this section; sections 1 and 2 are both closed.
