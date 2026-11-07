"""The add-in must stay parseable by Fusion's interpreter, not only by ours.

``addon/`` runs on the Python Fusion ships, which ``project.requires-python`` does
not govern — that is why ``ruff format`` is deliberately not run over the
directory.  PEP 758 (3.14) made the parentheses around an ``except`` tuple
optional, so a formatter targeting this package's floor rewrites

    except (TypeError, ValueError):

into

    except TypeError, ValueError:

which is legal for this package and not legal on an older interpreter.  It has
been rewritten that way by a local formatter hook four times in one session, and
CI cannot see it: ``ruff check`` parses both spellings to the same tree at the
3.14 target, and the formatter gate excludes ``addon/`` on purpose.

So this module is the copy that notices.  It reads the add-in's source tokens
rather than running a regex over the text, because prose about ``except`` in a
docstring must not be able to trip a guard that blocks every pull request.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon"


def unparenthesised_except_tuples(source: str) -> list[int]:
    """Line numbers where an ``except`` clause names two types without brackets.

    Walks the token stream, so a docstring or a comment quoting the forbidden
    form is invisible.  An ``except`` whose header reaches a top-level comma
    before its colon is the form; ``except (A, B)`` keeps the comma inside the
    brackets, where the depth counter ignores it.
    """
    hits: list[int] = []
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string != "except":
            continue
        depth = 0
        for follower in tokens[index + 1 :]:
            if follower.type == tokenize.OP:
                if follower.string in "([{":
                    depth += 1
                elif follower.string in ")]}":
                    depth -= 1
                elif follower.string == "*":
                    # `except*` groups: same syntax question, same answer.
                    continue
                elif depth == 0 and follower.string == ",":
                    hits.append(token.start[0])
                    break
                elif depth == 0 and follower.string == ":":
                    break
            if follower.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                break
    return hits


def addon_sources() -> list[Path]:
    return sorted(ADDON.rglob("*.py"))


def test_the_addon_has_sources_to_check():
    """A glob that matched nothing would make every case below vacuous."""
    assert addon_sources(), f"no Python files under {ADDON}"


@pytest.mark.parametrize(
    "path", addon_sources(), ids=lambda path: str(path.relative_to(ADDON))
)
def test_no_add_in_file_names_an_except_tuple_without_brackets(path):
    hits = unparenthesised_except_tuples(path.read_text(encoding="utf-8"))
    assert hits == [], (
        f"{path.relative_to(ADDON)}:{hits} uses PEP 758 syntax. It is legal for "
        "this package and not legal on Fusion's interpreter; restore the "
        "parentheses, and stop the formatter that removed them"
    )


def test_the_checker_trips_on_the_forbidden_form():
    """The guard's own test: a checker that cannot fail protects nothing."""
    source = "try:\n    pass\nexcept TypeError, ValueError:\n    pass\n"
    assert unparenthesised_except_tuples(source) == [3]


def test_the_checker_accepts_the_parenthesised_form():
    source = "try:\n    pass\nexcept (TypeError, ValueError):\n    pass\n"
    assert unparenthesised_except_tuples(source) == []


def test_the_checker_accepts_a_single_exception():
    source = "try:\n    pass\nexcept OSError:\n    pass\n"
    assert unparenthesised_except_tuples(source) == []


def test_the_checker_accepts_an_alias_after_a_tuple():
    source = "try:\n    pass\nexcept (TypeError, ValueError) as exc:\n    pass\n"
    assert unparenthesised_except_tuples(source) == []


def test_the_checker_ignores_the_phrase_inside_a_docstring():
    """Prose must not block every pull request."""
    source = '"""Turns `except A, B:` into something else."""\n'
    assert unparenthesised_except_tuples(source) == []
