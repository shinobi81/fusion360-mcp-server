"""Fuzz target: ``parameter_units`` must render finite values as finite text.

A unit string reaches Fusion as an expression, so junk that survives here
becomes a broken parameter rather than a failed tool call. The payload is two
independent regions: the first 8 bytes are the value (``<d``, the narrowest
thing Fusion accepts as a real) and the bytes after them are the unit, so a
payload can carry a real unit like ``mm`` rather than a float's own encoding.
"""

import math
import struct

from addon.server.parameter_units import (
    expression_for,
    needs_expression,
    normalise_unit,
)

from ._common import decode


def check(data: bytes) -> None:
    value = struct.unpack("<d", (data + b"\x00" * 8)[:8])[0]
    unit = decode(data[8:72])

    # Deliberately above the isfinite guard: the two unit functions must hold
    # their return types for non-finite input too, so moving these inside the
    # branch would silently narrow the target.
    assert isinstance(normalise_unit(unit), str)
    assert isinstance(needs_expression(unit), bool)

    if math.isfinite(value):
        expr = expression_for(value, unit)
        assert isinstance(expr, str) and expr
        # Only the numeric token is expression_for's rendering of *value*:
        # the unit is interpolated verbatim, so "nan" in a junk unit
        # (b"nan", b"info") is benign and must not fail the target.
        number = expr.split(" ", 1)[0]
        assert "inf" not in number.lower() and "nan" not in number.lower()


def main(argv: list[str]) -> None:
    # atheris has no Windows wheel, so it is imported here and never at module
    # level: the target has to import on every platform for the tests.
    import atheris

    atheris.Setup(argv, check)
    atheris.Fuzz()


if __name__ == "__main__":
    import sys

    main(sys.argv)
