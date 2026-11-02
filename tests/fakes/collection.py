"""Fusion-style collections, including the deletable ones ``delete_all`` sweeps.

Fusion collections expose ``count`` and ``item(i)``, not ``__getitem__``.  Items
that Fusion lets you delete get a ``deleteMe()`` that removes them from the
collection they live in, so a test can assert that a sweep really emptied the
design rather than merely recorded a call.
"""

from __future__ import annotations

from collections.abc import Iterator


class FakeDeletable:
    """Anything Fusion lets a caller delete: a body, a joint, a plane, a sketch."""

    def __init__(self, name: str = "Item1"):
        self.name = name
        self._collection: FakeCollection | None = None

    def deleteMe(self) -> None:
        if self._collection is not None:
            self._collection.remove(self)


class FakeCollection:
    """``.count`` / ``.item(i)`` over a list, with removal for ``deleteMe()``."""

    def __init__(self, items: list | None = None):
        self._items: list = []
        for item in items or []:
            self.add(item)

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int):
        return self._items[index]

    def add(self, item) -> None:
        self._items.append(item)
        setattr(item, "_collection", self)

    def remove(self, item) -> None:
        if item in self._items:
            self._items.remove(item)

    def __iter__(self) -> Iterator[object]:
        return iter(self._items)
