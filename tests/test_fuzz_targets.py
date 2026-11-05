import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addon.server.hole_geometry import plane_z_at  # noqa: E402
from fuzz.fuzz_hints_classify import check, classify  # noqa: E402
from fuzz.fuzz_hole_geometry import check as check_geom  # noqa: E402
from fuzz.fuzz_parameter_units import check as check_units  # noqa: E402


def test_classify_survives_hostile_text():
    for data in [
        b"",
        b"\xff\xfe\x00",
        b"\x00" * 4096,
        b"a" * 10000,
        ("(" * 200 + "empty").encode(),
        b"invalid argument " * 400,
    ]:
        check(data)


def test_a_known_message_reaches_a_real_rule():
    assert classify("no profiles in sketch")[0] == "PROFILE_NOT_CLOSED"


def test_unknown_text_falls_back():
    assert classify("not a rule at all")[0] == "UNKNOWN"


def test_units_survive_junk_that_is_not_a_unit():
    for unit in [b"", b"-mm", b"\xc2\xb5m", b"1e9", b"x" * 4096, b"-cm"]:
        check_units(struct.pack("<d", 12.5) + unit)


def test_a_finite_value_never_emits_inf_or_nan():
    for value in (0.0, -1.5, 1e300, 1e-300):
        check_units(struct.pack("<d", value) + b"mm")


def test_a_unit_that_spells_inf_or_nan_is_still_finite_text():
    # The expression embeds the unit verbatim, so a junk unit containing
    # "nan"/"inf" must not be mistaken for a non-finite value.
    for unit in (b"nan", b"inf", b"Infinity", b"info"):
        check_units(struct.pack("<d", 12.5) + unit)


def test_a_blank_unit_reaches_the_unitless_expression():
    # The packed double's own bytes are never blank, so the unitless arm of
    # expression_for needs an input that actually strips to "".
    check_units(struct.pack("<d", 3.0) + b"   ")


def test_a_non_finite_value_is_not_asserted_yet():
    # Parcel 3 changes this behaviour; the target must tolerate it until then.
    check_units(struct.pack("<d", float("inf")) + b"mm")
    check_units(struct.pack("<d", float("nan")) + b"")


def test_geometry_is_total_over_non_finite_normals():
    for payload in (
        b"\x00" * 40,
        b"\xff" * 40,
        struct.pack("<5d", *(float("nan"),) * 5),
    ):
        check_geom(payload)


def test_a_vertical_plane_raises_rather_than_returning_nan():
    with pytest.raises(ValueError):
        plane_z_at((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2.0, 3.0)


def test_geometry_is_total_for_a_payload_shorter_than_the_record():
    # atheris feeds b"" first, so the payload must be padded before both the
    # unpack and the flag bit are read.
    for payload in (b"", b"\x00", b"\x01", b"\xff" * 39):
        check_geom(payload)


def test_a_non_finite_origin_is_not_asserted_against():
    # plane_z_at hands an inf/nan origin straight back out, so the target must
    # not report that as a crash: only an all-finite input owes a finite Z.
    for origin_z in (float("inf"), float("nan")):
        check_geom(struct.pack("<5d", 1.0, origin_z, 0.0, 0.0, 0.0))
