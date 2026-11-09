"""``adsk.core.Application``, as far as the bridge and ``CommandHandler`` reach it.

The bridge registers a custom event, fires it, and unregisters it;
``CommandHandler.__init__`` reads ``Application.get()`` and ``app.userInterface``.
Nothing here models a document: a handler under test gets its design from a fixture, and
an invented ``activeProduct`` would change what ``_snapshot`` reports.
"""

from __future__ import annotations

import types


class FakeCustomEvent:
    """``adsk.core.CustomEvent``: the handler list the bridge adds to and drops from."""

    def __init__(self):
        self.handlers: list = []

    def add(self, handler) -> None:
        self.handlers.append(handler)

    def remove(self, handler) -> None:
        self.handlers.remove(handler)


class FakeCustomEventHandler:
    """``adsk.core.CustomEventHandler``: the base the bridge subclasses at construction.

    It lives on ``adsk.core``, not on the application, which is why a test that builds
    an ``EventBridge`` outside Fusion has to put it there - the adapter resolves it
    lazily.
    """

    def __init__(self):
        self.notified = []


class FakeApplication:
    """``adsk.core.Application``: an event registry and a UI, no document."""

    def __init__(self):
        self.userInterface = types.SimpleNamespace()
        #: ``None`` on purpose — ``_snapshot`` then reports no deltas, which is what
        #: every existing handler test already sees.
        self.activeProduct = None
        self.events: list[FakeCustomEvent] = []
        self.fired: list[str] = []
        self.unregistered: list[str] = []

    @staticmethod
    def get() -> "FakeApplication":
        return FakeApplication()

    def registerCustomEvent(self, event_id: str) -> FakeCustomEvent:
        event = FakeCustomEvent()
        self.events.append(event)
        return event

    def fireCustomEvent(self, event_id: str) -> None:
        self.fired.append(event_id)

    def unregisterCustomEvent(self, event_id: str) -> None:
        self.unregistered.append(event_id)
