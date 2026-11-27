"""`scripts/health_check.py`'s exit codes are its contract, so they are pinned here.

The script exists to tell a supervisor whether Fusion's *main thread* is answering, and
every one of its first three defects — a `None` host reaching `connect()`, an
add-in-side `ok: false` read as success, and a missing command reported as a wedge —
would have been caught by the tests below. Loaded by path, as the sibling script tests
do.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

from fusion360_mcp.connection import FusionError

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, stem: str):
    path = ROOT / "scripts" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = _load("health_check", "health_check")

GOOD = {
    "ok": True,
    "app_version": "2706.1.17",
    "active_document": "Plate",
    "queue_depth": 0,
}


class FakeConnection:
    """What the script needs from a connection, with the reply chosen per test."""

    def __init__(
        self, *, reply=None, raises=None, connects=True, record=None, **kwargs
    ):
        self.reply = GOOD if reply is None else reply
        self.raises = raises
        self.connects = connects
        self.kwargs = kwargs
        # The script's "nothing listening" message names them.
        self.host = kwargs.get("host", "127.0.0.1")
        self.port = kwargs.get("port", 9876)
        self.disconnected = False
        if record is not None:
            record.append(kwargs)

    def connect(self) -> bool:
        return self.connects

    def health(self, timeout: float):
        if self.raises is not None:
            raise self.raises
        return self.reply

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture
def connection_factory(monkeypatch):
    """Install a fake connection class and hand back the list of constructor kwargs."""

    def install(**options):
        calls: list[dict] = []
        monkeypatch.setattr(
            CHECK,
            "Fusion360Connection",
            lambda **kwargs: FakeConnection(record=calls, **options, **kwargs),
        )
        return calls

    return install


def test_a_good_reply_exits_zero(connection_factory):
    connection_factory()

    assert CHECK.main([]) == 0


def test_an_add_in_side_failure_is_not_success(connection_factory, capsys):
    """`send_command` raises only for transport errors, so an `ok: false` body is the
    script's own to read - and reading it as success is a false green."""
    connection_factory(
        reply={"ok": False, "error_kind": "INTERNAL_ERROR", "error_message": "boom"}
    )

    assert CHECK.main([]) == 1
    assert "boom" in capsys.readouterr().err


def test_a_wedged_thread_is_exit_one(connection_factory, capsys):
    connection_factory(raises=ConnectionError("timed out"))

    assert CHECK.main(["--json"]) == 1
    report = json.loads(capsys.readouterr().out.strip())
    assert report == {
        "answered": False,
        "error_kind": "NO_ANSWER",
        "error": "timed out",
    }


def test_a_missing_command_says_to_reload(connection_factory, capsys):
    """An add-in loaded before `health` existed is a "reload it", not a wedge."""
    connection_factory(raises=FusionError("Unknown command: health", "UNKNOWN_COMMAND"))

    assert CHECK.main([]) == 3
    err = capsys.readouterr().err
    assert "reload" in err
    assert "did not answer" not in err, (
        "UNKNOWN_COMMAND was answered by the main thread; a wedge hint here is false"
    )


def test_nothing_listening_is_exit_two(connection_factory):
    connection_factory(connects=False)

    assert CHECK.main([]) == 2


def test_the_connection_is_built_without_none_keywords(connection_factory):
    """The package's defaults apply only when the key is absent: `host=None` reaches
    `s.connect((None, None))` and the failure reads as "not connected"."""
    calls = connection_factory()

    CHECK.main([])

    assert calls == [{}], calls


def test_an_explicit_host_and_port_are_passed_through(connection_factory):
    calls = connection_factory()

    CHECK.main(["--host", "10.0.0.5", "--port", "9999"])

    assert calls == [{"host": "10.0.0.5", "port": 9999}], calls


def test_watch_mode_reports_the_first_failure_not_the_last(monkeypatch):
    """A run that saw a wedge did see it: the exit code is the first failure."""
    replies = [ConnectionError("timed out"), GOOD]

    class _Flaky(FakeConnection):
        def health(self, timeout: float):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(CHECK, "Fusion360Connection", lambda **_: _Flaky())

    assert CHECK.main(["--interval", "0", "-n", "2"]) == 1


def test_the_timeout_flag_reaches_the_client(monkeypatch):
    """`--timeout` is what bounds the wedge case; hard-coding 5.0 must fail this."""
    seen: list[float] = []

    class _Recording(FakeConnection):
        def health(self, timeout: float):
            seen.append(timeout)
            return GOOD

    monkeypatch.setattr(CHECK, "Fusion360Connection", lambda **_: _Recording())

    assert CHECK.main(["--timeout", "3"]) == 0
    assert seen == [3.0], seen


def test_json_mode_prints_one_object_per_poll(connection_factory, capsys):
    connection_factory()

    assert CHECK.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out.strip())
    assert report == {
        "answered": True,
        "ok": True,
        "app_version": "2706.1.17",
        "active_document": "Plate",
        "queue_depth": 0,
    }


def test_a_refusal_that_is_not_a_missing_command_is_exit_one(connection_factory):
    """Only UNKNOWN_COMMAND means "reload it"; a TIMEOUT-shaped refusal is not."""
    connection_factory(raises=FusionError("too slow", "TIMEOUT"))

    assert CHECK.main([]) == 1


def test_a_failed_command_is_reported_as_an_answer_not_a_wedge(
    connection_factory, capsys
):
    """`answered` stays true when the add-in answered with a failure."""
    connection_factory(
        reply={"ok": False, "error_kind": "INTERNAL_ERROR", "error_message": "boom"}
    )

    assert CHECK.main(["--json"]) == 1
    report = json.loads(capsys.readouterr().out.strip())
    assert report["answered"] is True
    assert report["ok"] is False


def test_the_socket_is_released_after_the_poll(monkeypatch):
    """A poll that leaves its socket open leaks one per supervisor run."""
    made: list = []

    def factory(**kwargs):
        connection = FakeConnection(**kwargs)
        made.append(connection)
        return connection

    monkeypatch.setattr(CHECK, "Fusion360Connection", factory)

    assert CHECK.main([]) == 0
    assert made and all(c.disconnected for c in made)
