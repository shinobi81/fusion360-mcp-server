"""Drift guards for the claims this repository makes about itself.

The Python floor is stated in ``requires-python``, in the ``Programming Language ::
Python :: 3.x`` classifiers, and in ``[tool.pyright]`` (a type checker cannot
infer it).  Once, these disagreed for four years while nobody looked — the floor
said 3.10 and 3.10 was already EOL.  These tests read the floor and fail the
suite when any surface falls out of step with it, when a tool grows a second copy
of the floor that can drift independently, when a document quotes a lint rule set
the configuration no longer has, when CI stops running a gate those configurations
describe, when the add-in's Fusion manifest declares a version the release does
not, when it changes the id it declares, when that add-in is renamed in one place and
not the others, when a documented install snippet pins a release other than the one
being cut, or when a document names a lint command CI does not run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ADD_IN_MANIFEST = REPO_ROOT / "addon" / "Fusion360MCP.manifest"
"""The add-in's manifest. Its filename is the add-in's name - see ``ADD_IN_NAME``."""

ADD_IN_NAME = ADD_IN_MANIFEST.stem


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


def _add_in_manifest() -> dict:
    """The Fusion manifest as data.

    Strict JSON, because Fusion parses it with the same rules: a comment or a trailing
    comma makes the add-in unloadable, not merely this module red.
    """
    manifest = ADD_IN_MANIFEST
    assert manifest.exists(), (
        "addon/Fusion360MCP.manifest is gone; these guards would pass vacuously"
    )
    return json.loads(manifest.read_text(encoding="utf-8"))


def test_the_add_in_manifest_declares_the_version_being_released():
    """The manifest Fusion registers carries a version, and nothing read it.

    The add-in and the server ship together - one changelog, one tag - so the manifest
    is not free to lag behind ``pyproject.toml``.  It said 0.1.0 from the commit that
    created it until 0.7.2, sixteen tagged releases, which is the same shape of stale
    claim the coverage-figure check exists to stop.
    """
    facts = _add_in_manifest()
    assert "version" in facts, (
        "addon/Fusion360MCP.manifest states no version; this guard would pass vacuously"
    )
    declared = facts["version"]
    packaged = _pyproject()["project"]["version"]

    assert declared == packaged, (
        f"addon/Fusion360MCP.manifest declares {declared}, pyproject.toml {packaged}; "
        "bump both in the release PR (CONTRIBUTING.md, Releasing)"
    )


def _tracked_markdown(*, exclude: tuple[str, ...] = ()) -> list[str]:
    """Every tracked ``*.md`` path, repo-relative.

    ``git ls-files`` rather than a glob: the suite runs in the working tree, where a
    glob would also sweep the venv, and the tracked set is what a reader can reach on
    GitHub.  Files that are not markdown are out of scope on purpose - the install
    snippets live in prose - so a stale tag in an issue template still needs a human.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert listed.returncode == 0, (
        "git ls-files failed, so every documented pin went unread; this guard is the "
        f"suite's only git dependency ({listed.returncode}): {listed.stderr.strip()}"
    )
    return [p for p in listed.stdout.split("\0") if p and p not in exclude]


INSTALL_PIN = re.compile(
    r"git\+https://github\.com/shinobi81/fusion360-mcp-server@v(?P<version>[0-9][\w.+-]*)"
)
"""A pinned install command: ``git+https://…@vX.Y.Z``.

The captured version runs to the end of the token rather than to the third dot, so a
prerelease such as ``0.8.0rc1`` compares whole instead of reading as ``0.8.0``.
"""

HISTORY_DOCUMENTS = ("CHANGELOG.md",)
"""Documents that record what past releases said, rather than what to install now."""


def _pinned_versions(text: str) -> list[tuple[int, str]]:
    """Every (line number, pinned version) in one document, in file order."""
    return [
        (number, match.group("version"))
        for number, line in enumerate(text.splitlines(), start=1)
        for match in INSTALL_PIN.finditer(line)
    ]


def _stale_pin_findings(pages: dict[str, str], release: str) -> list[str]:
    """One ``path:line pins vX`` finding per pin naming a version but *release*."""
    return [
        f"{name}:{number} pins v{version}"
        for name, text in pages.items()
        for number, version in _pinned_versions(text)
        if version != release
    ]


