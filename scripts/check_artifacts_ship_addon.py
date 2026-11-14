"""Prove that a built wheel or sdist carries the add-in, byte for byte.

A tag install copies the add-in out of the *artifact*, not out of a checkout, so the
files it installs have to be the ones git tracks.  Nothing in the build says so: they
arrive through the `package-dir` mapping in `pyproject.toml`, and a mapping that loses
an entry, or a stale file left behind in `addon/`, ships an installer that either
refuses outright or installs an add-in missing a module Fusion imports at load time.

So this reads the artifact back and compares it against `git ls-files addon`.  A name
missing, a name extra, and a name whose bytes differ are each a finding, and so is a
tracked file the installer's whitelist would skip - a file that ships and is never
installed reads as shipped, which is the silent half of the same bug.

Both artifacts are checked because both are published: `uvx --from ...@vX.Y.Z.tar.gz`
builds a wheel through this same mapping, so an sdist that quietly lacked the add-in
would only be found by whoever installed from a tarball.

An argument may name a directory instead of a file, and the artifacts inside it are
what gets read: the documented local command points at `dist`, because a shell that
does not expand `dist/*.whl` - PowerShell and cmd, on this project's primary OS - would
otherwise hand the literal glob to the check and get "cannot be read" instead.  A
directory stands for one build output, and the release publishes both artifacts, so a
directory holding only one of them is cannot check: checking the half that is there
would pass a release whose other half was never built.  A file argument is a
maintainer naming one artifact to read, and that stays one artifact.

Stdlib only, and 3.12-compatible syntax: the release job runs it on the runner's own
Python, which is not this package's floor.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]

# The suffixes the installer copies.  The copy decides what reaches Fusion and this
# check decides what the artifact may carry, so a tracked file outside the two of them
# is a finding rather than an omission.
WHITELIST: tuple[str, ...] = (".py", ".manifest")

# Below the add-on's root the copy takes `.py` only: Fusion reads the manifest beside
# the add-in's entry module, so a nested one is data the installer skips.
NESTED_WHITELIST: tuple[str, ...] = (".py",)

ADD_ON_DIR = "addon"

# Where the add-in lands inside the wheel: `fusion360_mcp.addon` is mapped to `addon/`
# as a package, so its files are stored under this prefix rather than at the root.
PACKAGE_PREFIX = "fusion360_mcp/addon/"

_WHEEL_SUFFIX = ".whl"
_SDIST_SUFFIX = ".tar.gz"

# What a build output carries.  A directory argument is expanded over these rather than
# over "whatever it holds", so notes or an SBOM beside the artifacts are not read.
_ARTIFACT_SUFFIXES: tuple[str, ...] = (_WHEEL_SUFFIX, _SDIST_SUFFIX)


def shipped_findings(shipped: dict[str, bytes], tracked: dict[str, bytes]) -> list[str]:
    """Every way *shipped* fails to be *tracked*, one message per file.

    Both mappings are keyed by the path relative to `addon/`, so nothing here has to
    know which artifact shape it was read from.
    """
    findings = [
        f"{path} is missing from the artifact"
        for path in sorted(tracked)
        if installable(path) and path not in shipped
    ]
    findings += [
        f"{path} is extra: not tracked in addon/"
        for path in sorted(shipped)
        if path not in tracked
    ]
    findings += [
        f"{path} differs from the tracked file"
        for path in sorted(tracked)
        if path in shipped and shipped[path] != tracked[path]
    ]
    findings += [
        f"{path} is tracked but the installer would not copy it"
        for path in sorted(tracked)
        if not installable(path)
    ]
    return findings


def installable(path: str) -> bool:
    """Whether the installer's copy would take *path* out of `addon/`.

    The copy rule has two depths - `.py` anywhere, `.manifest` only at the root - so a
    suffix test alone would call a nested manifest copyable when nothing copies it.
    """
    suffixes = NESTED_WHITELIST if "/" in path else WHITELIST
    return PurePosixPath(path).suffix in suffixes


def _refuse(message: str) -> NoReturn:
    """One line on stderr and exit 2: cannot check, which is not a finding.

    The collapse is here rather than only at the call sites, because a message built
    from a path is one line only if the path is: a tracked file's name is the caller's
    input, and a newline in it is legal on POSIX.
    """
    print(_one_line(message), file=sys.stderr)
    raise SystemExit(2)


def _one_line(text: str) -> str:
    """*text* with its whitespace collapsed, so a refusal stays one stderr line."""
    return " ".join(text.split())


def expand_argument(path: Path) -> list[Path]:
    """The artifacts to read for *path*: itself, or the ones a directory holds.

    The expansion happens here rather than in the shell that runs the command, because
    the documented shell is not the one every maintainer has.  Only the two artifact
    suffixes are picked up, so a `dist/` holding notes or a signature beside them
    reads as the artifacts alone.

    A directory is a build output rather than a list of files, so it has to hold both
    kinds.  One kind alone is cannot check, not a clean run: an empty `dist/` would
    otherwise report success over nothing, and a `uv build` that produced only a wheel
    would otherwise pass the gate and publish without the sdist.
    """
    if not path.is_dir():
        return [path]
    found = sorted(
        candidate
        for suffix in _ARTIFACT_SUFFIXES
        for candidate in path.glob(f"*{suffix}")
    )
    present = [
        suffix
        for suffix in _ARTIFACT_SUFFIXES
        if any(candidate.name.endswith(suffix) for candidate in found)
    ]
    missing = [suffix for suffix in _ARTIFACT_SUFFIXES if suffix not in present]
    if len(missing) == len(_ARTIFACT_SUFFIXES):
        _refuse(f"{path}: holds no {_WHEEL_SUFFIX} or {_SDIST_SUFFIX} to check")
    if missing:
        (held,) = present
        _refuse(
            f"{path}: holds a {held} but no {missing[0]} to check: a directory is a "
            "single build output, and both artifacts are published"
        )
    return found


def read_artifact(path: Path) -> dict[str, bytes]:
    """The artifact's add-in files, keyed by their path relative to `addon/`."""
    try:
        if path.name.endswith(_WHEEL_SUFFIX):
            with zipfile.ZipFile(path) as wheel:
                return {
                    name.removeprefix(PACKAGE_PREFIX): wheel.read(name)
                    for name in wheel.namelist()
                    if name.startswith(PACKAGE_PREFIX) and not name.endswith("/")
                }
        if path.name.endswith(_SDIST_SUFFIX):
            return _read_sdist(path)
    except (OSError, zipfile.BadZipFile, tarfile.ReadError) as error:
        # `tarfile` names every compression it tried, one per line, so collapse it.
        _refuse(f"{path}: cannot be read as an artifact: {_one_line(str(error))}")
    _refuse(f"{path}: neither a .whl nor a .tar.gz, so there is no add-in copy to read")


