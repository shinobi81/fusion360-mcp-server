"""Shared plumbing for the fuzz targets.

Every target exposes ``check(data: bytes) -> None`` so the same function can be
driven by atheris, by the pytest suite, and by any seed corpus.
"""


def decode(data: bytes) -> str:
    """Turn fuzz bytes into the ``str`` the code under test actually receives.

    Latin-1 maps every one of the 256 byte values, so decoding is total: there
    is no ``UnicodeDecodeError`` branch for a target to hide behind.
    """
    return data.decode("latin-1")
