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
uv sync                        # python deps into .venv
uv run pytest -q               # suite runs without Fusion
uv run ruff check src/ tests/ fuzz/ addon/ scripts/  # what CI runs
uv run ruff format --check src/ tests/ fuzz/ scripts/  # what CI runs (addon/ is exempt)
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
  `tests/test_addon_sync.py` fails if a command exists in one place but not the other.
- **Errors are data.** Return `{"ok": false, "error_kind": ..., "hints": [...]}`, don't
  raise through the bridge. New failure modes get a rule in `addon/server/hints.py`
  **and** `src/fusion360_mcp/hints.py` — they are mirrors, and a test enforces that.
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

## Releasing

1. Bump `version` in `pyproject.toml`, then `uv lock`.
2. PR it (`chore(release): x.y.z for <reason>`), merge as usual.
3. Annotated tag on the merge commit: `git tag -a vX.Y.Z -m "…"`, then
   `git push origin vX.Y.Z`.
4. Verify the tag actually installs:

   ```bash
   uvx --from 'git+https://github.com/shinobi81/fusion360-mcp-server@vX.Y.Z' \
     fusion360-mcp-server --help
   ```

5. Add a `CHANGELOG.md` entry.
