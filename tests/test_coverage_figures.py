"""The coverage percentage quoted in the docs must match the measurement.

`test_packaging.py` guards the *rule set* a document quotes. Nothing guarded the
*number* next to it, and the number moves whenever a test reaches new lines: inside
one parcel it went 60.73 -> 61.27 -> 61.44, and each move silently invalidated two
documents. A stale percentage is a false claim no gate can see, which is why the
check lives in `scripts/check_coverage_figures.py` and runs in CI after pytest,
when `.coverage` is complete.

These tests drive the check's logic with a synthetic measurement, because a test
cannot know the run's own total; the end-to-end comparison is the CI step.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_coverage_figures import READERS, problems, quoted  # noqa: E402

TESTING = "docs/TESTING.md"
PYPROJECT = "pyproject.toml"


def _pages(**overrides: str) -> dict[str, str]:
    """The real documents, with any named one replaced by the given text."""
    pages = {name: (ROOT / name).read_text(encoding="utf-8") for name, _ in READERS}
    pages.update(overrides)
    return pages


def test_the_changelog_is_not_read_because_its_figures_are_history():
    """A release note states what that release measured; it must not be checked."""
    assert "CHANGELOG.md" not in [name for name, _ in READERS]


@pytest.mark.parametrize(("name", "pattern"), READERS)
def test_every_document_still_states_the_figure_in_the_spelling_this_check_reads(
    name, pattern
):
    """A reflow that moves the number off the line empties the check silently."""
    assert quoted((ROOT / name).read_text(encoding="utf-8"), pattern), (
        f"{name} no longer matches {pattern.pattern!r}; the check would pass vacuously"
    )


def test_a_document_quoting_the_measured_figure_passes():
    pages = _pages(**{TESTING: "The measured total is 61.44%; the add-in dominates.\n"})

    assert problems(pages, "61.44") == []


def test_a_stale_figure_is_named_with_its_line_and_both_numbers():
    pages = _pages(
        **{TESTING: "Coverage.\nThe measured total is 60.73%; the add-in.\n"}
    )

    (problem,) = problems(pages, "61.44")

    assert f"{TESTING}:2" in problem
    assert "60.73" in problem
    assert "61.44" in problem


def test_a_document_that_stops_quoting_the_figure_fails_instead_of_passing():
    pages = _pages(**{TESTING: "The measured total is not stated here.\n"})

    (problem,) = problems(pages, "61.44")

    assert "vacuous" in problem
    assert TESTING in problem


def test_both_documents_are_checked_not_just_the_first():
    pages = _pages(
        **{
            TESTING: "The measured total is 61.44%.\n",
            PYPROJECT: "# 60.73% over both packages, so the floor is 59\n",
        }
    )

    (problem,) = problems(pages, "61.44")

    assert PYPROJECT in problem
