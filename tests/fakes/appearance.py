"""Fake appearances: the design's own collection and a material library's.

``set_color`` creates an appearance on the **design** and assigns it to a body;
``set_appearance`` finds one by name in a **material library**, copies it into the
design and assigns the copy.  Both commands read the same ``count``/``item``/
``itemByName`` shape on two different collections, so a body that merely recorded an
assignment could not tell which appearance it ended up with - or whether a copy was
made at all.  That is what these model.

What is **not** modelled: an appearance's colour for one nobody assigned.  Fusion
reports the library material's colour and this fake has no material to read, so a
``FakeAppearance``'s ``color`` stays ``None`` until something writes it - an absence
rather than a measurement.

Nothing here clamps or converts: ``add``/``addByCopy`` take the caller's name and
keep the source appearance's colour, which is the copying ``set_appearance`` is
tested for.  A wrong arity raises ``TypeError`` because Python's own call does;
no other refusal is invented, and names are compared exactly - no measurement says
Fusion's ``itemByName`` ignores case, so the fake does not.
"""

from __future__ import annotations

from collections.abc import Iterator


class FakeAppearance:
    """``adsk.core.Appearance``: a name, and the colour ``set_color`` writes.

    ``color`` holds whatever was assigned - a ``FakeColor`` from
    ``adsk.core.Color.create`` - and is never computed.
    """

    def __init__(self, name: str, color: object | None = None):
        self.name = name
        self.color = color

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakeAppearance({self.name!r})"


class FakeAppearances:
    """``design.appearances`` and ``materialLibrary.appearances``.

    The design's collection also takes ``add(name)`` and ``addByCopy(appearance,
    name)``, which is where the two commands differ: ``set_color`` adds a colour of
    its own, ``set_appearance`` copies a library appearance in.  Both return the
    created appearance, as Fusion's do, because that is what gets assigned to the
    body.
    """

    def __init__(self, items: list[FakeAppearance] | None = None):
        self._items: list[FakeAppearance] = list(items or [])

    @property
    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> FakeAppearance:
        return self._items[index]

    def itemByName(self, name: str) -> FakeAppearance | None:
        """The appearance of that name, or ``None``.

        ``None`` rather than a raise is the handler's own reading of Fusion: both
        commands test ``is None`` before creating one.  A fake that raised would
        say something about Fusion nobody measured.
        """
        for appearance in self._items:
            if appearance.name == name:
                return appearance
        return None

    def add(self, name: str) -> FakeAppearance:
        """``Appearances.add(name)``: a new design-local appearance."""
        return self._append(FakeAppearance(name))

    def addByCopy(self, appearance: FakeAppearance, name: str) -> FakeAppearance:
        """``Appearances.addByCopy(appearance, name)``: the design's own copy.

        A **new object** carrying the source's colour and no link back to it, so a
        handler that assigned the library appearance instead of the copy is
        visible here.
        """
        return self._append(FakeAppearance(name, appearance.color))

    def _append(self, appearance: FakeAppearance) -> FakeAppearance:
        self._items.append(appearance)
        return appearance

    def __iter__(self) -> Iterator[FakeAppearance]:
        return iter(self._items)


class FakeMaterialLibrary:
    """``adsk.core.MaterialLibrary``: a name, and the appearances in it."""

    def __init__(self, name: str, appearances: list[FakeAppearance] | None = None):
        self.name = name
        self.appearances = FakeAppearances(list(appearances or []))


class FakeMaterialLibraries:
    """``app.materialLibraries``: looked up by name, or picked positionally.

    ``set_appearance`` searches it three ways - two known library names, then the
    first library holding any appearance at all - so the fake answers an exact
    ``itemByName`` and nothing cleverer.  The *names* a test gives its library are
    the test's: which libraries a Fusion install ships was not measured here.
    """

    def __init__(self, libraries: list[FakeMaterialLibrary] | None = None):
        self._libraries: list[FakeMaterialLibrary] = list(libraries or [])

    @property
    def count(self) -> int:
        return len(self._libraries)

    def item(self, index: int) -> FakeMaterialLibrary:
        return self._libraries[index]

    def itemByName(self, name: str) -> FakeMaterialLibrary | None:
        for library in self._libraries:
            if library.name == name:
                return library
        return None

    def __iter__(self) -> Iterator[FakeMaterialLibrary]:
        return iter(self._libraries)
