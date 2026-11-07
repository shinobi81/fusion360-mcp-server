"""The MCP wiring, driven through the real protocol.

Every handler in ``server.py`` used to be a closure inside ``main()``, so the
wiring could only be exercised by launching the CLI — 104 of the module's 179
statements had no test. ``build_server()`` makes the same wiring
constructible, and ``create_connected_server_and_client_session`` drives it
over the actual MCP protocol instead of calling the closures directly.

Socket-mode failures run against a fake add-in on a real loopback socket. The
error envelopes are where the wiring used to lie about what happened, so they
are exercised end to end rather than mocked.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from datetime import timedelta

import click
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

from fusion360_mcp import server as server_module
from fusion360_mcp.connection import reset_connection
from fusion360_mcp.tools import TOOLS

HOST = "127.0.0.1"

# A wiring regression that registers a handler which never returns should fail
# the job, not hang it — the client has no read timeout by default.
READ_TIMEOUT = timedelta(seconds=10)


def drive(mode: str, check, port: int = 9876):
    """Run ``check`` against one in-process client session."""

    async def scenario():
        mcp_server = server_module.build_server(mode, HOST, port)
        async with create_connected_server_and_client_session(
            mcp_server, read_timeout_seconds=READ_TIMEOUT
        ) as session:
            return await check(session)

    reset_connection()
    try:
        return asyncio.run(scenario())
    finally:
        reset_connection()


def error_text(exc: BaseException) -> str:
    """Flatten an ExceptionGroup (3.11+) into its leaf messages."""
    nested = getattr(exc, "exceptions", None)
    if nested:
        return " ".join(error_text(child) for child in nested)
    return f"{type(exc).__name__}: {exc}"


def capture_main(monkeypatch, args: list[str]) -> list[tuple]:
    """Run the CLI with ``build_server`` and ``anyio`` substituted.

    Returns the argument tuples ``main()`` passed to ``build_server``.  This is
    the one place an interaction assertion is right: forwarding the CLI's
    values is the whole of what ``main()`` does.
    """
    seen: list[tuple] = []

    class NoRun:
        def run(self, func):
            # anyio.run receives the coroutine *function*; build it so the
            # stdio loop is never awaited and the CLI returns.
            coro = func()
            coro.close()

    def fake_build_server(*called):
        seen.append(called)
        return object()

    monkeypatch.setattr(server_module, "build_server", fake_build_server)
    monkeypatch.setattr(server_module, "anyio", NoRun())

    rc = server_module.main.main(args, standalone_mode=False)
    assert rc == 0
    return seen


class FakeAddIn:
    """A loopback socket speaking the add-in's newline-delimited JSON.

    ``reply`` is a dict (a well-formed response) or ``bytes`` sent as-is, for
    corrupt-reply cases.  Every command received is recorded in ``commands`` so
    a test can assert what actually went on the wire.  The accept loop keeps
    running until the context manager exits, so a retried command is served
    rather than left to block on the listen backlog.
    """

    def __init__(self, reply: dict | bytes):
        self._reply = reply
        self.commands: list[dict] = []
        self._stop = threading.Event()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((HOST, 0))
        self._srv.listen(4)
        self._srv.settimeout(0.25)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._stop.set()
        self._srv.close()
        self._thread.join(timeout=5)
        return False

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except TimeoutError, OSError:
                continue
            with conn:
                self._serve_one(conn)

    def _serve_one(self, conn: socket.socket) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.commands.append(json.loads(line))
                payload = (
                    self._reply
                    if isinstance(self._reply, bytes)
                    else (json.dumps(self._reply) + "\n").encode()
                )
                conn.sendall(payload)


class TestToolWiring:
    def test_every_registered_tool_is_listed(self):
        async def check(session):
            return (await session.list_tools()).tools

        listed = drive("mock", check)
        assert {tool.name for tool in listed} == {tool["name"] for tool in TOOLS}

    def test_listed_tools_keep_their_schema(self):
        async def check(session):
            return (await session.list_tools()).tools

        for tool in drive("mock", check):
            assert tool.description, tool.name
            assert tool.inputSchema.get("type") == "object", tool.name

    def test_a_tool_call_returns_content(self):
        async def check(session):
            return await session.call_tool("get_scene_info", {})

        result = drive("mock", check)
        assert result.isError is False
        assert result.content[0].type == "text"
        assert "get_scene_info" in result.content[0].text

    def test_mutation_deltas_reach_the_client(self):
        """The deltas are the contract a caller reads to know a mutation landed."""

        async def check(session):
            return await session.call_tool("extrude", {"height": 1.0})

        text = drive("mock", check).content[0].text
        assert "deltas:" in text
        assert "(Δ+1)" in text
        assert "bbox_after" in text

    def test_an_unknown_tool_is_reported_as_an_error(self):
        async def check(session):
            return await session.call_tool("no_such_tool", {})

        result = drive("mock", check)
        assert result.isError is True
        assert "no_such_tool" in result.content[0].text


class TestResources:
    def test_lists_the_three_resources(self):
        async def check(session):
            return (await session.list_resources()).resources

        uris = {str(resource.uri) for resource in drive("mock", check)}
        assert uris == {
            "fusion360://status",
            "fusion360://design",
            "fusion360://parameters",
        }

    @pytest.mark.parametrize(
        ("uri", "key"),
        [
            ("fusion360://design", "design_name"),
            ("fusion360://parameters", "parameters"),
        ],
    )
    def test_reads_each_data_resource(self, uri: str, key: str):
        async def check(session):
            return await session.read_resource(AnyUrl(uri))

        payload = json.loads(drive("mock", check).contents[0].text)
        assert payload[key]

    def test_status_reports_a_live_addin(self):
        async def check(session):
            return await session.read_resource(AnyUrl("fusion360://status"))

        payload = json.loads(drive("mock", check).contents[0].text)
        assert payload["connected"] is True
        assert payload["ping"]["status"] == "pong"

    def test_lists_the_two_resource_templates(self):
        async def check(session):
            return (await session.list_resource_templates()).resourceTemplates

        templates = {template.uriTemplate for template in drive("mock", check)}
        assert templates == {
            "fusion360://body/{name}",
            "fusion360://component/{name}",
        }

    @pytest.mark.parametrize("kind", ["body", "component"])
    def test_reads_a_template_uri(self, kind: str):
        async def check(session):
            return await session.read_resource(AnyUrl(f"fusion360://{kind}/Shaft"))

        payload = json.loads(drive("mock", check).contents[0].text)
        assert payload["name"] == "Shaft"

    def test_an_unknown_resource_is_an_error(self):
        async def check(session):
            return await session.read_resource(AnyUrl("fusion360://nope"))

        # anyio re-raises inside its task group, so the failure arrives wrapped;
        # error_text() flattens it.  pytest.raises(Exception) holds on every
        # supported version because the group only ever wraps Exceptions.
        with pytest.raises(Exception) as caught:
            drive("mock", check)
        assert "Unknown resource" in error_text(caught.value)


class TestPrompts:
    def test_lists_the_three_prompts(self):
        async def check(session):
            return (await session.list_prompts()).prompts

        names = {prompt.name for prompt in drive("mock", check)}
        assert names == {
            "create-box",
            "model-threaded-bolt",
            "sheet-metal-enclosure",
        }

    @pytest.mark.parametrize(
        ("name", "token"),
        [
            ("create-box", "draw_rectangle"),
            ("model-threaded-bolt", "create_thread designation="),
            ("sheet-metal-enclosure", "create_flange"),
        ],
    )
    def test_each_prompt_renders_its_own_steps(self, name: str, token: str):
        async def check(session):
            return await session.get_prompt(name)

        text = drive("mock", check).messages[0].content.text
        assert token in text

    def test_prompt_arguments_reach_the_template(self):
        async def check(session):
            return await session.get_prompt("create-box", {"length": "42"})

        text = drive("mock", check).messages[0].content.text
        assert "height=42" in text

    def test_an_unknown_prompt_is_an_error(self):
        async def check(session):
            return await session.get_prompt("no-such-prompt")

        with pytest.raises(Exception) as caught:
            drive("mock", check)
        assert "Unknown prompt" in error_text(caught.value)


class TestSocketFailures:
    def test_addin_error_envelope_reaches_the_client(self):
        envelope = {
            "status": "error",
            "message": "Body 'Nope' not found",
            "error_kind": "BODY_NOT_FOUND",
            "hints": ["call get_scene_info"],
        }
        with FakeAddIn(envelope) as addin:

            async def check(session):
                return await session.call_tool("get_object_info", {"name": "Nope"})

            result = drive("socket", check, port=addin.port)

        text = result.content[0].text
        assert result.isError is True
        assert "BODY_NOT_FOUND" in text
        assert "call get_scene_info" in text
        assert addin.commands == [
            {"type": "get_object_info", "params": {"name": "Nope"}}
        ]

    def test_a_corrupt_addin_reply_is_reported_not_raised(self):
        with FakeAddIn(b"this is not json\n") as addin:

            async def check(session):
                return await session.call_tool("ping", {})

            result = drive("socket", check, port=addin.port)

        text = result.content[0].text
        assert result.isError is True
        # The reply body, not a refused connection: the socket was used.
        assert "Expecting value" in text
        assert "Fusion 360" in text

    def test_status_resource_reports_a_disconnected_addin(self):
        with FakeAddIn(b"corrupt\n") as addin:

            async def check(session):
                return await session.read_resource(AnyUrl("fusion360://status"))

            reply = drive("socket", check, port=addin.port)
            payload = json.loads(reply.contents[0].text)

        assert payload["connected"] is False
        assert "error" in payload

    @pytest.mark.parametrize(
        "uri",
        ["fusion360://design", "fusion360://parameters"],
    )
    def test_data_resources_degrade_to_a_json_error(self, uri: str):
        with FakeAddIn(b"corrupt\n") as addin:

            async def check(session):
                return await session.read_resource(AnyUrl(uri))

            reply = drive("socket", check, port=addin.port)
            payload = json.loads(reply.contents[0].text)

        assert "error" in payload

    @pytest.mark.parametrize("kind", ["body", "component"])
    def test_template_resources_degrade_to_a_json_error(self, kind: str):
        with FakeAddIn(b"corrupt\n") as addin:

            async def check(session):
                return await session.read_resource(AnyUrl(f"fusion360://{kind}/Shaft"))

            reply = drive("socket", check, port=addin.port)
            payload = json.loads(reply.contents[0].text)

        assert "error" in payload


class TestCliSurface:
    def test_main_forwards_mode_host_and_port(self, monkeypatch):
        """The one interaction assertion worth making: this is main's only job."""
        seen = capture_main(
            monkeypatch,
            ["--mode", "mock", "--host", "1.2.3.4", "--port", "5555"],
        )

        assert seen == [("mock", "1.2.3.4", 5555)]

    def test_the_options_are_unchanged(self):
        assert isinstance(server_module.main, click.Command)
        flags = [opt for param in server_module.main.params for opt in param.opts]
        assert flags == ["--mode", "--host", "--port"]

    def test_host_and_port_defaults_read_the_environment(self, monkeypatch):
        monkeypatch.setenv("FUSION_MCP_HOST", "10.0.0.9")
        monkeypatch.setenv("FUSION_MCP_PORT", "9999")

        seen = capture_main(monkeypatch, [])

        assert seen == [("socket", "10.0.0.9", 9999)]
