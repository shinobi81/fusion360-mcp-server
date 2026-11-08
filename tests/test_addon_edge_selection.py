"""Which edges a fillet or chamfer is told to round.

``_select_edges`` decides that, and it had never run under a test: ``FakeBody``
carried faces but no ``edges`` collection at all.  These tests give the fake an
edge model, and pin the behaviour of the four existing selections before the new
selectors build on top of them.

Fusion reads an edge's position with ``edge.pointOnEdge`` (a point at the
parameter midpoint) and its direction from ``startVertex``/``endVertex``; the
fake models exactly those, because that is what the handler reads.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.hints import classify
from fusion360_mcp.mock import mock_command
from tests.fakes.bodies import (
    FakeBody,
    FakeBoundingBox,
    FakeEdge,
    FakeEdges,
    body_with_edges,
)
from tests.fakes.design import FakeDesign


@pytest.fixture
def select(bound_handler):
    """``select(edge_pairs, selection, indices=...)`` -> the built collection."""

    def factory(edge_pairs, selection, indices=None, points=None, tolerance=0.1):
        body = body_with_edges("Plate", edge_pairs)
        handler = bound_handler(FakeDesign(bodies=[body]))
        return handler._select_edges(
            body,
            selection,
            indices=indices,
            points=points,
            tolerance=tolerance,
        )

    return factory


def test_all_selects_every_edge(select):
    coll = select([((0, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0))], "all")
    assert coll.count == 2


def test_top_selects_the_edge_in_the_highest_plane(select):
    """Three heights, so a wrong plane changes which edges come back.

    The plane is the highest one that holds *any* edge, which is z=5 here.  A
    plane taken from the body's box would be the same number in this fixture,
    so the difference between the two rules is pinned by the tests below, where
    the body spans past every edge it owns.
    """
    coll = select(
        [
            ((0, 0, 0), (1, 0, 0)),
            ((0, 0, 2.5), (1, 0, 2.5)),
            ((0, 0, 5), (1, 0, 5)),
        ],
        "top",
    )
    assert coll.count == 1
    assert coll.item(0).pointOnEdge.z == pytest.approx(5.0)


def test_bottom_selects_the_edge_in_the_lowest_plane(select):
    coll = select(
        [
            ((0, 0, 0), (1, 0, 0)),
            ((0, 0, 2.5), (1, 0, 2.5)),
            ((0, 0, 5), (1, 0, 5)),
        ],
        "bottom",
    )
    assert coll.count == 1
    assert coll.item(0).pointOnEdge.z == pytest.approx(0.0)


def test_vertical_selects_only_edges_with_no_x_or_y_extent(select):
    """The predicate reads the edge's box, not its two ends (renamed for that).

    The selected edge's own ends must differ in z — a count is not enough, since
    both edges are at the same height and an inverted predicate passes a count.
    The closed-edge case this rename came with is the test below.
    """
    coll = select(
        [((0, 0, 0), (0, 0, 2)), ((0, 0, 0), (3, 0, 0))],
        "vertical",
    )
    assert coll.count == 1
    chosen = coll.item(0)
    assert chosen.startVertex.geometry.x == pytest.approx(0.0)
    assert chosen.startVertex.geometry.y == pytest.approx(0.0)
    assert chosen.endVertex.geometry.z == pytest.approx(2.0)


def test_an_unknown_selection_names_the_four_it_accepts(select):
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (1, 0, 0))], "diagonal")
    assert "all/top/bottom/vertical" in str(raised.value)


def test_a_selection_that_matches_nothing_says_so(select):
    """One vertical edge reaches the top plane without lying in it.

    The refusal is what stops a fillet from silently rounding nothing and
    reporting ``edges_count: 0`` as success — and rounding a vertical edge as
    "the top" would be worse than the refusal.
    """
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (0, 0, 5))], "top")
    assert "No edges matched" in str(raised.value)


# ── top/bottom: the plane is the edges', not the body's ───────────────


def test_top_uses_the_highest_edge_plane_not_the_body_extreme(bound_handler):
    """Measured live: a plate (z 0..1) with a spheroid joined on top spanned
    z -2..4, and all 14 of its edges lay at z=0 or z=1.

    A threshold taken from the body's own max Z then matched no edge at all and
    both selectors refused, on a body whose top edges are perfectly ordinary.
    The plane has to come from the edges.
    """
    body = body_with_edges(
        "Domed",
        [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1))],
        bounding_box=FakeBoundingBox((0.0, 0.0, -2.0), (1.0, 1.0, 4.0)),
    )
    handler = bound_handler(FakeDesign(bodies=[body]))

    coll = handler._select_edges(body, "top")

    assert [edge.index for edge in coll] == [1]
    assert coll.item(0).pointOnEdge.z == pytest.approx(1.0)


def test_bottom_uses_the_lowest_edge_plane_not_the_body_extreme(bound_handler):
    """The same body refused `bottom` too: its belly reached z=-2 with no edge."""
    body = body_with_edges(
        "Domed",
        [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1))],
        bounding_box=FakeBoundingBox((0.0, 0.0, -2.0), (1.0, 1.0, 4.0)),
    )
    handler = bound_handler(FakeDesign(bodies=[body]))

    coll = handler._select_edges(body, "bottom")

    assert [edge.index for edge in coll] == [0]
    assert coll.item(0).pointOnEdge.z == pytest.approx(0.0)


def test_an_edge_that_only_reaches_the_top_plane_is_not_a_top_edge(select):
    """Whole-edge membership: the vertical edge spans 0..1, so it is not at z=1.

    A single point on the edge is not enough to place it — the same reason
    point-to-edge distance is not point-to-sample distance (#40).
    """
    coll = select(
        [
            ((0, 0, 1), (1, 0, 1)),
            ((0, 0, 0), (0, 0, 1)),
            ((0, 0, 0), (1, 0, 0)),
        ],
        "top",
    )
    assert [edge.index for edge in coll] == [0]


def test_the_top_plane_holds_every_edge_that_lies_in_it(select):
    """A plate's four top lines are one plane, so all four come back."""
    coll = select(
        [
            ((0, 0, 1), (4, 0, 1)),
            ((4, 0, 1), (4, 3, 1)),
            ((4, 3, 1), (0, 3, 1)),
            ((0, 3, 1), (0, 0, 1)),
            ((0, 0, 0), (4, 0, 0)),
            ((0, 0, 0), (0, 0, 1)),
        ],
        "top",
    )
    assert [edge.index for edge in coll] == [0, 1, 2, 3]


def test_the_no_match_refusal_is_classified_and_names_the_next_step(select):
    """Live, this refusal was UNKNOWN with no hints — the mode AGENTS.md forbids."""
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (0, 0, 5))], "top")
    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("list_edges" in hint for hint in hints), hints


