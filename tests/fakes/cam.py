"""Fake CAM generation futures, one completion shape each.

``GenerateToolpathFuture`` on Fusion 2706.1.17 exposes ``isGenerationCompleted``
and the ``numberOfCompleted`` / ``numberOfOperations`` pair; it has neither
``isCompleted`` nor ``wait``.  These fakes model one shape each rather than a
convenient superset, so reading a field a shape does not have raises
``AttributeError`` exactly as SWIG does -- a handler that invents ``wait()``
cannot pass by finding it here.
"""

from __future__ import annotations

from .collection import FakeItemCollection


class _PollingFuture:
    """A future that completes on its *completed_after*-th read; ``None`` never.

    The completion attribute itself lives on the subclass, not here: this base
    carries only the poll counter and the switch the tests flip.
    """

    def __init__(self, completed_after: int | None = 2):
        self._completed_after = completed_after
        self._reads = 0

    def _poll(self) -> bool:
        self._reads += 1
        return (
            self._completed_after is not None and self._reads >= self._completed_after
        )


class FakeGenerationFlagFuture(_PollingFuture):
    """The 2706.1.17 ``GenerateToolpathFuture``: one boolean flag, no counters."""

    @property
    def isGenerationCompleted(self) -> bool:
        return self._poll()


class FakeCompletedFlagFuture(_PollingFuture):
    """Another future type's spelling: ``isCompleted`` and nothing else."""

    @property
    def isCompleted(self) -> bool:
        return self._poll()


class FakeCounterFuture(_PollingFuture):
    """Only the completed/total counters, with no boolean flag."""

    def __init__(self, number_of_operations: int = 2, completed_after: int | None = 2):
        super().__init__(completed_after)
        self.numberOfOperations = number_of_operations

    @property
    def numberOfCompleted(self) -> int:
        self._reads += 1
        if self._completed_after is None:
            return 0
        return min(self._reads, self._completed_after)


class FakeNoFlagFuture:
    """A future exposing no completion field this add-in knows how to read."""


class FakeCAMProduct:
    """The CAM ``Product`` shape ``cam_generate_toolpath`` reads.

    ``generateToolpath`` records the target and answers the future it was built
    with, so the end-to-end test can prove the operation object reached Fusion's
    own call and that the result is only reported after the future completes.
    """

    def __init__(self, setups, future):
        self.setups = FakeItemCollection(setups)
        self.future = future
        self.generated = []

    def generateToolpath(self, target):
        self.generated.append(target)
        return self.future
