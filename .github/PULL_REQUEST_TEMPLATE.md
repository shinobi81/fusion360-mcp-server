## What and why

<!-- One paragraph: what changes, and what problem it solves. Link the issue. -->

## How it was verified

- [ ] `uv run pytest -q` — all tests pass
- [ ] `uv run ruff check src/ tests/ fuzz/ addon/`
- [ ] `npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"`
- [ ] Live Fusion check if this touches the add-in (`ping` → `pong`, then the operation)

<!-- Paste the measurement, tool result or error envelope.
     "Works locally" is not evidence. -->

## Contract changes

Delete what does not apply — these are the places a change quietly breaks callers.

- [ ] Tool added/renamed → `tools.py`, `mock.py`, annotations, `tests/test_tools.py`
- [ ] New failure mode → `hints.py` in **both** mirrors
      (`addon/server/` and `src/fusion360_mcp/`)
- [ ] Response shape changed → `AGENTS.md` and `CHANGELOG.md`
- [ ] Design-type or undo behaviour touched → note the parametric **and**
      direct paths

## Checklist

- [ ] One concern per PR
- [ ] Bug fix: the new test was watched failing before the fix
- [ ] No secrets, no `.venv`, no hand-edited `uv.lock`
- [ ] Not opening this from `main` — it is protected; use a fork or a branch