def test_planes_closer_than_the_epsilon_are_one_plane(bound_handler):
    """A 5 µm foil has no top to tell from its bottom, and the old code agreed.

    ``_EDGE_PLANE_EPSILON`` is 1e-3 cm, which was also the old threshold's slack:
    measured, this body returned all three edges for ``top`` *and* ``bottom``
    before the fix and returns all three now.  Pinned so the merge is a decision
    rather than an accident of the constant, and so a future tightening of the
    epsilon has to notice this case.
    """
    body = body_with_edges(
        "Foil",
        [
            ((0, 0, 0), (1, 0, 0)),
            ((0, 0, 0.0005), (1, 0, 0.0005)),
            ((0, 0, 0), (0, 0, 0.0005)),
        ],
    )
    handler = bound_handler(FakeDesign(bodies=[body]))

    assert [e.index for e in handler._select_edges(body, "top")] == [0, 1, 2]
    assert [e.index for e in handler._select_edges(body, "bottom")] == [0, 1, 2]
    # The vertical answer is unaffected by the merged planes.
    assert [e.index for e in handler._select_edges(body, "vertical")] == [2]


def test_an_unknown_selection_is_classified_too(select):
    """The kind alone does not prove *which* rule fired — the hint text does."""
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (1, 0, 0))], "diagonal")
    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    assert any("edge_selection is one of" in hint for hint in hints), hints


