"""Fake CAM generation futures, one completion shape each.

``GenerateToolpathFuture`` on Fusion 2706.1.17 exposes ``isGenerationCompleted``
and the ``numberOfCompleted`` / ``numberOfOperations`` pair; it has neither
``isCompleted`` nor ``wait``.  It also *raises* ``RuntimeError("3 : Generation not
started")`` when a completion field is read before generation begins.  These fakes
model one shape each rather than a convenient superset, so reading a field a
shape does not have raises ``AttributeError`` exactly as SWIG does -- a handler
that invents ``wait()`` cannot pass by finding it here.
"""

from __future__ import annotations

from .collection import FakeItemCollection

_NOT_STARTED = "3 : Generation not started"


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


class FakeNotStartedFuture:
    """``isGenerationCompleted`` raises "not started" for the first reads.

    Measured on 2706.1.17: ``cam.generateToolpath`` returns the future before
    generation starts, and the property raises until it does.  The first
    ``starts_after - 1`` reads raise, then it answers ``True``.
    """

    def __init__(self, starts_after: int = 3):
        self._starts_after = starts_after
        self._reads = 0

    @property
    def isGenerationCompleted(self) -> bool:
        self._reads += 1
        if self._reads < self._starts_after:
            raise RuntimeError(_NOT_STARTED)
        return True


class FakeNeverStartedFuture:
    """``isGenerationCompleted`` raises "not started" forever."""

    @property
    def isGenerationCompleted(self) -> bool:
        raise RuntimeError(_NOT_STARTED)


class FakeGenerationFailureFuture:
    """A getter failing for a reason other than "not started"."""

    @property
    def isGenerationCompleted(self) -> bool:
        raise RuntimeError("3 : generation failed")


class FakeNotStartedCounterFuture(FakeCounterFuture):
    """The counter pair raises "not started" once, then answers normally."""

    def __init__(self):
        super().__init__(number_of_operations=2, completed_after=2)
        self._not_started = True

    @property
    def numberOfCompleted(self) -> int:
        if self._not_started:
            self._not_started = False
            self._reads += 1
            raise RuntimeError(_NOT_STARTED)
        return super().numberOfCompleted


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


class FakePostProcessInput:
    """``adsk.cam.PostProcessInput`` as the 2706 stub declares it.

    The class is marked *retired* in that stub and still shipped, which is why the
    handler can call it.  ``create`` takes the four positional arguments the stub
    names - ``programName``, ``postConfiguration``, ``outputFolder``,
    ``outputUnits`` - and ``isOpenInEditor`` is the writable property the handler
    sets afterwards.
    """

    def __init__(self, *args, **kwargs):
        # The shipped class refuses direct construction the same way
        # (``AttributeError("No constructor defined")``): only ``create`` builds one, so
        # a handler that swapped ``create(a, b, c, d)`` for ``PostProcessInput(a, b, c,
        # d)`` must fail here rather than pass a fake Fusion would not.
        raise AttributeError("No constructor defined")

    @classmethod
    def create(
        cls,
        programName: str,
        postConfiguration: str,
        outputFolder: str,
        outputUnits: object,
    ) -> FakePostProcessInput:
        instance = cls.__new__(cls)
        instance.programName = programName
        instance.postConfiguration = postConfiguration
        instance.outputFolder = outputFolder
        instance.outputUnits = outputUnits
        instance.isOpenInEditor = True
        return instance
