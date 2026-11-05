"""Fuzz target: ``classify()`` must always return a usable ``(kind, hints)``.

The four invariants are what callers of a failed tool rely on: a kind they can
branch on, hints they can print, and never a rule match that yields no hint.
"""

from addon.server.hints import _RULES, classify

from ._common import decode

KNOWN_KINDS = frozenset(kind for _, kind, _ in _RULES) | {"UNKNOWN"}


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
