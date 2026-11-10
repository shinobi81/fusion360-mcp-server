"""The bridge, constructed outside Fusion: the factory is the part that moved.

``_MainThreadHandler`` used to take ``adsk.core.CustomEventHandler`` as a base class at
import time, and annotate with ``adsk.core.Application`` in a module without
``from __future__ import annotations``.  Both now happen at construction, so this test
exists to prove the class is still wired to the bridge and still drains the queue.
"""

from __future__ import annotations

import threading
import types

import pytest

from addon.server import event_bridge, fusion_api
from tests.fakes.app import FakeApplication, FakeCustomEventHandler


@pytest.fixture(autouse=True)
def _bridge_base():
    """Give the adapter a ``core`` carrying the base class the bridge subclasses.

    ``EventBridge.__init__`` resolves ``adsk.core.CustomEventHandler`` at
    construction, so a test that builds a bridge outside Fusion supplies exactly that.
    If a core is already installed (a module-scoped ``handler_module``), the base class
    is added to it rather than replacing it: replacing would strip the rest of the
    fake API mid-module.
    """
    installed = fusion_api.__dict__.get("core")
    added = installed is None or not hasattr(installed, "CustomEventHandler")

    if installed is None:
        fusion_api.core = types.SimpleNamespace(
            CustomEventHandler=FakeCustomEventHandler
        )
    elif added:
        installed.CustomEventHandler = FakeCustomEventHandler

    yield

    if installed is None:
        fusion_api.__dict__.pop("core", None)
    elif added:
        delattr(installed, "CustomEventHandler")


class Handler:
    """A command handler with no Fusion behind it, standing in for the real one."""

    def __init__(self):
        self.commands: list = []

    def execute_command(self, command):
        self.commands.append(command)
        return {"ok": True, "ran": command["type"]}


class StubBridge:
    """Only what ``notify`` needs from the bridge: a queue to drain."""

    def __init__(self):
        self.drained = 0

    def drain_queue(self) -> None:
        self.drained += 1


def test_the_event_handler_is_built_for_the_bridge_and_drains_its_queue():
    app = FakeApplication()
    handler = Handler()
    bridge = event_bridge.EventBridge(app, handler)
    try:
        (event_handler,) = app.events[0].handlers
        bridge._queue.put(event_bridge.WorkItem({"type": "queued"}))

        event_handler.notify(None)

        assert handler.commands == [{"type": "queued"}]
    finally:
        bridge.stop()

    assert app.unregistered == [event_bridge.CUSTOM_EVENT_ID]


def test_the_factory_builds_a_subclass_of_the_base_it_is_given():
    class Base:
        def __init__(self):
            self.base_ran = True

    bridge = StubBridge()
    cls = event_bridge._handler_class(Base)
    instance = cls(bridge)

    assert issubclass(cls, Base)
    assert instance.base_ran is True

    instance.notify(None)
    assert bridge.drained == 1, "the handler reached the bridge it was given"


def test_submit_survives_a_failing_fire_because_the_timer_retries():
    """A dead ``fireCustomEvent`` must not fail the call: the timer picks it up.

    ``submit``'s own fire raises; the 200 ms timer fires again, and this time the
    faked application drains the queue the way Fusion's handler does on notify.  So
    the command still runs - a nudge that fails is not a lost command, which is the
    claim the ``suppress`` in ``submit`` exists to make.

    Which fire raises is decided by the calling thread, not by arrival order: a fire
    that happened to come from the timer first would put the raise inside
    ``_timer_loop``'s own ``suppress`` and leave ``submit``'s swallowed one untested.
    """
    app = FakeApplication()
    fires = []

    def flaky(event_id):
        fires.append(event_id)
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError("no event")  # submit's own fire, always
        bridge.drain_queue()  # the timer's retry, standing in for Fusion's notify

    app.fireCustomEvent = flaky
    bridge = event_bridge.EventBridge(app, Handler())

    try:
        result = bridge.submit({"type": "noop"}, timeout=5.0)
    finally:
        bridge.stop()

    assert fires[0] == event_bridge.CUSTOM_EVENT_ID
    assert len(fires) >= 2, "the timer never retried the fire"
    assert result == {"ok": True, "ran": "noop"}


def test_a_permanently_dead_fire_times_out_instead_of_raising():
    """A nudge that never works is a timeout, not an exception at the caller.

    The item can never be drained here - the only thing that would drain it is the
    same ``fireCustomEvent``, and that raises every time - so ``timeout=0`` decides
    the result deterministically.  This is the caller-facing half of the ``suppress``:
    a dead nudge delays nothing, and what comes back is the envelope any unpicked-up
    command gets.
    """
    app = FakeApplication()

    def dead(_event_id):
        raise RuntimeError("no event")

    app.fireCustomEvent = dead
    bridge = event_bridge.EventBridge(app, Handler())

    try:
        result = bridge.submit({"type": "noop"}, timeout=0)
    finally:
        bridge.stop()

    assert result["status"] == "error"
    assert result["error_kind"] == "TIMEOUT"