def test_an_edge_whose_sample_is_at_the_top_but_sags_is_not_top(bound_handler):
    """The case a single sample cannot see, modelled the way Fusion behaves.

    A curved edge's ``pointOnEdge`` is its parameter midpoint, which can sit in
    the top plane while the edge reaches below it — a ``Circle3D`` seam is
    exactly that shape (measured: its two vertices are one point and its box
    spans the circle).  The old sample rule selected this edge; the whole-extent
    rule excludes it, and with no other flat edge the answer is a refusal rather
    than a wrong edge.
    """
    sagging = FakeEdge(
        (0.0, 0.0, 1.0),
        (2.0, 0.0, 1.0),
        index=0,
        curve_type="Arc3D",
        bounding_box=FakeBoundingBox((0.0, 0.0, 0.2), (2.0, 0.0, 1.0)),
    )
    assert sagging.pointOnEdge.z == pytest.approx(1.0), "the sample really is top"

    only = FakeBody("Dome", edges=FakeEdges([sagging]))
    alone = bound_handler(FakeDesign(bodies=[only]))
    with pytest.raises(RuntimeError) as raised:
        alone._select_edges(only, "top")
    assert "No edges matched" in str(raised.value)

    floor = FakeEdge((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), index=1)
    body = FakeBody("Domed", edges=FakeEdges([sagging, floor]))
    handler = bound_handler(FakeDesign(bodies=[body]))

    # The floor is the only plane that holds an edge, so it is what comes back.
    assert [e.index for e in handler._select_edges(body, "top")] == [1]


def test_a_raking_edge_does_not_invent_a_top_plane(bound_handler):
    """Docs promise the highest plane that *holds* an edge, so one is not enough.

    A tilted or curved edge's box peaks at a single point, in no plane at all.
    Taking that peak as the plane would refuse a body whose flat top ring is
    perfectly ordinary — the same shape of defect the body-bbox threshold had.
    """
    flat = FakeEdge((0.0, 0.0, 1.0), (2.0, 0.0, 1.0), index=0)
    raking = FakeEdge((0.0, 0.0, 1.0), (1.0, 0.0, 2.0), index=1)
    body = FakeBody("Drafted", edges=FakeEdges([flat, raking]))
    handler = bound_handler(FakeDesign(bodies=[body]))

    assert [e.index for e in handler._select_edges(body, "top")] == [0]


def test_a_curved_edge_without_an_explicit_box_refuses_to_guess(bound_handler):
    """The fake must not invent a box for a curve — an endpoint box is a lie.

    Fusion's ``Circle3D`` has one vertex, so an endpoint-derived box is a point,
    and a test that trusted it would pass on the exact falsehood the ``vertical``
    fix removed.  ``ARCHITECTURE.md`` says the fakes model Fusion's awkwardness on
    purpose; this is that policy enforced.
    """
    ring = FakeEdge((0.0, 0.0, 1.0), (0.0, 0.0, 1.0), curve_type="Circle3D")
    with pytest.raises(RuntimeError) as raised:
        ring.boundingBox
    assert "needs an explicit bounding_box" in str(raised.value)


def test_degenerate_edges_are_never_selected(bound_handler):
    """A cone apex: measured on 2706, ``isDegenerate`` true and geometry ``None``.

    Handing one to ``fillet`` fails inside Fusion with ``FILLET_NO_EDGE_FOUND``,
    so a selector that returns them is offering work that cannot be done.  Their
    zero-extent box would also satisfy ``vertical`` for no good reason.
    """
    apex = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), index=0)
    apex.isDegenerate = True
    post = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 2.0), index=1)
    rim = FakeEdge((1.0, 0.0, 2.0), (2.0, 0.0, 2.0), index=2)
    body = FakeBody("Cone", edges=FakeEdges([apex, post, rim]))
    handler = bound_handler(FakeDesign(bodies=[body]))

    assert [e.index for e in handler._select_edges(body, "all")] == [1, 2]
    assert [e.index for e in handler._select_edges(body, "vertical")] == [1]
    assert [e.index for e in handler._select_edges(body, "top")] == [2]


