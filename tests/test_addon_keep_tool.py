"""Whether a boolean may keep the body it used as a tool.

``boolean_operation`` always consumed the tool body: Fusion's combine feature
swallows it. That is the right default and the wrong only option — a caller that
wanted to keep the cutter had no way to say so.

Fusion exposes the choice on the combine input (``isKeepToolBodies``). These tests
record what the input was told, because what matters is the value that reached
Fusion, not what the handler returned.
"""

from __future__ import annotations

import pytest

from fusion360_mcp.mock import mock_command
from tests.fakes.bodies import FakeBody
from tests.fakes.design import FakeDesign


@pytest.fixture
def two_bodies(bound_handler):
    target = FakeBody("Target")
    tool = FakeBody("Tool")
    handler = bound_handler(FakeDesign(bodies=[target, tool]))
    return handler, target, tool


def test_the_tool_body_is_consumed_by_default(two_bodies):
    """The behaviour that shipped: a combine eats its tool."""
    handler, _, _ = two_bodies

    result = handler.boolean_operation("Target", "Tool", operation="cut")

    assert result["keep_tool"] is False
    recorded = handler._root().features.combineFeatures.added[0]
    assert recorded.isKeepToolBodies is False


def test_keep_tool_asks_fusion_to_leave_the_tool_body_alone(two_bodies):
    """One property on the input — the add-in copies and recreates nothing."""
    handler, _, _ = two_bodies

    result = handler.boolean_operation(
        "Target", "Tool", operation="cut", keep_tool=True
    )

    assert result["keep_tool"] is True
    recorded = handler._root().features.combineFeatures.added[0]
    assert recorded.isKeepToolBodies is True


def test_keep_tool_does_not_displace_the_operation(two_bodies):
    """The two settings travel together; neither may overwrite the other."""
    handler, _, _ = two_bodies

    handler.boolean_operation("Target", "Tool", operation="intersect", keep_tool=True)
    handler.boolean_operation("Target", "Tool", operation="cut")

    features = handler._root().features.combineFeatures
    intersect, cut = features.added[0], features.added[1]
    assert intersect.operation != cut.operation
    assert intersect.isKeepToolBodies is True
    assert cut.isKeepToolBodies is False


def test_an_unknown_operation_is_still_refused(two_bodies):
    """`keep_tool` must not bypass the operation check in front of it."""
    handler, _, _ = two_bodies

    with pytest.raises(RuntimeError) as raised:
        handler.boolean_operation("Target", "Tool", operation="union", keep_tool=True)

    assert "join/cut/intersect" in str(raised.value)
    assert handler._root().features.combineFeatures.added == []


def test_mock_mode_reports_keep_tool():
    result = mock_command(
        "boolean_operation",
        {"target_body": "Target", "tool_body": "Tool", "keep_tool": True},
    )
    assert result["keep_tool"] is True
