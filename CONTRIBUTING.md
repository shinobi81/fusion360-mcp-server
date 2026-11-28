# Contributing

Thanks for helping. This file covers what you need to get a change merged; the deeper
architecture and tool conventions live in [AGENTS.md](AGENTS.md).

## What this project is

Two pieces that talk over TCP:

1. **MCP server** (`src/fusion360_mcp/`) — speaks the Model Context Protocol over stdio
   and forwards commands to Fusion as JSON.
2. **Fusion add-in** (`addon/`) — runs inside Fusion, executes commands on the main
   thread through a CustomEvent bridge.

A change usually touches both, plus a mock handler and tests.

## Getting set up

```bash
git clone https://github.com/shinobi81/fusion360-mcp-server
cd fusion360-mcp-server
uv sync --locked               # python deps into .venv; refuses a stale lock
uv run pytest -q               # suite runs without Fusion
uv run ruff check src/ tests/ fuzz/ addon/ scripts/  # what CI runs
uv run ruff format --check src/ tests/ fuzz/ scripts/  # what CI runs (addon/ is exempt)
uv run mypy src                # what CI runs; addon/ is excluded (adsk is unresolvable)
```

Optional, for live testing against Fusion:

1. Fusion → **Utilities → Add-Ins → Add** → point at `addon/Fusion360MCP.manifest`
2. Run it, then `uv run fusion360-mcp-server --mode socket`
3. `ping` should answer `pong`

**Windows note:** `uv run` rebuilds the package when `pyproject.toml` changes, and Windows
will not let it replace `.venv/Scripts/fusion360-mcp-server.exe` while a running MCP server
holds it (`os error 32`). Stop the server, or use `uv run --no-sync ...`.

## Making a change

`main` is protected: direct pushes and force-pushes are rejected, every change arrives as
a pull request, and merging requires **one approving review** (from a code owner for the
paths in [CODEOWNERS](.github/CODEOWNERS)), a green CI run, and resolved review threads.
As a contributor you fork the repo and open the PR from your fork.

**Unresolved review threads block the merge**, and that includes bot findings — CodeQL,
dependabot, any inline comment. Check before merging, don't assume:

```bash
python scripts/check_review_threads.py <pr>   # exit 0 = clear, 1 = threads open
```

The same script runs as the `threads` CI job. Resolving a thread means engineering an
answer, not silencing it: fix the finding, or reply explaining why it does not apply,
then resolve. The code owner's `--admin` merge bypasses the ruleset that enforces this,
so the check is a habit, not a guard rail.

```bash
git checkout -b fix/short-description    # or feat/, docs/, chore/, test/
# ... make the change, with tests ...
git push -u origin fix/short-description
```

Guidelines that actually get followed here:

- **One concern per PR.** A fix and a refactor in the same branch make review harder, and
  squash-merging hides nothing.
- **Test first when fixing a bug.** Write the failing test, watch it fail for the right
  reason, then fix it. Tests here assert on real behaviour (what the Fusion API is asked
  to do), not on mock internals.
- **Keep the mock in step.** Every tool has a handler in `src/fusion360_mcp/mock.py`;
  `tests/test_mock.py` fails if one is missing, and `tests/test_addon_sync.py` if the
  command list and `tools.py` drift apart.
- **Errors are data.** Return `{"ok": false, "error_kind": ..., "hints": [...]}`, don't
  raise through the bridge. New failure modes get a rule in `addon/server/hints.py` — the
  canonical table, since the add-in cannot import this package — then
  `uv run python scripts/sync_mirrors.py` regenerates `src/fusion360_mcp/hints.py`.
  `tests/test_addon_sync.py` fails while the generated copy is stale.
- **Units are centimetres.** Fusion's internal unit. Not millimetres.

## Commit messages

Conventional commits, scope optional but useful:

```text
fix(sketch): keep drawn curves in the sketch plane
feat(hints): classify entitlement refusals as NOT_ENTITLED
docs(readme): this is the maintained repo, not a fork
```

Explain *why* in the body when the change is not obvious, and include the measurement or
error that motivated it.

## Style

- Python: `ruff check` and `ruff format` (line length 88,
  rules `B`, `E`, `F`, `I`, `RUF`, `SIM`).
- Markdown: `npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"` — 88-column
  prose, tables exempt (see `.markdownlint-cli2.jsonc`).
- `addon/` is excluded from pyright/mypy on purpose: it reaches Fusion's `adsk` API
  through a lazy adapter, and `adsk` cannot be resolved outside Fusion. Don't add type
  ignores for it.
- Comments state the constraint or the measured fact, never the edit that introduced
  it.

## Releasing

### When to bump

A bump is classified from the **diff**, never counted by the number of closed issues. An
issue is not a unit of release: much of the open queue is documentation, tests and fakes,
and a tag for a range that only touched those publishes a version a reader cannot act on.

| the diff touches | bump |
| --- | --- |
| `src/fusion360_mcp/tools.py`'s schema, a tool added or renamed, a reply key renamed or removed, an `error_kind` changed, or a call that now answers differently | **minor** — a caller has to change, or reads a different answer |
| a defect fixed with no contract change — same arguments, same keys, the right answer — including an add-in fix and a reply key *added* | **patch** |
| only `tests/`, `docs/`, `fuzz/`, `scripts/` or comments | **none** — no tag; the merges accumulate |

