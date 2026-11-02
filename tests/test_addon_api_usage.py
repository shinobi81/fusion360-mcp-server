"""Guards against the add-in calling Fusion APIs that do not exist.

Each test runs a handler against the fake runtime in ``tests/fakes/`` and asserts
on what it produced.  The fakes implement only the API Fusion actually has, so a
handler that calls ``TimelineObject.deleteMe()``, ``Component.interfere()`` or
reads ``MeasureResults.pointOnEntityOne`` raises ``AttributeError`` here exactly
as it did in Fusion — which is what the old source-reading guards caught.

``add_joint`` still has source guards in ``test_addon_joints.py``: modelling
joint motions costs more fake than those guards are worth today, and that
conversion is a follow-up rather than a silent omission.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody, body_with_faces
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence
from tests.fakes.features import FakeInterferenceResult, FakeMeasureManager


def bound(handler_module, design, app=None):
    """A ``CommandHandler`` wired to *design*, with no Fusion application."""
    handler = handler_module.CommandHandler.__new__(handler_module.CommandHandler)
    handler._design = lambda: design
    handler._root = lambda: design.rootComponent
    if app is not None:
        handler.app = app
    return handler


class TestDeleteAll:
    def test_deletes_through_the_timeline_entity(self, handler_module):
        """TimelineObject has no deleteMe(); the entity it wraps does.

        Calling deleteMe() on the TimelineObject raised AttributeError on every
        item, so delete_all removed nothing — and then reported success.
        """
        design = FakeDesign(features=2)

        result = bound(handler_module, design).delete_all()

        assert result["deleted"]["timeline"] == 2
        assert result["remaining"]["timeline"] == 0

    def test_raises_when_something_survives(self, handler_module):
        """A bare ``except: pass`` is what let it claim success doing nothing."""

        class StubbornBody(FakeBody):
            def deleteMe(self):
                raise RuntimeError("Fusion refused")

        design = FakeDesign(features=0, bodies=[StubbornBody("Keeper")])

        with pytest.raises(RuntimeError, match="did not clear the design"):
            bound(handler_module, design).delete_all()

    def test_reports_what_it_did(self, handler_module):
        design = FakeDesign(features=2)

        result = bound(handler_module, design).delete_all()

        assert result["deleted"]["bodies"] == 1
        assert result["errors"] == []
        assert set(result["remaining"]) == {
            "bodies",
            "sketches",
            "occurrences",
            "joints",
            "construction",
            "timeline",
        }


class TestCheckInterference:
    def test_reports_the_interfering_pairs(self, handler_module):
        """Component.interfere() does not exist; the API is on Design."""
        body_a, body_b = FakeBody("Base"), FakeBody("Lid")
        design = FakeDesign(
            features=0,
            interferences=[FakeInterferenceResult(body_a, body_b, volume=0.75)],
        )
        design.rootComponent.occurrences.add(
            FakeOccurrence(FakeComponent("Base", [body_a]))
        )
        design.rootComponent.occurrences.add(
            FakeOccurrence(FakeComponent("Lid", [body_b]))
        )

        result = bound(handler_module, design).check_interference(["Base", "Lid"])

        assert result["count"] == 1
        assert result["interferences"] == [
            {"body_one": "Base", "body_two": "Lid", "volume": 0.75}
        ]

    def test_requires_two_components_with_bodies(self, handler_module):
        design = FakeDesign(features=0)
        design.rootComponent.occurrences.add(
            FakeOccurrence(FakeComponent("Base", [FakeBody("Only")]))
        )

        with pytest.raises(RuntimeError, match="at least 2 components"):
            bound(handler_module, design).check_interference(["Base"])


class TestDraftFaces:
    """``DraftFeatures.createInput(inputFaces, plane, isTangentChain)``.

    ``inputFaces`` is a BRepFace *array* — an ObjectCollection is rejected — and
    the angle goes on the returned input via ``setSingleAngle(isSymmetric,
    angle)``.  The fake rejects a non-sequence with the same TypeError Fusion
    raises, so passing the collection by mistake fails here.
    """

    def test_builds_the_feature_and_reports_the_face_count(self, handler_module):
        body = body_with_faces("Plate", [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)])
        design = FakeDesign(features=2, bodies=[body])

        result = bound(handler_module, design).draft_faces(body_name="Plate", angle=5)

        assert result == {"feature_name": "Draft1", "angle": 5, "face_count": 1}

    def test_passes_faces_as_an_array(self, handler_module):
        body = body_with_faces("Plate", [(1.0, 0.0, 0.0)])
        design = FakeDesign(features=2, bodies=[body])
        drafts = design.rootComponent.features.draftFeatures

        bound(handler_module, design).draft_faces(body_name="Plate", angle=5)

        assert isinstance(drafts.added[0].faces, list)

    def test_sets_the_angle_on_the_input(self, handler_module):
        body = body_with_faces("Plate", [(1.0, 0.0, 0.0)])
        design = FakeDesign(features=2, bodies=[body])
        drafts = design.rootComponent.features.draftFeatures

        bound(handler_module, design).draft_faces(body_name="Plate", angle=5)

        inp = drafts.added[0]
        assert inp.angle is not None, "the draft angle was never set on the input"
        assert inp.angle.value == "5 deg"
        assert inp.symmetric is False


class TestMeasureDistance:
    """``MeasureResults`` exposes ``positionOne``/``positionTwo`` and nothing else."""

    def test_reads_the_result_positions(self, handler_module):
        design = FakeDesign(features=0, bodies=[FakeBody("A"), FakeBody("B")])
        app = _app(FakeMeasureManager(value=2.5, point_two=(2.5, 0.0, 0.0)))

        result = bound(handler_module, design, app).measure_distance("A", "B")

        assert result["distance"] == 2.5
        assert result["point_one"] == [0.0, 0.0, 0.0]
        assert result["point_two"] == [2.5, 0.0, 0.0]

    def test_unknown_entity_is_refused(self, handler_module):
        design = FakeDesign(features=0)
        app = _app(FakeMeasureManager())

        with pytest.raises(RuntimeError, match="not found"):
            bound(handler_module, design, app).measure_distance("Ghost", "Ghost")


def _app(measure_manager: FakeMeasureManager):
    return type("FakeApp", (), {"measureManager": measure_manager})()