def test_every_documented_install_pin_is_the_version_being_released():
    """Readers copy the install snippets, so a stale pin installs a stale server.

    ``README.md`` pinned ``@v0.3.1`` in five snippets from 0.4.0 until 0.7.2 - four
    minors behind, in the one place a new user is guaranteed to look - and nothing read
    it.  Same shape as the manifest version, same fix: the release PR moves the pin, and
    this fails when it does not.

    ``CONTRIBUTING.md`` shows ``@vX.Y.Z`` as a placeholder, which the pattern does not
    match, and ``HISTORY_DOCUMENTS`` is exempt because it records what past releases
    said rather than telling anyone what to install.
    """
    release = _pyproject()["project"]["version"]
    pages = {
        relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in _tracked_markdown(exclude=HISTORY_DOCUMENTS)
    }
    findings = _stale_pin_findings(pages, release)

    assert findings == [], (
        f"documented install snippets must pin the release being cut (v{release}): "
        + "; ".join(findings)
        + ". A document that quotes a pin as history rather than as an instruction "
        "belongs in HISTORY_DOCUMENTS, with a reason."
    )
    assert _pinned_versions(pages.get("README.md", "")), (
        "README.md pins no install version, so this guard would pass vacuously; if the "
        "snippets moved, point this assertion at the page that carries them: "
        + ", ".join(sorted(pages))
    )


def _install_snippet(version: str) -> str:
    """The install command the README's snippets are built from."""
    return (
        "uvx --from "
        f"'git+https://github.com/shinobi81/fusion360-mcp-server@v{version}' "
        "fusion360-mcp-server --mode socket"
    )


def test_a_stale_install_pin_is_named_with_its_path_and_line():
    pages = {"docs/INSTALL.md": f"intro\n{_install_snippet('0.3.1')}\n"}

    assert _stale_pin_findings(pages, "0.7.2") == ["docs/INSTALL.md:2 pins v0.3.1"]


def test_a_pin_at_the_release_is_not_a_finding():
    pages = {"README.md": _install_snippet("0.7.2")}

    assert _stale_pin_findings(pages, "0.7.2") == []


def test_the_prerelease_suffix_is_compared_whole_not_truncated_to_the_numbers():
    pages = {"README.md": _install_snippet("0.8.0rc1")}

    assert _stale_pin_findings(pages, "0.8.0") == ["README.md:1 pins v0.8.0rc1"]
    assert _stale_pin_findings(pages, "0.8.0rc1") == []


def test_the_release_placeholder_is_not_a_pin_at_all():
    assert _pinned_versions(_install_snippet("X.Y.Z")) == []


def test_the_changelog_is_excluded_because_it_records_what_past_releases_said():
    """A release note states what that release shipped; it must not be re-pinned."""
    assert "CHANGELOG.md" in HISTORY_DOCUMENTS
    assert "CHANGELOG.md" not in _tracked_markdown(exclude=HISTORY_DOCUMENTS)
    # Exclusion is load-bearing, not luck: in the corpus it would be a stale pin.
    history = {"CHANGELOG.md": _install_snippet("0.3.1")}

    assert _stale_pin_findings(history, "0.7.2") == ["CHANGELOG.md:1 pins v0.3.1"]


ADD_IN_INSTALL_ID = "6b98393d-7998-4d19-a8e5-c8b5e3d7f4a2"
"""The ``id`` the manifest declares, pinned so that changing it is a deliberate act.

Nothing in this repository reads the value, and Fusion's own persisted registration
record (``%APPDATA%/Autodesk/Autodesk Fusion 360/<install>/JSLoadedScriptsinfo``)
keys an installed add-in on its name and the path of its entry module, not on this
id - so there is no second copy to compare against and no install to check from here.
The pin buys exactly one thing, and states it: an edit to the constant, in a review
that has to say why, instead of a stray value in a manifest nobody reads.
"""