def test_a_body_whose_every_edge_is_degenerate_says_so(bound_handler):
    apex = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), index=0)
    apex.isDegenerate = True
    body = FakeBody("Cone", edges=FakeEdges([apex]))
    handler = bound_handler(FakeDesign(bodies=[body]))

    with pytest.raises(RuntimeError) as raised:
        handler._select_edges(body, "all")
    assert "no edges that can be rounded" in str(raised.value)
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_a_closed_edge_whose_ends_coincide_is_not_vertical(bound_handler):
    """Measured live on Fusion 2706: a Circle3D's two vertices are one point.

    An end-to-end test therefore calls *every* circle edge vertical.  On the
    plate-plus-spheroid body it selected two rings and missed nothing else; the
    edge's own box says the ring spans 6 cm in x, which no vertical edge does.
    """
    ring = FakeEdge(
        (0.0, 0.0, 1.0),
        (0.0, 0.0, 1.0),
        curve_type="Circle3D",
        index=0,
        bounding_box=FakeBoundingBox((-3.0, -3.0, 1.0), (3.0, 3.0, 1.0)),
    )
    post = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), index=1)
    body = FakeBody("Domed", edges=FakeEdges([ring, post]))
    handler = bound_handler(FakeDesign(bodies=[body]))

    coll = handler._select_edges(body, "vertical")

    assert [edge.index for edge in coll] == [1]


def test_a_body_with_no_edges_refuses_rather_than_selecting_nothing(select):
    """``all`` on a body with no edges raises, and that is deliberate.

    The refusal is what stops a fillet from rounding nothing and reporting
    ``edges_count: 0`` as success.  It says *no edges*, not *nothing matched*:
    the hint for a match failure sends the caller to ``list_edges``, which is
    useless on a body with nothing to list.  A *listing* of a zero-edge body is a
    different question, answered by ``list_edges``.
    """
    with pytest.raises(RuntimeError) as raised:
        select([], "all")
    assert "has no edges to select from" in str(raised.value)
    assert "No edges matched" not in str(raised.value)
    kind, hints = classify(raised.value)
    assert kind == "INVALID_INPUT"
    # The kind alone cannot prove *this* rule fired — the generic INVALID_INPUT
    # rule gives the same kind, so the hint text is the assertion (§14).
    assert any("nothing a fillet can round" in hint for hint in hints), hints


# ── list_edges ────────────────────────────────────────────────────────


@pytest.fixture
def list_body(bound_handler):
    """``list_body(pairs)`` -> a handler bound to that body, and the body."""

    def factory(pairs, curve_type="Line3D"):
        body = body_with_edges("Plate", pairs, curve_type=curve_type)
        return bound_handler(FakeDesign(bodies=[body])), body

    return factory


def test_list_edges_reports_every_edge_in_index_order(list_body):
    handler, _ = list_body(
        [((0, 0, 0), (4, 0, 0)), ((4, 0, 0), (4, 0, 2))],
    )
    result = handler.list_edges(body_name="Plate")
    assert result["body_name"] == "Plate"
    assert result["count"] == 2
    assert result["truncated"] is False
    assert [edge["index"] for edge in result["edges"]] == [0, 1]


def test_list_edges_reports_the_geometry_of_each_edge(list_body):
    """Midpoints are what an agent uses to pick an edge by eye."""
    handler, _ = list_body([((0, 0, 2), (4, 0, 2))])
    edge = handler.list_edges(body_name="Plate")["edges"][0]
    assert edge["start"] == [0.0, 0.0, 2.0]
    assert edge["end"] == [4.0, 0.0, 2.0]
    assert edge["midpoint"] == [2.0, 0.0, 2.0]
    assert edge["length"] == pytest.approx(4.0)
    assert edge["curve_type"] == "Line3D"


def test_list_edges_truncates_but_reports_the_real_count(list_body):
    """``count`` is the body's count, not the length of the list handed back."""
    handler, _ = list_body(
        [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1)), ((0, 0, 2), (1, 0, 2))],
    )
    result = handler.list_edges(body_name="Plate", limit=2)
    assert result["count"] == 3
    assert result["truncated"] is True
    assert len(result["edges"]) == 2


def test_list_edges_of_a_body_with_no_edges_is_empty_not_an_error(list_body):
    handler, _ = list_body([])
    result = handler.list_edges(body_name="Plate")
    assert result["count"] == 0
    assert result["edges"] == []
    assert result["truncated"] is False


def test_list_edges_names_an_unknown_body(list_body):
    handler, _ = list_body([((0, 0, 0), (1, 0, 0))])
    with pytest.raises(RuntimeError) as raised:
        handler.list_edges(body_name="Nope")
    assert classify(raised.value)[0] == "BODY_NOT_FOUND"


