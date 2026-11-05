"""Drift guards for the Python support window.

The window is stated in two places in ``pyproject.toml``: ``requires-python``
and the ``Programming Language :: Python :: 3.x`` classifiers.  Once, they
disagreed for four years while nobody looked — the floor said 3.10 and 3.10
was already EOL.  These tests read the floor and fail the suite when the
classifiers fall out of step with it, or when ruff grows a second copy of
the floor that can drift independently.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PYRIGHTCONFIG = REPO_ROOT / "pyrightconfig.json"


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _floor_minor() -> int:
    """The minor of ``requires-python``, e.g. 14 for ``">=3.14"``."""
    spec = _pyproject()["project"]["requires-python"]
    match = re.fullmatch(r">=\s*3\.(\d+)", spec)
    assert match, (
        f"requires-python is {spec!r}; this guard only understands a bare '>=3.X' "
        "floor, and a compound specifier would be misread instead of failing"
    )
    return int(match.group(1))


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
    assert "target-version" not in _pyproject()["tool"].get("ruff", {}), (
        "ruff must infer its target from project.requires-python; a second copy drifts"
    )


def test_pyright_does_not_pin_an_older_python_than_the_floor():
    """pyright cannot infer from ``requires-python``, so its copy needs a guard.

    A ``pyrightconfig.json`` that lags the floor is not cosmetic: pinned at 3.10
    it resolves ``tomllib`` (standard library from 3.11) as a missing import and
    reports an error on supported code.
    """
    with PYRIGHTCONFIG.open(encoding="utf-8") as fh:
        declared = json.load(fh)["pythonVersion"]
    declared_minor = int(declared.split(".")[1])
    assert declared_minor >= _floor_minor(), (
        f"pyrightconfig.json pins pyright to {declared}, "
        f"below the 3.{_floor_minor()} floor"
    )
