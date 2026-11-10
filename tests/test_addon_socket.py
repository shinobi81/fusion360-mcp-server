"""The add-in socket must refuse malformed input rather than skip it.

Browsers can reach the loopback port, and an HTTP request line is never valid
JSON. While unparseable lines were merely skipped, the body of a cross-protocol
POST - ``POST / HTTP/1.1`` plus headers, then a JSON command - was dispatched as
a command. Closing the connection on the first malformed complete line removes
that path.

``socket_server.py`` imports no ``adsk``, so this runs in CI.
"""

import json
import pathlib
import socket
import sys
import threading
from contextlib import suppress

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addon.server.socket_server import Fusion360MCPServer  # noqa: E402
from tests.fakes.design import FakeDesign  # noqa: E402


class _RecordingBridge:
    def __init__(self):
        self.commands = []

    def submit(self, command):
        self.commands.append(command)
        return {"status": "success", "result": {"ok": True}}


def _exchange(payload: bytes, timeout: float = 5.0):
    """Push *payload* through one _handle_client and collect what came back."""
    bridge = _RecordingBridge()
    server = Fusion360MCPServer(bridge)
    server._running = True

    addin_end, client_end = socket.socketpair()
    thread = threading.Thread(
        target=server._handle_client, args=(addin_end,), daemon=True
    )
    thread.start()

    client_end.sendall(payload)
    client_end.shutdown(socket.SHUT_WR)

    replies = b""
    client_end.settimeout(timeout)
    try:
        with suppress(socket.timeout):
            while True:
                chunk = client_end.recv(4096)
                if not chunk:
                    break
                replies += chunk
    finally:
        client_end.close()
        thread.join(timeout)

    return bridge, [json.loads(line) for line in replies.splitlines() if line.strip()]


def test_http_post_body_is_not_dispatched():
    """A POST whose body carries a command must never reach the bridge."""
    body = json.dumps({"type": "execute_code", "params": {"code": "pass"}})
    request = (
        "POST /x HTTP/1.1\r\n"
        "Host: 127.0.0.1:9876\r\n"
        "Content-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n" + body + "\n"
    ).encode()

    bridge, replies = _exchange(request)

    assert bridge.commands == [], (
        "an HTTP request must not be parsed into a command - that was the "
        "drive-by code-execution path from a web page"
    )
    assert replies and replies[0]["message"] == "Invalid JSON"


def test_valid_line_still_dispatches():
    """The fix must not disturb ordinary newline-framed commands."""
    bridge, replies = _exchange((json.dumps({"type": "ping"}) + "\n").encode())

    assert bridge.commands == [{"type": "ping"}]
    assert replies[0]["status"] == "success"


def test_unterminated_buffer_waits_instead_of_failing():
    """A partial JSON blob with no newline is incomplete, not malformed."""
    bridge, replies = _exchange(b'{"type": "pi')

    assert bridge.commands == []
    assert not any(r.get("message") == "Invalid JSON" for r in replies)


def test_execute_code_survives_a_script_that_closes_its_document(bound_handler):
    """The envelope used to say "failed" after the script had already succeeded.

    Fusion's design raises "4 : An API Object refers to a deleted Object" once its
    document is gone, and the handler read ``design.designType`` *after* the script
    ran - so closing a document from the REPL reported a failure that did not
    happen. Measured while cleaning up this session's scratch documents.
    """
    handler = bound_handler(FakeDesign())

    result = handler.execute_code("design.isValid = False\n'the script ran'")

    assert result["executed"] is True
    assert result["result"] == "the script ran"
    assert result["document_closed"] is True


def test_execute_code_does_not_claim_a_closed_document_when_it_is_alive(bound_handler):
    handler = bound_handler(FakeDesign())

    result = handler.execute_code("1 + 1")

    assert result["result"] == 2
    assert "document_closed" not in result


def test_execute_code_reports_a_syntax_error_without_chaining_it(bound_handler):
    """The message carries the syntax error; the cause must not repeat it.

    ``execute_code`` turns a ``SyntaxError`` into a ``RuntimeError`` whose text is
    the diagnostic the agent reads.  Raised bare inside the ``except``, Python also
    attaches the original as ``__context__``, so the rendered traceback shows the
    syntax error twice.
    """
    handler = bound_handler(FakeDesign())

    with pytest.raises(RuntimeError) as raised:
        handler.execute_code("def (")

    assert str(raised.value).startswith("SyntaxError: ")
    assert raised.value.__suppress_context__ is True