def test_mock_list_edges_returns_the_same_shape():
    result = mock_command("list_edges", {"body_name": "Plate"})
    assert result["body_name"] == "Plate"
    assert result["edges"]
    assert set(result["edges"][0]) == {
        "index",
        "start",
        "end",
        "midpoint",
        "length",
        "curve_type",
        "is_degenerate",
    }


# ── edge_indices ──────────────────────────────────────────────────────


def test_edge_indices_selects_exactly_the_named_edges(select):
    """What a person means by 'round edges 0 and 2' — nothing else."""
    coll = select(
        [
            ((0, 0, 0), (1, 0, 0)),
            ((0, 0, 1), (1, 0, 1)),
            ((0, 0, 2), (1, 0, 2)),
        ],
        "all",
        indices=[0, 2],
    )
    assert [edge.index for edge in coll] == [0, 2]


def test_edge_indices_collapses_duplicates(select):
    coll = select(
        [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1))], "all", indices=[1, 1]
    )
    assert [edge.index for edge in coll] == [1]


def test_an_out_of_range_index_names_the_body_the_index_and_the_count(select):
    """Guessing here would round a neighbouring edge and report success."""
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (1, 0, 0))], "all", indices=[4])
    message = str(raised.value)
    assert "4" in message and "1" in message
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_indices_with_an_explicit_edge_selection_is_refused(select):
    """`all` is the default and means 'unset'; `top` alongside indices is not."""
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (1, 0, 0))], "top", indices=[0])
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_fillet_rounds_the_edges_the_index_named(bound_handler):
    body = body_with_edges(
        "Plate",
        [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1))],
    )
    handler = bound_handler(FakeDesign(bodies=[body]))

    result = handler.fillet(radius=0.3, body_name="Plate", edge_indices=[1])

    assert result["edges_count"] == 1
    recorded = handler._root().features.filletFeatures.last_edge_indices
    assert recorded == [1]


def test_fillet_rounds_the_edges_edge_selection_top_chose(bound_handler):
    """Closes the loop the direct ``_select_edges`` tests leave open.

    They prove which edges the collection holds; this proves the feature is told
    to round those and nothing else, which is the end of the path a caller sees.
    """
    body = body_with_edges(
        "Plate",
        [
            ((0, 0, 1), (4, 0, 1)),
            ((4, 0, 1), (4, 3, 1)),
            ((0, 0, 0), (4, 0, 0)),
            ((0, 0, 0), (0, 0, 1)),
        ],
    )
    handler = bound_handler(FakeDesign(bodies=[body]))

    result = handler.fillet(radius=0.3, body_name="Plate", edge_selection="top")

    assert result["edges_count"] == 2
    assert handler._root().features.filletFeatures.last_edge_indices == [0, 1]


def test_chamfer_bevels_the_edges_the_index_named(bound_handler):
    body = body_with_edges(
        "Plate",
        [((0, 0, 0), (1, 0, 0)), ((0, 0, 1), (1, 0, 1))],
    )
    handler = bound_handler(FakeDesign(bodies=[body]))

    result = handler.chamfer(distance=0.2, body_name="Plate", edge_indices=[0])

    assert result["edges_count"] == 1
    assert handler._root().features.chamferFeatures.last_edge_indices == [0]


# ── edge_points ───────────────────────────────────────────────────────


def test_a_point_on_an_edge_selects_that_edge(select):
    coll = select(
        [((0, 0, 0), (4, 0, 0)), ((0, 0, 5), (4, 0, 5))],
        "all",
        points=[[2.0, 0.0, 5.0]],
    )
    assert [edge.index for edge in coll] == [1]


def test_a_point_near_the_end_of_a_long_edge_still_selects_it(select):
    """A midpoint measure would refuse this: 4.5 cm from the midpoint, 0.0 on it."""
    coll = select(
        [((0, 0, 0), (10, 0, 0)), ((0, 0, 1), (1, 0, 1))],
        "all",
        points=[[9.5, 0.0, 0.0]],
    )
    assert [edge.index for edge in coll] == [0]


def test_a_point_far_from_every_edge_names_the_distance_and_the_nearest(select):
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (4, 0, 0))], "all", points=[[2.0, 0.0, 9.0]])
    message = str(raised.value)
    assert "0.1" in message, "the refusal must name the tolerance it applied"
    assert "9.000" in message, "and how far off the point actually was"
    assert "nearest is edge 0" in message, "and which edge it almost hit"
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_a_wider_tolerance_accepts_a_further_point(select):
    coll = select(
        [((0, 0, 0), (4, 0, 0))],
        "all",
        points=[[2.0, 0.0, 0.5]],
        tolerance=1.0,
    )
    assert coll.count == 1


