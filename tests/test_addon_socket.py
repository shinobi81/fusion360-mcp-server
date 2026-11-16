"""The add-in socket must refuse malformed input rather than skip it.

Browsers can reach the loopback port, and an HTTP request line is never valid
JSON. While unparseable lines were merely skipped, the body of a cross-protocol
POST - ``POST / HTTP/1.1`` plus headers, then a JSON command - was dispatched as
a command. Closing the connection on the first malformed complete line removes
that path.

What a malformed line costs is one connection: the listener has to survive it,
which is why the same module also starts a real one and stops it, drives the
accept loop's error arms, and pins what happens to a command whose client, or
whose bridge, fails while it is in flight.

``socket_server.py`` imports no ``adsk``, so this runs in CI.
"""

import errno
import json
import logging
import pathlib
import socket
import sys
import threading
import time
from contextlib import suppress

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addon.server import socket_server  # noqa: E402
from addon.server.socket_server import Fusion360MCPServer  # noqa: E402
from tests.fakes.design import FakeDesign  # noqa: E402

_TIMEOUT = 5.0  # bounds every wait: a handler that never answers must fail the test


class _RecordingBridge:
    """The add-in's bridge seam: the commands offered and the answer given back.

    ``reply`` is what ``submit`` returns, so a test can put the envelope a real
    command produces on the wire without running the handler, and ``error`` is
    raised in its place.  ``hold()`` parks the next submit until ``release()``,
    which is how a test gets a command in flight instead of racing one.
    """

    def __init__(self):
        self.commands = []
        self.reply = {"status": "success", "result": {"ok": True}}
        self.error = None
        self.arrived = threading.Event()
        self._released = threading.Event()
        self._released.set()

    def hold(self):
        self._released.clear()
        self.arrived.clear()

    def release(self):
        self._released.set()

    def submit(self, command):
        self.commands.append(command)
        self.arrived.set()
        self._released.wait(timeout=_TIMEOUT)
        if self.error is not None:
            raise self.error
        return self.reply


def _exchange(payload: bytes, timeout: float = _TIMEOUT, bridge=None):
    """Push *payload* through one _handle_client and collect what came back.

    *bridge* replaces the recording one, so a test can script the answer or make
    ``submit`` raise.
    """
    bridge = _RecordingBridge() if bridge is None else bridge
    server = Fusion360MCPServer(bridge)
    server._running = True

    addin_end, client_end = socket.socketpair()
    thread = threading.Thread(
        target=server._handle_client, args=(addin_end,), daemon=True
    )
    thread.start()

    # Bounded before the write: a payload past the handler's buffer cap makes it
    # close the connection while this is still sending, and a client that has
    # nothing left to say has already done what the write was for.
    client_end.settimeout(timeout)
    with suppress(OSError, socket.timeout):
        client_end.sendall(payload)
    # A peer that answered and closed at once has already ended the stream, which
    # is all this was for; darwin calls that ENOTCONN where Windows returns
    # quietly (measured on the sibling fuzz target's identical call).
    with suppress(OSError):
        client_end.shutdown(socket.SHUT_WR)

    replies = b""
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

    # Reached only when nothing above raised, so this cannot mask a real failure.
    # It is weaker than it looks: the `close` above also unblocks the handler, so
    # what this catches is a handler still running after both - not one that was
    # merely never told about end of input. The fuzz twin counts the call instead,
    # and the test below counts its stub, which is where the signal itself is
    # pinned.
    assert not thread.is_alive(), "the handler outlived its peer and a close"

    return bridge, [json.loads(line) for line in replies.splitlines() if line.strip()]


class _Peer:
    """One loopback client of a started server, buffered so a reply is not lost."""

    def __init__(self, server):
        port = server._socket.getsockname()[1]
        self._conn = socket.create_connection((server.host, port), timeout=_TIMEOUT)
        self._buffer = b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        with suppress(OSError):
            self._conn.close()

    def send(self, text: str):
        self._conn.sendall(text.encode("utf-8"))

    def reply(self) -> dict:
        while b"\n" not in self._buffer:
            chunk = self._conn.recv(4096)
            assert chunk, "the server closed without answering"
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return json.loads(line)

    def closed(self) -> bool:
        """Whether the server ended the stream - read, not inferred.

        Two seconds rather than ``_TIMEOUT``: the answer is meant to be already
        waiting, and a close that never comes should not hold the suite up.
        """
        self._conn.settimeout(2.0)
        while True:
            try:
                chunk = self._conn.recv(4096)
            except socket.timeout:
                return False
            if not chunk:
                return True
            self._buffer += chunk

    def drop(self):
        """Hang up without reading, the way a killed client does."""
        with suppress(OSError):
            self._conn.close()


