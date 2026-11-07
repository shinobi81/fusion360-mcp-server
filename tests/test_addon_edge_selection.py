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

from tests.fakes.bodies import body_with_edges
from tests.fakes.design import FakeDesign


@pytest.fixture
def select(bound_handler):
    """``select(edge_pairs, selection)`` -> the collection the handler built."""

    def factory(edge_pairs, selection):
        body = body_with_edges("Plate", edge_pairs)
        handler = bound_handler(FakeDesign(bodies=[body]))
        return handler._select_edges(body, selection)

    return factory


def test_all_selects_every_edge(select):
    coll = select([((0, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0))], "all")
    assert coll.count == 2


def test_top_selects_the_edge_whose_midpoint_is_highest(select):
    """Three heights, so a wrong threshold changes which edges come back.

    With edges at z = 0, 2.5 and 5, a threshold taken from the *top* of the box
    returns one edge and a threshold taken from the bottom returns two, which is
    how this test tells the two apart.
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


def test_bottom_selects_the_edge_whose_midpoint_is_lowest(select):
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


def test_vertical_selects_only_edges_whose_ends_share_x_and_y(select):
    """The selected edge's own ends must differ in z — a count is not enough.

    Both edges are at the same height, so an assertion on ``count`` alone passes
    even when the predicate is inverted: the test has to name the geometry.
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
    """A body whose edges are all at mid-height has no 'top' edge.

    The refusal is what stops a fillet from silently rounding nothing and
    reporting ``edges_count: 0`` as success.
    """
    with pytest.raises(RuntimeError) as raised:
        select([((0, 0, 0), (0, 0, 5))], "top")
    assert "No edges matched" in str(raised.value)


def test_a_body_with_no_edges_refuses_rather_than_selecting_nothing(select):
    """``all`` on a body with no edges raises, and that is deliberate.

    The refusal is what stops a fillet from rounding nothing and reporting
    ``edges_count: 0`` as success.  A *listing* of a zero-edge body is a different
    question, answered by ``list_edges``.
    """
    with pytest.raises(RuntimeError) as raised:
        select([], "all")
    assert "No edges matched" in str(raised.value)