def test_the_add_in_manifest_keeps_the_id_it_declares():
    """The add-in's ``id`` is unread, and unread is how the version beside it drifted.

    So it is pinned as a change detector: it passes on the current tree by
    construction, which is not evidence that it works, and it was falsified by mutating
    the manifest - a different GUID, a non-GUID spelling, and the key deleted.  Any
    textual change is deliberately not caught: the comparison normalises case and
    surrounding braces, because a respelling that parses as the same GUID changes no
    identity, and a guard that failed on one would be a guard failing for the wrong
    reason.
    """
    facts = _add_in_manifest()

    assert "id" in facts, (
        "addon/Fusion360MCP.manifest declares no id; this guard would pass vacuously"
    )
    declared = str(facts["id"]).strip("{} ").lower()

    assert declared == ADD_IN_INSTALL_ID, (
        f"addon/Fusion360MCP.manifest declares the id {facts['id']!r}, not "
        f"{ADD_IN_INSTALL_ID!r}. No install can be checked from here, so this pin "
        "exists to make an id change deliberate: if the change is intended, update "
        "ADD_IN_INSTALL_ID and say why in the PR."
    )


GATE_DOCUMENTS = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "docs/TESTING.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)
"""Documents that tell a contributor which lint command to run.

The sweep reads every tracked markdown page except ``HISTORY_DOCUMENTS``, so a new page
that spells the gate the way these do is checked the moment it exists; this tuple is the
other half - the pages that must keep saying it, so a reflow that drops the line cannot
empty the check silently.
"""

RUFF_COMMAND = re.compile(r"uv run ruff\b(?P<args>[^`\n]*)")
"""A ``uv run ruff`` invocation, up to a backtick or the end of the line.

Stopping at the backtick keeps a command inside inline code from swallowing the prose
after it, and stopping at the newline keeps a table row or a fenced block from merging
with the next line.  Loosening either half makes the sweep read other people's words.
"""


def _ci_directories(ci: list[str]) -> set[str]:
    """The top-level directories the CI lint commands name."""
    return {token for command in ci for token in command.split() if token.endswith("/")}


def _sorted_command(command: str) -> str:
    """*command* with its directory arguments sorted, so argument order is not drift."""
    head, *tokens = command.split()
    others = [token for token in tokens if not token.endswith("/")]
    return " ".join([head, *others, *sorted(t for t in tokens if t.endswith("/"))])


def _ruff_gate_command(args: list[str], directories: set[str]) -> str | None:
    """The gate an argument list names, or ``None`` if it names a targeted run.

    A gate is a verb and then top-level directories, ending at the first token that is
    not one of them - which is where a trailing comment, prose in parentheses, or a
    display flag begins, and none of those changes which directories get linted.  A flag
    *before* the directories leaves none to read, and a line with none of them is a
    targeted run (`--select`, one file), free to differ from the gate.
    """
    if args[:2] == ["format", "--check"]:
        verb, rest = "format --check", args[2:]
    elif args[:1] in (["check"], ["format"]):
        verb, rest = args[0], args[1:]
    else:
        return None
    named = []
    for token in rest:
        if token not in directories:
            break
        named.append(token)
    if not named:
        return None
    return f"uv run ruff {verb} {' '.join(sorted(named))}"


def _ruff_gate_claims(text: str, directories: set[str]) -> list[tuple[int, str]]:
    """(line number, normalised gate) for every gate-shaped ``uv run ruff`` line."""
    claims = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = RUFF_COMMAND.search(line)
        if match is None:
            continue
        command = _ruff_gate_command(match.group("args").split(), directories)
        if command is not None:
            claims.append((number, command))
    return claims


def _documented_ruff_findings(pages: dict[str, str], ci: list[str]) -> list[str]:
    """One finding per documented gate that is not one of the gates CI runs.

    The apply form (``ruff format`` without ``--check``) is allowed, because the
    documents also say how to fix what the gate reports - but only as the gate command
    with ``--check`` removed, so the directories cannot drift apart.
    """
    directories = _ci_directories(ci)
    allowed: set[str] = set()
    for command in ci:
        gate = _ruff_gate_command(
            command.removeprefix("uv run ruff").split(), directories
        )
        if gate is not None:
            allowed.add(gate)
            allowed.add(gate.replace("format --check", "format"))
    return [
        f"{name}:{number} documents `{command}`, which CI does not run "
        f"(the Lint step runs: {', '.join(f'`{each}`' for each in ci)})"
        for name, text in pages.items()
        for number, command in _ruff_gate_claims(text, directories)
        if command not in allowed
    ]


def _unreadable_ci_commands(ci: list[str]) -> list[str]:
    """CI's lint commands this guard cannot classify.

    Reported rather than mirrored: with a flag before the directories, no document text
    can satisfy both halves of the guard, so the edit that needs making is here, not in
    five markdown pages.
    """
    directories = _ci_directories(ci)
    return [
        command
        for command in ci
        if _ruff_gate_command(command.removeprefix("uv run ruff").split(), directories)
        is None
    ]


