"""Guards against the add-in calling Fusion APIs that do not exist.

Each test runs a handler against the fake runtime in ``tests/fakes/`` and asserts
on what it produced.  The fake models Fusion's API and, where it departs from it,
departs deliberately — no ``TimelineObject.deleteMe()``, no
``MeasureResults.pointOnEntityOne``, no ``Component.interfere()`` — so the call
shapes these guards protect against fail here the way they failed in Fusion.

``add_joint`` still has source guards in ``test_addon_joints.py``: modelling
joint motions costs more fake than those guards are worth today, and that
conversion is a follow-up rather than a silent omission.
"""

from __future__ import annotations

import pytest

from tests.fakes.bodies import FakeBody, body_with_faces
from tests.fakes.design import FakeComponent, FakeDesign, FakeOccurrence
from tests.fakes.features import FakeInterferenceResult, FakeMeasureManager


class TestDeleteAll:
    def test_deletes_through_the_timeline_entity(self, bound_handler):
        """TimelineObject has no deleteMe(); the entity it wraps does.

        Calling deleteMe() on the TimelineObject raised AttributeError on every
        item, so delete_all removed nothing — and then reported success.
        """
        design = FakeDesign(features=2)

        result = bound_handler(design).delete_all()

        assert result["deleted"]["timeline"] == 2
        assert result["remaining"]["timeline"] == 0

    def test_raises_when_a_body_survives(self, bound_handler):
        """A bare ``except: pass`` is what let it claim success doing nothing."""

        class StubbornBody(FakeBody):
            def deleteMe(self):
                raise RuntimeError("Fusion refused")

        design = FakeDesign(features=0, bodies=[StubbornBody("Keeper")])

        with pytest.raises(RuntimeError, match="did not clear the design"):
            bound_handler(design).delete_all()

    def test_timeline_failures_are_reported_not_swallowed(self, bound_handler):
        """The timeline sweep is outside the fatal check, so it must report.

        The old source guard banned a bare ``except: pass`` anywhere in the
        handler; the behavioural equivalent is a timeline entry whose deletion
        fails, which has to surface in ``errors`` rather than vanish.
        """

        class StubbornDesign(FakeDesign):
            def _new_entry(self, index):
                entry = super()._new_entry(index)

                def refuse():
                    raise RuntimeError("Fusion refused")

                entry.entity.deleteMe = refuse
                return entry

        design = StubbornDesign(features=1)

        result = bound_handler(design).delete_all()

        assert [error["stage"] for error in result["errors"]] == ["timeline"]
        assert result["deleted"]["timeline"] == 0

    def test_reports_what_it_did(self, bound_handler):
        design = FakeDesign(features=2)

        result = bound_handler(design).delete_all()

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
    def test_reports_the_interfering_pairs(self, bound_handler):
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

        result = bound_handler(design).check_interference(["Base", "Lid"])

        assert result["count"] == 1
        assert result["interferences"] == [
            {"body_one": "Base", "body_two": "Lid", "volume": 0.75}
        ]
        # The analysis is asked about bodies, not components.
        assert design.interference.inputs[0].entities.items == [body_a, body_b]

    def test_requires_two_components_with_bodies(self, bound_handler):
        design = FakeDesign(features=0)
        design.rootComponent.occurrences.add(
            FakeOccurrence(FakeComponent("Base", [FakeBody("Only")]))
        )

        with pytest.raises(RuntimeError, match="at least 2 components"):
            bound_handler(design).check_interference(["Base"])


class TestDraftFaces:
    """``DraftFeatures.createInput(inputFaces, plane, isTangentChain)``.

    ``inputFaces`` is a BRepFace *array* — an ObjectCollection is rejected — and
    the angle goes on the returned input via ``setSingleAngle(isSymmetric,
    angle)``.  The fake raises the same TypeError Fusion does for a collection,
    so passing one by mistake fails here.
    """

    def test_builds_the_feature_and_reports_the_face_count(self, bound_handler):
        body = body_with_faces("Plate", [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)])
        design = FakeDesign(features=2, bodies=[body])

        result = bound_handler(design).draft_faces(body_name="Plate", angle=5)

        assert result == {"feature_name": "Draft1", "angle": 5, "face_count": 1}

    def test_passes_the_selected_faces_as_an_array(self, bound_handler):
        body = body_with_faces("Plate", [(1.0, 0.0, 0.0)])
        design = FakeDesign(features=2, bodies=[body])
        drafts = design.rootComponent.features.draftFeatures

        bound_handler(design).draft_faces(body_name="Plate", angle=5)

        assert drafts.added[0].faces == [body.faces.item(0)]

    def test_sets_the_angle_on_the_input(self, bound_handler):
        body = body_with_faces("Plate", [(1.0, 0.0, 0.0)])
        design = FakeDesign(features=2, bodies=[body])
        drafts = design.rootComponent.features.draftFeatures

        bound_handler(design).draft_faces(body_name="Plate", angle=5)

        inp = drafts.added[0]
        assert inp.angle is not None, "the draft angle was never set on the input"
        assert inp.angle.value == "5 deg"
        assert inp.symmetric is False


class TestMeasureDistance:
    """``MeasureResults`` exposes ``positionOne``/``positionTwo`` and nothing else."""

    def test_reads_the_result_positions(self, bound_handler):
        body_a, body_b = FakeBody("A"), FakeBody("B")
        manager = FakeMeasureManager(value=2.5, point_two=(2.5, 0.0, 0.0))
        design = FakeDesign(features=0, bodies=[body_a, body_b])

        result = bound_handler(design, _app(manager)).measure_distance("A", "B")

        assert result["distance"] == 2.5
        assert result["point_one"] == [0.0, 0.0, 0.0]
        assert result["point_two"] == [2.5, 0.0, 0.0]
        # The names resolved to the bodies, not to strings or components.
        assert manager.measured == [(body_a, body_b)]

    def test_unknown_entity_is_refused(self, bound_handler):
        design = FakeDesign(features=0)

        with pytest.raises(RuntimeError, match="not found"):
            bound_handler(design, _app(FakeMeasureManager())).measure_distance(
                "Ghost", "Ghost"
            )


def _app(measure_manager: FakeMeasureManager):
    return type("FakeApp", (), {"measureManager": measure_manager})()
