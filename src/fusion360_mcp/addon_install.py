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

Where it lands is Fusion's per-user `AddIns` folder, read from `APPDATA` on Windows and
`HOME` on macOS.  Nothing there is guessed and nothing above `Autodesk Fusion 360` is
created: a missing install is refused, not invented.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

WHITELIST: tuple[str, ...] = (".py", ".manifest")

# Fusion's install layout, relative to the per-user directory that holds Autodesk's
# application data: `APPDATA` on Windows, `HOME` on macOS.  The add-in runs on Fusion's
# own interpreter and can only be loaded from here, so the two spellings are the whole
# reason this module knows a platform at all.  `scripts/install-addon.sh` resolves the
# same two folders for the development path.
ADD_INS_TAIL = "Autodesk/Autodesk Fusion 360/API/AddIns"
DARWIN_TAIL = "Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"


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
    _add_on_dir(source)
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


def _add_on_dir(source: Path) -> Path:
    """*source*, once it is a directory — the check that says which install this is.

    A wheel has the add-in inside the package; a source checkout has it at `addon/`, and
    installing that is `scripts/install-addon.sh`'s job.  Both the copy and the install
    that names the copy's folder go through here, so the refusal is spelled once.
    """
    if not source.is_dir():
        raise InstallRefused(
            f"{source} is not a directory: this installs the add-in packaged in the "
            f"wheel, and a source checkout installs with scripts/install-addon.sh"
        )
    return source


def add_ins_dir(
    environ: Mapping[str, str] | None = None, system: str | None = None
) -> Path:
    """Fusion's ``AddIns`` directory, created if Fusion is installed and it is missing.

    Only the last folder is ever created: Fusion makes ``Autodesk Fusion 360`` on
    install, so its absence means Fusion is not installed here and a directory tree
    invented under it would be an install nobody can find.

    *environ* and *system* are seams — the environment and the platform name are read
    rather than guessed, so a test can hand over either one.
    """
    env = os.environ if environ is None else environ
    system = system or _current_system()
    if system == "windows":
        path = _required_dir(env, "APPDATA") / ADD_INS_TAIL
    elif system == "darwin":
        path = _required_dir(env, "HOME") / DARWIN_TAIL
    else:
        raise InstallRefused(
            f"Fusion 360 runs on Windows and macOS only; this system is {system!r}"
        )
    fusion_root = path.parents[1]
    if not fusion_root.is_dir():
        raise InstallRefused(
            f"{fusion_root} does not exist: is Fusion 360 installed, and has it been "
            f"started once so it creates its AddIns folder?"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _current_system() -> str:
    """The platform name :func:`add_ins_dir` reads when it is not told one.

    ``sys.platform`` already spells macOS ``darwin``, so only Windows needs a name of
    its own; anything else survives as itself and is refused there.
    """
    return {"nt": "windows"}.get(os.name, sys.platform)


def _required_dir(environ: Mapping[str, str], name: str) -> Path:
    """The per-user directory the variable *name* holds, refused when it is unset.

    There is no default to fall back on — a guess would install where Fusion never
    looks, and the add-in would silently not load.
    """
    value = environ.get(name)
    if not value:
        raise InstallRefused(
            f"{name} is not set: this cannot guess where Fusion keeps its AddIns folder"
        )
    return Path(value)


def install_addon(addin_dir: Path | None = None, source: Path | None = None) -> int:
    """Copy the packaged add-in into Fusion's AddIns folder; 0 installed, 1 refused.

    Both arguments are seams: the defaults are the add-in inside the installed package
    and the folder Fusion reads on this machine.  A refusal is reported, not raised,
    because the only caller is a CLI whose exit code is the answer.
    """
    try:
        source = _add_on_dir(source or add_on_source())
        target_root = addin_dir or add_ins_dir()
        manifest = manifest_for(source)
        target = target_root / manifest.stem
        copied = copy_add_on(source, target)
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        print(f"Installing {manifest.stem} add-in...")
        print(f"  Source: {source}")
        print(f"  Target: {target}")
        print(f"  {len(copied)} files copied")
        print(f"  Version: {version}")
        print()
        print("Next steps:")
        print("  1. Open Fusion 360")
        print("  2. Press Shift+S to open Scripts and Add-Ins")
        print(f"  3. Find '{manifest.stem}' in the Add-Ins tab")
        print("  4. Click 'Run' to start the add-in")
        return 0
    except InstallRefused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