def _undocumented_gate_commands(pages: dict[str, str], ci: list[str]) -> list[str]:
    """One finding per gate document that does not name each gate CI runs.

    Both halves, not just "a command": a page that keeps the linter line and drops the
    formatter line states the gate CI ran before #80, which is how four unformatted
    files reached `main`.
    """
    directories = _ci_directories(ci)
    required: dict[str, str] = {}
    for command in ci:
        gate = _ruff_gate_command(
            command.removeprefix("uv run ruff").split(), directories
        )
        if gate is not None:
            required.setdefault(gate, command)
    findings: list[str] = []
    for name in GATE_DOCUMENTS:
        documented = {
            command
            for _, command in _ruff_gate_claims(pages.get(name, ""), directories)
        }
        findings.extend(
            f"{name} no longer documents `{raw}`"
            for gate, raw in required.items()
            if gate not in documented
        )
    return findings


# Fixtures, not truth: hand-written copies for the helper tests.  The guard itself
# re-reads `ci.yml` through `_ci_ruff_commands()`, and swapping that for these would
# make it vacuous against CI drift - the failure this module exists to prevent.
CI_CHECK = "uv run ruff check src/ tests/ fuzz/ addon/ scripts/"
CI_FORMAT = "uv run ruff format --check src/ tests/ fuzz/ scripts/"


def test_a_documented_lint_command_missing_a_directory_is_a_finding():
    pages = {"README.md": "install\nuv run ruff check src/ tests/ fuzz/ addon/\n"}

    (finding,) = _documented_ruff_findings(pages, [CI_CHECK, CI_FORMAT])

    assert "README.md:2" in finding
    assert "scripts/" in finding


def test_a_demonstration_command_is_not_read_as_the_gate():
    pages = {
        "README.md": "uv run ruff check --select B010 src/ tests/\n"
        "uv run ruff --version\n"
        "uv run ruff check\n"
    }

    assert _documented_ruff_findings(pages, [CI_CHECK, CI_FORMAT]) == []


def test_the_apply_form_must_be_the_gate_without_check():
    apply_same = {"AGENTS.md": "uv run ruff format src/ tests/ fuzz/ scripts/\n"}
    apply_narrower = {"AGENTS.md": "uv run ruff format src/ tests/\n"}

    assert _documented_ruff_findings(apply_same, [CI_CHECK, CI_FORMAT]) == []
    (finding,) = _documented_ruff_findings(apply_narrower, [CI_CHECK, CI_FORMAT])
    assert "AGENTS.md:1" in finding


def test_a_trailing_comment_is_not_part_of_the_command():
    pages = {"AGENTS.md": "uv run ruff check src/ tests/ fuzz/ addon/ scripts/  # CI\n"}

    assert _documented_ruff_findings(pages, [CI_CHECK, CI_FORMAT]) == []


def test_every_gate_document_documents_both_halves_of_the_gate():
    """A page naming only the linter states half a gate, which is the pre-#80 gate.

    `ruff check` alone let four unformatted files reach `main`, so a document that stops
    naming `format --check` teaches that half back - quieter than a wrong command, and
    just as wrong.
    """
    pages = {name: "nothing here\n" for name in GATE_DOCUMENTS}
    pages["README.md"] = f"{CI_CHECK}\n"
    pages["CONTRIBUTING.md"] = f"{CI_CHECK}\n{CI_FORMAT}\n"

    findings = _undocumented_gate_commands(pages, [CI_CHECK, CI_FORMAT])

    assert any("README.md" in each and "format --check" in each for each in findings)
    assert any("AGENTS.md" in each for each in findings)
    assert not any("CONTRIBUTING.md" in each for each in findings)


