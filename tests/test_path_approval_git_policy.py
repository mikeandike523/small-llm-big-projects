"""needs_path_approval git policy: repo vs. non-repo, .git metadata, git failures.

See general-notes/file-access-approval-policy.md for the policy itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import src.tools._approval as approval
from src.tools import check_needs_approval
from src.utils.exceptions import ToolTimeoutError


def _git_init(root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), "init"], check=True, capture_output=True, text=True
    )


def _sr(root: Path, mode: str = "default") -> dict:
    return {
        "session_init_working_dir": str(root),
        "session_current_working_dir": str(root),
        "approval_mode": mode,
    }


def _needs(tool: str, args: dict, root: Path, mode: str = "default") -> bool:
    needs_approval, _hop_path = check_needs_approval(
        tool, args, special_resources=_sr(root, mode), session_data={"memory": {}}
    )
    return needs_approval


@pytest.fixture
def plain_dir(tmp_path: Path) -> Path:
    """A directory that is not inside any git repository."""
    if approval._find_enclosing_git_root(str(tmp_path)) is not None:
        pytest.skip("pytest tmp_path is itself inside a git repository")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "file.txt").write_text("hi\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=x\n", encoding="utf-8")
    (root / "sub").mkdir()
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git_init(root)
    (root / ".gitignore").write_text(".env\nignored-dir/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("hello\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (root / "ignored-dir").mkdir()
    return root


# ---------------------------------------------------------------------------
# Not inside any repo: under an approved root is enough
# ---------------------------------------------------------------------------


def test_non_repo_descendants_are_auto_approved(plain_dir: Path) -> None:
    assert not _needs("read_text_file", {"path": "file.txt"}, plain_dir)
    assert not _needs("read_text_file", {"path": ".env"}, plain_dir)
    assert not _needs("line_reader", {"path": "file.txt"}, plain_dir)
    assert not _needs("list_dir", {"path": "sub"}, plain_dir)
    assert not _needs("read_text_file", {"path": "missing/new.txt"}, plain_dir)


def test_non_repo_outside_roots_still_asks(plain_dir: Path) -> None:
    outside = plain_dir.parent / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    assert _needs("read_text_file", {"path": str(outside)}, plain_dir)
    assert _needs("read_text_file", {"path": "../outside.txt"}, plain_dir)


def test_stray_gitignore_above_non_repo_is_not_consulted(plain_dir: Path) -> None:
    (plain_dir.parent / ".gitignore").write_text("file.txt\n", encoding="utf-8")
    assert not _needs("read_text_file", {"path": "file.txt"}, plain_dir)


def test_existing_file_in_non_repo_now_matches_write_tools(plain_dir: Path) -> None:
    # Previously an existing file asked while a new file did not.
    args = {"path": "file.txt", "content": "x"}
    assert not _needs("write_text_file", args, plain_dir, "auto-accept-edits")


# ---------------------------------------------------------------------------
# Inside a repo: git decides
# ---------------------------------------------------------------------------


def test_repo_tracked_vs_ignored(repo: Path) -> None:
    assert not _needs("read_text_file", {"path": "tracked.txt"}, repo)
    assert _needs("read_text_file", {"path": ".env"}, repo)
    assert _needs("list_dir", {"path": "ignored-dir"}, repo)


def test_repo_new_path_under_missing_dir_uses_nearest_existing_ancestor(
    repo: Path,
) -> None:
    # git -C on the missing directory used to fail (exit 128) and be read as
    # "not ignored".
    assert _needs("read_text_file", {"path": "ignored-dir/new/x.txt"}, repo)
    assert not _needs("read_text_file", {"path": "new-dir/deeper/x.txt"}, repo)


def test_nested_repo_under_non_repo_cwd(plain_dir: Path) -> None:
    nested = plain_dir / "project"
    nested.mkdir()
    _git_init(nested)
    (nested / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    (nested / "secret.txt").write_text("x\n", encoding="utf-8")
    (nested / "code.py").write_text("x\n", encoding="utf-8")
    assert _needs("read_text_file", {"path": "project/secret.txt"}, plain_dir)
    assert not _needs("read_text_file", {"path": "project/code.py"}, plain_dir)


def test_git_metadata_always_asks(repo: Path) -> None:
    assert _needs("list_dir", {"path": ".git"}, repo)
    assert _needs("read_text_file", {"path": ".git/config"}, repo)


@pytest.mark.parametrize("exc", [FileNotFoundError("git"), ToolTimeoutError("git", 5)])
def test_git_unavailable_or_stalled_asks(
    repo: Path, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    def _raise(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(approval, "run_command", _raise)
    assert _needs("read_text_file", {"path": "tracked.txt"}, repo)
    assert _needs("list_dir", {"path": "ignored-dir"}, repo)


# ---------------------------------------------------------------------------
# search_filesystem_by_regex with use_gitignore=false
# ---------------------------------------------------------------------------


def test_search_without_gitignore_asks_for_directories(repo: Path) -> None:
    assert not _needs("search_filesystem_by_regex", {"pattern": "x"}, repo)
    assert _needs(
        "search_filesystem_by_regex", {"pattern": "x", "use_gitignore": False}, repo
    )
    assert _needs(
        "search_filesystem_by_regex",
        {"pattern": "x", "path": ".", "use_gitignore": False},
        repo,
    )
    # A single file is fully covered by the normal path check.
    assert not _needs(
        "search_filesystem_by_regex",
        {"pattern": "x", "path": "tracked.txt", "use_gitignore": False},
        repo,
    )
    assert not _needs(
        "search_filesystem_by_regex",
        {"pattern": "x", "use_gitignore": False},
        repo,
        "full-auto",
    )
