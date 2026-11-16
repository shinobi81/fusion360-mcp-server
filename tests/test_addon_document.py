"""The document, the design type, and the two meshes ``compare_meshes`` compares.

``new_document``, ``set_design_type`` and ``compare_meshes`` were executed by no test
in this suite: ``FakeApplication`` models no document, no fixture had
``rootComponent.meshBodies``, and the design type was only ever *read* (by
``get_design_type``, pinned in ``test_addon_scene_reads.py``).  The Fusion reads these
tests are built on are named where each is asserted:

* ``app.documents.add(DocumentTypes.FusionDesignDocumentType)`` -> the new document's
  ``name``, and ``products.itemByProductType("DesignProductType")`` ->
  ``designType`` / ``rootComponent.name``: the whole of ``new_document``'s reply;
* ``design.designType = ...`` and ``adsk.doEvents()``: what ``set_design_type`` writes
  and nudges;
* ``rootComponent.meshBodies.count`` / ``.item(i)`` / ``.name`` -> ``body.mesh`` ->
  ``PolygonMesh.compareWith(other)``: the deviations ``compare_meshes`` summarises.

Every collection a command walks holds a **decoy first**: an already-open document
ahead of the one ``add`` mints, a CAM product ahead of the design in the new
document's products, and a mesh body ahead of the one compared.  A reply or a
statistic built from the first thing found is therefore wrong, not merely untested.

What is the **fake's**, not Fusion's: the name a document ``add`` mints
(``"Untitled"``), and the per-node deviations ``compareWith`` answers.  Fusion
computes those from two tessellations; nothing here models a surface, so the numbers
are handed to the fake by the test and are marked where they are asserted.
"""

from __future__ import annotations

import pytest

from addon.server import fusion_api
from tests.fakes.app import FakeApplication
from tests.fakes.design import FakeDesign
from tests.fakes.document import FakeDocument, FakeDocuments, FakeProduct
from tests.fakes.mesh import FakeMeshBody, FakePolygonMesh
from tests.fakes.runtime import DIRECT, PARAMETRIC


def _app_with_documents(design: FakeDesign, **kwargs) -> FakeApplication:
    """An application whose ``documents`` collection is this test's, not invented."""
    app = FakeApplication()
    app.documents = FakeDocuments(design, **kwargs)
    return app


def _no_nudge(monkeypatch) -> list:
    """Record ``adsk.doEvents()`` instead of calling it: a switch must nudge Fusion."""
    nudges: list = []
    monkeypatch.setattr(fusion_api, "doEvents", lambda: nudges.append(True))
    return nudges


# ── new_document ─────────────────────────────────────────────────────


def test_new_document_creates_a_design_document_and_reports_its_name(bound_handler):
    design = FakeDesign(features=0)
    # A document that was already open, ahead of the one ``add`` mints: a reply built
    # from ``documents.item(0).name`` names this one instead.
    app = _app_with_documents(design, existing_documents=[FakeDocument("Earlier")])
    handler = bound_handler(design, app=app)

    reply = handler.new_document("Bracket")

    created = app.documents.added[0]
    assert app.documents.requested_types == ["FusionDesignDocumentType"], (
        "a document made through the API, not through the UI"
    )
    assert created.name == "Bracket"
    assert reply == {
        "created": True,
        "document": "Bracket",
        "design_type": "parametric",
        "component": design.rootComponent.name,
    }
    assert app.documents.count == 2, "the decoy plus the new document"


def test_new_document_without_a_name_reports_the_name_fusion_gave_it(bound_handler):
    """``"Untitled"`` is the fake's default name, not a measured Fusion one.

    The assertion is that the reply carries the *new* document's name and that the
    handler renames nothing when it was not asked to: the decoy document ahead of it
    is called something else, so a reply built from it fails.
    """
    design = FakeDesign(features=0)
    app = _app_with_documents(design, existing_documents=[FakeDocument("Earlier")])
    handler = bound_handler(design, app=app)

    reply = handler.new_document()

    assert app.documents.added[0].name == "Untitled"
    assert reply["document"] == "Untitled"


@pytest.mark.parametrize(
    "design_type, expected",
    [(PARAMETRIC, "parametric"), (DIRECT, "direct")],
)
def test_new_document_reports_the_design_product_it_found_by_type(
    bound_handler, design_type, expected
):
    """The design comes out of ``products`` by product type, not by position.

    The CAM product the test puts first is the test's arrangement: what a new Fusion
    design document's ``products`` holds was not measured here.  What it pins is that
    the handler searches - ``item(0)`` is a product with no ``designType``, so a
    reply built from it raises instead of answering.
    """
    design = FakeDesign(features=0, design_type=design_type)
    app = _app_with_documents(
        design, preceding_products=[FakeProduct("CAMProductType")]
    )
    handler = bound_handler(design, app=app)

    reply = handler.new_document()

    assert reply["design_type"] == expected
    assert reply["component"] == design.rootComponent.name


# ── set_design_type ──────────────────────────────────────────────────


def test_set_design_type_to_parametric_switches_a_direct_design_with_features(
    bound_handler, monkeypatch
):
    nudges = _no_nudge(monkeypatch)
    design = FakeDesign(features=3, design_type=DIRECT)
    handler = bound_handler(design)

    reply = handler.set_design_type("parametric")

    assert design.designType == PARAMETRIC
    assert reply == {"changed": True, "design_type": "parametric"}
    assert nudges == [True], "Fusion is nudged to take the switch"
    assert design.timeline_count == 3, "the switch is a property write, not a rebuild"