def test_every_documented_lint_command_is_the_one_ci_runs():
    """Contributors copy the lint line, so a drifted one runs a gate CI does not.

    #80's reviewer caught the drift by eye; nothing read these lines, so the next edit
    could move any of the five documents back to a three-directory gate.  The sweep is
    automatic over tracked markdown, and `GATE_DOCUMENTS` keeps the pages that must say
    it from going quiet, which is the shape that let the README's install pins rot.
    """
    ci = _ci_ruff_commands()
    assert ci, "ci.yml's Lint step runs no `uv run ruff` command"
    unreadable = _unreadable_ci_commands(ci)

    assert unreadable == [], (
        "CI runs a lint command this guard cannot classify, so no document could "
        f"satisfy it - teach `_ruff_gate_command` or drop the flag: {unreadable}"
    )
    pages = {
        relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in _tracked_markdown(exclude=HISTORY_DOCUMENTS)
    }
    findings = _documented_ruff_findings(pages, ci)
    undocumented = _undocumented_gate_commands(pages, ci)

    assert findings == [], (
        "a document names a lint command CI does not run: "
        + "; ".join(findings)
        + ". A targeted or demonstration command is not read here, only the "
        "gate-shaped one; the release notes in HISTORY_DOCUMENTS are exempt as history."
    )
    assert undocumented == [], (
        "these documents no longer state every command the gate runs, so a contributor "
        f"following them would not run the gate: {undocumented}"
    )


def test_one_space_before_a_comment_is_still_a_comment():
    """People write `…# note` with one space; cutting on two spaces dropped the claim.

    Dropping it is not harmless: the page then counts as one that no longer documents
    the gate, so a correct line reports as drift.
    """
    line = "uv run ruff check src/ tests/ fuzz/ addon/ scripts/ # CI\n"

    expected = [(1, _sorted_command(CI_CHECK))]

    assert _ruff_gate_claims(line, _ci_directories([CI_CHECK])) == expected


def test_prose_after_a_command_is_not_part_of_it():
    line = "uv run ruff check src/ tests/ fuzz/ addon/ scripts/ (what CI runs)\n"

    expected = [(1, _sorted_command(CI_CHECK))]

    assert _ruff_gate_claims(line, _ci_directories([CI_CHECK])) == expected


def test_directory_order_is_not_part_of_the_command():
    reordered = {"README.md": "uv run ruff check scripts/ src/ tests/ fuzz/ addon/\n"}

    assert _documented_ruff_findings(reordered, [CI_CHECK, CI_FORMAT]) == []


def test_a_ci_command_the_classifier_cannot_read_is_reported_not_mirrored():
    """A flag before the directories leaves no document able to satisfy both halves."""
    flagged = [
        "uv run ruff check --output-format github src/ tests/ fuzz/ addon/ scripts/",
        CI_FORMAT,
    ]

    (finding,) = _unreadable_ci_commands(flagged)

    assert "--output-format" in finding


# The two ways prose names the installed add-in: a path under Fusion's AddIns
# directory, and the entry in the Scripts and Add-Ins dialog.  `Add-Ins → Run`,
# `Add-Ins → Stop` and `Add-Ins → Add` name the dialog's buttons rather than its
# entries, so those words are skipped; the set has its own test so it cannot be
# widened silently.  The dialog arrow is written three ways in this repo - `→`, `->`
# and `>` - and all three mean the same thing to a reader.
ADD_INS_PATH = re.compile(r"AddIns[/\\](?P<name>[A-Za-z0-9_.-]+)")
ADD_INS_DIALOG = re.compile(r"Add-Ins\s*(?:→|->|>)\s*(?P<name>[A-Za-z0-9_.-]+)")
DIALOG_BUTTONS = frozenset({"Run", "Stop", "Add"})
ADD_IN_DOCUMENTS = ("README.md", "devcontainer/README.md")
ADD_IN_FILE_SUFFIXES = (".manifest", ".py")


def _add_in_name_claims(text: str) -> list[tuple[int, str]]:
    """(line number, name a document gives the add-in) for every mention in *text*.

    A mention ending in `.manifest` or `.py` is naming the add-in's file, not a
    differently-named add-in, so the suffix comes off before the comparison.
    """
    claims = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in (ADD_INS_PATH, ADD_INS_DIALOG):
            for match in pattern.finditer(line):
                name = match.group("name").rstrip(".")
                for suffix in ADD_IN_FILE_SUFFIXES:
                    name = name.removesuffix(suffix)
                if name not in DIALOG_BUTTONS:
                    claims.append((number, name))
    return claims


def _add_in_name_findings(pages: dict[str, str], name: str) -> list[str]:
    """One finding per mention that calls the add-in something other than *name*."""
    return [
        f"{page}:{number} calls the add-in {found!r}; the manifest calls it {name!r}"
        for page, text in pages.items()
        for number, found in _add_in_name_claims(text)
        if found != name
    ]


