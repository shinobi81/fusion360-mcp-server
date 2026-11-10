"""The bridge, constructed outside Fusion: the factory is the part that moved.

``_MainThreadHandler`` used to take ``adsk.core.CustomEventHandler`` as a base class at
import time, and annotate with ``adsk.core.Application`` in a module without
``from __future__ import annotations``.  Both now happen at construction, so this test
exists to prove the class is still wired to the bridge and still drains the queue.
"""

from __future__ import annotations

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
