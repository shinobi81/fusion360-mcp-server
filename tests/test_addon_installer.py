"""The installed-package side of the add-in copy: find it, name it, copy it.

The copy rule lives in two files: this package's `addon_install._installable`, which
decides what reaches Fusion, and `scripts/check_artifacts_ship_addon.py`'s
`installable`, which decides what the built artifact may carry.  The script is not in
the wheel, so the rule is spelled twice; the last test here is the tie that keeps the
two from drifting apart silently.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from fusion360_mcp import addon_install
from fusion360_mcp.addon_install import (
    ADD_INS_TAIL,
    DARWIN_TAIL,
    InstallRefused,
    add_ins_dir,
    add_on_source,
    copy_add_on,
    install_addon,
    manifest_for,
    target_for,
)
from fusion360_mcp.server import main

REPO_ROOT = Path(__file__).resolve().parent.parent

MANIFEST = '{"type": "addin", "version": "0.7.3"}'

# Paths relative to the add-on's root that the copy rule has to decide, one per case
# it can get wrong: a root manifest and entry module, a module at two depths, a nested
# manifest nothing copies, and three suffixes a whitelist has to keep out.
COPY_RULE_PATHS = (
    "Fusion360MCP.manifest",
    "Fusion360MCP.py",
    "server/hints.py",
    "server/deep/mod.py",
    "server/Other.manifest",
    "notes.txt",
    "icon.svg",
    ".env",
)


def _load_module_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _add_on_tree(tmp_path: Path, *, extra: dict[str, str] | None = None) -> Path:
    """A stand-in for the packaged add-in: a manifest, an entry point, one module."""
    source = tmp_path / "addon"
    (source / "server").mkdir(parents=True)
    (source / "Fusion360MCP.manifest").write_text(MANIFEST, encoding="utf-8")
    (source / "Fusion360MCP.py").write_text("import os\n", encoding="utf-8")
    (source / "server" / "__init__.py").write_text("", encoding="utf-8")
    (source / "server" / "hints.py").write_text("X = 1\n", encoding="utf-8")
    for name, text in (extra or {}).items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return source


def test_the_copy_mirrors_the_layout_and_reports_what_it_wrote(tmp_path: Path):
    source = _add_on_tree(tmp_path)
    target = tmp_path / "AddIns" / "Fusion360MCP"

    copied = copy_add_on(source, target)

    assert copied == [
        "Fusion360MCP.manifest",
        "Fusion360MCP.py",
        "server/__init__.py",
        "server/hints.py",
    ]
    assert (target / "server" / "hints.py").read_text(encoding="utf-8") == "X = 1\n"


def test_a_developer_dotfile_never_travels(tmp_path: Path):
    source = _add_on_tree(
        tmp_path,
        extra={
            ".env": "SECRET=1\n",
            ".vscode/settings.json": "{}",
            "__pycache__/x.pyc": "",
        },
    )

    copied = copy_add_on(source, tmp_path / "out")

    assert not any("env" in p or "vscode" in p or "pyc" in p for p in copied)
    assert sorted(p.name for p in (tmp_path / "out").rglob("*")) == [
        "Fusion360MCP.manifest",
        "Fusion360MCP.py",
        "__init__.py",
        "hints.py",
        "server",
    ]


def test_the_walk_is_recursive_not_one_level_deep(tmp_path: Path):
    source = _add_on_tree(tmp_path, extra={"server/deep/mod.py": "Y = 2\n"})

    copied = copy_add_on(source, tmp_path / "out")

    assert "server/deep/mod.py" in copied


def test_a_source_without_an_add_on_directory_is_refused(tmp_path: Path):
    with pytest.raises(InstallRefused) as exc:
        copy_add_on(tmp_path / "missing", tmp_path / "out")

    assert "install-addon.sh" in str(exc.value)


def test_the_name_comes_from_the_root_manifest(tmp_path: Path):
    source = _add_on_tree(tmp_path)

    assert manifest_for(source).name == "Fusion360MCP.manifest"


def test_no_manifest_is_refused_without_inventing_a_name(tmp_path: Path):
    (tmp_path / "addon").mkdir()

    with pytest.raises(InstallRefused) as exc:
        manifest_for(tmp_path / "addon")

    assert "found 0" in str(exc.value)


def test_two_manifests_are_refused_and_listed(tmp_path: Path):
    source = _add_on_tree(tmp_path)
    (source / "Other.manifest").write_text(MANIFEST, encoding="utf-8")

    with pytest.raises(InstallRefused) as exc:
        manifest_for(source)

    assert "found 2" in str(exc.value)
    assert "Other.manifest" in str(exc.value)


def test_a_manifest_that_is_not_a_regular_file_is_refused(tmp_path: Path):
    source = tmp_path / "addon"
    (source / "Bogus.manifest").mkdir(parents=True)

    with pytest.raises(InstallRefused) as exc:
        manifest_for(source)

    assert "not a regular file" in str(exc.value)


def test_a_nested_manifest_does_not_name_the_add_in(tmp_path: Path):
    source = _add_on_tree(tmp_path, extra={"server/Other.manifest": MANIFEST})

    assert manifest_for(source).name == "Fusion360MCP.manifest"
    assert "server/Other.manifest" not in copy_add_on(source, tmp_path / "out")


def test_a_source_checkout_is_named_as_the_development_path(tmp_path: Path):
    """In a checkout `src/fusion360_mcp/addon` does not exist, so the refusal names
    the script that *is* the development path rather than a wheel bug."""
    source = add_on_source(package=tmp_path)

    assert source == tmp_path / "addon"
    with pytest.raises(InstallRefused) as exc:
        copy_add_on(source, tmp_path / "out")
    assert "install-addon.sh" in str(exc.value)


def test_windows_reads_appdata(tmp_path: Path):
    (tmp_path / "Autodesk" / "Autodesk Fusion 360").mkdir(parents=True)

    path = add_ins_dir(environ={"APPDATA": str(tmp_path)}, system="windows")

    assert path == tmp_path / "Autodesk" / "Autodesk Fusion 360" / "API" / "AddIns"


def test_both_layouts_are_spelled_out_verbatim():
    """The two tails are the interface: `scripts/install-addon.sh` resolves the same
    folders, and a component edited here without editing there splits the two."""
    assert ADD_INS_TAIL == "Autodesk/Autodesk Fusion 360/API/AddIns"
    assert DARWIN_TAIL == (
        "Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
    )


def test_the_install_script_spells_the_same_two_tails():
    """The other side of the pair above: the bash script is the development path and
    resolves the same two folders.  Comparing the constants with the script's literals
    is the only place the two spellings meet, so a component edited on one side fails
    here rather than installing a link Fusion never loads."""
    script = (REPO_ROOT / "scripts" / "install-addon.sh").read_text(encoding="utf-8")

    assert f'"$APPDATA/{ADD_INS_TAIL}"' in script, (
        "scripts/install-addon.sh no longer builds Windows' AddIns path from "
        f"addon_install.ADD_INS_TAIL ({ADD_INS_TAIL})"
    )
    assert f'"$HOME/{DARWIN_TAIL}"' in script, (
        "scripts/install-addon.sh no longer builds macOS' AddIns path from "
        f"addon_install.DARWIN_TAIL ({DARWIN_TAIL})"
    )


def test_windows_without_appdata_is_refused_not_guessed():
    with pytest.raises(InstallRefused) as exc:
        add_ins_dir(environ={}, system="windows")

    assert "APPDATA" in str(exc.value)


def test_macos_reads_home(tmp_path: Path):
    (tmp_path / "Library" / "Application Support" / "Autodesk").mkdir(parents=True)
    (
        tmp_path
        / "Library"
        / "Application Support"
        / "Autodesk"
        / "Autodesk Fusion 360"
    ).mkdir()

    path = add_ins_dir(environ={"HOME": str(tmp_path)}, system="darwin")

    assert path == (
        tmp_path
        / "Library"
        / "Application Support"
        / "Autodesk"
        / "Autodesk Fusion 360"
        / "API"
        / "AddIns"
    )


def test_an_unsupported_os_is_refused():
    with pytest.raises(InstallRefused) as exc:
        add_ins_dir(environ={"HOME": "/tmp"}, system="linux")

    assert "Fusion" in str(exc.value)


def test_the_add_ins_directory_is_created_under_an_existing_fusion_root(tmp_path: Path):
    (tmp_path / "Autodesk" / "Autodesk Fusion 360").mkdir(parents=True)

    path = add_ins_dir(environ={"APPDATA": str(tmp_path)}, system="windows")

    assert path.is_dir()


def test_a_read_only_fusion_root_is_refused_as_a_line(
    tmp_path: Path, monkeypatch, capsys
):
    """Fusion installed but its tree not writable: the ``mkdir`` that creates
    ``API/AddIns`` raises ``PermissionError``, which is an ``OSError`` and not an
    ``InstallRefused``.  Left unhandled it would escape as a traceback from a CLI whose
    only answer is an exit code.
    """
    source = _add_on_tree(tmp_path)
    (tmp_path / "Autodesk" / "Autodesk Fusion 360").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(addon_install, "_current_system", lambda: "windows")

    def read_only(path, *args, **kwargs):
        raise PermissionError(f"{path} is read-only")

    monkeypatch.setattr(Path, "mkdir", read_only)

    code = install_addon(source=source)
    err = capsys.readouterr().err

    assert code == 1
    assert "cannot create" in err
    assert not (tmp_path / "Autodesk" / "Autodesk Fusion 360" / "API").exists()


def test_a_missing_fusion_root_is_refused_and_nothing_is_created(tmp_path: Path):
    with pytest.raises(InstallRefused) as exc:
        add_ins_dir(environ={"APPDATA": str(tmp_path)}, system="windows")

    assert "Fusion 360" in str(exc.value)
    assert not (tmp_path / "Autodesk").exists()


def test_the_environment_defaults_to_this_process(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Autodesk" / "Autodesk Fusion 360").mkdir(parents=True)

    assert add_ins_dir(system="windows") == tmp_path / ADD_INS_TAIL


def test_the_system_defaults_to_this_machine():
    """`system=None` reads the interpreter: Windows gets a name of its own, and macOS
    is already `sys.platform`'s `darwin`.  Anything else survives unchanged, which is
    what `add_ins_dir` refuses."""
    derived = addon_install._current_system()

    assert derived == ("windows" if os.name == "nt" else sys.platform)


def test_install_add_on_reports_success_and_copies(tmp_path: Path, capsys):
    source = _add_on_tree(tmp_path)
    target_root = tmp_path / "AddIns"

    code = install_addon(addin_dir=target_root, source=source)

    assert code == 0
    assert (target_root / "Fusion360MCP" / "server" / "hints.py").is_file()
    assert "0.7.3" in capsys.readouterr().out


def test_the_reported_version_comes_from_the_manifest(tmp_path: Path, capsys):
    """One version source: the number printed is the manifest's, not a literal here."""
    source = _add_on_tree(
        tmp_path, extra={"Fusion360MCP.manifest": '{"version": "9.9.9"}'}
    )

    assert install_addon(addin_dir=tmp_path / "AddIns", source=source) == 0
    assert "9.9.9" in capsys.readouterr().out


