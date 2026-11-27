"""``docs/PROVEN.md`` is a claim per tool, so it is guarded both ways.

The table exists because nothing recorded which of the tools had ever been called
against a real Fusion: the repo's three invented ``adsk`` names were found by hand, and
``scripts/check_fusion_api.py`` proves *names*, never behaviour. This module fails the
suite when the table and ``src/fusion360_mcp/tools.py`` disagree in either direction,
when a row claims a probe without saying when/against which build/where, and when a doc
that should point at the table stops doing so.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from fusion360_mcp.tools import _READ_ONLY, TOOLS, get_tool_by_name

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROVEN = ROOT / "docs" / "PROVEN.md"


def _load_checker():
    """Load ``scripts/check_proven.py`` by path: ``scripts/`` is not a package, and a
    ``sys.path`` insertion is what the sibling script test avoids."""
    path = ROOT / "scripts" / "check_proven.py"
    spec = importlib.util.spec_from_file_location("check_proven", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()
check = CHECKER.check
parse_table = CHECKER.parse_table


@pytest.fixture(scope="module")
def text() -> str:
    return PROVEN.read_text(encoding="utf-8")


def test_the_table_is_well_formed(text):
    assert check(text) == []


def test_every_tool_has_exactly_one_row(text):
    names = [row.tool for row in parse_table(text)]

    assert sorted(names) == sorted(tool["name"] for tool in TOOLS)
    assert len(names) == len(set(names)) == len(TOOLS)


def test_a_missing_row_is_reported(text):
    """The direction that matters when a tool is added: silence would be the defect."""
    rows = parse_table(text)
    dropped = next(row for row in rows if row.proven)
    trimmed = text.replace(f"| `{dropped.tool}` | {dropped.evidence} |\n", "")

    problems = check(trimmed)

    assert any(dropped.tool in problem and "no row" in problem for problem in problems)


def test_a_row_naming_no_tool_is_reported(text):
    problems = check(text + "\n| `no_such_tool` | unproven — invented by the test |\n")

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
    unproven = next(row for row in parse_table(text) if row.tool == "scale_body")
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
    unproven = next(row for row in parse_table(text) if row.tool == "scale_body")
    broken = text.replace(unproven.evidence, f"unproven — {placeholder}")
    assert broken != text

    assert any("placeholder" in problem for problem in check(broken)), placeholder


def test_a_row_that_does_not_parse_is_reported_not_dropped(text):
    """A stray or mis-piped line used to vanish, and the reader trusts what is left."""
    broken = text + "\n| `ping` | unproven — x | extra cell |\n"

    assert any("exactly two cells" in problem for problem in check(broken))


def test_a_duplicate_row_is_reported(text):
    row = parse_table(text)[0]
    broken = text + f"\n| `{row.tool}` | {row.evidence} |\n"

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
    # and three docs quote them.
    assert len(_READ_ONLY) == 18, "_READ_ONLY grew or shrank: update PROVEN.md/TOOLS.md"
    assert len(live) == 12, "the 'twelve of the eighteen' in the docs is stale"
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

    assert refused == {"ok": False, "error_kind": "TIMEOUT", "error_message": "x"}
    assert lost["ok"] is False
    assert lost["error_kind"] == "CONNECTION_LOST"
    assert "lost" in lost["error_message"]


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

    monkeypatch.setattr(CHECKER, "PROVEN", good)
    assert CHECKER.main([]) == 0
    monkeypatch.setattr(CHECKER, "PROVEN", bad)
    assert CHECKER.main([]) == 1


@pytest.mark.parametrize("doc", ["docs/TOOLS.md", "AGENTS.md"])
def test_the_docs_point_at_the_table(doc):
    """A record nobody is sent to is a record nobody reads - and the path, not the word,
    is what a reader can follow."""
    assert "`docs/PROVEN.md`" in (ROOT / doc).read_text(encoding="utf-8")
