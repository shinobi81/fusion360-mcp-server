"""Drift guards for the Python support window.

The window is stated in ``requires-python``, in the ``Programming Language ::
Python :: 3.x`` classifiers, and in ``[tool.pyright]`` (a type checker cannot
infer it).  Once, these disagreed for four years while nobody looked — the floor
said 3.10 and 3.10 was already EOL.  These tests read the floor and fail the
suite when any surface falls out of step with it, when a tool grows a second copy
of the floor that can drift independently, when a document quotes a lint rule set
the configuration no longer has, when CI stops running a gate those configurations
describe, when the add-in's Fusion manifest declares a version the release does
not, when it changes the id it declares, or when a documented install snippet pins a
release other than the one being cut.
"""

from __future__ import annotations

import json
import re
import subprocess
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


def _add_in_manifest() -> dict:
    """The Fusion manifest as data.

    Strict JSON, because Fusion parses it with the same rules: a comment or a trailing
    comma makes the add-in unloadable, not merely this module red.
    """
    manifest = REPO_ROOT / "addon" / "Fusion360MCP.manifest"
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