def test_install_add_on_reports_a_refusal_without_raising(tmp_path: Path, capsys):
    code = install_addon(addin_dir=tmp_path / "AddIns", source=tmp_path / "missing")

    assert code == 1
    assert "install-addon.sh" in capsys.readouterr().err


def test_a_path_with_spaces_and_non_ascii_characters_still_installs(tmp_path: Path):
    awkward = tmp_path / "Jane Doe" / "Jörg"
    source = _add_on_tree(awkward)

    code = install_addon(addin_dir=awkward / "AddIns", source=source)

    assert code == 0
    assert (awkward / "AddIns" / "Fusion360MCP" / "Fusion360MCP.py").is_file()


@pytest.mark.skipif(os.name == "nt", reason="a POSIX symlink needs no privilege")
def test_a_symlinked_target_is_refused_and_the_repo_is_untouched(
    tmp_path: Path, capsys
):
    """Assert the phrase, not the word: pytest names this test's temporary directory
    after the test, so a bare ``symlink`` also matches the path in the message the
    containment refusal prints — an assertion that cannot fail.
    """
    checkout = _add_on_tree(tmp_path)
    add_ins = tmp_path / "AddIns"
    add_ins.mkdir()
    (add_ins / "Fusion360MCP").symlink_to(checkout, target_is_directory=True)

    code = install_addon(addin_dir=add_ins, source=checkout)
    err = capsys.readouterr().err

    assert code == 1
    assert "is a symlink or junction" in err
    assert (checkout / "Fusion360MCP.py").read_text(encoding="utf-8") == "import os\n"


