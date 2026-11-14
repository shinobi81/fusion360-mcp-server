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
    development path — both refuse rather than pick a name nobody chose.  Two kinds of
    candidate are dropped so that both paths name the same file: a dot-prefixed name,
    which the shell's glob never matches and pathlib's does, and a name whose suffix is
    `.manifest` only under a case-insensitive glob - Windows' - where the shell's glob
    and the copy rule's suffix test are both case-sensitive.
    """
    manifests = sorted(
        manifest
        for manifest in source.glob("*.manifest")
        if manifest.name.endswith(".manifest") and not manifest.name.startswith(".")
    )
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


def target_for(add_ins: Path, stem: str) -> Path:
    """The add-in's directory under *add_ins*, refused when *stem* points out of it.

    *stem* is the manifest's name read as a path segment, so it is the one piece of the
    install the package does not spell.  ``..`` is the case that matters: it would put
    the copy beside ``AddIns`` instead of in it, where Fusion never looks.
    """
    target = add_ins / stem
    if target.resolve().parent != add_ins.resolve():
        raise InstallRefused(f"{stem} resolves outside {add_ins}")
    return target


def add_ins_dir(
    environ: Mapping[str, str] | None = None, system: str | None = None
) -> Path:
    """Fusion's ``AddIns`` directory, created when Fusion's own folder is there.

    ``mkdir(parents=True)`` makes ``API`` as well as ``AddIns``, and nothing above
    ``Autodesk Fusion 360``: that folder is Fusion's own rather than this install's, so
    its absence means Fusion is not installed here — and a directory tree invented
    under it would be an install nobody can find.

    A folder that cannot be created — Fusion's root is there but not writable, say — is
    refused as a line like every other refusal, rather than escaping as the
    ``PermissionError`` the caller has no handler for.

    *environ* and *system* are seams — the environment and the platform name are read
    rather than guessed, so a test can hand over either one.
    """
    env = os.environ if environ is None else environ
    system = _current_system() if system is None else system
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
            f"{fusion_root} does not exist: that folder is Fusion 360's own, so Fusion "
            f"is not installed here, and an AddIns folder invented beneath it would be "
            f"an install Fusion never looks at"
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallRefused(f"cannot create {path}: {exc}") from exc
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


def _manifest_version(manifest: Path) -> str:
    """The manifest's ``version``, refused as a line when it cannot be read.

    The manifest is the one file the install reads rather than copies, and it is read
    before anything is written: raising ``JSONDecodeError`` here would be a traceback
    at the end of an install that had already replaced the folder on disk.  One clause
    covers an unreadable file, bytes that are not UTF-8 and text that is not JSON —
    all three mean the same thing to the caller, which is that no version was read.

    The key's *value* is part of the contract, not just its presence: ``null`` and
    ``""`` would otherwise pass ``str`` and print ``Version: None`` or an empty line
    from an install that went ahead anyway, so anything but a non-empty string is the
    same refusal as a missing key.
    """
    try:
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError) as exc:
        raise InstallRefused(f"{manifest.name} cannot be read as JSON: {exc}") from exc
    except KeyError, TypeError:
        raise InstallRefused(f"{manifest.name} has no version") from None
    if not isinstance(version, str) or not version:
        raise InstallRefused(f"{manifest.name} has no version")
    return version


def _fresh_copy(target: Path, source: Path) -> list[str]:
    """Make *target* hold exactly the copy of *source*, and check that it does.

    A stale directory is removed rather than merged: a merge keeps files the copy no
    longer ships, so a module deleted from the add-on would go on running.  The copied
    set *copy_add_on* reports is then compared with the files that are actually there,
    because that list is a claim about the disk and the disk is what Fusion reads.
    """
    try:
        if target.is_dir():
            shutil.rmtree(target)
        copied = copy_add_on(source, target)
    except OSError as exc:
        raise InstallRefused(f"cannot write to {target}: {exc}") from exc
    written = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    }
    missing = written ^ set(copied)
    if missing:
        raise InstallRefused(f"copy incomplete: {', '.join(sorted(missing))}")
    return copied


def install_addon(addin_dir: Path | None = None, source: Path | None = None) -> int:
    """Copy the packaged add-in into Fusion's AddIns folder; 0 installed, 1 refused.

    Both arguments are seams: the defaults are the add-in inside the installed package
    and the folder Fusion reads on this machine.  A refusal is reported, not raised,
    because the only caller is a CLI whose exit code is the answer.

    No add-in file is written until every refusal has had its turn, and the first of
    them is the link: a development install is a link to a checkout, so a copy through
    it would overwrite the sources rather than install them.  The one thing that can
    appear first is Fusion's own empty ``API/AddIns`` folder, which *add_ins_dir*
    creates because Fusion is installed and the folder is missing.
    """
    try:
        source = _add_on_dir(source or add_on_source())
        target_root = addin_dir or add_ins_dir()
        manifest = manifest_for(source)
        # The link check comes before `target_for`, which resolves: a link out of
        # `AddIns` would be reported there as an install outside the folder, and a
        # junction to a checkout is the state this must name rather than copy into.
        target = target_root / manifest.stem
        if target.is_symlink() or os.path.isjunction(target):
            raise InstallRefused(
                f"{target} is a symlink or junction; it is a development install. "
                f"Run scripts/install-addon.sh to restore it, or remove it first."
            )
        target = target_for(target_root, manifest.stem)
        if target.exists() and not target.is_dir():
            raise InstallRefused(f"{target} exists and is not a directory")
        version = _manifest_version(manifest)
        copied = _fresh_copy(target, source)
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
