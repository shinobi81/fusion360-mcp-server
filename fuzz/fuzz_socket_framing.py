"""Fuzz target: a malformed complete line must cost the connection, not dispatch.

Browsers can reach the loopback port, so the newline framing loop is a trust
boundary: an HTTP request line is never valid JSON, and skipping bad lines let
the body of a cross-protocol ``POST`` be dispatched as a command (#11). The
contract the handler owes is one ``Invalid JSON`` reply that ends the stream --
whatever follows the bad line is never dispatched. Bytes that do not form a
complete line are merely incomplete: ``b""``, a truncated blob and blank lines
must stay silent.

Every input has to survive, so the frames are counted the way the handler
reads them rather than the way the wire looks: it strips a line before parsing
it, and it parses bytes, which can fail on UTF-8 before JSON is ever tried.
"""

import json
import socket
import threading
from contextlib import suppress

from addon.server.socket_server import Fusion360MCPServer

from ._bridge import RecordingBridge

INVALID_JSON_REPLY = {"status": "error", "message": "Invalid JSON"}
# Bounds a handler that never closes, and a reply stream that never ends.
TIMEOUT_S = 2.0


def _verdict(line: bytes) -> str:
    """What ``_handle_client`` does with one stripped, non-blank line.

    ``"dispatch"`` is a well-formed frame. ``"invalid"`` is a syntax error,
    which is answered with one ``Invalid JSON`` reply and the connection.
    ``"not_text"`` is bytes it cannot decode: ``json.loads`` raises
    ``UnicodeDecodeError`` there, which is not a ``JSONDecodeError``, so the
    handler closes without replying. That gap is recorded here, not enforced:
    #11 is about what gets *dispatched*, and both arms dispatch nothing.
    """
    try:
        json.loads(line)
    except json.JSONDecodeError:
        return "invalid"
    except ValueError:
        return "not_text"
    return "dispatch"


def _frames(data: bytes) -> tuple[list[bytes], str | None]:
    """The frames the handler owes a dispatch, and how the first bad one fails.

    Only complete lines count, and counting stops at the first one the handler
    refuses -- that is where it returns, so every later line is mute. The
    residual buffer counts when it parses on its own, because the handler's
    no-newline fallback dispatches such a blob: ``b"123"`` and
    ``b'{"type": "ping"}'`` are tolerable input that really does reach the
    bridge, and a count that left them out would report them as a crash.
    """
    expected: list[bytes] = []
    bad = None
    for line in data.split(b"\n")[:-1]:  # complete lines only
        stripped = line.strip()  # the handler strips before it parses
        if not stripped:
            continue
        bad = _verdict(stripped)
        if bad != "dispatch":
            break
        expected.append(stripped)
    else:
        tail = data.rsplit(b"\n", 1)[-1].strip()
        if tail and _verdict(tail) == "dispatch":
            expected.append(tail)
    return expected, None if bad == "dispatch" else bad


def check(data: bytes) -> None:
    bridge = RecordingBridge()
    server = Fusion360MCPServer(bridge)
    # _handle_client loops on this flag, but the peer closing its write side is
    # what actually ends the loop; nothing runs at all while it is False.
    server._running = True

    ours, addin = socket.socketpair()
    thread = threading.Thread(target=server._handle_client, args=(addin,), daemon=True)
    thread.start()

    replies: list[dict] = []
    try:
        ours.sendall(data)
        # End of input: the handler's recv returns b"" and it exits. Nothing
        # would close the connection otherwise, so the read below is bounded.
        ours.shutdown(socket.SHUT_WR)
        ours.settimeout(TIMEOUT_S)
        buffer = b""
        with suppress(socket.timeout):
            while True:
                chunk = ours.recv(65536)
                if not chunk:
                    break
                buffer += chunk
        replies = [json.loads(line) for line in buffer.split(b"\n") if line.strip()]
    finally:
        # Unconditional and before any assertion, so a payload that fails the
        # contract still closes both ends and joins the thread.
        ours.close()
        thread.join(TIMEOUT_S)
        if thread.is_alive():
            # Still blocked in recv: force the handler out through its own end.
            with suppress(OSError):
                addin.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                addin.close()
            thread.join(TIMEOUT_S)

    expected, bad = _frames(data)
    assert len(bridge.commands) == len(expected), (bridge.commands, expected)
    if bad == "invalid":
        errors = [reply for reply in replies if reply == INVALID_JSON_REPLY]
        assert errors == [INVALID_JSON_REPLY], replies
        # Last of the stream: the handler returned on the bad line, so nothing
        # from after it was dispatched.
        assert replies[-1] == INVALID_JSON_REPLY
    elif bad is not None:
        # Undecodable bytes end the connection with no reply at all.
        assert not any(reply == INVALID_JSON_REPLY for reply in replies), replies
    else:
        assert all(reply.get("status") == "success" for reply in replies), replies


def main(argv: list[str]) -> None:
    # atheris has no Windows wheel, so it is imported here and never at module
    # level: the target has to import on every platform for the tests.
    import atheris

    atheris.Setup(argv, check)
    atheris.Fuzz()


if __name__ == "__main__":
    import sys

    main(sys.argv)
