# Testing

How the suite runs, what it deliberately cannot run, and what has to be green before a
pull request merges. Why the fakes exist and what they model is in
[ARCHITECTURE.md](../ARCHITECTURE.md#testing-strategy); this page is the operator's view.

## Checking that Fusion is actually alive

`scripts/health_check.py` polls the add-in's `health` command, which runs on the main
thread: `ping` is answered by the socket thread before a command is queued, so a Fusion
blocked on a modal dialog still says `pong`. The script's exit codes are its contract —
`0` answered, `1` did not answer inside `--timeout` or answered with a failure, `2`
nothing is listening (`argparse` uses 2 for a usage error too), `3` the add-in has
no `health` command and needs reloading — and its
docstring says what it cannot do: reload the add-in (itself a main-thread command), kill
Fusion (that takes the unsaved document), or tell a busy thread from a dead one.

## Running it

```bash
uv sync --dev --locked                   # deps into .venv, no Fusion needed
uv lock                                  # only if you changed pyproject.toml
uv run pytest -q                         # the whole suite, ~16s
uv run pytest -q --no-cov tests/test_tools.py   # one file, without the coverage floor
uv run pytest -q -k revolve              # by name
uv run ruff check src/ tests/ fuzz/ addon/ scripts/      # what CI runs
uv run ruff format --check src/ tests/ fuzz/ scripts/    # what CI runs (addon/ is exempt)
uv run mypy src                          # what CI runs (src/ only; addon/ is exempt)
```

Nothing in the suite needs Fusion, a network, or a display. The packaging guards in
`tests/test_packaging.py` shell out to `git ls-files` to read the tracked documents;
that is the suite's only git dependency. The install tests drive
`scripts/install-addon.sh` through `bash`: POSIX always provides one, and the suite
fails rather than skips without it — the install tests that run the script would
otherwise vanish from a green run — while Windows skips those tests with the reason when
only the WSL stub is found. The socket tests bind `127.0.0.1` and close immediately.

## The coverage floor

`addopts` in `pyproject.toml` measures coverage on every run and fails below the floor
recorded there. The floor is **two gates**, because one number cannot hold two very
different populations:

- **59** for the whole suite, which now measures `src/fusion360_mcp` **and**
  `addon/server`. The CAM paths still uncovered only run inside Fusion, and they
  account for almost all of the statements left.
  (The export family *is* covered offline, by `tests/test_addon_export.py`: body
  STL/STEP and f3d against a fake export manager, both default output paths, and —
  once the fake runtime gained `adsk.core.CameraTypes` and the test module grew a
  viewport that writes bytes and hands the camera out as the *copy* Fusion documents —
  `render_view`'s capture and decode, `export_view_sheet` end to end, `import_mesh`'s
  two import paths and `export`'s stl dispatch. `handler_export` is at 93%; the floor
  itself has not moved, because moving it is a separate decision.)
- **95** for the server alone, enforced separately in CI:
  `uv run coverage report --include="src/fusion360_mcp/*" --fail-under=95`. Without it,
  an add-in regression would buy slack for `src/`.

Both live in `addopts`/CI rather than in one file's scope, so a subset is run with
`--no-cov`. The uncovered statements are all printed by `--cov-report=term-missing`; the
four below are by design, named by symbol because line numbers drift on every edit and a
stale one reads as a waiver for code that no longer exists:

- `server.py`'s `bbox_before` branch: no mock sets it.
- The unreachable prompt fallback: clients only ask for prompts `list_prompts`
  advertised.
- The two lines inside `arun()` (`async with stdio_server()` and the `app.run` it
  awaits); `anyio.run(arun)` itself runs in the tests.
- `__main__.py`'s click entry point.

The measured total is deliberately not written down in any document that describes the
current tree: it moves whenever a test reaches new lines, so a quoted figure is a claim
that has to be re-edited rather than a fact anyone acts on. The test job prints it, and
the floors above are what the tools enforce. `CHANGELOG.md` still quotes the totals of
past releases, which are true of the releases they describe.

## The fake runtime

The add-in is imported under pytest as an ordinary module. Nothing under `addon/` imports
`adsk` at module scope: it resolves Autodesk's API through the lazy adapter in
`addon/server/fusion_api.py`, and `tests/conftest.py`'s `handler_module` fixture
injects a fake `adsk` into that adapter from `tests/fakes/` (`runtime.py` for the API
surface, `app.py` for the application, `sketch.py` and `design.py` for geometry and the
document tree). `bound_handler` then wires a handler to a fake design, which is how most
add-in tests reach a method.

`tests/test_addon_importable.py` pins the invariant in a subprocess: the package, the
handler and the bridge all import with no `adsk` installed, and importing them creates no
files.

Because `adsk` still cannot resolve offline, `addon/` is excluded from pyright and mypy
in `pyproject.toml` on purpose. Do not "fix" it with type ignores: ruff plus the suite
still cover the directory.

## Checking the running add-in

The add-in loads `command_handler` from the checkout and keeps it in memory, so a
`git pull` changes what is on disk and nothing about what Fusion executes. `inspect`
cannot tell you either: `getsource` reads the *file*, so a stale class describes itself
with the new code - a live check can pass for days after a merge that was never loaded.
Edits to a command go to the domain module that owns it, one of the `handler_*.py`
modules `COMMAND_MODULES` lists; `command_handler.py` only composes them.

```bash
uv run python scripts/reload_addin.py            # reload, then verify
uv run python scripts/reload_addin.py --check    # verify only, change nothing
```

It asks the add-in which file it loaded and prints that path before it sends anything,
and goes no further unless the path is this checkout's `command_handler.py`: a copy in
an AddIns folder is a failure, not a note. Unless you passed `--check` it then sends
`reload_handler`, which re-executes the modules in `RELOAD_ORDER` - the sibling modules
a handler module imports at module scope, then the command modules `COMMAND_MODULES`
lists, `command_handler` last - and prints that list, then the line naming the two
modules it does not reload; `--check` re-executes nothing, so it prints neither. It
then compares the running class's **method names**, read up its `__mro__`, with the
methods the command modules declare. `COMMAND_MODULES` is the one list of command
modules, and `tests/test_reload_addin.py` fails if the add-in's copy of the reload order
drifts from the script's, or if a module that declares commands is in neither. Exit 1
means the sets differ, or the loaded path was another tree's. What "ok" therefore means
is narrow, and the script's own output says so: editing a method *body* changes no name
and still prints ok, so reload whenever you have pulled, not only when the check
complains.

What it cannot cover: `event_bridge.py` and `socket_server.py` are not reloaded, and that
line is printed only by a reload - restart the add-in for those. The check also needs an
**open document**, a precondition rather than a printed line: it rides on `execute_code`,
which resolves the active design, so with none open it fails and says so instead of
reporting.

## The policy

New functionality arrives with tests in the same pull request, and a bug fix starts with
a test watched failing for the right reason. This is the rule in `CONTRIBUTING.md`, in
`.github/PULL_REQUEST_TEMPLATE.md` (tick-boxes for the suite, the linter and markdownlint)
and in `AGENTS.md` under "Adding a tool". The mock is part of it: every tool has a
handler in `src/fusion360_mcp/mock.py`, and `tests/test_addon_sync.py` fails if a command
exists on one side but not the other.

When a fuzz target finds something, the order is: keep the crashing input, turn it into
a regression test in `tests/test_fuzz_targets.py`, then fix. The fuzz job is not a
required check, so a finding never blocks an unrelated pull request; the regression test
is what keeps it fixed.

## The fuzz targets

Four targets live in `fuzz/`: `fuzz_hints_classify`, `fuzz_parameter_units`,
`fuzz_hole_geometry` and `fuzz_socket_framing`. atheris is **Linux-only and CI-only** -
it publishes no Windows wheel, and the `fuzz` dependency group in `pyproject.toml` carries
a marker that keeps it empty everywhere else. Run them from the repository root, in module
mode:

```bash
uv sync --locked --only-group fuzz --python 3.14
uv run --no-sync python -m fuzz.fuzz_hints_classify -max_total_time=60 -rss_limit_mb=2048
```

`-m` is not a style choice. The targets import their shared plumbing package-relatively
(`from ._common import decode`), so `python fuzz/fuzz_hints_classify.py` fails on that
import; module mode is the only mode that works, and it also puts the repository root on
`sys.path`, which is how `from addon.server... import` resolves. The group is pinned to
Python 3.14 because that is the only interpreter inside the project's `>=3.14` window that
atheris 3.1.0 has a wheel for: it publishes cp312, cp313 and cp314 wheels and nothing for
3.15 (no wheel, no sdist), so at 3.15 the group does not resolve at all.

Two more things the job depends on:

- **No `PYTHONOPTIMIZE`.** The targets' invariants are bare `assert`s. `-O` compiles them
  out, and a fuzzer that reports clean because it checks nothing is worse than no fuzzer.

Every target exposes `check(data: bytes) -> None`, which is also how
`tests/test_fuzz_targets.py` drives the same invariants inside the ordinary suite - that
part runs on any platform, atheris or not.

## The merge gate

A pull request merges when all of this is true, and the ruleset on `main` enforces it:

- one approving review, from a code owner for the paths in `.github/CODEOWNERS`;
- green CI (`.github/workflows/ci.yml`): the test, windows, macos, docs and threads jobs.
  The `test` job is a required status check; renaming it unprotects merges silently;
- no unresolved review threads, bot findings included. `scripts/check_review_threads.py`
  checks it and the `threads` CI job runs the same script, because the code owner's
  `gh pr merge --admin` bypasses the ruleset that would otherwise enforce it.

The fuzz job is deliberately outside that list: atheris is available on Linux only, and
the invariants it explores already run in the ordinary suite through
`tests/test_fuzz_targets.py`, so a fuzz finding is turned into a regression test rather
than gating an unrelated pull request.
