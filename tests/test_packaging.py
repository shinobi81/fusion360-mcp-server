"""Drift guards for the Python support window.

The window is stated in two places in ``pyproject.toml``: ``requires-python``
and the ``Programming Language :: Python :: 3.x`` classifiers.  Once, they
disagreed for four years while nobody looked — the floor said 3.10 and 3.10
was already EOL.  These tests read the floor and fail the suite when the
classifiers fall out of step with it, or when ruff grows a second copy of
the floor that can drift independently.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _floor_minor() -> int:
    """The minor of ``requires-python``, e.g. 14 for ``">=3.14"``."""
    spec = _pyproject()["project"]["requires-python"]
    return int(spec.removeprefix(">=").split(".")[1])


def _classifier_minors() -> set[int]:
    return {
        int(classifier.rsplit(".", 1)[-1])
        for classifier in _pyproject()["project"]["classifiers"]
        if classifier.startswith("Programming Language :: Python :: 3.")
    }


def test_classifiers_do_not_claim_unsupported_pythons():
    floor = _floor_minor()
    claimed = sorted(minor for minor in _classifier_minors() if minor < floor)
    assert claimed == [], (
        f"classifiers claim 3.{claimed} but requires-python floors at 3.{floor}"
    )


def test_the_floor_itself_is_classified():
    floor = _floor_minor()
    assert floor in _classifier_minors(), (
        f"3.{floor} is the requires-python floor but has no classifier"
    )


def test_ruff_has_no_second_copy_of_the_floor():
    assert "target-version" not in _pyproject()["tool"]["ruff"], (
        "ruff must infer its target from project.requires-python; a second copy drifts"
    )