def test_set_design_type_to_direct_on_a_parametric_design_with_features(
    bound_handler, monkeypatch
):
    """Nothing substantiates the refusal the task brief guessed at.

    ``set_design_type`` writes ``design.designType`` and verifies it for the
    parametric direction only; neither it nor the SDK's documented setter says a
    design with features may not be switched.  So this pins the behaviour that
    exists — the property is written and the features survive — instead of inventing
    a refusal Fusion was never measured making.
    """
    nudges = _no_nudge(monkeypatch)
    design = FakeDesign(features=2)
    handler = bound_handler(design)

    reply = handler.set_design_type("direct")

    assert design.designType == DIRECT
    assert reply == {"changed": True, "design_type": "direct"}
    assert nudges == [True]
    assert design.timeline_count == 2


def test_set_design_type_already_in_that_mode_changes_nothing(
    bound_handler, monkeypatch
):
    nudges = _no_nudge(monkeypatch)
    design = FakeDesign(features=1)
    handler = bound_handler(design)

    reply = handler.set_design_type("parametric")

    assert design.designType == PARAMETRIC
    assert reply["changed"] is False
    assert nudges == [], "there is nothing to switch, so Fusion is not nudged"


def test_set_design_type_with_an_unknown_name_is_refused(bound_handler):
    design = FakeDesign(features=2)
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.set_design_type("hybrid")

    assert design.designType == PARAMETRIC


# ── compare_meshes ───────────────────────────────────────────────────


def _decoy_mesh_body() -> FakeMeshBody:
    """A mesh body placed *before* the named ones in every fixture.

    Its one deviation is absurd on purpose, so a search that stopped comparing names
    reports ``node_count`` 1 and a 99 cm deviation instead of the fixture's.
    """
    return FakeMeshBody("Spacer", FakePolygonMesh(node_count=1, deviations=[99.0]))


def test_compare_meshes_of_one_mesh_and_itself_reports_no_deviation(bound_handler):
    panel = FakeMeshBody("Panel", FakePolygonMesh(node_count=5))
    design = FakeDesign(features=0, mesh_bodies=[_decoy_mesh_body(), panel])
    handler = bound_handler(design)

    reply = handler.compare_meshes("Panel", "Panel")

    assert reply["mesh_a"] == "Panel"
    assert reply["mesh_b"] == "Panel"
    assert reply["node_count"] == 5
    # A node lies on its own surface, so this is the one deviation list the geometry
    # supplies rather than the test: zero, five times.
    assert reply["min_deviation"] == 0.0
    assert reply["max_deviation"] == 0.0
    assert reply["mean_abs_deviation"] == 0.0
    assert reply["rms_deviation"] == 0.0
    assert reply["max_abs_deviation"] == 0.0
    assert reply["units"] == "cm"


def test_compare_meshes_reports_the_signed_deviations_it_was_given(bound_handler):
    """The four deviations are the *fake's*; the statistics are the handler's.

    Fusion computes one signed distance per node of mesh A against mesh B's surface.
    That needs two surfaces, so the list is handed to the fake by this test.  What the
    numbers pin is the summary: ``min``/``max`` keep the sign, ``mean_abs`` /
    ``max_abs`` / ``rms`` are over the absolute values, and RMS is not the mean.
    """
    deviations = [0.0, 0.1, -0.2, 0.3]
    panel = FakeMeshBody("Panel", FakePolygonMesh(node_count=4, deviations=deviations))
    # The mirror of A's list: a handler that compared B with A reports flipped signs,
    # so min/max swap and this fails.
    offset = FakeMeshBody(
        "PanelOffset",
        FakePolygonMesh(node_count=4, deviations=[-d for d in deviations]),
    )
    design = FakeDesign(features=0, mesh_bodies=[_decoy_mesh_body(), panel, offset])
    handler = bound_handler(design)

    reply = handler.compare_meshes("Panel", "PanelOffset")

    assert reply["mesh_a"] == "Panel"
    assert reply["mesh_b"] == "PanelOffset"
    assert reply["node_count"] == 4
    assert reply["min_deviation"] == pytest.approx(-0.2)
    assert reply["max_deviation"] == pytest.approx(0.3)
    assert reply["max_abs_deviation"] == pytest.approx(0.3)
    assert reply["mean_abs_deviation"] == pytest.approx(0.15)
    # sqrt((0 + 0.01 + 0.04 + 0.09) / 4), not the mean of 0.15.
    assert reply["rms_deviation"] == pytest.approx(0.18708286933869708)
    assert reply["units"] == "cm"


def test_compare_meshes_of_a_name_no_mesh_body_has_is_refused(bound_handler):
    """Two mesh bodies exist and neither is the one asked for.

    A search that stopped comparing names would answer for the decoy and return
    statistics instead, so the refusal is what pins the comparison.
    """
    panel = FakeMeshBody("Panel", FakePolygonMesh(node_count=5))
    design = FakeDesign(features=0, mesh_bodies=[_decoy_mesh_body(), panel])
    handler = bound_handler(design)

    with pytest.raises(RuntimeError):
        handler.compare_meshes("Panel", "PanelCopy")
