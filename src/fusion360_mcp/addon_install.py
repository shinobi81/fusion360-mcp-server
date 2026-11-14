"""Copy the add-in out of the installed package into Fusion's AddIns folder.

The add-in is data for Fusion, not a supported import path: Fusion runs
`Fusion360MCP.py` on its own interpreter, so this module copies files into place
rather than importing them.  What travels is a whitelist — `.py` at any depth, and
`*.manifest` only at the add-on's root — which is why a `.env`, a `.vscode/` or a
`__pycache__/` living inside `addon/` cannot reach Fusion.

The release check in `scripts/check_artifacts_ship_addon.py` applies the same rule to
a built artifact, and that is what makes its findings mean anything.  The script is
not shipped and cannot be imported from here, so the predicate is spelled twice;
`test_the_copy_rule_matches_the_release_check` fails if the two ever disagree.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

WHITELIST: tuple[str, ...] = (".py", ".manifest")


class InstallRefused(Exception):
    """A state the install must not touch; the message is what the CLI prints."""


def add_on_source(package: Path | None = None) -> Path:
    """The add-in's directory inside the installed package.

    *package* is a seam for a test that keeps an add-on tree of its own; nothing
    reaches it from the command line.
    """
    return (package or Path(__file__).parent) / "addon"


def manifest_for(source: Path) -> Path:
    """The single `*.manifest` at the add-on's root, whose stem names the add-in.

    Shallow on purpose: Fusion loads `<name>.py` beside `<name>.manifest`, so a
    nested manifest is data the copy skips and must not name the install.  The two
    checks and their wording mirror `scripts/install-addon.sh`, which is the
    development path — both refuse rather than pick a name nobody chose.
    """
    manifests = sorted(source.glob("*.manifest"))
    if len(manifests) != 1:
        listed = "".join(f"\n  {manifest.name}" for manifest in manifests)
        raise InstallRefused(
            f"addon/ must hold exactly one *.manifest; found {len(manifests)}{listed}"
        )
    manifest = manifests[0]
    # The glob does not stat its matches, so a directory called `<name>.manifest`
    # counts as the one manifest and would name the add-in after a file Fusion cannot
    # load.
    if not manifest.is_file():
        raise InstallRefused(f"{manifest.name} is not a regular file")
    return manifest


def copy_add_on(source: Path, target: Path) -> list[str]:
    """Copy the installable files under *source* into *target*.

    Returns the copied paths relative to *source*, POSIX-style and sorted, so the
    caller can report exactly what it wrote and re-read that list afterwards.
    """
    if not source.is_dir():
        raise InstallRefused(
            f"{source} is not a directory: this installs the add-in packaged in the "
            f"wheel, and a source checkout installs with scripts/install-addon.sh"
        )
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source).as_posix()
        if not path.is_file() or not _installable(rel):
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(rel)
    return copied


def _installable(rel: str) -> bool:
    """Whether the copy takes *rel*, a path relative to the add-on's root.

    Two depths: `.py` anywhere, `*.manifest` only at the root.  A suffix test alone
    would call a nested manifest copyable when nothing copies it.
    """
    suffixes = (".py",) if "/" in rel else WHITELIST
    return PurePosixPath(rel).suffix in suffixes