def _started(bridge=None) -> Fusion360MCPServer:
    """A server already serving on an ephemeral port.

    Port 0 rather than a fixed one, so nothing else on the machine can hold it.
    ``_bind_socket`` runs in the accept thread, so the wait is for what that
    thread leaves behind rather than for ``start()``, which only starts it.
    """
    server = Fusion360MCPServer(
        _RecordingBridge() if bridge is None else bridge, port=0
    )
    assert server.start() is True
    deadline = time.monotonic() + _TIMEOUT
    while server._socket is None:
        assert time.monotonic() < deadline, "the listener never bound its port"
        time.sleep(0.005)
    return server


@pytest.fixture
def server():
    """A started listener on an ephemeral port, stopped after the test."""
    started = _started()
    yield started
    started.stop()


class _ScriptedListener:
    """``accept()`` that replays steps, so the loop's arms need no racing peers.

    An exception step is raised; a callable step runs and the next step is used
    instead; anything else is handed back as the accepted client.
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def accept(self):
        self.calls += 1
        while self.steps:
            step = self.steps.pop(0)
            if isinstance(step, BaseException):
                raise step
            if callable(step):
                step()
                continue
            return step
        raise AssertionError("the accept loop asked for more than the script allows")


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


def test_an_exchange_survives_a_peer_that_closed_first(monkeypatch):
    """The refusal path replies and closes at once, so the client races that close.

    macOS answers the client's ``shutdown(SHUT_WR)`` with ``ENOTCONN`` when the
    handler's close landed first; Windows returns quietly (measured), which is why
    no run here reaches it unaided. A peer already gone has ended the stream, which
    is what the call was for - the exchange still owes the reply it already read.
    """
    real_shutdown = socket.socket.shutdown
    signalled: list[int] = []

    def enotconn(sock, how):
        if how != socket.SHUT_WR:
            return real_shutdown(sock, how)
        signalled.append(how)
        raise OSError(errno.ENOTCONN, "Socket is not connected")

    monkeypatch.setattr(socket.socket, "shutdown", enotconn)

    bridge, replies = _exchange(
        b'POST /x HTTP/1.1\r\nHost: 127.0.0.1:9876\r\n\r\n{"type": "ping"}\n'
    )

    # The stub firing is the precondition: without this the test would stay green
    # if `_exchange` stopped signalling end-of-input at all, and prove nothing
    # about the darwin path it exists for.
    assert signalled == [socket.SHUT_WR]
    assert bridge.commands == []
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


def test_blank_lines_between_frames_are_skipped():
    """``\\n\\n`` is framing noise: not a command, not an error."""
    payload = b"\n\n" + json.dumps({"type": "ping"}).encode() + b"\n\n"

    bridge, replies = _exchange(payload)

    assert bridge.commands == [{"type": "ping"}]
    assert replies == [{"status": "success", "result": {"ok": True}}]


def test_a_complete_frame_needs_no_newline():
    """The fallback: a blob that parses on its own is dispatched, newline or not."""
    bridge, replies = _exchange(json.dumps({"type": "ping"}).encode())

    assert bridge.commands == [{"type": "ping"}]
    assert replies == [{"status": "success", "result": {"ok": True}}]


def test_a_line_that_is_not_text_closes_without_answering(caplog):
    """Bytes that are not UTF-8 reach the catch-all, not the refusal.

    ``json.loads`` raises ``UnicodeDecodeError`` - a ``ValueError``, but not a
    ``JSONDecodeError`` - so the framing loop's refusal never runs and the
    connection closes with no reply at all. The fuzz target records that gap as
    deferred; this pins the close it does produce, not a reply it does not.

    ``\\x80`` and not ``\\xff\\xfe``: the latter is a UTF-16 BOM, which
    ``json.loads`` decodes to the empty string and then refuses as JSON, so it
    reaches the other arm.
    """
    caplog.set_level(logging.DEBUG, logger="fusion360mcp.socket")

    bridge, replies = _exchange(b"\x80\n")

    assert bridge.commands == []
    assert replies == []
    assert "Client handler error" in caplog.text


def test_an_enormous_line_is_refused_without_buffering_it_all(caplog):
    """Past ``_MAX_BUFFER_BYTES`` with no newline, the connection is dropped.

    The log line is what makes this a test of the cap: an unterminated buffer that
    simply reaches end of input is closed too, so "nothing was dispatched and the
    stream ended" would pass with no cap at all.
    """
    bridge, replies = _exchange(b"x" * (socket_server._MAX_BUFFER_BYTES + 1))

    assert bridge.commands == []
    assert replies == []
    assert "Client buffer over" in caplog.text


def test_a_line_that_is_not_json_closes_the_connection(server):
    """One bad line costs that connection and everything behind it.

    The ping is in the same write as the bad line, so it is already in the
    handler's buffer when the refusal returns: only the close keeps it off the
    bridge. The second peer is the other half of the claim - one connection,
    not the listener.
    """
    bridge = server._bridge
    with _Peer(server) as peer:
        peer.send("GET / HTTP/1.1\n" + json.dumps({"type": "ping"}) + "\n")

        assert peer.reply() == {"status": "error", "message": "Invalid JSON"}
        assert peer.closed() is True
    assert bridge.commands == []

    with _Peer(server) as afterwards:
        afterwards.send(json.dumps({"type": "ping"}) + "\n")
        assert afterwards.reply()["status"] == "success"
    assert bridge.commands == [{"type": "ping"}]


def test_a_bridge_failure_answers_an_error_envelope():
    """A submit that raises is data on the wire, not a dropped connection."""
    bridge = _RecordingBridge()
    bridge.error = RuntimeError("the handler blew up")

    answered, replies = _exchange(b'{"type": "explode"}\n', bridge=bridge)

    assert answered is bridge
    assert replies == [{"status": "error", "message": "the handler blew up"}]


def test_a_command_with_no_name_answers_an_envelope_rather_than_closing(
    server, handler_module
):
    """``{}`` is valid JSON, so the socket forwards it and relays what comes back.

    The envelope is the handler's own, computed here rather than copied, so the
    socket test cannot drift from the wording an agent branches on. The ping
    after it is the proof the connection was not the price of asking.
    """
    bridge = server._bridge
    bridge.reply = handler_module.CommandHandler().execute_command({})

    with _Peer(server) as peer:
        peer.send("{}\n")
        answer = peer.reply()
        assert answer["status"] == "error"
        assert answer["error_kind"] == "UNKNOWN_COMMAND"

        # The socket relays whatever the bridge answers, so the second answer is
        # the bridge's own: what the ping proves is that a frame still arrives.
        bridge.reply = {"status": "success", "result": {"ok": True}}
        peer.send(json.dumps({"type": "ping"}) + "\n")
        assert peer.reply()["status"] == "success"
    assert bridge.commands == [{}, {"type": "ping"}]


def test_a_reply_to_a_client_that_is_gone_is_logged_not_raised(caplog):
    """``_send`` is best effort: the reply is lost, the handler does not fall over.

    Driven at ``_send`` because the race a real client would need - gone after its
    command was submitted but before the answer - cannot be made to raise on
    demand: a peer that closed normally still accepts the write.
    """
    client, other_end = socket.socketpair()
    client.close()

    Fusion360MCPServer._send(client, {"status": "success"})

    other_end.close()
    assert "Failed to send response" in caplog.text


# ----------------------------------------------------------------------
# The listener: start, stop, and the accept loop's error arms
# ----------------------------------------------------------------------


def test_a_started_listener_serves_a_client_and_releases_its_port(server):
    """Start binds and serves; stop frees the address and hangs up on its client.

    ``stop()`` closes the accepted sockets as well as the listener: a per-client
    thread blocked in ``recv`` would otherwise outlive the server it belongs to.
    The command is parked in the bridge while ``stop()`` runs, and it stays
    parked until after the read: a handler free to loop notices ``_running``
    going false and closes its own socket, so only a handler that cannot close
    it can show that ``stop()`` did.

    The freed port is proven by connecting, not by binding: this test makes the
    server the side that closed first, so its end of the connection is in
    TIME_WAIT, and a plain ``bind`` is refused there until the state expires
    (Linux, macOS - the reason ``_bind_socket`` sets ``SO_REUSEADDR``). Giving the
    probe that option instead would defeat the check on Windows, where a second
    socket carrying it can bind over a live listener.
    """
    port = server._socket.getsockname()[1]
    bridge = server._bridge
    assert server.is_running() is True
    bridge.hold()
    with _Peer(server) as peer:
        peer.send(json.dumps({"type": "slow"}) + "\n")
        assert bridge.arrived.wait(_TIMEOUT), "the command never reached the bridge"
        try:
            server.stop()

            assert server.is_running() is False
            assert peer.closed() is True, "stop() must close the client it accepted"
        finally:
            bridge.release()
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=_TIMEOUT)


def test_starting_a_running_server_answers_false(server):
    """``start()`` twice is one listener: the second call reports it did nothing."""
    listener = server._accept_thread

    assert server.start() is False
    assert server._accept_thread is listener
    with _Peer(server) as peer:
        peer.send(json.dumps({"type": "ping"}) + "\n")
        assert peer.reply()["status"] == "success"


def test_a_port_that_cannot_be_bound_is_reported_rather_than_raised(caplog):
    """The restarter counts a ``False``; an exception here would kill its thread.

    192.0.2.1 is TEST-NET-1 (RFC 5737): reserved for documentation, assigned to no
    interface, so the bind is refused on every platform without needing an
    occupied or privileged port.
    """
    server = Fusion360MCPServer(_RecordingBridge(), host="192.0.2.1", port=0)

    assert server._bind_socket() is False
    assert server._socket is None
    assert "Bind failed" in caplog.text


def test_the_accept_loop_returns_when_nothing_is_bound():
    """No socket means nothing to accept: rebind in the outer loop, not spin here."""
    server = Fusion360MCPServer(_RecordingBridge())
    server._running = True

    server._accept_loop()

    assert server._socket is None


def test_a_quiet_accept_loop_waits_out_its_timeouts_then_fails_loudly():
    """A one-second accept timeout is a poll; a dead socket is not, and must bubble.

    Bubbling is the contract the outer loop restarts on: swallowing the ``OSError``
    would leave a running server that accepts nothing.
    """
    server = Fusion360MCPServer(_RecordingBridge())
    server._running = True
    listener = _ScriptedListener(
        socket.timeout(), socket.timeout(), OSError("listener died")
    )
    server._socket = listener

    with pytest.raises(OSError, match="listener died"):
        server._accept_loop()

    assert listener.calls == 3


def test_an_accept_error_after_stop_ends_the_loop_quietly():
    """Once ``_running`` is false the error is the stop, not a fault to restart."""
    server = Fusion360MCPServer(_RecordingBridge())
    server._running = True
    listener = _ScriptedListener(
        lambda: setattr(server, "_running", False), OSError("stopped")
    )
    server._socket = listener

    server._accept_loop()

    assert listener.calls == 1


def test_a_listener_that_cannot_bind_gives_up_after_the_restart_cap(
    monkeypatch, caplog
):
    """Ten retries, then stop trying: a loop that never binds would retry forever."""
    monkeypatch.setattr(socket_server, "_RESTART_DELAY", 0.0)
    server = Fusion360MCPServer(_RecordingBridge())
    server._running = True
    attempts = []

    def refuse():
        attempts.append(1)
        return False

    monkeypatch.setattr(server, "_bind_socket", refuse)

    server._accept_loop_with_restart()

    assert len(attempts) == socket_server._MAX_RESTARTS + 1
    assert "giving up" in caplog.text


def test_a_crashed_accept_loop_is_rebound_rather_than_left_dead(monkeypatch, caplog):
    """A crash in one life costs a rebind, not the bridge: the loop comes back.

    The bind is scripted because what is under test is the policy - rebind, and
    stop when the server has been told to - not the timing of a real socket loss.
    """
    monkeypatch.setattr(socket_server, "_RESTART_DELAY", 0.0)
    server = Fusion360MCPServer(_RecordingBridge())
    server._running = True
    lives = []

    def bind():
        lives.append(1)
        # The third life is the stop that ends the loop, so it does not run forever.
        server._running = len(lives) < 3
        return True

    def crash():
        raise RuntimeError("accept loop crashed")

    monkeypatch.setattr(server, "_bind_socket", bind)
    monkeypatch.setattr(server, "_accept_loop", crash)

    server._accept_loop_with_restart()

    assert len(lives) == 3
    assert "Accept loop crashed" in caplog.text


def test_a_client_that_disappears_mid_command_does_not_stop_the_server(server):
    """The client loses its reply, not the listener.

    The handler is inside ``submit`` when the peer goes - the state where the
    answer has nowhere to go - and the next client must still be served.
    """
    bridge = server._bridge
    bridge.hold()
    vanished = _Peer(server)
    vanished.send(json.dumps({"type": "slow"}) + "\n")
    assert bridge.arrived.wait(_TIMEOUT), "the command never reached the bridge"

    vanished.drop()
    bridge.release()

    with _Peer(server) as afterwards:
        afterwards.send(json.dumps({"type": "ping"}) + "\n")
        assert afterwards.reply()["status"] == "success"
    assert bridge.commands == [{"type": "slow"}, {"type": "ping"}]


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

    message = str(raised.value)
    assert message.startswith("SyntaxError: ")
    assert "def (" in message and "^" in message, (
        "the offending line and its caret are the only view of the source the agent "
        "gets once the chained block is suppressed"
    )
    assert raised.value.__suppress_context__ is True
    # ``from None`` and ``from exc`` both suppress the context; only the cause
    # tells them apart, and ``from exc`` would re-print the parser's message.
    assert raised.value.__cause__ is None
