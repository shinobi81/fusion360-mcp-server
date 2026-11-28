"""``docs/TOOLS.md`` carries a claim per tool, so it is guarded both ways.

The catalogue exists because nothing recorded which of the tools had ever been called
against a real Fusion: the repo's three invented ``adsk`` names were found by hand, and
``scripts/check_fusion_api.py`` proves *names*, never behaviour. This module fails the
suite when a row and ``src/fusion360_mcp/tools.py`` disagree in either direction, when a
row claims a probe without saying when/against which build/where, when a row's derived
``Proven`` cell drifts from its own evidence, and when a doc that should point at the
record stops doing so.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from fusion360_mcp.tools import _READ_ONLY, TOOLS, get_tool_by_name

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs" / "TOOLS.md"

#: A whole tool table, four cells wide: the shape every fixture below starts from.
_TABLE_HEAD = "| Tool | Proven | Description | Evidence |\n| --- | --- | --- | --- |\n"


def _load(name: str, filename: str):
    """Load a script by path: ``scripts/`` is not a package, and a ``sys.path``
    insertion is what the sibling script test avoids."""
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load("check_proven", "check_proven.py")
#: The pattern a proven row's version lives in - the checker's own, never a copy.
CELL_VERSION = CHECKER._PROVEN_RE
check = CHECKER.check
parse_table = CHECKER.parse_table


@pytest.fixture(scope="module")
def text() -> str:
    return CATALOGUE.read_text(encoding="utf-8")


def _unproven_row(text: str):
    return next(row for row in parse_table(text) if not row.proven)


def test_the_table_is_well_formed(text):
    assert check(text) == []


def test_every_tool_has_exactly_one_row(text):
    names = [row.tool for row in parse_table(text)]

    assert sorted(names) == sorted(tool["name"] for tool in TOOLS)
    assert len(names) == len(set(names)) == len(TOOLS)


def test_only_tool_tables_are_read():
    """The catalogue also carries a legend and argument breakdowns; neither is a row.

    ``docs/TOOLS.md`` holds seventeen tool tables beside a table whose first cells are
    ``x``, ``y`` and ``z``. A parser that read every ``|``-line would report three rows
    naming no tool, so the header decides - and this is the test that says so.
    """
    legend = "| x | y | z |\n| --- | --- | --- |\n| `extrude` | `sweep` | `loft` |\n"
    with_tool = _TABLE_HEAD + "| `ping` | `2706.1.17` | d | unproven — x |\n"

    assert parse_table(legend) == []
    assert [row.tool for row in parse_table(with_tool + "\n" + legend)] == ["ping"]


def test_a_missing_row_is_reported(text):
    """The direction that matters when a tool is added: silence would be the defect."""
    dropped = next(row for row in parse_table(text) if row.proven)
    trimmed = "".join(
        line
        for line in text.splitlines(keepends=True)
        if not line.startswith(f"| `{dropped.tool}`")
    )
    assert trimmed != text, "fixture must actually remove the row"

    problems = check(trimmed)

    assert any(dropped.tool in problem and "no row" in problem for problem in problems)


def test_a_row_naming_no_tool_is_reported(text):
    invented = "| `no_such_tool` | — | invented by the test | unproven — x |\n"

    problems = check(text + invented)

    assert any(
        "no_such_tool" in problem and "naming no tool" in problem
        for problem in problems
    )


@pytest.mark.parametrize(
    "mutant",
    [
        "proven — `2706.1.17`, #1: no date",
        "proven — 2026-11-26, 2706.1.17, #1: version not in backticks",
        "proven — 2026-11-26, `2706.1.17`: no PR number",
        "proven — 2026-11-26, `2706.1.17`, #1:",
        "proven — 26-11-2026, `2706.1.17`, #1: the date is not a date",
        "proven — 2026-11-26, `2706`, #1: a one-part build number",
    ],
)
def test_a_proven_row_must_cite_a_date_a_build_a_pr_and_what(text, mutant):
    """One mutant per field, so relaxing any one of them fails this test."""
    proven = next(row for row in parse_table(text) if row.proven)
    broken = text.replace(proven.evidence, mutant)
    assert broken != text, "fixture must actually change the row"

    assert any(proven.tool in problem for problem in check(broken)), mutant


def test_an_unproven_row_must_read_unproven(text):
    """A row missing the state word is reported as malformed, not as an unknown state.

    ``"unproven — "`` would strip to ``"unproven —"`` and trip the *state* branch, so
    the mutant keeps the word and drops the separator."""
    unproven = _unproven_row(text)
    broken = text.replace(unproven.evidence, "unproven")
    assert broken != text

    assert any("must read" in problem for problem in check(broken)), check(broken)


@pytest.mark.parametrize(
    "placeholder",
    ["not yet", "todo", "tbd", "N/A", "n/a", "unknown", "none", "nothing", "-"],
)
def test_a_placeholder_is_not_a_reason(text, placeholder):
    """The preamble says "not yet" is not a reason, so a rule that accepts anything
    non-empty is not the rule it describes."""
    unproven = _unproven_row(text)
    broken = text.replace(unproven.evidence, f"unproven — {placeholder}")
    assert broken != text

    assert any("placeholder" in problem for problem in check(broken)), placeholder


def test_a_row_that_does_not_parse_is_reported_not_dropped(text):
    """A stray or mis-piped line used to vanish, and the reader trusts what is left."""
    broken = text + "| `ping` | — | unproven — x |\n"

    assert any("four cells" in problem for problem in check(broken))


def test_a_duplicate_row_is_reported(text):
    row = parse_table(text)[0]
    broken = text + f"| `{row.tool}` | — | duplicate | {row.evidence} |\n"

    assert any("more than once" in problem for problem in check(broken))


def test_a_state_word_nothing_defines_is_reported(text):
    row = parse_table(text)[0]
    broken = text.replace(row.evidence, "probably fine — nothing measured")

    assert any("unknown state" in problem for problem in check(broken))


def test_the_live_subset_is_read_only_and_names_real_parameters():
    """``--live`` executes whatever is in ``LIVE_CALLS``/``LIVE_BODY_CALLS`` against the
    caller's document.  Both facts it rests on are asserted: the tools are read-only,
    and each parameter name exists in that tool's schema - a mutating tool or a renamed
    argument would otherwise be found by whoever runs it."""
    live = set(CHECKER.LIVE_CALLS) | set(CHECKER.LIVE_BODY_CALLS)

    # The subset relation is asserted at import (`_LIVE_TOOLS <= _READ_ONLY`), so a
    # mutating entry fails collection; the counts are what no test could see until here,
    # and the catalogue's preamble quotes them.
    assert len(_READ_ONLY) == 19, "_READ_ONLY grew or shrank: update docs/TOOLS.md"
    assert len(live) == 12, "the 'twelve of the nineteen' in the docs is stale"
    for tool, params in CHECKER.LIVE_CALLS.items():
        declared = (
            (get_tool_by_name(tool) or {}).get("inputSchema", {}).get("properties", {})
        )
        assert set(params) <= set(declared), (tool, sorted(set(params) - set(declared)))
    for tool, parameter in CHECKER.LIVE_BODY_CALLS.items():
        declared = (
            (get_tool_by_name(tool) or {}).get("inputSchema", {}).get("properties", {})
        )
        assert parameter in declared, (tool, parameter)


# ── the live half, offline ────────────────────────────────────────────
#
# `probe()` needs a running add-in, but everything it feeds is pure, so the judgement
# and the exit codes are pinned without one.

_PROVEN_ROW = "proven — 2026-11-26, `2706.1.17`, #158: answered"


def test_a_proven_row_whose_call_fails_is_a_mismatch():
    rows = [CHECKER.Row("ping", _PROVEN_ROW)]
    replies = {"ping": {"ok": False, "error_kind": "TIMEOUT", "error_message": "x"}}

    problems = CHECKER.live_mismatches(replies, rows)

    assert len(problems) == 1
    assert "ping" in problems[0] and "TIMEOUT" in problems[0]


def test_an_unproven_row_whose_call_answers_is_a_mismatch():
    """The table being out of date is the other half of the check."""
    rows = [CHECKER.Row("ping", "unproven — nothing measured")]
    problems = CHECKER.live_mismatches({"ping": {"ok": True}}, rows)

    assert len(problems) == 1
    assert "record it" in problems[0]


def test_an_agreeing_reply_is_not_a_mismatch():
    rows = [CHECKER.Row("ping", _PROVEN_ROW)]

    assert CHECKER.live_mismatches({"ping": {"ok": True}}, rows) == []


def test_a_proven_tool_the_probe_skipped_is_a_note_not_a_failure():
    """A proven tool `--live` has no call for must not make the check red."""
    rows = [CHECKER.Row("ping", _PROVEN_ROW)]

    assert CHECKER.live_mismatches({}, rows) == []
    assert CHECKER.not_probed({}, rows) == [
        "ping: proven, but --live sent it no call here (no root body to name, "
        "or no LIVE_CALLS entry)"
    ]


def test_a_bridge_failure_becomes_a_reply_not_a_traceback():
    """`send_command` raises for a refusal and for an exhausted read-only timeout; both
    must reach `live_mismatches` as a reply, or `--live` dies before printing what it
    already found."""
    from fusion360_mcp.connection import FusionError

    class _Raising:
        def __init__(self, exc):
            self.exc = exc

        def send_command(self, tool, params):
            raise self.exc

    refused = CHECKER._send(
        _Raising(FusionError("x", error_kind="TIMEOUT")), "ping", {}
    )
    lost = CHECKER._send(_Raising(ConnectionError("lost")), "ping", {})
    truncated = CHECKER._send(_Raising(ValueError("Expecting value")), "ping", {})

    assert refused == {"ok": False, "error_kind": "TIMEOUT", "error_message": "x"}
    assert lost["ok"] is False
    assert lost["error_kind"] == "CONNECTION_LOST"
    assert "lost" in lost["error_message"]
    assert truncated["ok"] is False and truncated["error_kind"] == "CONNECTION_LOST"


def test_a_row_indented_under_the_table_is_still_a_row():
    """A row a formatter indented is a row: the reader strips the line, not the file."""
    indented = (
        "  | Tool | Proven | Description | Evidence |\n"
        "  | --- | --- | --- | --- |\n"
        "  | `ping` | — | d | unproven — nothing measured |\n"
    )

    assert [row.tool for row in parse_table(indented)] == ["ping"]
    assert CHECKER.malformed_lines(indented) == []


def test_an_aligned_separator_is_not_a_row():
    """``| :--- | ---: |`` is what a formatter writes; it is not a tool named ':---'."""
    aligned = (
        "| Tool | Proven | Description | Evidence |\n| :--- | ---: | --- | --- |\n"
    )

    assert parse_table(aligned) == []
    assert CHECKER.malformed_lines(aligned) == []


def test_a_live_run_with_no_add_in_still_prints_the_table_s_problems(
    monkeypatch, tmp_path, text, capsys
):
    proven = next(row for row in parse_table(text) if row.proven)
    broken = tmp_path / "TOOLS.md"
    broken.write_text(
        text.replace(proven.evidence, "unproven — not yet"), encoding="utf-8"
    )
    monkeypatch.setattr(CHECKER, "CATALOGUE", broken)
    monkeypatch.setattr(CHECKER, "probe", lambda host, port: None)

    assert CHECKER.main(["--live"]) == 1
    assert "the table was checked alone" in capsys.readouterr().err


def test_main_exits_non_zero_for_a_broken_table_and_zero_for_a_good_one(
    monkeypatch, tmp_path, text
):
    proven = next(row for row in parse_table(text) if row.proven)
    good = tmp_path / "good.md"
    good.write_text(text, encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text(
        text.replace(proven.evidence, "unproven — not yet"), encoding="utf-8"
    )

    monkeypatch.setattr(CHECKER, "CATALOGUE", good)
    assert CHECKER.main([]) == 0
    monkeypatch.setattr(CHECKER, "CATALOGUE", bad)
    assert CHECKER.main([]) == 1


def test_the_docs_say_where_the_record_lives():
    """A record nobody is sent to is a record nobody reads — and the path, not the
    word, is what a reader can follow."""
    catalogue = CATALOGUE.read_text(encoding="utf-8")

    assert "``proven — YYYY-MM-DD" in catalogue, (
        "docs/TOOLS.md must document the Evidence convention it is read by"
    )
    assert "`docs/TOOLS.md`" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")


# ── the derived Proven column ─────────────────────────────────────────
#
# The version a reader scans is generated from the Evidence cell beside it, so the two
# cannot drift: a hand-edited cell fails here, and the script is the only writer.

SYNC = _load("sync_proven_column", "sync_proven_column.py")


def test_the_proven_column_is_the_version_each_row_cites(text):
    """Rendering the catalogue reproduces it byte for byte, cells included."""
    assert SYNC.render(text) == text, (
        "docs/TOOLS.md's Proven column is stale: "
        "run uv run python scripts/sync_proven_column.py"
    )


def test_the_column_says_the_build_the_row_cites(text):
    """The cells, read back: one per row, the row's own version, a dash where none."""
    cells = SYNC.cells_by_tool(text)
    rows = {row.tool: row for row in parse_table(text)}

    assert set(cells) == set(rows)
    for tool, row in rows.items():
        version = CELL_VERSION.match(row.evidence)
        assert cells[tool] == (f"`{version.group('version')}`" if version else "—")


def test_a_stale_cell_is_reported(text):
    """The direction that matters: a hand-edited cell must fail, not pass quietly."""
    proven_tool = next(row.tool for row in parse_table(text) if row.proven)
    lines = text.splitlines(keepends=True)
    index = next(
        number
        for number, line in enumerate(lines)
        if line.startswith(f"| `{proven_tool}`")
    )
    cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
    assert cells[1] != "—", "the fixture picked an unproven tool"
    lines[index] = lines[index].replace(cells[1], "`9999.0.0`", 1)
    edited = "".join(lines)

    assert edited != text, "the fixture did not change the file"
    assert SYNC.render(edited) != edited
