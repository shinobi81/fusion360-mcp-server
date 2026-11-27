"""The document ``new_document`` creates, and the products it holds.

``new_document`` is the one command that makes a Fusion document: it asks
``Application.documents.add(DocumentTypes.FusionDesignDocumentType)``, renames what
comes back, and reads the Design product out of it with
``products.itemByProductType("DesignProductType")``.  None of that was reachable
before, because ``FakeApplication`` deliberately models no document - and it still
does not: a test installs a ``FakeDocuments`` on the instance it hands to
``bound_handler``, so an application reached any other way keeps the absence
``app.py`` describes.

What is **not** modelled, and is the fake's own choice rather than a measurement:
the name a new document gets.  ``FakeDocuments`` mints ``"Untitled"``; a test that
reads a name either renames the document (``new_document(name=...)``) or asserts
against the name the fake minted, and says which.  Nothing here claims what Fusion
calls it, nor which products a fresh design document holds beyond the Design product
the handler searches for.
"""

from __future__ import annotations

from collections.abc import Iterator

from .design import FakeDesign


class FakeProduct:
    """A product that is not a design: what ``products.item(0)`` finds when a test
    puts one ahead of the design.

    It carries ``productType`` and nothing else, because that is all the handler's
    search compares - so reading ``designType`` off it raises, which is what makes
    the position-blind read fail loudly rather than answer wrongly.
    """

    def __init__(self, product_type: str):
        self.productType = product_type


class FakeProducts:
    """``document.products``: ``count`` / ``item(i)`` / ``itemByProductType``."""

    def __init__(self, products=()):
        self._products: list = list(products)

    @property
    def count(self) -> int:
        return len(self._products)

    def item(self, index: int):
        return self._products[index]

    def itemByProductType(self, product_type: str):
        """The product of that type, or ``None`` - which is what the handler tests.

        A ``FakeDesign`` answers ``productType`` with Fusion's own
        ``"DesignProductType"``, so this searches over a value Fusion supplies, not
        one the fake made up.
        """
        for product in self._products:
            if product.productType == product_type:
                return product
        return None

    def __iter__(self) -> Iterator[object]:
        return iter(self._products)


class FakeDocument:
    """``adsk.core.Document``: a name, the products it holds, and its save state.

    Measured on 2706.1.17: ``save(description)`` takes a required description and
    ``saveAs(name, dataFolder, description, tag)`` a name and a **data folder** - there
    is no local-file overload.  A document made through the API starts with
    ``dataFile: None, isSaved: False, isModified: True``, which is the untitled state
    ``save_document`` refuses without a name.
    """

    def __init__(self, name: str, products=(), is_saved: bool = False):
        self.name = name
        self.products = FakeProducts(products)
        self.isSaved = is_saved
        self.isModified = not is_saved
        #: The folder a saved document reports; ``None`` until ``saveAs`` names one.
        self.dataFile = None
        #: What the two save calls were given, in order - the reply is built from them.
        self.saved: list[tuple] = []

    def save(self, description: str) -> bool:
        self.saved.append(("save", description))
        self.isModified = False
        return True

    def saveAs(self, name: str, dataFolder, description: str, tag: str) -> bool:
        self.saved.append(("saveAs", name, dataFolder, description, tag))
        if name:
            self.name = name
        self.isSaved = True
        self.isModified = False
        self.dataFile = type("FakeDataFile", (), {"parentFolder": dataFolder})()
        return True


class FakeDocuments:
    """``Application.documents``: the open ones, and ``add``.

    ``add`` mints a document holding the test's ``preceding_products`` and *then* the
    design, so a handler that took ``products.item(0)`` finds a product no design
    command can use.  A test that puts a CAM product there is arranging a decoy, not
    reporting what Fusion ships in a new design document.

    ``requested_types`` records the ``DocumentTypes`` member each ``add`` was given:
    that is how a test says the document was created through the API rather than in
    the UI, which is the reason the command exists.
    """

    def __init__(
        self,
        design: FakeDesign,
        existing_documents=(),
        preceding_products=(),
        name: str = "Untitled",
    ):
        #: The design product every document ``add`` mints holds.
        self.design = design
        #: The fake's default name, not a measured one - see the module docstring.
        self.name = name
        self._documents: list[FakeDocument] = list(existing_documents)
        self.preceding_products: list = list(preceding_products)
        self.added: list[FakeDocument] = []
        self.requested_types: list[str] = []

    def add(self, document_type: str) -> FakeDocument:
        self.requested_types.append(document_type)
        document = FakeDocument(self.name, [*self.preceding_products, self.design])
        self._documents.append(document)
        self.added.append(document)
        return document

    @property
    def count(self) -> int:
        return len(self._documents)

    def item(self, index: int) -> FakeDocument:
        return self._documents[index]

    def __iter__(self) -> Iterator[FakeDocument]:
        return iter(self._documents)
