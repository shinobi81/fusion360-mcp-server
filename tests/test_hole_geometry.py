"""Tests for create_hole's face picking and plane solving.

``addon/server/hole_geometry.py`` is loaded by path so the test needs neither the
add-in package nor the fake runtime: this module deliberately has no ``adsk``
dependency.

The rules here are the pure ones - whether a face counts as horizontal, how two
candidates rank, and where a plane sits above an (x, y).  The call site that
uses them is tested behaviourally in ``test_addon_hole.py`` now that the fake
runtime can build a hole feature; the ``ast`` scans that used to guard it are
gone.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ADDON_SERVER = Path(__file__).resolve().parent.parent / "addon" / "server"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hole_geometry = _load(ADDON_SERVER / "hole_geometry.py", "hole_geometry")


def _nz(degrees_of_tilt: float) -> float:
    return math.cos(math.radians(degrees_of_tilt))


class TestIsHorizontalFace:
    def test_accepts_the_face_pointing_the_requested_way(self):
        assert hole_geometry.is_horizontal_face(1.0, want_up=True)
        assert hole_geometry.is_horizontal_face(-1.0, want_up=False)

    def test_rejects_the_face_pointing_the_other_way(self):
        assert not hole_geometry.is_horizontal_face(-1.0, want_up=True)
        assert not hole_geometry.is_horizontal_face(1.0, want_up=False)

    def test_rejects_a_vertical_face(self):
        # The side faces of a box share the top face's bounding-box max Z,
        # which is how a "top" search used to end up drilling sideways.
        assert not hole_geometry.is_horizontal_face(0.0, want_up=True)
        assert not hole_geometry.is_horizontal_face(0.0, want_up=False)

    @pytest.mark.parametrize("tilt", [0.0, 0.5])
    def test_accepts_a_face_within_tolerance(self, tilt):
        assert hole_geometry.is_horizontal_face(_nz(tilt), want_up=True)

    @pytest.mark.parametrize("tilt", [1.0, 5.0, 45.0])
    def test_rejects_a_slanted_face(self, tilt):
        assert not hole_geometry.is_horizontal_face(_nz(tilt), want_up=True)


class TestFaceRankKey:
    def test_top_prefers_the_highest_face(self):
        keys = [hole_geometry.face_rank_key(z, 1.0, want_up=True) for z in (0.0, 5.0)]
        assert max(keys) == keys[1]

    def test_bottom_prefers_the_lowest_face(self):
        keys = [hole_geometry.face_rank_key(z, 1.0, want_up=False) for z in (0.0, 5.0)]
        assert max(keys) == keys[0]

    def test_ties_go_to_the_larger_face(self):
        small = hole_geometry.face_rank_key(2.0, 1.0, want_up=True)
        large = hole_geometry.face_rank_key(2.0, 9.0, want_up=True)
        assert max(small, large) == large


class TestPlaneZAt:
    def test_horizontal_plane_keeps_its_height_everywhere(self):
        z = hole_geometry.plane_z_at((0, 0, 1), (0, 0, 0.5), 22.0, 1.5)
        assert z == pytest.approx(0.5)

    def test_tilted_plane_z_follows_the_requested_xy(self):
        # 45 degrees about Y: the plane through the origin has z == x.
        n = (-math.sqrt(0.5), 0.0, math.sqrt(0.5))
        assert hole_geometry.plane_z_at(n, (0, 0, 0), 3.0, 99.0) == pytest.approx(3.0)

    def test_tilted_plane_z_differs_from_an_arbitrary_point_on_it(self):
        # Reusing face.pointOnFace instead of solving would put the hole
        # centre off the requested location on any non-horizontal face.
        n = (-math.sqrt(0.5), 0.0, math.sqrt(0.5))
        arbitrary_point_z = 0.0
        assert hole_geometry.plane_z_at(n, (0, 0, 0), 3.0, 0.0) != arbitrary_point_z

    def test_vertical_plane_is_rejected(self):
        with pytest.raises(ValueError):
            hole_geometry.plane_z_at((1, 0, 0), (0, 0, 0), 1.0, 1.0)
