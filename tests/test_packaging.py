"""Drift guards for the Python support window.

The window is stated in ``requires-python``, in the ``Programming Language ::
Python :: 3.x`` classifiers, and in ``[tool.pyright]`` (a type checker cannot
infer it).  Once, these disagreed for four years while nobody looked — the floor
said 3.10 and 3.10 was already EOL.  These tests read the floor and fail the
suite when any surface falls out of step with it, when a tool grows a second copy
of the floor that can drift independently, when a document quotes a lint rule set
the configuration no longer has, when CI stops running a gate those configurations
describe, or when the add-in's Fusion manifest declares a version the release does
not.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _floor_minor() -> int:
    """The minor of ``requires-python``, e.g. 14 for ``">=3.14"``."""
    spec = _pyproject()["project"]["requires-python"]
    match = re.fullmatch(r">=\s*3\.(\d+)", spec)
    assert match, (
        f"requires-python is {spec!r}; this guard only understands a bare '>=3.X' "
        "floor, and a compound specifier would be misread instead of failing"
    )
    return int(match.group(1))


def _classifier_minors() -> set[int]:
    return {
        int(classifier.rsplit(".", 1)[-1])
        for classifier in _pyproject()["project"]["classifiers"]
        if classifier.startswith("Programming Language :: Python :: 3.")
    }


def test_classifiers_do_not_claim_unsupported_pythons():
    floor = _floor_minor()
    claimed = sorted(minor for minor in _classifier_minors() if minor < floor)
    assert claimed == [], (
        f"classifiers claim 3.{claimed} but requires-python floors at 3.{floor}"
    )


def test_the_floor_itself_is_classified():
    floor = _floor_minor()
    assert floor in _classifier_minors(), (
        f"3.{floor} is the requires-python floor but has no classifier"
    )


def test_ruff_has_no_second_copy_of_the_floor():
    assert "target-version" not in _pyproject()["tool"].get("ruff", {}), (
        "ruff must infer its target from project.requires-python; a second copy drifts"
    )


def test_pyright_pins_exactly_the_floor():
    """pyright cannot infer from ``requires-python``, so its value needs a guard.

    "At or above" is not enough.  Pinned *below* the floor, pyright reports errors
    on supported code — a 3.10 pin resolves ``tomllib`` (stdlib from 3.11) as a
    missing import, which is exactly how this was found.  Pinned *above* it, the
    checker accepts syntax the package still advertises as unsupported.  The
    checked version must be the lowest one we support.
    """
    declared = _pyproject()["tool"].get("pyright", {}).get("pythonVersion")
    assert declared is not None, (
        "pyproject.toml's [tool.pyright] states no pythonVersion; pyright cannot "
        "infer it from requires-python"
    )
    assert int(declared.split(".")[1]) == _floor_minor(), (
        f"[tool.pyright] pins {declared}; the floor is 3.{_floor_minor()}"
    )


def test_there_is_no_second_pyright_config():
    """``pyrightconfig.json`` silently wins over ``[tool.pyright]``; keep one.

    Two config files is how ``pythonVersion`` said 3.10 for a year while the lint
    target said something else, and it is why the same change had to touch the
    same value twice.  If a second file ever returns, it must be because someone
    deleted this test on purpose.
    """
    second = REPO_ROOT / "pyrightconfig.json"
    assert not second.exists(), (
        "pyrightconfig.json takes precedence over [tool.pyright] in pyproject.toml; "
        "a second config file shadows the one this suite checks"
    )


def test_documents_quoting_the_ruff_selection_match_the_config():
    """A quoted rule set in docs is a claim about this config.

    Stale copies have surfaced across more than one change, one of them in a table that
    argued an external criterion was met.  Quoting the list in a document is fine;
    quoting a list the configuration no longer has is a false claim that no reader can
    be expected to catch.  Two spellings are in use - ``select = [...]`` in the roadmap
    and the prose ``rules `E`, `F`, ...`` in CONTRIBUTING - so both are read, and each
    must still be found: a quote that quietly disappears takes the guard with it.
    """
    configured = sorted(_pyproject()["tool"]["ruff"]["lint"]["select"])
    readers = (
        (REPO_ROOT / "docs" / "ROADMAP.md", re.compile(r"select = \[([^\]]*)\]")),
        (REPO_ROOT / "CONTRIBUTING.md", re.compile(r"rules ((?:`[A-Z]+`(?:, )?)+)")),
    )
    offenders = []
    for doc, pattern in readers:
        assert doc.exists(), f"{doc.name} is gone; this guard would pass vacuously"
        hits = 0
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            found = pattern.search(line)
            if found is None:
                continue
            hits += 1
            stated = sorted(re.findall(r'["`]([A-Z]+)["`]', found.group(1)))
            if stated != configured:
                offenders.append(f"{doc.name}:{number} quotes {stated}")
        assert hits, f"{doc.name} no longer quotes the rule set; the guard is vacuous"
    assert offenders == [], f"{'; '.join(offenders)}; pyproject configures {configured}"


def _ci_lines() -> list[str]:
    return CI_WORKFLOW.read_text(encoding="utf-8").splitlines()


def _ci_lint_step_start(lines: list[str]) -> int | None:
    return next(
        (i for i, line in enumerate(lines) if line.strip() == "- name: Lint"),
        None,
    )


def _ci_lint_step_lines() -> list[str]:
    """The lines of ci.yml's ``- name: Lint`` step, header to the next step.

    Scoped to the step rather than to the file: a command that exists somewhere in
    the workflow gates nothing when the job around it never runs.  Returns ``[]``
    when the step is gone, which the test reports.
    """
    lines = _ci_lines()
    start = _ci_lint_step_start(lines)
    if start is None:
        return []
    indent = len(lines[start]) - len(lines[start].lstrip())
    rest = lines[start + 1 :]
    end = next(
        (
            offset
            for offset, line in enumerate(rest)
            if line.strip().startswith("- name:")
            and len(line) - len(line.lstrip()) == indent
        ),
        len(rest),
    )
    return [lines[start], *rest[:end]]


def _ci_lint_job_preamble() -> list[str]:
    """The `Lint` step's job header plus every key between it and the step.

    A step that only runs on `push`, or whose job is conditional, is not a gate
    on a pull request.  The keys are returned rather than parsed so the caller can
    name the job and reject a conditional one in the same breath.
    """
    lines = _ci_lines()
    start = _ci_lint_step_start(lines)
    if start is None:
        return []
    job = next(
        (
            i
            for i in range(start - 1, -1, -1)
            if re.fullmatch(r"  [\w-]+:\s*", lines[i])
        ),
        None,
    )
    if job is None:
        return []
    return lines[job:start]


def _ci_ruff_commands() -> list[str]:
    """The `uv run ruff …` shell lines the `Lint` step executes.

    Deliberately a line scan, not a YAML parse: PyYAML is not a dependency, and
    each command is a single line inside the `run:` block.  Comment lines fail
    the `startswith`, so a commented-out command cannot satisfy the guard.
    """
    return [
        stripped
        for line in _ci_lint_step_lines()
        if (stripped := line.strip()).startswith("uv run ruff")
    ]


def test_ci_gates_the_formatter_as_well_as_the_linter():
    """`ruff check` alone left four unformatted files on `main` across two changes.

    Nothing ran the formatter, so the drift only surfaced when someone typed
    `ruff format` by hand — and the notes that said the gate was clean were
    notes, not a gate.  A claim no gate backs is the failure mode this whole
    module exists to prevent, so the gate itself is asserted here.

    `addon/` must stay out of the formatter line: it runs on Fusion's own
    interpreter, which `requires-python` does not govern, and finishing its one
    remaining reformat would move the add-in to 3.14-only syntax.  If that
    exclusion is ever lifted, lift it here too.

    The shape is pinned on purpose — one `Lint` step, one formatter command, the
    directories spelled out — because every looser form of this test was a form that
    passed with the gate disarmed.
    """
    block = _ci_lint_step_lines()
    assert block, "ci.yml has no `- name: Lint` step"
    preamble = _ci_lint_job_preamble()
    assert preamble and preamble[0].strip() == "test:", (
        "the Lint step must live in the `test` job: the ruleset's required checks "
        f"are `test (3.14)` and `test (3.15)`, so a gate in any other job is not "
        f"required; found {preamble[:1]}"
    )
    disarmed = [
        line.strip()
        for line in preamble + block
        if line.strip().startswith(("if:", "continue-on-error:"))
    ]
    assert disarmed == [], (
        f"the `test` job and its Lint step must not be conditional: {disarmed}"
    )
    commands = _ci_ruff_commands()
    assert "uv run ruff check src/ tests/ fuzz/ addon/ scripts/" in commands, (
        f"the Lint step no longer lints every directory in one gate: {commands}"
    )
    format_commands = [cmd for cmd in commands if "ruff format --check" in cmd]
    assert len(format_commands) == 1, (
        "the Lint step must run `ruff format --check` exactly once, "
        f"found {format_commands}"
    )
    # Strip the fixed prefix rather than slicing by index: an index into a
    # command someone reorders is a guard that fails for the wrong reason.
    prefix = "uv run ruff format --check "
    command = format_commands[0]
    assert command.startswith(prefix), (
        f"the formatter gate is not shaped like `{prefix}…`: {command}"
    )
    assert command.removeprefix(prefix).split() == [
        "src/",
        "tests/",
        "fuzz/",
        "scripts/",
    ], (
        "the formatter gate must cover src/ tests/ fuzz/ scripts/ and exclude addon/ "
        "(Fusion's interpreter is not governed by requires-python): "
        f"{command}"
    )


def test_the_add_in_manifest_declares_the_version_being_released():
    """The manifest Fusion registers carries a version, and nothing read it.

    The add-in and the server ship together - one changelog, one tag - so the manifest
    is not free to lag behind ``pyproject.toml``.  It said 0.1.0 from the commit that
    created it until 0.7.2, sixteen tagged releases, which is the same shape of stale
    claim the coverage-figure check exists to stop.

    The file has to stay strict JSON: Fusion parses it with the same rules, so a comment
    or a trailing comma makes the add-in unloadable, not merely this test red.
    """
    manifest = REPO_ROOT / "addon" / "Fusion360MCP.manifest"
    assert manifest.exists(), (
        "addon/Fusion360MCP.manifest is gone; this guard would pass vacuously"
    )
    facts = json.loads(manifest.read_text(encoding="utf-8"))
    assert "version" in facts, (
        "addon/Fusion360MCP.manifest states no version; this guard would pass vacuously"
    )
    declared = facts["version"]
    packaged = _pyproject()["project"]["version"]

    assert declared == packaged, (
        f"addon/Fusion360MCP.manifest declares {declared}, pyproject.toml {packaged}; "
        "bump both in the release PR (CONTRIBUTING.md, Releasing)"
    )