@pytest.mark.skipif(os.name != "nt", reason="junctions exist only on Windows")
def test_a_junction_target_is_refused_and_the_repo_is_untouched(tmp_path: Path, capsys):
    """A junction needs no privilege, so unlike the POSIX symlink this half runs on
    Windows — and it is the half the falsification measured: with the link check
    replaced by `False` the bare word ``junction`` still matched the temporary
    directory's name, `test_a_junction_target_is_refu0`, in the containment refusal's
    path, so the test passed for the wrong reason.
    """
    checkout = _add_on_tree(tmp_path)
    add_ins = tmp_path / "AddIns"
    add_ins.mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(add_ins / "Fusion360MCP"), str(checkout)],
        check=True,
        capture_output=True,
    )

    code = install_addon(addin_dir=add_ins, source=checkout)
    err = capsys.readouterr().err

    assert code == 1
    assert "is a symlink or junction" in err
    assert (checkout / "Fusion360MCP.py").read_text(encoding="utf-8") == "import os\n"


def test_a_target_that_is_a_regular_file_is_refused(tmp_path: Path, capsys):
    source = _add_on_tree(tmp_path)
    add_ins = tmp_path / "AddIns" / "Fusion360MCP"
    add_ins.parent.mkdir()
    add_ins.write_text("not a directory", encoding="utf-8")

    code = install_addon(addin_dir=add_ins.parent, source=source)

    assert code == 1
    assert "not a directory" in capsys.readouterr().err