def _documents_naming_the_add_in(pages: dict[str, str]) -> list[str]:
    """Documents that never name the add-in at all, in name order.

    Presence only: a wrong name is `_add_in_name_findings`'s finding, and asking this
    one for equality would report the same page twice.
    """
    return sorted(
        page
        for page in ADD_IN_DOCUMENTS
        if not _add_in_name_claims(pages.get(page, ""))
    )


def test_the_entry_module_is_named_after_the_manifest():
    entry = ADD_IN_MANIFEST.with_suffix(".py")

    assert entry.exists(), (
        f"Fusion loads {ADD_IN_NAME}.py beside {ADD_IN_MANIFEST.name}; {entry.name} is "
        "missing. The two files are one identity - a rename has to carry both."
    )


ADD_INS_TAIL = Path("Autodesk/Autodesk Fusion 360/API/AddIns")
"""Where the script puts the add-in, relative to whichever root it reads.

It reads ``$APPDATA`` on msys/cygwin and ``$HOME`` on darwin, and *both* are redirected
into the test's own directory.  ``OSTYPE`` is a bash shell variable, so redirecting only
the branch this bash appears to take would leave the other one able to reach the real
Fusion install - where the script's ``rm -rf "$TARGET"`` would delete it.
"""


def _bash() -> str:
    """A bash that is not Windows' WSL stub, or a skip.

    ``C:\\Windows\\System32\\bash.exe`` sits on PATH on every Windows runner and exits
    with "no installed distributions", so resolving ``bash`` by name alone can hand this
    test a shell that never runs the script.
    """
    candidates = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    usable = [
        candidate
        for candidate in candidates
        if candidate
        and "system32" not in candidate.lower()
        and Path(candidate).exists()
    ]
    if not usable:
        pytest.skip("no usable bash: only Windows' WSL stub was found")
    return usable[0]


