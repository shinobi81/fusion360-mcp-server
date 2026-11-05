"""Fuzz target: ``parameter_units`` must render finite values as finite text.

A unit string reaches Fusion as an expression, so junk that survives here
becomes a broken parameter rather than a failed tool call. The value is a
``<d`` because that is the narrowest thing Fusion accepts as a real.
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
    unit = decode(data[:64])
    value = struct.unpack("<d", (data + b"\x00" * 8)[:8])[0]

    assert isinstance(normalise_unit(unit), str)
    assert isinstance(needs_expression(unit), bool)

    if math.isfinite(value):
        expr = expression_for(value, unit)
        assert isinstance(expr, str) and expr
        assert "inf" not in expr.lower() and "nan" not in expr.lower()


def main(argv: list[str]) -> None:
    # atheris has no Windows wheel, so it is imported here and never at module
    # level: the target has to import on every platform for the tests.
    import atheris

    atheris.Setup(argv, check)
    atheris.Fuzz()


if __name__ == "__main__":
    import sys

    main(sys.argv)
