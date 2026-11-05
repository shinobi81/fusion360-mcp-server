"""Fuzz target: ``classify()`` must always return a usable ``(kind, hints)``.

The four invariants are what callers of a failed tool rely on: a kind they can
branch on, hints they can print, and never a rule match that yields no hint.
"""

from addon.server.hints import classify

from ._common import decode

KNOWN_KINDS = frozenset(
    {
        "AXIS_OUT_OF_PLANE",
        "BODY_NOT_FOUND",
        "BOOLEAN_NO_OP",
        "DESIGN_TYPE_MISMATCH",
        "INVALID_INPUT",
        "NOT_ENTITLED",
        "NO_ACTIVE_DESIGN",
        "PROFILE_NOT_CLOSED",
        "REGEN_FAILED",
        "SELF_INTERSECTION",
        "SKETCH_NOT_FOUND",
        "TIMEOUT",
        "UNKNOWN_COMMAND",
        "UNKNOWN",
    }
)
# Spelled out rather than derived from `_RULES` on purpose. A set computed from
# the rules agrees with them by construction, so `kind in KNOWN_KINDS` could
# never fail; a literal is what makes a typo in a new rule's kind a red target.
# Adding a rule with a new kind means adding it here too.


def check(data: bytes) -> None:
    kind, hints = classify(decode(data))
    assert kind in KNOWN_KINDS, kind
    assert isinstance(hints, list)
    assert all(isinstance(h, str) and h for h in hints)
    assert hints or kind == "UNKNOWN"


def main(argv: list[str]) -> None:
    # atheris has no Windows wheel, so it is imported here and never at module
    # level: the target has to import on every platform for the tests below.
    import atheris

    atheris.Setup(argv, check)
    atheris.Fuzz()


if __name__ == "__main__":
    import sys

    main(sys.argv)
