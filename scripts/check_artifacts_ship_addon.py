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

Stdlib only, and 3.12-compatible syntax: the release job runs it on the runner's own
Python, which is not this package's floor.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

# The suffixes the installer copies.  The copy decides what reaches Fusion and this
# check decides what the artifact may carry, so a tracked file outside the two of them
# is a finding rather than an omission.
WHITELIST: tuple[str, ...] = (".py", ".manifest")

ADD_ON_DIR = "addon"

# Where the add-in lands inside the wheel: `fusion360_mcp.addon` is mapped to `addon/`
# as a package, so its files are stored under this prefix rather than at the root.
PACKAGE_PREFIX = "fusion360_mcp/addon/"

_WHEEL_SUFFIX = ".whl"
_SDIST_SUFFIX = ".tar.gz"


def shipped_findings(shipped: dict[str, bytes], tracked: dict[str, bytes]) -> list[str]:
    """Every way *shipped* fails to be *tracked*, one message per file.

    Both mappings are keyed by the path relative to `addon/`, so nothing here has to
    know which artifact shape it was read from.
    """
    findings = [
        f"{path} is missing from the artifact"
        for path in sorted(tracked)
        if _installable(path) and path not in shipped
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
        if not _installable(path)
    ]
    return findings


def _installable(path: str) -> bool:
    """Whether the installer's whitelist would copy *path* out of `addon/`."""
    return PurePosixPath(path).suffix in WHITELIST


def read_artifact(path: Path) -> dict[str, bytes]:
    """The artifact's add-in files, keyed by their path relative to `addon/`."""
    if path.name.endswith(_WHEEL_SUFFIX):
        with zipfile.ZipFile(path) as wheel:
            return {
                name.removeprefix(PACKAGE_PREFIX): wheel.read(name)
                for name in wheel.namelist()
                if name.startswith(PACKAGE_PREFIX) and not name.endswith("/")
            }
    if path.name.endswith(_SDIST_SUFFIX):
        return _read_sdist(path)
    print(
        f"{path}: neither a .whl nor a .tar.gz, so there is no add-in copy to read",
        file=sys.stderr,
    )
    raise SystemExit(2)


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
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", ADD_ON_DIR],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        print(
            f"git ls-files failed in {root}: "
            f"{completed.stderr.decode('utf-8', 'replace').strip()}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    prefix = f"{ADD_ON_DIR}/"
    files: dict[str, bytes] = {}
    for entry in completed.stdout.decode("utf-8", "replace").split("\0"):
        if entry.startswith(prefix):
            files[entry.removeprefix(prefix)] = (root / entry).read_bytes()
    return files


def main(argv: list[str] | None = None) -> int:
    """Exit 0 when every artifact matches `addon/`, 1 on a finding, 2 if uncheckable."""
    arguments = sys.argv[1:] if argv is None else argv
    artifacts = [Path(argument) for argument in arguments]
    if not artifacts:
        print(
            f"usage: {Path(__file__).name} <artifact.whl|artifact.tar.gz> ...",
            file=sys.stderr,
        )
        return 2
    tracked = tracked_add_on(ROOT)
    findings = []
    for artifact in artifacts:
        findings.extend(shipped_findings(read_artifact(artifact), tracked))
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    for artifact in artifacts:
        print(f"{artifact}: {len(tracked)} add-on files match addon/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
