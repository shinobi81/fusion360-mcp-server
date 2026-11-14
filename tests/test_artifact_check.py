from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_checker():
    """Load `scripts/check_artifacts_ship_addon.py` by path, as `test_addon_sync.py`
    loads the add-in: loaded by path so this test needs no `sys.path` insertion and no
    lint suppression."""
    path = REPO_ROOT / "scripts" / "check_artifacts_ship_addon.py"
    spec = importlib.util.spec_from_file_location("check_artifacts_ship_addon", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = _load_checker()

TRACKED = {
    "Fusion360MCP.manifest": b'{"version": "0.7.3"}',
    "Fusion360MCP.py": b"import os\n",
    "server/__init__.py": b"",
    "server/hints.py": b"X = 1\n",
}


def test_a_shipped_set_matching_the_tracked_set_is_clean():
    assert CHECK.shipped_findings(dict(TRACKED), TRACKED) == []


def test_a_missing_file_is_named():
    shipped = {k: v for k, v in TRACKED.items() if k != "server/hints.py"}

    (finding,) = CHECK.shipped_findings(shipped, TRACKED)

    assert "server/hints.py" in finding
    assert "missing" in finding


def test_an_extra_file_is_named():
    shipped = {**TRACKED, "server/stale.py": b""}

    (finding,) = CHECK.shipped_findings(shipped, TRACKED)

    assert "server/stale.py" in finding
    assert "extra" in finding


def test_a_byte_difference_is_named():
    shipped = {**TRACKED, "server/hints.py": b"X = 2\n"}

    (finding,) = CHECK.shipped_findings(shipped, TRACKED)

    assert "server/hints.py" in finding
    assert "differ" in finding


def test_a_tracked_file_outside_the_whitelist_is_a_finding():
    tracked = {**TRACKED, "icon.svg": b"<svg/>"}

    findings = CHECK.shipped_findings(dict(tracked), tracked)

    assert any("icon.svg" in f and "installer would not copy" in f for f in findings)


def test_a_tracked_nested_manifest_is_a_finding():
    """Only the root manifest names and ships the add-in; a nested one is data the
    installer skips, so its presence in the wheel is the silent case."""
    tracked = {**TRACKED, "server/Other.manifest": b"{}"}

    (finding,) = CHECK.shipped_findings(dict(tracked), tracked)

    assert "server/Other.manifest" in finding
    assert "installer would not copy" in finding


def _wheel(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(f"fusion360_mcp/addon/{name}", data)
    return path


def _sdist(path: Path, entries: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(f"pkg-0.7.3/addon/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_a_wheel_is_read_under_its_package_prefix(tmp_path: Path):
    path = _wheel(tmp_path / "a.whl", TRACKED)

    assert CHECK.read_artifact(path) == TRACKED


def test_an_sdist_is_read_under_its_distribution_directory(tmp_path: Path):
    path = _sdist(tmp_path / "a.tar.gz", TRACKED)

    assert CHECK.read_artifact(path) == TRACKED


def test_an_unreadable_artifact_is_refused_not_guessed(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        CHECK.read_artifact(tmp_path / "notes.txt")

    assert exc.value.code == 2


def test_a_missing_artifact_is_cannot_check_not_a_finding(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        CHECK.read_artifact(tmp_path / "absent.whl")

    assert exc.value.code == 2


def test_absent_git_is_cannot_check_not_a_finding(monkeypatch, tmp_path: Path):
    def no_git(*_args: object, **_kwargs: object):
        raise FileNotFoundError("git")

    monkeypatch.setattr(CHECK.subprocess, "run", no_git)

    with pytest.raises(SystemExit) as exc:
        CHECK.tracked_add_on(tmp_path)

    assert exc.value.code == 2


def test_main_names_the_artifact_a_finding_came_from(tmp_path: Path, capsys):
    tracked = CHECK.tracked_add_on(REPO_ROOT)
    clean = _wheel(tmp_path / "clean.whl", tracked)
    stale = _sdist(tmp_path / "stale.tar.gz", {**tracked, "server/hints.py": b""})

    assert CHECK.main([str(clean), str(stale)]) == 1

    stderr = capsys.readouterr().err
    assert f"{stale}: server/hints.py differs from the tracked file" in stderr
    assert f"{clean}:" not in stderr


def test_a_directory_argument_is_expanded_to_the_artifacts_it_holds(
    tmp_path: Path, capsys
):
    """PowerShell and cmd do not expand `dist/*.whl`, so the check expands it.

    The documented command names the directory for exactly this reason: a literal glob
    reaching `read_artifact` would be refused rather than checked.  The order is the
    directory's, sorted - `clean.tar.gz` before `clean.whl` - not wheels first.  A
    directory is a build output, so both artifacts have to be in it.
    """
    tracked = CHECK.tracked_add_on(REPO_ROOT)
    wheel = _wheel(tmp_path / "clean.whl", tracked)
    sdist = _sdist(tmp_path / "clean.tar.gz", tracked)

    assert CHECK.main([str(tmp_path)]) == 0

    matched = f"{len(tracked)} add-on files match addon/"
    assert capsys.readouterr().out.splitlines() == [
        f"{sdist}: {matched}",
        f"{wheel}: {matched}",
    ]


def test_a_directory_holding_no_artifact_is_cannot_check_and_names_itself(
    tmp_path: Path, capsys
):
    """Checking nothing must not read as a clean run - an unbuilt `dist/` is common."""
    empty = tmp_path / "dist"
    empty.mkdir()

    with pytest.raises(SystemExit) as refused:
        CHECK.main([str(empty)])

    assert refused.value.code == 2
    stderr = capsys.readouterr().err
    assert str(empty) in stderr
    assert len(stderr.strip().splitlines()) == 1, stderr


def test_a_directory_picks_up_only_the_two_artifact_suffixes(tmp_path: Path, capsys):
    """`dist/` also collects signatures, notes and an SBOM; only artifacts are read.

    Pinned as ignoring them rather than refusing: a directory is the build output a
    maintainer points at, not a list of files to check one by one, so anything the
    release would publish beside the artifacts must not fail the check.
    """
    tracked = CHECK.tracked_add_on(REPO_ROOT)
    wheel = _wheel(tmp_path / "clean.whl", tracked)
    sdist = _sdist(tmp_path / "clean.tar.gz", tracked)
    (tmp_path / "sbom.cdx.json").write_text("{}\n", encoding="utf-8")

    assert CHECK.main([str(tmp_path)]) == 0

    matched = f"{len(tracked)} add-on files match addon/"
    out = capsys.readouterr().out
    assert out.splitlines() == [f"{sdist}: {matched}", f"{wheel}: {matched}"]
    assert "sbom.cdx.json" not in out


def test_a_directory_holding_only_a_wheel_is_cannot_check(tmp_path: Path, capsys):
    """`uv build` producing one artifact must fail the gate, not pass over the half
    that exists: the release publishes both, and a missing sdist would go unnoticed."""
    tracked = CHECK.tracked_add_on(REPO_ROOT)
    _wheel(tmp_path / "clean.whl", tracked)

    with pytest.raises(SystemExit) as refused:
        CHECK.main([str(tmp_path)])

    assert refused.value.code == 2
    stderr = capsys.readouterr().err
    assert str(tmp_path) in stderr
    assert ".tar.gz" in stderr
    assert len(stderr.strip().splitlines()) == 1, stderr


def test_a_directory_holding_only_an_sdist_is_cannot_check(tmp_path: Path, capsys):
    tracked = CHECK.tracked_add_on(REPO_ROOT)
    _sdist(tmp_path / "clean.tar.gz", tracked)

    with pytest.raises(SystemExit) as refused:
        CHECK.main([str(tmp_path)])

    assert refused.value.code == 2
    stderr = capsys.readouterr().err
    assert str(tmp_path) in stderr
    assert ".whl" in stderr
    assert len(stderr.strip().splitlines()) == 1, stderr


def test_a_file_argument_is_checked_alone(tmp_path: Path, capsys):
    """A maintainer naming one artifact asked for that one, not for a build output."""
    tracked = CHECK.tracked_add_on(REPO_ROOT)
    wheel = _wheel(tmp_path / "clean.whl", tracked)
    sdist = _sdist(tmp_path / "clean.tar.gz", tracked)

    assert CHECK.main([str(wheel)]) == 0
    assert CHECK.main([str(sdist)]) == 0

    matched = f"{len(tracked)} add-on files match addon/"
    assert capsys.readouterr().out.splitlines() == [
        f"{wheel}: {matched}",
        f"{sdist}: {matched}",
    ]


def test_a_path_that_is_neither_a_file_nor_a_directory_is_still_cannot_check(
    tmp_path: Path,
):
    """Expanding directories must not turn a missing artifact into a clean run."""
    with pytest.raises(SystemExit) as refused:
        CHECK.main([str(tmp_path / "absent.whl")])

    assert refused.value.code == 2


def test_the_repository_tracks_ten_add_on_files():
    tracked = CHECK.tracked_add_on(REPO_ROOT)

    assert set(tracked) == {
        "Fusion360MCP.manifest",
        "Fusion360MCP.py",
        "server/__init__.py",
        "server/command_handler.py",
        "server/event_bridge.py",
        "server/fusion_api.py",
        "server/hints.py",
        "server/hole_geometry.py",
        "server/parameter_units.py",
        "server/socket_server.py",
    }
