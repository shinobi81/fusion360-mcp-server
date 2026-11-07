"""Drift guards for the Python support window.

The window is stated in ``requires-python``, in the ``Programming Language ::
Python :: 3.x`` classifiers, and in ``[tool.pyright]`` (a type checker cannot
infer it).  Once, these disagreed for four years while nobody looked — the floor
said 3.10 and 3.10 was already EOL.  These tests read the floor and fail the
suite when any surface falls out of step with it, when a tool grows a second copy
of the floor that can drift independently, or when a document quotes a lint rule
set the configuration no longer has.
"""

from __future__ import annotations

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
    """A quoted ``select = [...]`` in docs is a claim about this config.

    Four stale copies of the rule set have surfaced in three changes, one of them
    in the Scorecard evidence table that argues a criterion is met.  Quoting the
    list in a document is fine; quoting a list the configuration no longer has is
    a false claim that no reader can be expected to catch.
    """
    configured = sorted(_pyproject()["tool"]["ruff"]["lint"]["select"])
    quoted = re.compile(r"select = \[([^\]]*)\]")
    offenders = []
    for doc in (REPO_ROOT / "docs" / "BADGE.md", REPO_ROOT / "CONTRIBUTING.md"):
        if not doc.exists():
            continue
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            found = quoted.search(line)
            if found is None:
                continue
            stated = sorted(re.findall(r'"([^"]+)"', found.group(1)))
            if stated != configured:
                offenders.append(f"{doc.name}:{number} quotes {stated}")
    assert offenders == [], f"{'; '.join(offenders)}; pyproject configures {configured}"


def _ci_ruff_commands() -> list[str]:
    """The `uv run ruff …` shell lines CI actually executes.

    Deliberately a line scan, not a YAML parse: PyYAML is not a dependency, and
    each command is a single line inside the `run:` block.  Comment lines fail
    the `startswith`, so a commented-out command cannot satisfy the guard.
    """
    return [
        stripped
        for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()).startswith("uv run ruff")
    ]


def test_ci_gates_the_formatter_as_well_as_the_linter():
    """`ruff check` alone left four unformatted files on `main` for two changes.

    Nothing ran the formatter, so the drift only surfaced when someone typed
    `ruff format` by hand — and the notes that said the gate was clean were
    notes, not a gate.  A claim no gate backs is the failure mode this whole
    module exists to prevent, so the gate itself is asserted here.

    `addon/` must stay out of the formatter line: it runs on Fusion's embedded
    interpreter, and finishing its one remaining reformat would move the add-in
    to 3.14-only syntax.  If that exclusion is ever lifted, lift it here too.
    """
    commands = _ci_ruff_commands()
    assert "uv run ruff check src/ tests/ fuzz/ addon/" in commands, (
        f"ci.yml no longer lints src/ tests/ fuzz/ addon/ in one gate: {commands}"
    )
    format_commands = [cmd for cmd in commands if "ruff format --check" in cmd]
    assert len(format_commands) == 1, (
        f"ci.yml must run `ruff format --check` exactly once, found {format_commands}"
    )
    # Strip the fixed prefix rather than slicing by index: an index into a
    # command someone reorders is a guard that fails for the wrong reason.
    prefix = "uv run ruff format --check "
    command = format_commands[0]
    assert command.startswith(prefix), (
        f"the formatter gate is not shaped like `{prefix}…`: {command}"
    )
    assert command.removeprefix(prefix).split() == ["src/", "tests/", "fuzz/"], (
        "the formatter gate must cover src/ tests/ fuzz/ and exclude addon/ "
        "(Fusion's interpreter is not governed by requires-python): "
        f"{command}"
    )
