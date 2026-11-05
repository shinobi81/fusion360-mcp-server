"""Fuzz target: ``create_hole``'s face picking and plane solving stay total.

The three helpers decide which face a hole goes on and where it lands, so a
non-finite number reaching them must not turn into a silent ``nan`` Z that
Fusion accepts as a coordinate. The payload is five little-endian doubles --
normal Z, origin Z, x, y, and a face area -- and one bit of the first byte
picks the up/down face.
"""

import math
import struct

from addon.server.hole_geometry import face_rank_key, is_horizontal_face, plane_z_at


def check(data: bytes) -> None:
    # Padded to the full record, so the unpack and the flag are total for an
    # empty or truncated payload -- atheris feeds b"" first.
    payload = (data + b"\x00" * 40)[:40]
    nz, oz, x, y, area = struct.unpack("<5d", payload)
    want_up = bool(payload[0] & 1)

    assert isinstance(is_horizontal_face(nz, want_up), bool)
    key = face_rank_key(x, area, want_up)
    assert isinstance(key, tuple) and len(key) == 2

    try:
        z = plane_z_at((0.0, 0.0, nz), (0.0, 0.0, oz), x, y)
    except ValueError:
        assert nz == 0.0
    else:
        # Guard the whole input, not just the normal: an inf/nan origin or
        # coordinate is garbage in, garbage out -- plane_z_at hands the value
        # straight back, and asserting finiteness there would report the number
        # rather than a defect. Only an all-finite input owes a finite Z.
        if all(math.isfinite(v) for v in (nz, oz, x, y)):
            assert math.isfinite(z)


def main(argv: list[str]) -> None:
    # atheris has no Windows wheel, so it is imported here and never at module
    # level: the target has to import on every platform for the tests.
    import atheris

    atheris.Setup(argv, check)
    atheris.Fuzz()


if __name__ == "__main__":
    import sys

    main(sys.argv)