def test_a_stale_install_is_replaced(tmp_path: Path):
    source = _add_on_tree(tmp_path)
    add_ins = tmp_path / "AddIns"
    stale = add_ins / "Fusion360MCP"
    stale.mkdir(parents=True)
    (stale / "gone.py").write_text("", encoding="utf-8")

    assert install_addon(addin_dir=add_ins, source=source) == 0

    assert not (stale / "gone.py").exists()
    assert (stale / "Fusion360MCP.py").is_file()


def test_a_stem_that_escapes_the_add_ins_directory_is_refused(tmp_path: Path):
    """A manifest stem is a path segment. `Path.stem` cannot produce `..` from a
    `*.manifest` glob, so the refusal is pinned at the helper that takes a stem,
    rather than through a filename that cannot exist."""
    with pytest.raises(InstallRefused) as exc:
        target_for(tmp_path / "AddIns", "..")

    assert "AddIns" in str(exc.value)


def test_a_copy_that_drops_a_file_is_reported(tmp_path: Path, monkeypatch, capsys):
    source = _add_on_tree(tmp_path)
    real = addon_install.copy_add_on

    def lossy(src: Path, dst: Path) -> list[str]:
        copied = real(src, dst)
        Path(dst / "server" / "hints.py").unlink()
        return copied

    monkeypatch.setattr(addon_install, "copy_add_on", lossy)

    code = install_addon(addin_dir=tmp_path / "AddIns", source=source)

    assert code == 1
    assert "server/hints.py" in capsys.readouterr().err


def test_a_write_that_fails_is_reported_as_a_line(tmp_path: Path, monkeypatch, capsys):
    """The last line of defence: whatever a filesystem refuses, the CLI answers with
    an exit code rather than a traceback."""
    source = _add_on_tree(tmp_path)
    add_ins = tmp_path / "AddIns"
    (add_ins / "Fusion360MCP").mkdir(parents=True)

    def read_only(path, *args, **kwargs):
        raise PermissionError(f"{path} is read-only")

    monkeypatch.setattr(addon_install.shutil, "rmtree", read_only)

    code = install_addon(addin_dir=add_ins, source=source)

    assert code == 1
    assert "cannot write to" in capsys.readouterr().err


