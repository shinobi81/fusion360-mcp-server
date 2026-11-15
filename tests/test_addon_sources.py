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


@pytest.mark.parametrize(
    "label, body",
    [
        ("parenthesised", "except (TypeError, ValueError):"),
        ("single exception", "except OSError:"),
        ("aliased tuple", "except (TypeError, ValueError) as exc:"),
        ("aliased single", "except OSError as exc:"),
        ("starred", "except* (TypeError, ValueError):"),
        ("wrapped across lines", "except (\n    TypeError,\n):"),
    ],
    ids=lambda label: label,
)
def test_the_checker_accepts_the_forms_fusion_can_parse(label, body):
    """Every spelling Fusion parses, with the case named in the id."""
    source = "try:\n    pass\n" + body + "\n    pass\n"
    assert unparenthesised_except_tuples(source) == [], label


@pytest.mark.parametrize(
    "body",
    ["except TypeError, ValueError:", "except* TypeError, ValueError:"],
)
def test_the_checker_trips_on_the_forbidden_form(body):
    """The guard own test: a checker that cannot fail protects nothing."""
    source = "try:\n    pass\n" + body + "\n    pass\n"
    assert unparenthesised_except_tuples(source) == [3], body


def test_the_checker_ignores_the_phrase_in_a_comment():
    """The docstring case is tested above; this pins the same claim for comments."""
    source = "x = 1  # turns except A, B: into except (A, B):\n"
    assert unparenthesised_except_tuples(source) == []


def test_the_checker_accepts_a_single_exception_with_an_alias():
    source = "try:\n    pass\nexcept OSError as exc:\n    pass\n"
    assert unparenthesised_except_tuples(source) == []


def test_the_add_in_tolerates_a_bad_port_like_the_server_does():
    """``FUSION_MCP_PORT`` is parsed twice, in two languages of one contract.

    The add-in cannot import the server package (separate interpreter, separate
    install) and the server cannot import the add-in, so the tolerance is
    duplicated. It is asserted here because the two halves are one setting: a
    server that falls back to 9876 while the add-in refuses to start leaves the
    user with an add-in that is running nothing and a server looking for it.
    """
    add_in = (ADDON / "Fusion360MCP.py").read_text(encoding="utf-8")
    server = (ADDON.parent / "src" / "fusion360_mcp" / "connection.py").read_text(
        encoding="utf-8"
    )

    assert "except ValueError:" in add_in, (
        "the add-in parses FUSION_MCP_PORT without tolerating a typo"
    )
    assert "port = 9876" in add_in
    assert "def default_port() -> int:" in server
    assert "return 9876" in server
