"""Which faces `shell` / `draft_faces` / `offset_faces` are told to open.

`_select_faces` and `shell` both took their threshold from the body's bounding
box, so a face matched whenever it *reached* the top - and on a plain box every
side wall reaches it. Measured live on Fusion 2706: `shell(face_selection="top")`
on a 10 x 10 x 2 box removed **five** faces, the top and all four walls.

"Top" now means the faces lying in the top plane, the rule the edge selectors got
in #46, and `shell` shares it instead of duplicating the threshold.

The fake carries a `shellFeatures` collection for this; `shell` had no test at all
before (no fake could build one).
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from fusion360_mcp.mock import mock_command
from tests.fakes.bodies import FakeBody, FakeBoundingBox, FakeFace
from tests.fakes.collection import FakeCollection
from tests.fakes.design import FakeDesign


def face(z0: float, z1: float, normal=(0.0, 0.0, 1.0)) -> FakeFace:
    """A face spanning *z0*..*z1* — a box face, or a curved one if the span is wide."""
    return FakeFace(
        normal=normal,
        bounding_box=FakeBoundingBox((-1.0, -1.0, z0), (1.0, 1.0, z1)),
    )


def box_faces() -> list[FakeFace]:
    """A 2 cm plate: one top face, one bottom, four walls that reach both."""
    wall_normal = (1.0, 0.0, 0.0)
    return [
        face(2.0, 2.0),  # 0 top
        face(0.0, 0.0),  # 1 bottom
        face(0.0, 2.0, wall_normal),  # 2 wall
        face(0.0, 2.0, wall_normal),  # 3 wall
        face(0.0, 2.0, wall_normal),  # 4 wall
        face(0.0, 2.0, wall_normal),  # 5 wall
    ]


def _removed_faces(design: FakeDesign) -> list:
    """The faces the last shell was told to open, narrowed for the type checker."""
    inp = design.rootComponent.features.shellFeatures.last_input
    assert inp is not None, "no shell input was created"
    return list(inp.facesToRemove or [])


def _design(faces: list[FakeFace]) -> FakeDesign:
    body = FakeBody("Plate", faces=FakeCollection(faces))
    return FakeDesign(bodies=[body])


def test_shell_top_opens_one_face_on_a_box(bound_handler):
    """The measured defect: five faces removed where one is meant."""
    design = _design(box_faces())
    handler = bound_handler(design)

    result = handler.shell(thickness=0.2, body_name="Plate", face_selection="top")

    assert result["faces_removed"] == 1
    removed = _removed_faces(design)
    assert removed == [design.rootComponent.bRepBodies.item(0).faces.item(0)], (
        "the top face is the only one in the top plane"
    )


def test_shell_bottom_opens_the_bottom_face_only(bound_handler):
    design = _design(box_faces())
    handler = bound_handler(design)

    result = handler.shell(thickness=0.2, body_name="Plate", face_selection="bottom")

    assert result["faces_removed"] == 1
    assert _removed_faces(design) == [
        design.rootComponent.bRepBodies.item(0).faces.item(1)
    ]


def test_select_faces_top_returns_only_the_flat_top(bound_handler):
    """Identity, not index: the fake's faces carry no index of their own."""
    faces = box_faces()
    handler = bound_handler(_design(faces))
    body = handler._root().bRepBodies.item(0)

    assert list(handler._select_faces(body, "top")) == [faces[0]]


def test_a_face_that_only_reaches_the_top_is_not_in_it(bound_handler):
    """A wall spans 0..2; the top plane is z=2. Reaching is not lying in."""
    handler = bound_handler(_design(box_faces()))
    body = handler._root().bRepBodies.item(0)

    chosen = list(handler._select_faces(body, "top"))

    assert all(f.boundingBox.minPoint.z == pytest.approx(2.0) for f in chosen)


def test_a_domed_body_resolves_to_its_flat_top_ring(bound_handler):
    """A curved face's box peaks at the dome apex; a plane needs a face in it."""
    faces = [face(1.0, 1.0), face(-2.0, 4.0)]  # flat ring at z=1, dome bulging
    handler = bound_handler(_design(faces))
    body = handler._root().bRepBodies.item(0)

    coll = handler._select_faces(body, "top")

    assert list(coll) == [faces[0]], "the flat ring at z=1, not the dome"


def test_a_body_with_no_flat_top_refuses_and_says_where_it_lost(bound_handler):
    handler = bound_handler(_design([face(-2.0, 4.0)]))
    body = handler._root().bRepBodies.item(0)

    with pytest.raises(RuntimeError) as raised:
        handler._select_faces(body, "top")

    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("flat plane" in hint for hint in hints), hints


def test_shell_refuses_an_unknown_selection_before_touching_a_body(bound_handler):
    design = _design(box_faces())
    handler = bound_handler(design)

    with pytest.raises(RuntimeError) as raised:
        handler.shell(thickness=0.2, body_name="Plate", face_selection="sideways")

    assert "top/bottom" in str(raised.value)
    assert design.rootComponent.features.shellFeatures.inputs == [], (
        "no shell input may exist after a refusal"
    )


def test_vertical_still_selects_by_normal(bound_handler):
    """Unchanged behaviour: walls have a horizontal normal, the flat faces do not."""
    faces = box_faces()
    handler = bound_handler(_design(faces))
    body = handler._root().bRepBodies.item(0)

    coll = handler._select_faces(body, "vertical")

    assert list(coll) == faces[2:]


# ── mock parity ───────────────────────────────────────────────────────


def test_mock_refuses_an_unknown_face_selection():
    result = mock_command("shell", {"thickness": 0.2, "face_selection": "sideways"})

    assert result["ok"] is False
    assert result["error_kind"] == "INVALID_INPUT"
    assert result["hints"]


def test_mock_accepts_the_two_it_documents():
    for selection in ("top", "bottom"):
        assert mock_command("shell", {"thickness": 0.2, "face_selection": selection})[
            "ok"
        ]