def test_a_manifest_that_is_not_json_is_refused_as_a_line(tmp_path: Path, capsys):
    source = _add_on_tree(tmp_path, extra={"Fusion360MCP.manifest": "not json"})

    code = install_addon(addin_dir=tmp_path / "AddIns", source=source)

    assert code == 1
    assert "cannot be read as JSON" in capsys.readouterr().err


def test_a_manifest_without_a_version_is_refused_as_a_line(tmp_path: Path, capsys):
    source = _add_on_tree(
        tmp_path, extra={"Fusion360MCP.manifest": '{"type": "addin"}'}
    )

    code = install_addon(addin_dir=tmp_path / "AddIns", source=source)

    assert code == 1
    assert "no version" in capsys.readouterr().err
    assert not (tmp_path / "AddIns" / "Fusion360MCP").exists()


def test_an_unset_system_is_derived_from_this_machine(tmp_path: Path, monkeypatch):
    """`system=None` is the only value that dispatches to this machine.  A set-but-empty
    system is an unknown one, which `add_ins_dir` refuses rather than overrides."""
    monkeypatch.setattr(addon_install, "_current_system", lambda: "windows")
    (tmp_path / "Autodesk" / "Autodesk Fusion 360").mkdir(parents=True)

    path = add_ins_dir(environ={"APPDATA": str(tmp_path)}, system=None)

    assert path == tmp_path / ADD_INS_TAIL


def test_an_empty_system_is_refused_not_replaced_by_this_machine():
    with pytest.raises(InstallRefused) as exc:
        add_ins_dir(environ={"HOME": "/tmp"}, system="")

    assert "Fusion 360 runs on Windows and macOS only" in str(exc.value)


def test_the_copy_rule_matches_the_release_check():
    """The release check only means something while it agrees with the copy.

    Both predicates answer "would the install take this file out of `addon/`": one
    decides what reaches Fusion, the other what a built artifact may carry.  A drift
    makes the artifact check pass over files the install skips, so the message names
    the two files rather than the two answers alone.
    """
    release_check = _load_module_by_path(
        REPO_ROOT / "scripts" / "check_artifacts_ship_addon.py",
        "check_artifacts_ship_addon",
    )

    disagreed = [
        f"{rel!r}: addon_install.py says {addon_install._installable(rel)}, "
        f"scripts/check_artifacts_ship_addon.py says {release_check.installable(rel)}"
        for rel in COPY_RULE_PATHS
        if addon_install._installable(rel) != release_check.installable(rel)
    ]

    assert not disagreed, (
        "the copy rule lives in two different files and they disagree:\n"
        + "\n".join(disagreed)
    )


def test_the_flag_installs_and_exits_without_starting_a_server(
    tmp_path: Path, monkeypatch
):
    source = _add_on_tree(tmp_path)
    add_ins = tmp_path / "AddIns"
    monkeypatch.setattr(addon_install, "add_on_source", lambda: source)

    result = CliRunner().invoke(main, ["--install-addon", "--addin-dir", str(add_ins)])

    assert result.exit_code == 0, result.stderr
    assert (add_ins / "Fusion360MCP" / "Fusion360MCP.py").is_file()
    assert "files copied" in result.stdout
    assert "Fusion360MCP" in result.stdout


def test_the_flag_sets_a_failing_exit_status_on_refusal(tmp_path: Path, monkeypatch):
    """The refusal is the exit status, and it is set before `anyio.run`: a standalone
    command's `return 1` would leave the status at 0 and the shell would not see it.
    """
    monkeypatch.setattr(addon_install, "add_on_source", lambda: tmp_path / "absent")

    result = CliRunner().invoke(
        main, ["--install-addon", "--addin-dir", str(tmp_path / "AddIns")]
    )

    assert result.exit_code == 1
    assert "install-addon.sh" in result.stderr


def test_the_server_path_is_unchanged_without_the_flag():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "--install-addon" in result.stdout
    assert "--mode" in result.stdout
