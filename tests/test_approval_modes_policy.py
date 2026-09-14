from __future__ import annotations

import subprocess
from pathlib import Path

from src.tools import check_needs_approval


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(
        ["git", "-C", str(root), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    (root / ".gitignore").write_text(".env\nignored-dir/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("hello\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (root / "ignored-dir").mkdir()
    (root / "ignored-dir" / "file.txt").write_text("ignored\n", encoding="utf-8")
    return root


def _sr(root: Path, mode: str) -> dict:
    return {
        "session_init_working_dir": str(root),
        "session_current_working_dir": str(root),
        "approval_mode": mode,
    }


def _needs(tool: str, args: dict, root: Path, mode: str) -> bool:
    return check_needs_approval(
        tool,
        args,
        special_resources=_sr(root, mode),
        session_data={"memory": {}},
    )


def test_auto_accept_edits_write_tools_use_scoped_nonignored_paths(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)

    args = {"path": "tracked.txt", "content": "x"}
    assert _needs("write_text_file", args, root, "default")
    assert not _needs("write_text_file", args, root, "auto-accept-edits")
    assert _needs(
        "write_text_file",
        {"path": ".env", "content": "x"},
        root,
        "auto-accept-edits",
    )
    assert _needs(
        "write_text_file",
        {"path": str(tmp_path / "outside.txt"), "content": "x"},
        root,
        "auto-accept-edits",
    )
    assert not _needs(
        "write_text_file",
        {"path": ".env", "content": "x"},
        root,
        "full-auto",
    )


def test_auto_accept_edits_multi_path_tools_require_both_paths_allowed(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)

    assert not _needs(
        "copy_file",
        {"src": "tracked.txt", "dst": "copy.txt"},
        root,
        "auto-accept-edits",
    )
    assert _needs(
        "copy_file",
        {"src": ".env", "dst": "copy.txt"},
        root,
        "auto-accept-edits",
    )
    assert _needs(
        "copy_file",
        {"src": "tracked.txt", "dst": ".env"},
        root,
        "auto-accept-edits",
    )
    assert not _needs(
        "copy_file",
        {"src": ".env", "dst": str(tmp_path / "outside.txt")},
        root,
        "full-auto",
    )


def test_shell_terminal_and_cwd_modes(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)

    shell_args = {"command": "echo", "command_args": ["ok"]}
    assert _needs("host_shell", shell_args, root, "auto-accept-edits")
    assert not _needs("host_shell", shell_args, root, "full-auto")
    assert _needs("open_in_terminal", {"cmdline": "echo ok"}, root, "full-auto")
    assert not _needs("change_pwd", {"path": str(tmp_path)}, root, "full-auto")


def test_snapshot_and_restore_follow_read_write_semantics(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)

    assert not _needs("snapshot_file", {"path": "tracked.txt"}, root, "default")
    assert _needs("snapshot_file", {"path": ".env"}, root, "default")
    assert _needs("snapshot_file", {"path": ".env"}, root, "auto-accept-edits")
    assert not _needs("snapshot_file", {"path": ".env"}, root, "full-auto")

    assert not _needs(
        "restore_file",
        {"path": ".env", "action": "list"},
        root,
        "default",
    )
    assert _needs(
        "restore_file",
        {"path": "tracked.txt", "action": "restore"},
        root,
        "default",
    )
    assert not _needs(
        "restore_file",
        {"path": "tracked.txt", "action": "restore"},
        root,
        "auto-accept-edits",
    )
    assert _needs(
        "restore_file",
        {"path": ".env", "action": "restore"},
        root,
        "auto-accept-edits",
    )
    assert not _needs(
        "restore_file",
        {"path": ".env", "action": "restore"},
        root,
        "full-auto",
    )


def test_request_unredacted_stays_central_hard_gate(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)

    assert _needs(
        "read_text_file",
        {"path": "tracked.txt", "request_unredacted": True},
        root,
        "full-auto",
    )
