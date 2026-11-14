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
