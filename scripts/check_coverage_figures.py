"""Check that every coverage figure quoted in the docs is the one this tree measures.

`test_packaging.py` guards the rule set a document quotes.  Nothing guarded the
number beside it, and that number moves whenever a test reaches new lines: inside
one parcel it went 60.73 -> 61.27 -> 61.44, and each move silently invalidated
`docs/TESTING.md` and the comment above `addopts` in `pyproject.toml`.  A stale
figure is a false claim no gate sees.

The check cannot live inside the suite, because the measured total is the thing
being measured and is only complete once pytest has finished writing `.coverage`.
So it runs from CI after the test step, alongside the `src/` floor it complements.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each document states the figure in its own voice, so each gets its own pattern,
# and each must still match: a reflow that moves the number off the line would
# otherwise leave the check passing nothing.  CHANGELOG.md is deliberately absent -
# its percentages describe releases, not this tree, and stay true of the release
# they describe.
READERS = (
    ("docs/TESTING.md", re.compile(r"measured total is ([\d.]+)%")),
    ("pyproject.toml", re.compile(r"#\s*([\d.]+)% over both packages")),
)


def quoted(text: str, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """Every (line number, quoted percentage) in *text* that *pattern* matches."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        match = pattern.search(line)
        if match is not None:
            found.append((number, match.group(1)))
    return found


def problems(pages: dict[str, str], measured: str) -> list[str]:
    """One message per document missing a figure or disagreeing with *measured*."""
    found_problems = []
    for name, pattern in READERS:
        found = quoted(pages.get(name, ""), pattern)
        if not found:
            found_problems.append(
                f"{name} no longer quotes the measured figure; this check is vacuous"
            )
            continue
        for number, value in found:
            if value != measured:
                found_problems.append(
                    f"{name}:{number} quotes {value}%, the run measured {measured}%"
                )
    return found_problems


def current_coverage() -> str:
    """The measured total, from coverage's own report, spelled as the docs do."""
    completed = subprocess.run(
        [sys.executable, "-m", "coverage", "report", "--format=total", "--precision=2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"coverage report failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def main() -> int:
    measured = current_coverage()
    pages = {name: (ROOT / name).read_text(encoding="utf-8") for name, _ in READERS}
    found_problems = problems(pages, measured)
    for problem in found_problems:
        print(problem)
    if found_problems:
        print(
            f"\nquote {measured}% in the documents above: that is what this run "
            "measured",
            file=sys.stderr,
        )
        return 1
    print(f"{len(READERS)} documents quote the measured figure ({measured}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
