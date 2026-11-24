"""The tool JSON ``cam_create_operation`` gives Fusion.

``Operation.tool`` accepts only a ``Tool``, and Fusion builds one from a JSON
string (``Tool.createFromJson``), so a diameter argument has to become that JSON.
This module owns the shape, and it is deliberately free of ``adsk`` imports so the
shape can be tested without a running Fusion instance.

**Every key is emitted, and that is not tidiness.** Measured on Fusion 2706.1.17:

* A complete tool object - every key below, with one ``start-values.presets``
  entry - is accepted by ``Tool.createFromJson``; assigning the result to
  ``Operation.tool`` registers it in ``documentToolLibrary`` and
  ``generateToolpath`` then finishes with ``hasToolpath`` ``True``.
* A **partial** object (no ``holder``, an empty ``start-values``) neither raised
  nor refused: Fusion 360 **exited** during ``createFromJson``. A trimmed shape
  is therefore not an optimisation available here, whatever it looks like.

The units are millimetres because the shipped libraries are millimetres
(``.../CAM360/Data/libraries/Samples/Milling Tools (Metric).json``); the tool
calls the add-in receives are centimetres, Fusion's internal unit, so the
conversion happens here at the one boundary that needs it.
"""

from __future__ import annotations

import json
import math
import uuid

from . import hints as _hints

MM_PER_CM = 10.0
DEFAULT_FLUTES = 2
# Measured from Fusion's own shipped library (CAM360/Data/libraries/Samples,
# "Milling Tools (Metric).json", 12 flat end mills): flute length over diameter runs
# 1.52 to 4.0, mean 2.64, median 2.39. Three is the round default above the median, so
# an unnamed length still leaves a 1 mm cutter usable.
FLUTE_LENGTHS_PER_DIAMETER = 3.0
# A plain cylinder of shank behind the flutes, and the length the assembly hangs it out
# of a holder by. Nothing recorded here says a toolpath reads either value - the
# measured generation succeeded with these numbers, which is all this claims. A value
# too small to be plausible is a CAM dialog's objection, not the generator's.
SHANK_LENGTH_MM = 20.0
HOLDER_GAUGE_LENGTH_MM = 20.0
#: Feed per tooth, and the spindle speed every emitted preset uses. ``v_f`` below is
#: derived from these and the flute count rather than fixed, because a preset whose
#: per-tooth feed implies a different feed rate is a tool that cuts at the wrong speed.
#: ``f_n`` is emitted equal to ``f_z`` because that is what Fusion's own library does:
#: measured across ``Milling Tools (Metric).json``, every preset carries ``f_n == f_z``
#: beside ``v_f == f_z * n * NOF`` (a 3 mm 3-flute entry: 0.0667, 0.0667, 1000 at
#: n 5000). Whatever the name suggests, it is not a per-revolution figure here.
FEED_PER_TOOTH_MM = 0.05
SPINDLE_RPM = 10000.0


