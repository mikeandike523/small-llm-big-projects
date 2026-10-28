"""Tests for src/utils/cwd_policy.py and src/utils/folder_shortcuts.py."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from src.utils import cwd_policy
from src.utils.cwd_policy import (
    HARD_ERROR_DIRS_LINUX,
    WARNING_DIRS_LINUX,
    WARNING_DIRS_WINDOWS,
    _match_rule,
    check_initial_cwd,
)
from src.utils import folder_shortcuts
from src.utils.folder_shortcuts import get_folder_shortcuts, read_xdg_user_dirs


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


# --- check_initial_cwd: basic validation ------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", 42])
def test_blank_or_non_string_is_error(raw):
    assert check_initial_cwd(raw).status == "error"


def test_control_characters_are_error(tmp_path):
    assert check_initial_cwd(str(tmp_path) + "\x00").status == "error"
    assert check_initial_cwd(str(tmp_path) + "\nmore").status == "error"


def test_relative_path_is_error():
    check = check_initial_cwd("some/relative/dir")
    assert check.status == "error"
    assert "absolute" in check.message


def test_missing_directory_is_error(tmp_path):
    check = check_initial_cwd(str(tmp_path / "nope"))
    assert check.status == "error"
    assert "does not exist" in check.message


def test_file_is_error(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert check_initial_cwd(str(f)).message == "Path is not a directory."


def test_plain_directory_is_ok_and_resolved(tmp_path, monkeypatch):
    # On Windows tmp_path lives under ~/AppData, itself a warning folder.
    hard, _warnings = cwd_policy.rules_for(cwd_policy.current_os_family())
    monkeypatch.setattr(cwd_policy, "rules_for", lambda family: (hard, ()))
    sub = tmp_path / "proj"
    sub.mkdir()
    check = check_initial_cwd(str(sub / ".." / "proj") + "/")
    assert check.status == "ok"
    assert check.resolved_path == _portable(sub.resolve())


def test_filesystem_root_is_hard_error(tmp_path):
    root = Path(tmp_path.anchor)
    check = check_initial_cwd(str(root))
    assert check.status == "error"
    assert "filesystem root" in check.message


def test_home_itself_is_warning_and_tilde_expands():
    check = check_initial_cwd("~")
    assert check.status == "warning"
    assert check.message == cwd_policy.PRIVILEGED_CWD_WARNING
    assert check.resolved_path == _portable(Path.home().resolve())


def test_unc_path_is_error_on_windows():
    check = check_initial_cwd(r"\\server\share\dir", family="windows")
    assert check.status == "error"
    assert "UNC" in check.message


# --- session workspace exemption ---------------------------------------------


def test_own_session_workspace_is_ok_before_it_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cwd_policy,
        "get_session_workspace_dir",
        lambda sid: f"{_portable(tmp_path)}/ws/{sid}",
    )
    sid = str(uuid.uuid4())
    check = check_initial_cwd(f"{_portable(tmp_path)}/ws/{sid}", sid)
    assert check.status == "ok"
    assert check.resolved_path == f"{_portable(tmp_path)}/ws/{sid}"


def test_other_sessions_workspace_is_not_exempt(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cwd_policy,
        "get_session_workspace_dir",
        lambda sid: f"{_portable(tmp_path)}/ws/{sid}",
    )
    other = str(uuid.uuid4())
    check = check_initial_cwd(f"{_portable(tmp_path)}/ws/{other}", str(uuid.uuid4()))
    assert check.status == "error"


# --- rule matching (OS-independent) --------------------------------------------


def test_linux_subtree_and_exact_rules():
    home = "/home/me"
    assert _match_rule(["/etc/nginx"], WARNING_DIRS_LINUX, "linux", home)
    assert _match_rule(["/home"], WARNING_DIRS_LINUX, "linux", home)
    assert _match_rule(["/home/me"], WARNING_DIRS_LINUX, "linux", home) == "~"
    assert _match_rule(["/home/me/project"], WARNING_DIRS_LINUX, "linux", home) is None
    assert _match_rule(["/etcetera"], WARNING_DIRS_LINUX, "linux", home) is None
    assert _match_rule(["/var/www/site"], WARNING_DIRS_LINUX, "linux", home) is None
    assert _match_rule(["/proc/1"], HARD_ERROR_DIRS_LINUX, "linux", home)
    assert _match_rule(["/"], HARD_ERROR_DIRS_LINUX, "linux", home)


def test_linux_matching_is_case_sensitive():
    assert _match_rule(["/ETC"], WARNING_DIRS_LINUX, "linux", "/home/me") is None


def test_windows_matching_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    home = "C:/Users/me"
    assert _match_rule(["c:/windows/system32"], WARNING_DIRS_WINDOWS, "windows", home)
    assert _match_rule(["C:/Users/ME"], WARNING_DIRS_WINDOWS, "windows", home) == "~"
    assert (
        _match_rule(["C:/Users/me/code"], WARNING_DIRS_WINDOWS, "windows", home) is None
    )


# --- folder shortcuts -----------------------------------------------------------


def test_shortcuts_skip_missing_folders(tmp_path):
    (tmp_path / "Documents").mkdir()
    shortcuts = get_folder_shortcuts(tmp_path, family="windows")
    assert shortcuts[0] == {"label": "Home", "path": _portable(tmp_path)}
    assert [s["label"] for s in shortcuts] == ["Home", "Documents"]


def test_xdg_user_dirs_are_used_on_linux(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(folder_shortcuts, "_linux_distro_ids", lambda: ["ubuntu"])
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text(
        '# comment\nXDG_DOCUMENTS_DIR="$HOME/Dokumente"\nXDG_DESKTOP_DIR="$HOME/"\n',
        encoding="utf-8",
    )
    (tmp_path / "Dokumente").mkdir()
    (tmp_path / "Documents").mkdir()  # conventional name; XDG wins for the label
    (tmp_path / "Projects").mkdir()
    # "$HOME/" means "disabled" per the XDG spec, so Desktop is skipped.
    assert read_xdg_user_dirs(tmp_path) == [("Documents", tmp_path / "Dokumente")]
    shortcuts = get_folder_shortcuts(tmp_path, family="linux")
    labels = {s["label"]: s["path"] for s in shortcuts}
    assert labels["Documents"] == _portable(tmp_path / "Dokumente")
    assert "Projects" in labels