def _read_sdist(path: Path) -> dict[str, bytes]:
    """The add-in files under `*/addon/` in an sdist, keyed as a wheel's are.

    An sdist stores everything beneath one distribution directory, whose name carries
    the version, so the key starts after `addon/` rather than at a fixed offset.
    """
    marker = f"/{ADD_ON_DIR}/"
    files: dict[str, bytes] = {}
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            if not member.isfile() or marker not in member.name:
                continue
            handle = archive.extractfile(member)
            # `isfile()` above already ruled this out; typeshed spells the return as
            # optional and the narrower check is cheaper than an assertion.
            if handle is None:
                continue
            files[member.name.split(marker, 1)[1]] = handle.read()
    return files


def tracked_add_on(root: Path) -> dict[str, bytes]:
    """The add-on files git tracks under *root*, keyed and read the same way."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", ADD_ON_DIR],
            capture_output=True,
            check=False,
        )
    except OSError as error:
        _refuse(f"cannot run git in {root}: {_one_line(str(error))}")
    if completed.returncode != 0:
        _refuse(
            f"git ls-files failed in {root}: "
            f"{_one_line(completed.stderr.decode('utf-8', 'replace'))}"
        )
    prefix = f"{ADD_ON_DIR}/"
    files: dict[str, bytes] = {}
    for entry in completed.stdout.decode("utf-8", "replace").split("\0"):
        if not entry.startswith(prefix):
            continue
        path = root / entry
        try:
            files[entry.removeprefix(prefix)] = path.read_bytes()
        except OSError as error:
            # The index names files the working tree no longer has, so a tracked file
            # deleted without `git rm` lands here.  Unreadable is cannot check - the
            # answer absent git gets - and a traceback would exit 1 as a finding.
            _refuse(f"{path}: tracked but cannot be read: {_one_line(str(error))}")
    return files


def main(argv: list[str] | None = None) -> int:
    """Exit 0 when every artifact matches `addon/`, 1 on a finding, 2 if uncheckable."""
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print(
            f"usage: {Path(__file__).name} <artifact.whl|artifact.tar.gz|dir> ...",
            file=sys.stderr,
        )
        return 2
    artifacts = [
        artifact
        for argument in arguments
        for artifact in expand_argument(Path(argument))
    ]
    tracked = tracked_add_on(ROOT)
    findings: list[str] = []
    for artifact in artifacts:
        artifact_findings = shipped_findings(read_artifact(artifact), tracked)
        findings.extend(f"{artifact}: {finding}" for finding in artifact_findings)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    copied = sum(1 for path in tracked if installable(path))
    for artifact in artifacts:
        print(f"{artifact}: {copied} add-on files match addon/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
