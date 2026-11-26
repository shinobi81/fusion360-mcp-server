"""``docs/PROVEN.md`` is a claim per tool, so it is guarded both ways.

The table exists because nothing recorded which of the tools had ever been called
against a real Fusion: the repo's three invented ``adsk`` names were found by hand, and
``scripts/check_fusion_api.py`` proves *names*, never behaviour. This module fails the
suite when the table and ``src/fusion360_mcp/tools.py`` disagree in either direction,
when a row claims a probe without saying when/against which build/where, and when a doc
that should point at the table stops doing so.
"""

from __future__ import annotations

import pathlib

import pytest

from fusion360_mcp.tools import TOOLS
from scripts.check_proven import check, parse_table

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROVEN = ROOT / "docs" / "PROVEN.md"


@pytest.fixture(scope="module")
def text() -> str:
    return PROVEN.read_text(encoding="utf-8")


def _rows(text: str):
    return parse_table(text)


def test_the_table_is_well_formed(text):
    assert check(text) == []


def test_every_tool_has_exactly_one_row(text):
    names = [row.tool for row in _rows(text)]

    assert sorted(names) == sorted(tool["name"] for tool in TOOLS)
    assert len(names) == len(set(names)) == len(TOOLS)


def test_a_missing_row_is_reported(text):
    """The direction that matters when a tool is added: silence would be the defect."""
    rows = _rows(text)
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


def test_a_proven_row_must_cite_a_date_a_build_and_a_pr(text):
    rows = _rows(text)
    proven = next(row for row in rows if row.proven)
    without_pr = proven.evidence.replace(
        f"#{proven.evidence.split('#')[1].split(':')[0]}", "#0"
    )
    assert without_pr != proven.evidence, "fixture must actually change the row"
    broken = text.replace(proven.evidence, "proven — 2026-11-26, no build, no PR")

    assert any(proven.tool in problem for problem in check(broken))


def test_an_unproven_row_must_say_why(text):
    rows = _rows(text)
    unproven = next(row for row in rows if not row.proven)
    broken = text.replace(unproven.evidence, "unproven — ")

    assert any(unproven.tool in problem for problem in check(broken))


def test_a_state_word_nothing_defines_is_reported(text):
    rows = _rows(text)
    row = rows[0]
    broken = text.replace(row.evidence, "probably fine — nothing measured")

    assert any(row.tool in problem for problem in check(broken))


@pytest.mark.parametrize("doc", ["docs/TOOLS.md", "AGENTS.md"])
def test_the_docs_point_at_the_table(doc):
    """A record nobody is sent to is a record nobody reads."""
    assert "PROVEN.md" in (ROOT / doc).read_text(encoding="utf-8")


def test_every_proven_row_cites_this_repository_s_pr_convention(text):
    """``#157``-style numbers, not links: the evidence lives in the PR body, and a bare
    number is what ``check_proven.py`` can parse."""
    for row in _rows(text):
        if not row.proven:
            continue
        assert "#" in row.evidence, row.tool
        number = row.evidence.split("#")[1].split(":")[0]
        assert number.isdigit(), (row.tool, number)
