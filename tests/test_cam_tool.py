"""The tool JSON ``cam_create_operation`` hands Fusion.

Measured on Fusion 2706.1.17, and the first test is the reason this module is a
pure function with a complete shape rather than a few keys patched onto
whatever the caller passed:

* ``Tool.createFromJson`` accepts a **complete** tool object - every key and
  sub-key below, with one ``start-values.presets`` entry - and the result can be
  assigned to ``Operation.tool``, after which ``generateToolpath`` completes and
  ``hasToolpath`` answers ``True``.
* A **partial** object (no ``holder``, an empty ``start-values``) did not raise
  and did not refuse: Fusion 360 **exited** during ``createFromJson``, taking the
  document's unsaved state with it. That is why every key is emitted, and why
  the key sets are pinned here rather than assumed.
"""

from __future__ import annotations

import json
import uuid

import pytest

from addon.server import hints as addon_hints
from addon.server.cam_tool import build_tool_json

# The key sets a shipped Fusion tool library carries, read from
# Applications/CAM360/Data/libraries/Samples/Milling Tools (Metric).json.
TOP_KEYS = {
    "BMC",
    "GRADE",
    "description",
    "geometry",
    "guid",
    "holder",
    "post-process",
    "product-id",
    "product-link",
    "start-values",
    "type",
    "unit",
    "vendor",
}
GEOMETRY_KEYS = {
    "CSP",
    "DC",
    "HAND",
    "LB",
    "LCF",
    "NOF",
    "OAL",
    "SFDM",
    "assemblyGaugeLength",
    "shoulder-diameter",
    "shoulder-length",
}
HOLDER_KEYS = {
    "description",
    "gaugeLength",
    "guid",
    "product-id",
    "product-link",
    "segments",
    "type",
    "unit",
    "vendor",
}
PRESET_KEYS = {
    "description",
    "f_n",
    "f_z",
    "guid",
    "material",
    "n",
    "n_ramp",
    "name",
    "ramp-angle",
    "tool-coolant",
    "use-stepdown",
    "use-stepover",
    "v_c",
    "v_f",
    "v_f_leadIn",
    "v_f_leadOut",
    "v_f_plunge",
    "v_f_ramp",
    "v_f_transition",
}


def _built(**kwargs):
    return json.loads(build_tool_json(**kwargs))


def test_a_built_tool_carries_every_key_a_shipped_library_entry_carries():
    """A missing key crashed Fusion, so the shape is pinned, not assumed."""
    tool = _built(tool_diameter=0.6)

    assert set(tool) == TOP_KEYS
    assert set(tool["geometry"]) == GEOMETRY_KEYS
    assert set(tool["holder"]) == HOLDER_KEYS
    assert len(tool["start-values"]["presets"]) == 1
    assert set(tool["start-values"]["presets"][0]) == PRESET_KEYS


def test_the_geometry_is_millimetres_because_the_library_is_millimetres():
    """Callers pass centimetres; the tool JSON is Fusion's library unit."""
    tool = _built(tool_diameter=0.6)

    assert tool["unit"] == "millimeters"
    assert tool["holder"]["unit"] == "millimeters"
    assert tool["geometry"]["DC"] == 6.0
    # Three diameters of flute is the default cutting length.
    assert tool["geometry"]["LCF"] == 18.0


def test_a_given_length_and_flute_count_reach_the_geometry():
    tool = _built(tool_diameter=1.0, tool_length=4.0, tool_flutes=4)

    assert tool["geometry"]["DC"] == 10.0
    assert tool["geometry"]["LCF"] == 40.0
    assert tool["geometry"]["NOF"] == 4.0
    # The body is never shorter than the flute, or the shank would be negative.
    assert tool["geometry"]["LB"] >= tool["geometry"]["LCF"]


def test_the_tool_number_reaches_the_post_process_block():
    """``tool_number`` is the number the post writes, not an operation parameter."""
    tool = _built(tool_diameter=0.6, tool_number=7)

    assert tool["post-process"]["number"] == 7.0
    assert tool["description"].startswith("#7 ")


def test_every_call_gets_a_fresh_guid():
    """Two operations must not collide in the document tool library."""
    first = _built(tool_diameter=0.6)["guid"]
    second = _built(tool_diameter=0.6)["guid"]

    assert uuid.UUID(first) and uuid.UUID(second)
    assert first != second


def test_the_type_is_the_one_measured_to_generate_a_toolpath():
    """Only the flat end mill is measured end to end: create, attach, generate."""
    tool = _built(tool_diameter=0.6)

    assert tool["type"] == "flat end mill"
    assert tool["description"].endswith("Flat Endmill")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_diameter", "6mm"),
        ("tool_length", None.__class__),
        ("tool_flutes", "two"),
        ("tool_number", "#7"),
    ],
)
def test_a_non_numeric_argument_is_refused_by_name(field, value):
    """``require_finite`` passes a non-number through, so this is the last guard.

    A typed refusal rather than a bare ``ValueError``: the kind is what a caller
    branches on, and the hint is what tells it the units.
    """
    arguments = {"tool_diameter": 0.6, field: value}

    # Through the module, not a by-name import: ``reload_handler`` replaces
    # ``hints.Refusal``, and a class bound at import time would go stale in a full run.
    with pytest.raises(addon_hints.Refusal) as raised:
        build_tool_json(**arguments)

    assert raised.value.error_kind == "INVALID_INPUT"
    assert field in str(raised.value)
