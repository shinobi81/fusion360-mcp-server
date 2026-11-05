import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fuzz.fuzz_hints_classify import check  # noqa: E402


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
    check(b"no profiles in sketch")


def test_unknown_text_falls_back():
    check(b"\xc3\x28 not a rule")
