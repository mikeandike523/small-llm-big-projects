from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.tools._subprocess import run_command

_APPROVAL_CMD_TIMEOUT = 5  # seconds; deny approval if git commands stall


def _resolve(raw_path: str) -> str:
    """Resolve a raw path (absolute or relative-to-cwd) to an absolute string."""
    if os.path.isabs(raw_path):
        return str(Path(raw_path).resolve())
    return str(Path(os.path.join(os.getcwd(), raw_path)).resolve())


def _is_under_cwd(resolved: str) -> bool:
    cwd = str(Path(os.getcwd()).resolve())
    try:
        Path(resolved).relative_to(cwd)
        return True
    except ValueError:
        return False


def _git_file_is_included(resolved: str) -> bool:
    """True if the file is tracked or untracked+non-ignored (auto-approve)."""
    try:
        r = run_command(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", resolved],
            timeout=_APPROVAL_CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False  # deny approval on timeout (safer than hanging)
    return bool(r.stdout.strip())


def _git_dir_is_ignored(resolved: str) -> bool:
    """True if git considers this directory ignored."""
    try:
        r = run_command(["git", "check-ignore", "-q", "--", resolved], timeout=_APPROVAL_CMD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return True  # deny approval on timeout (safer than hanging)
    return r.returncode == 0


def file_needs_approval(args: dict, path_arg: str = "path") -> bool:
    """Convenience wrapper: approval check for a single path argument in a tool's args dict."""
    return needs_path_approval(args.get(path_arg))


def needs_path_approval(raw_path: str | None) -> bool:
    """
    Core approval check for a path argument.

    - None / empty  → refers to cwd itself → auto-approved (False)
    - Outside cwd   → True
    - Inside cwd, directory → check git check-ignore; ignored → True
    - Inside cwd, file      → check git ls-files; ignored → True
    - Inside cwd, non-ignored → False
    """
    if not raw_path:
        return False

    resolved = _resolve(raw_path)

    if not _is_under_cwd(resolved):
        return True

    cwd = str(Path(os.getcwd()).resolve())
    if resolved == cwd:
        return False

    if os.path.isdir(resolved):
        return _git_dir_is_ignored(resolved)
    else:
        return not _git_file_is_included(resolved)
