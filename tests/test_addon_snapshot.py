"""What a mutation reports back: the deltas, and the name of what it created.

``_snapshot`` read ``app.activeProduct`` — the one thing ``_design()`` exists to
avoid, because in the Manufacture workspace that product is the **CAM** product
and ``hasattr(design, "rootComponent")`` is false.  The snapshot then returned
``None``, ``execute_command`` attached no deltas, and every mutation in that
workspace reported "body count and mass unchanged" to an agent that AGENTS.md
tells to read exactly those numbers.

``create_section_analysis`` had the mirror-image defect: it discarded the object
``analyses.add()`` returned and reported ``created: True`` with no name, so the
analysis it just made could not be referenced — unlike every other builder, which
reports ``feature_name``.
"""

from __future__ import annotations

from types import SimpleNamespace

from tests.fakes.bodies import FakeBody
from tests.fakes.design import FakeDesign


def _handler(handler_module, design, active_product=None):
    """A handler wired to the *real* ``_design``, so the lookup itself is under test."""
    handler = handler_module.CommandHandler.__new__(handler_module.CommandHandler)
    handler.app = SimpleNamespace(
        activeDocument=SimpleNamespace(
            products=SimpleNamespace(itemByProductType=lambda _type: design)
        ),
        activeProduct=active_product,
    )
    handler.ui = object()
    return handler


def test_the_snapshot_reads_the_design_product_even_in_the_manufacture_workspace(
    handler_module,
):
    design = FakeDesign(bodies=[FakeBody("Body1")])
    # The Manufacture workspace: activeProduct is the CAM product, no rootComponent.
    cam_product = SimpleNamespace(name="CAM")

    snapshot = _handler(handler_module, design, active_product=cam_product)._snapshot()

    assert snapshot is not None, "no deltas would be attached to any mutation here"
    assert snapshot["body_count"] == 1


def test_the_snapshot_still_returns_nothing_when_there_is_no_design(handler_module):
    """Best-effort stays best-effort: a missing design must not reach the mutation."""
    handler = _handler(handler_module, design=None, active_product=None)

    assert handler._snapshot() is None


def test_a_section_analysis_reports_the_name_it_created(bound_handler):
    design = FakeDesign(bodies=[FakeBody("Body1")])
    handler = bound_handler(design)

    out = handler.create_section_analysis(plane="xz", offset=2.0)

    created = design.rootComponent.analyses.added[0]
    assert out["analysis_name"] == created.name
    analysis_input = created.input
    assert analysis_input is not None, "the analysis was added with no input"
    assert analysis_input.distance is not None
