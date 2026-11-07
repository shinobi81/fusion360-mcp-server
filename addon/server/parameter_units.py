"""Unit handling for user parameters.

Fusion reads a bare real in its internal units -- centimetres for a length,
radians for an angle -- so a value the caller meant as millimetres has to be
handed over as a unit-bearing string instead. Kept free of ``adsk`` imports
so the rules can be unit-tested without a running Fusion instance.
"""

from __future__ import annotations

import math
from typing import TypeVar

_T = TypeVar("_T")


def require_finite(value: _T) -> _T:
    """Return *value*, refusing infinity and NaN.

    ``json.loads`` accepts the non-standard ``Infinity`` and ``NaN`` literals,
    so a socket client can deliver one; written through, it becomes the
    expression ``"inf mm"``, which Fusion rejects as an opaque API error.  The
    message is shaped to classify as ``INVALID_INPUT``.

    Only a number is judged.  ``math.isfinite`` raises ``TypeError`` on anything
    else, no hints rule matches that, and the caller would see ``UNKNOWN`` with
    no hints for a value that used to work: ``create_parameter(value="2.5")``
    reaches Fusion as ``createByString("2.5 mm")``, which is fine.

    The value is returned unchanged, so the signature is a ``TypeVar``: a caller
    holding a ``float`` still has a ``float`` afterwards, and ``value_input_for``
    -- which accepts any object because a string expression passes through -- is
    not a type error at its own call site.
    """
    # An int is always finite, and converting an oversized one to float raises
    # OverflowError (a 401-digit JSON integer does exactly that), so ints skip
    # the conversion entirely rather than being judged by it.
    if isinstance(value, int):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"invalid parameter value: {value} is not finite")
    return value


def value_input_for(value: object) -> tuple[str, object]:
    """How a Fusion numeric input should be written: real, or expression.

    ``("real", float)`` goes through ``createByReal`` / ``parameter.value``;
    ``("expression", str)`` goes through ``createByString`` / ``parameter.expression``.

    A non-finite number is refused here (so it classifies as ``INVALID_INPUT``),
    an int too large for ``float`` becomes an expression rather than raising
    ``OverflowError``, and a string expression — ``"boxL"``, ``"56 mm"`` — passes
    through as the expression it already is.
    """
    value = require_finite(value)
    if isinstance(value, (int, float)):
        try:
            return "real", float(value)
        except OverflowError:
            # Finite, but beyond float: let Fusion judge the magnitude.
            return "expression", str(value)
    return "expression", str(value)


def normalise_unit(unit: str | None) -> str:
    """Trim a unit to its canonical form; blank means unitless."""
    return (unit or "").strip()


def expression_for(value: float, unit: str | None) -> str:
    """The expression text that stores *value* as *unit*.

    A unitless parameter has nothing to interpolate, so it keeps the bare
    number -- Fusion then reads it as internal units, which is what unitless
    means.  Formatting only: reject a non-finite value with
    :func:`require_finite` before calling this.
    """
    unit = normalise_unit(unit)
    return f"{value} {unit}" if unit else f"{value}"


def needs_expression(unit: str | None) -> bool:
    """True when the value must go through a string rather than a real."""
    return bool(normalise_unit(unit))


def build_value_input(value: float, unit: str | None, from_string, from_real):
    """Build the ValueInput that preserves *unit*.

    The two factories are ``ValueInput.createByString`` and
    ``ValueInput.createByReal``; they are passed in so the choice between
    them -- the thing that was wrong -- can be tested without ``adsk``.
    """
    if needs_expression(unit):
        return from_string(expression_for(value, unit))
    # Unitless: a real is the honest form, except where a real cannot carry the
    # number.  ``value_input_for`` already decides that -- a 401-digit JSON
    # integer goes to the expression form -- and ``createByReal`` raises
    # OverflowError on one, which matches no hints rule and surfaces as UNKNOWN.
    # The value itself is passed through untouched; only the choice of factory
    # comes from that decision.
    kind, _ = value_input_for(value)
    return from_real(value) if kind == "real" else from_string(str(value))
