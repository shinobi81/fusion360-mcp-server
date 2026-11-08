"""Fusion-style collections, including the deletable ones ``delete_all`` sweeps.

Fusion collections expose ``count`` and ``item(i)``, not ``__getitem__``.  Items
that Fusion lets you delete get a ``deleteMe()`` that removes them from the
collection they live in, so a test can assert that a sweep really emptied the
design rather than merely recorded a call.
"""

from __future__ import annotations

from collections.abc import Iterator


class FakeItemCollection:
    """Fusion's ``count`` / ``item(i)`` shape over items that live elsewhere.

    A **derived** collection — ``Feature.bodies``, which names bodies that already
    sit in ``bRepBodies`` — must not be a ``FakeCollection``: that one *adopts*
    what it is given (``_collection`` is how ``deleteMe`` works and how the shell
    ownership check finds the owning body), so wrapping bodies in it would quietly
    reparent them.  This view iterates and counts without touching its items.
    """

    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int):
        return self._items[index]

    def __iter__(self) -> Iterator[object]:
        return iter(self._items)


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
        # Not ``self.add(item)``: a subclass that overrides ``add`` (``FakeJoints``
        # does, because Fusion's ``joints.add`` returns the joint) would then be
        # called from the base constructor - flagged by CodeQL as
        # ``py/init-calls-subclass``, and a real footgun rather than a style point.
        self._items: list = list(items or [])
        for item in self._items:
            setattr(item, "_collection", self)

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int):
        return self._items[index]

    def add(self, item) -> object:
        """Append and hand the item back.

        Fusion's ``joints.add`` returns the joint it created, so a collection that
        returns nothing cannot model it.  Every other caller ignores the result.
        """
        self._items.append(item)
        setattr(item, "_collection", self)
        return item

    def remove(self, item) -> None:
        if item in self._items:
            self._items.remove(item)

    def __iter__(self) -> Iterator[object]:
        return iter(self._items)