def test_two_equidistant_edges_are_refused_rather_than_guessed(select):
    """Two edges mirror-imaged about the point, both inside the tolerance.

    Ambiguity only means something when both candidates are reachable: a far
    point that happens to sit symmetrically between three edges is a miss, and
    is reported as one (see the test below).
    """
    with pytest.raises(RuntimeError) as raised:
        select(
            [((0, 0, 0), (4, 0, 0)), ((0, 0, 1), (4, 0, 1))],
            "all",
            points=[[2.0, 0.0, 0.5]],
            tolerance=1.0,
        )
    assert "equally close" in str(raised.value)


def test_a_non_finite_point_coordinate_is_refused(select):
    with pytest.raises(ValueError) as raised:
        select([((0, 0, 0), (4, 0, 0))], "all", points=[[float("inf"), 0.0, 0.0]])
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_two_points_on_the_same_edge_select_it_once(select):
    coll = select(
        [((0, 0, 0), (4, 0, 0)), ((0, 0, 5), (4, 0, 5))],
        "all",
        points=[[1.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
    )
    assert coll.count == 1


def test_a_point_on_a_body_with_no_edges_says_so(list_body):
    handler, _ = list_body([])
    with pytest.raises(RuntimeError) as raised:
        handler._select_edges(
            handler._root().bRepBodies.item(0), "all", points=[[0.0, 0.0, 0.0]]
        )
    assert "no edges" in str(raised.value)


# ── mock parity for the selectors ─────────────────────────────────────


def test_mock_fillet_reports_the_edges_the_indices_named():
    result = mock_command("fillet", {"radius": 0.3, "edge_indices": [1, 2, 2]})
    assert result["edges_count"] == 2


def test_mock_chamfer_counts_points_as_edges():
    result = mock_command("chamfer", {"distance": 0.2, "edge_points": [[0, 0, 0]]})
    assert result["edges_count"] == 1


def test_mock_without_a_selector_reports_a_whole_body():
    assert mock_command("fillet", {"radius": 0.3})["edges_count"] > 1


@pytest.mark.parametrize(
    ("command", "params", "expected_kind"),
    [
        # Two ways of naming the same edges: the handler refuses before it looks
        # at a body, so mock mode must not accept a call Fusion would refuse.
        (
            "fillet",
            {"radius": 0.3, "edge_indices": [0], "edge_points": [[0, 0, 0]]},
            "INVALID_INPUT",
        ),
        (
            "chamfer",
            {"distance": 0.2, "edge_selection": "top", "edge_indices": [0]},
            "INVALID_INPUT",
        ),
        ("fillet", {"radius": 0.3, "edge_indices": []}, "INVALID_INPUT"),
        ("fillet", {"radius": 0.3, "edge_points": []}, "INVALID_INPUT"),
        ("fillet", {"radius": 0.3, "edge_selection": "diagonal"}, "INVALID_INPUT"),
        # Element types are the same kind of pure check: the handler refuses a
        # fractional index and a two-coordinate point before it looks at a body.
        ("fillet", {"radius": 0.3, "edge_indices": [1.9]}, "INVALID_INPUT"),
        ("fillet", {"radius": 0.3, "edge_points": [[0, 0]]}, "INVALID_INPUT"),
    ],
)
def test_mock_refuses_what_the_handler_refuses(command, params, expected_kind):
    """Every one of these is a pure parameter check — no geometry needed."""
    result = mock_command(command, params)
    assert result["ok"] is False
    assert result["error_kind"] == expected_kind
    assert result["hints"], "a refusal with no hints is the mode AGENTS.md forbids"


def test_mock_still_accepts_one_selector_at_a_time():
    """The refusals above must not have turned a valid call into a refusal."""
    assert mock_command("fillet", {"radius": 0.3, "edge_selection": "top"})["ok"]
    assert mock_command("fillet", {"radius": 0.3, "edge_indices": [0, 1]})["ok"]
    assert mock_command("fillet", {"radius": 0.3, "edge_points": [[0, 0, 0]]})["ok"]


def test_the_edge_selection_enum_agrees_in_all_three_places():
    """Mock mode refuses an unknown selection against its *own* copy of the enum.

    Three copies exist — this one, the handler's message, and ``tools.py``'s
    schema — so a fifth selection added to one of them would make mock mode
    refuse a call real mode accepts.  Same idea as ``test_addon_sync.py``.
    """
    from fusion360_mcp import mock, tools

    advertised = set()
    for tool in tools.TOOLS:
        enum = tool["inputSchema"]["properties"].get("edge_selection", {}).get("enum")
        if enum:
            advertised.add(tuple(enum))
    assert advertised == {tuple(mock._EDGE_SELECTIONS)}, (
        "tools.py and the mock disagree about the edge_selection enum: "
        f"{advertised} vs {mock._EDGE_SELECTIONS}"
    )


# ── refusals the review asked for ─────────────────────────────────────


def test_a_nan_tolerance_cannot_be_used_to_accept_a_far_point(select):
    """`NaN > tolerance` is always False, so an unguarded NaN accepts anything."""
    with pytest.raises(ValueError) as raised:
        select(
            [((0, 0, 0), (4, 0, 0))],
            "all",
            points=[[2.0, 0.0, 9.0]],
            tolerance=float("nan"),
        )
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_an_empty_points_list_is_refused_like_an_empty_indices_list(select):
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (4, 0, 0))], "all", points=[])
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_a_fractional_index_is_refused_rather_than_truncated(select):
    """`int(1.9)` is 1: silently rounding a different edge than named."""
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (4, 0, 0)), ((0, 0, 1), (4, 0, 1))], "all", indices=[1.9])
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_an_index_on_a_body_with_no_edges_does_not_claim_index_zero_exists(select):
    with pytest.raises(RuntimeError) as raised:
        select([], "all", indices=[0])
    assert "no edges" in str(raised.value)


