import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addon.server.hole_geometry import plane_z_at  # noqa: E402
from addon.server.parameter_units import expression_for  # noqa: E402
from fuzz.fuzz_hints_classify import check, classify  # noqa: E402
from fuzz.fuzz_hole_geometry import check as check_geom  # noqa: E402
from fuzz.fuzz_parameter_units import check as check_units  # noqa: E402
from fuzz.fuzz_socket_framing import check as check_frames  # noqa: E402


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
    # And the arm's result, independent of how the target slices: check_units
    # only inspects the number token, so a target that took the unit from the
    # whole payload would still render "3.0 ..." and pass every case above.
    # fuzz/ is outside the coverage source, so nothing else would notice.
    assert expression_for(3.0, "   ") == "3.0"


def test_the_formatter_tolerates_non_finite_values():
    # By design: require_finite refuses at the handlers, expression_for stays
    # formatting. Its docstring says so, and both handlers already hold the
    # guard -- moving the refusal in here would give a pure formatter an error
    # channel it has no way to signal through.
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


def test_a_non_finite_coordinate_is_not_asserted_against():
    # The finiteness guard is over all four inputs, not just the two Z values.
    # A horizontal normal has zero x and y components, so 0 * inf and 0 * nan
    # both leave a nan Z -- narrowing the guard to (nz, oz) therefore turns
    # these three inputs red, and nothing else in this file would.
    for x, y in ((float("inf"), 0.0), (float("-inf"), 0.0), (0.0, float("nan"))):
        check_geom(struct.pack("<5d", 1.0, 0.0, x, y, 0.0))


def test_an_http_request_dispatches_nothing():
    check_frames(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n{"type": "execute_code"}\n')


def test_a_partial_frame_that_parses_is_dispatched_once():
    # No trailing newline, but the handler's raw-JSON fallback dispatches the
    # residual buffer when it parses, so this is a frame, not a refusal.
    check_frames(b'{"type": "ping"}')


def test_a_bad_line_after_a_good_one_stops_dispatch():
    check_frames(b'{"type": "ping"}\nnot json\n{"type": "ping"}\n')


def test_clean_frames_all_dispatch():
    check_frames(b'{"type": "ping"}\n{"type": "get_scene_info"}\n')


def test_an_empty_payload_is_not_an_error():
    # atheris feeds b"" first: no complete line, so no dispatch and no reply.
    check_frames(b"")


def test_blank_lines_are_not_frames():
    for data in (b"\n\n\n", b"   \n  \n"):
        check_frames(data)


def test_a_frame_without_a_trailing_newline_is_still_a_frame():
    # Same fallback arm, with a bare number: json.loads accepts a top-level
    # scalar, so b"123" reaches the bridge too.
    check_frames(b"123")


def test_a_line_is_stripped_before_it_is_parsed():
    # \x0c is not JSON whitespace but bytes.strip() removes it, so the handler
    # dispatches this line: a target parsing the raw line would call it bad.
    check_frames(b"\x0c{}\x0c\n")


def test_a_truncated_residual_dispatches_nothing():
    # No newline, so this is a residual rather than a line, and it does not
    # parse: the handler's no-newline fallback ignores an incomplete buffer and
    # closes silently. Nothing is dispatched and no reply is owed -- calling it
    # a bad line instead would demand an "Invalid JSON" reply that never comes.
    check_frames(b'{"type": "ping"')


def test_a_line_that_is_not_text_dispatches_nothing():
    # json.loads fails on UTF-8 before it ever tries JSON, so these bytes are
    # refused. Whether a reply follows is undecided -- the handler currently
    # closes silently -- and the target must stay green either way, so only the
    # dispatch side is pinned here.
    check_frames(b"\x80 not text\n")
    check_frames(b'{"type": "ping"}\n\x80 not text\n')