def _installer_tree(tmp_path: Path, *stems: str) -> Path:
    """A throwaway repo holding only what the script reads: itself and its manifests.

    The script resolves ``addon/`` from its own location, so this copy is
    self-contained and the repository's ``addon/`` is never written to.  Variadic on
    purpose: Task 2 needs a tree with none and with two.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "addon").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "install-addon.sh", repo / "scripts")
    for stem in stems:
        shutil.copy2(ADD_IN_MANIFEST, repo / "addon" / f"{stem}.manifest")
    return repo


def _run_installer(repo: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the copied script against a throwaway add-ins root.

    ``OSTYPE`` is forced so every CI leg drives one branch, and decoding is explicit
    UTF-8: the script prints ``✓``, which cp1252 cannot hold.  Both roots the script
    can read are redirected, and the script's path is passed POSIX-style, because a
    literal ``C:\\...`` argument reaches bash with backslashes it does not resolve.
    """
    root = tmp_path / "root"
    (root / ADD_INS_TAIL).mkdir(parents=True)
    return subprocess.run(
        [_bash(), (repo / "scripts" / "install-addon.sh").as_posix()],
        env={**os.environ, "OSTYPE": "msys", "APPDATA": str(root), "HOME": str(root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.mark.parametrize("stem", [ADD_IN_NAME, "RenamedAddIn"])
def test_the_install_script_installs_under_the_name_its_manifest_declares(
    tmp_path: Path, stem: str
) -> None:
    """The installed folder follows the manifest's filename, whatever it is called.

    ``RenamedAddIn`` is the case that can fail: the script used to spell the name, so a
    manifest called anything else still installed as ``Fusion360MCP``.  The first
    parameter keeps a failure naming the real add-in instead of a fixture.
    """
    repo = _installer_tree(tmp_path, stem)

    result = _run_installer(repo, tmp_path)

    assert result.returncode == 0, result.stderr
    add_ins_dirs = [
        path for path in (tmp_path / "root").rglob("AddIns") if path.is_dir()
    ]
    assert len(add_ins_dirs) == 1, add_ins_dirs
    add_ins = add_ins_dirs[0]
    assert [path.name for path in add_ins.iterdir()] == [stem]
    assert (add_ins / stem / f"{stem}.manifest").exists(), (
        "the installed entry is not the add-in's own directory"
    )
    assert f"'{stem}'" in result.stdout, (
        "the instructions printed to the user name a different add-in than the folder "
        "that was installed"
    )
    other = "RenamedAddIn" if stem == ADD_IN_NAME else ADD_IN_NAME
    assert other not in result.stdout, (
        f"the output still names {other!r} as well as {stem!r}; one of the lines the "
        "script prints has its own copy of the name again"
    )


@pytest.mark.parametrize(
    ("stems", "expected"),
    [((), "found 0"), (("Fusion360MCP", "Second"), "Second.manifest")],
)
def test_the_install_script_refuses_when_addon_holds_no_single_manifest(
    tmp_path: Path, stems: tuple[str, ...], expected: str
) -> None:
    """Zero manifests reads as `*`, two crash with an "extra operand" - both refused.

    Neither message would tell a developer what is actually wrong with ``addon/``, and
    the zero case would install under a folder literally named ``*``.
    """
    repo = _installer_tree(tmp_path, *stems)

    result = _run_installer(repo, tmp_path)

    assert result.returncode != 0
    assert expected in result.stderr
    add_ins_dirs = [
        path for path in (tmp_path / "root").rglob("AddIns") if path.is_dir()
    ]
    assert len(add_ins_dirs) == 1, add_ins_dirs
    assert list(add_ins_dirs[0].iterdir()) == [], (
        "the script installed something anyway"
    )


def test_a_document_naming_the_add_in_uses_its_name():
    pages = {
        "README.md": "Shift+S → Add-Ins → WrongName → Run\n"
        "cp -r addon …/API/AddIns/WrongName\n",
        "docs/OTHER.md": "Shift+S → Add-Ins → Run\n",
    }

    findings = _add_in_name_findings(pages, ADD_IN_NAME)

    assert any("README.md:1" in each for each in findings)
    assert any("README.md:2" in each for each in findings)
    assert not any("OTHER.md" in each for each in findings)


def test_the_documents_that_install_the_add_in_still_name_it():
    pages = {name: "nothing here\n" for name in ADD_IN_DOCUMENTS}
    pages["README.md"] = "Shift+S → Add-Ins → Fusion360MCP → Run\n"

    missing = _documents_naming_the_add_in(pages)

    assert missing == ["devcontainer/README.md"]


def test_every_document_naming_the_add_in_uses_its_name():
    """The copies of the name the suite can read, and only one of them is functional.

    Fusion loads ``<name>.py`` beside ``<name>.manifest``, so those two are one
    identity; the install script and the two pages are the copies a reader follows
    afterwards.  A rename that carries four of five leaves someone hunting a folder
    that is not there.

    The script prints the name more often than this reads it - the ``TARGET`` it
    installs into and the instruction it echoes are checked, its comments are not - so
    the claim here is about the copies that are read, not every occurrence.

    The sweep reads tracked markdown, so a new page is covered the moment it exists, and
    README plus devcontainer/README.md must keep naming the add-in - otherwise a rename
    could quietly delete the mentions instead of updating them.
    """
    pages = {
        relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in _tracked_markdown(exclude=HISTORY_DOCUMENTS)
    }
    findings = _add_in_name_findings(pages, ADD_IN_NAME)
    missing = _documents_naming_the_add_in(pages)

    assert findings == [], (
        "a document calls the add-in something other than its manifest name: "
        + "; ".join(findings)
        + ". A dialog button (Run, Stop, Add) is not read as a name."
    )
    assert missing == [], (
        "these documents no longer name the add-in at all, so the check would pass "
        f"vacuously: {missing}"
    )


def test_a_path_naming_the_manifest_file_still_calls_the_add_in_by_name():
    """`AddIns/Fusion360MCP.manifest` names the add-in, not a differently-named one."""
    text = "copy it to AddIns/Fusion360MCP.manifest, beside AddIns/Fusion360MCP.py\n"

    assert _add_in_name_claims(text) == [(1, "Fusion360MCP"), (1, "Fusion360MCP")]


def test_the_dialog_entry_is_read_through_ascii_arrows_too():
    """The repo writes the same instruction with `>` in places; that is not a name."""
    for arrow in ("→", "->", ">"):
        assert _add_in_name_claims(f"Shift+S → Add-Ins {arrow} OtherTab\n") == [
            (1, "OtherTab")
        ]


def test_the_dialog_button_skip_list_is_exactly_the_buttons():
    """A wider skip list silences a name with no test noticing; pin it."""
    assert {"Run", "Stop", "Add"} == DIALOG_BUTTONS