def test_a_far_point_that_ties_reports_the_distance_not_ambiguity(select):
    """A miss is a miss, however symmetric the geometry around it.

    The point is exactly equidistant from both edges (5.024938 cm each, checked
    by hand) and far outside the tolerance, so the right answer is "no edge
    within".  Live, a point at (9, 9, 9) tied across three edges and was reported
    as *ambiguous* — sending the caller to pick an index instead of moving the
    point.  Ambiguity requires both candidates within reach.
    """
    with pytest.raises(RuntimeError) as raised:
        select(
            [((0, 0, 0), (4, 0, 0)), ((0, 0, 1), (4, 0, 1))],
            "all",
            points=[[2.0, 5.0, 0.5]],
        )
    message = str(raised.value)
    assert "No edge within" in message
    assert "equally close" not in message


def test_a_body_whose_edges_have_no_usable_range_says_that_not_no_edges(bound_handler):
    """Two failures, two messages: the fake lets an edge report a dead range."""
    from tests.fakes.bodies import FakeBody, FakeEdge, FakeEdges
    from tests.fakes.design import FakeDesign

    body = FakeBody("Odd", edges=FakeEdges([FakeEdge((0, 0, 0), (1, 0, 0))]))
    body.edges.item(0).evaluator.ranges = (0.0, 0.0)  # high <= low
    handler = bound_handler(FakeDesign(bodies=[body]))

    with pytest.raises(RuntimeError) as raised:
        handler._select_edges(body, "all", points=[[0.0, 0.0, 0.0]])

    message = str(raised.value)
    assert "no usable parameter range" in message
    assert "has no edges" not in message
    assert classify(raised.value)[0] == "INVALID_INPUT"


def test_an_edge_that_reports_a_failed_extent_is_skipped(bound_handler):
    """Fusion's first answer is a flag; False means "could not measure"."""
    from tests.fakes.bodies import FakeBody, FakeEdge, FakeEdges
    from tests.fakes.design import FakeDesign

    edge = FakeEdge((0, 0, 0), (1, 0, 0))
    edge.evaluator.found = False
    body = FakeBody("Blind", edges=FakeEdges([edge]))
    handler = bound_handler(FakeDesign(bodies=[body]))

    with pytest.raises(RuntimeError) as raised:
        handler._select_edges(body, "all", points=[[0.0, 0.0, 0.0]])

    assert "no usable parameter range" in str(raised.value)
