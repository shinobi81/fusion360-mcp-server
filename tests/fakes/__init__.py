"""Fakes shared by the add-in tests.

``runtime`` holds the fake ``adsk`` surface and injects it into the add-in's adapter;
``sketch`` and ``design`` hold the geometry and document trees.  A test imports only the
module it needs, so a sketch test cannot silently depend on the revolve fakes.
"""