A range that straddles two rows takes the higher of them (`none` < `patch` < `minor`): a
patch that should have been a minor is a caller who never upgraded, while a minor that
should have been a patch is one line in the changelog. A trigger below firing on a range
the table gives **none** cuts nothing - two documentation merges are not a release, and
the next bumping range carries them.

Cut a release when either of these comes first:

- an issue closes that changed what a tool answers;
- three PRs have merged since the previous tag, not counting a release PR.

The first is the one that matters: `README.md` pins a tag, so a fix nobody tags is
invisible to every reader who installs from that pin. The second bounds the wait - a
released fix should not sit behind a batch bigger than one round of live proof
(`docs/WORK-LOOP.md`, *Live proof*).

This is where the project's earlier practice changes. `0.8.2` cut a documentation-and-
guards payload as a patch, and `0.7.3` shipped docs, tooling and a version bump; each
publishes a wheel that behaves as the release before it did. Both were judgement calls,
and this rule replaces them.

### Cutting the tag

1. Classify the range since the last tag against the table above, and put the bump in the
   PR body. A judgement that is not written down cannot be reviewed.
2. Move `version` in `pyproject.toml`, `addon/Fusion360MCP.manifest` and the install
   snippets in `README.md`, and on a **minor or major** both rows of `SECURITY.md`'s
   supported-versions table - the new `<major>.<minor>.x` Yes row and its
   `< major.minor` No row beneath it, in the shape that file already uses. Then
   `uv lock`. They ship together, and `tests/test_packaging.py` fails naming whichever
   one you missed: the manifest, pin and supported-versions guards each name the file and
   the fix, and the pin guard also gives the line.
3. Write the `CHANGELOG.md` entry: the heading `## [X.Y.Z] - YYYY-MM-DD`, the sections
   under it, and the compare link at the bottom of the file in the shape the others use,
   `[X.Y.Z]: https://github.com/shinobi81/fusion360-mcp-server/compare/vX.Y.W...vX.Y.Z`.
   Three guards read it - the opening heading, its date, and that link - and each names
   what is missing. The entry is written **in this PR**, while the reason for every
   change is still in hand; that is the practice `CHANGELOG.md`'s 0.8.2 entry records.
4. PR it (`chore(release): x.y.z`), merge as usual.
5. Start from the merged `main` (`git checkout main && git pull`), so the tree you tag is
   the tree you built, then check that the artifacts ship the add-in, unpiped -
   `release.yml` runs this before it publishes, so a build that loses `addon/` fails
   here rather than in a user's install. It reads both the wheel and the sdist back
   and compares them with `git ls-files addon`:

   ```bash
   uv build
   uv run --no-project python scripts/check_artifacts_ship_addon.py dist
   ```

   The argument is the directory, not `dist/*.whl dist/*.tar.gz`: the check expands it
   itself, so the same line works in bash, PowerShell and cmd. A directory is one build
   output and has to hold both artifacts — one alone is a cannot-check failure, not a
   pass over the half that was built. Unpiped on purpose: a status read through a pipe
   is the pipe's, not the check's.
6. Annotated tag on the merge commit: `git tag -a vX.Y.Z -m "…"`, then
   `git push origin vX.Y.Z`.

   **The push publishes the release.** `release.yml` triggers on `v*`, and its publish
   step is `gh release create` with the wheel, the sdist, `sbom.cdx.json` and
   `provenance.sigstore.json` - the four assets a tag is meant to carry. Do not run
   `gh release create` yourself: a release that already exists makes that step fail with
   `a release with the same tag name already exists`, and what is left behind is a
   release with **no assets** - the attestation was produced, since
   `attest-build-provenance` ran, but its bundle never became an asset. The recovery is
   at the end of this section.
7. Verify the tag actually installs:

   ```bash
   uvx --from 'git+https://github.com/shinobi81/fusion360-mcp-server@vX.Y.Z' \
     fusion360-mcp-server --help
   ```

   Then confirm the **release** published, not only the tag: this is the one step that
   can see step 6's failure mode, because installing from a tag works whether or not a
   release exists or carries anything.

   ```bash
   gh release view vX.Y.Z --json assets --jq '.assets[].name'
   ```

   Four names, or `gh run list --workflow release.yml -L 1` green.

### Correcting a published entry

A published entry that states something false is corrected by annotating it in place, in
a PR against `main`, named as a post-release correction, citing the PR and — where a
later change made the corrected claim true — that change. The tag's tree is never
rewritten, so the tag's copy keeps the original sentence.

### If the release workflow failed

`gh release create` refusing with `a release with the same tag name already exists` means
a release was made by hand. Delete it and re-run the job:

```bash
gh release delete vX.Y.Z --yes   # the tag stays, which --verify-tag needs
gh run rerun <run-id> --failed   # a job re-run starts at its first step, not at the
                                 # one that failed, so the build and attestation redo
```

The assets arrive with the new run. Re-tagging is never the fix: the tag is correct, only
the release was.
