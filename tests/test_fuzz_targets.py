import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fuzz.fuzz_hints_classify import check, classify  # noqa: E402


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