def _number(value: object, field: str) -> float:
    """*value* as a float, or a refusal naming *field*.

    ``parameter_units.require_finite`` deliberately passes a non-number through
    (a unit-bearing expression is a legal parameter value), so a string reaching
    this module has not been judged by anything yet. ``bool`` is refused with the
    rest: it is an ``int`` to Python and a mistake here.

    Refused here rather than left to raise later: the message names the argument the
    caller sent, which a ``ValueError`` wrapped by a caller could not guarantee.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _hints.Refusal(
            "INVALID_INPUT",
            f"{field} must be a number, got {value!r}",
            hints=("Lengths are centimetres; a count is a whole number.",),
        )
    # `* 1.0` rather than `float(...)`: the guard above has already settled the
    # type, and a bare `float()` there reads like an unguarded parse even though
    # it cannot fail.
    return value * 1.0


def build_tool_json(
    *,
    tool_diameter: float,
    tool_length: float | None = None,
    tool_flutes: int = DEFAULT_FLUTES,
    tool_number: int = 1,
    description: str | None = None,
) -> str:
    """A complete flat-endmill tool object, as JSON, in Fusion's library units.

    *tool_diameter* and *tool_length* are centimetres (the units every tool call
    takes); the JSON is millimetres. *tool_number* is the number the post writes, and
    every argument keeps the tool's own spelling so a refusal names the argument the
    caller sent.

    Only the flat end mill is offered: it is the one type measured to survive
    ``createFromJson`` and then generate a toolpath. A type whose geometry block
    this function invented would be exactly the partial shape that crashed
    Fusion, so a caller that needs another tool supplies ``tool_json``.
    """
    diameter_mm = _number(tool_diameter, "tool_diameter") * MM_PER_CM
    # Judged here rather than at the call site so every argument is refused by
    # the same function, in the caller's own spelling.
    flute_count = _number(tool_flutes, "tool_flutes")
    tool_number_value = _number(tool_number, "tool_number")
    flute_mm = (
        _number(tool_length, "tool_length") * MM_PER_CM
        if tool_length is not None
        else diameter_mm * FLUTE_LENGTHS_PER_DIAMETER
    )
    body_mm = flute_mm
    overall_mm = body_mm + SHANK_LENGTH_MM
    # v_c follows the shipped presets' own arithmetic: the library's 6 mm flat entry
    # reports v_c 188.5 at n 10000, which is pi * D * n / 1000 for a millimetre
    # diameter. Same formula, so the emitted preset is not fiction.
    surface_speed = math.pi * diameter_mm * SPINDLE_RPM / 1000.0
    # v_f = f_z x n x NOF: derived, so the preset stays self-consistent whatever the
    # flute count is. A fixed feed beside a varying NOF describes a tool that cuts at
    # half the intended rate at 4 flutes.
    feed_rate = FEED_PER_TOOTH_MM * SPINDLE_RPM * flute_count
    # Defence in depth, for a caller that reaches this function without the rules in
    # front of it: ``inf`` serialises as ``Infinity``, which is not JSON and is handed
    # to the one Fusion call in this path with a measured exit. The rules refuse these
    # magnitudes first; this is the last line, not the first.
    derived = (diameter_mm, flute_mm, body_mm, overall_mm, surface_speed, feed_rate)
    if not all(math.isfinite(number) for number in derived):
        raise _hints.Refusal(
            "INVALID_INPUT",
            "the tool dimensions are too large to describe as JSON numbers",
            hints=("A tool a few centimetres across is the intended range.",),
        )

    tool = {
        "BMC": "unspecified",
        "GRADE": "Mill Generic",
        "description": description
        or f"#{tool_number_value:g} Ø{diameter_mm:g}mm Flat Endmill",
        "unit": "millimeters",
        "type": "flat end mill",
        "vendor": "fusion360-mcp-server",
        "product-id": "",
        "product-link": "",
        "guid": str(uuid.uuid4()),
        "geometry": {
            "CSP": False,
            "DC": diameter_mm,
            "HAND": True,
            "LB": body_mm,
            "LCF": flute_mm,
            "NOF": flute_count,
            "OAL": overall_mm,
            "SFDM": diameter_mm,
            "assemblyGaugeLength": overall_mm + HOLDER_GAUGE_LENGTH_MM,
            "shoulder-diameter": diameter_mm,
            "shoulder-length": flute_mm,
        },
        "holder": {
            "description": "",
            "gaugeLength": HOLDER_GAUGE_LENGTH_MM,
            "guid": "",
            "product-id": "",
            "product-link": "",
            "segments": [],
            "type": "holder",
            "unit": "millimeters",
            "vendor": "",
        },
        "post-process": {
            "break-control": False,
            "comment": "",
            "diameter-offset": 0.0,
            "length-offset": 0.0,
            "live": True,
            "manual-tool-change": False,
            "number": tool_number_value,
            "turret": 0.0,
        },
        "start-values": {
            "presets": [
                {
                    "description": "Default preset",
                    "f_n": FEED_PER_TOOTH_MM,
                    "f_z": FEED_PER_TOOTH_MM,
                    "guid": str(uuid.uuid4()),
                    "material": {
                        "category": "all",
                        "query": "",
                        "use-hardness": False,
                    },
                    "n": SPINDLE_RPM,
                    "n_ramp": SPINDLE_RPM,
                    "name": "Default preset",
                    "ramp-angle": 2.0,
                    "tool-coolant": "flood",
                    "use-stepdown": False,
                    "use-stepover": False,
                    "v_c": surface_speed,
                    "v_f": feed_rate,
                    "v_f_leadIn": feed_rate,
                    "v_f_leadOut": feed_rate,
                    "v_f_plunge": feed_rate / 2.0,
                    "v_f_ramp": feed_rate / 2.0,
                    "v_f_transition": feed_rate,
                }
            ]
        },
    }
    return json.dumps(tool)
