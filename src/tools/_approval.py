from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.tools._subprocess import run_command

_APPROVAL_CMD_TIMEOUT = 5  # seconds; deny approval if git commands stall

@dataclass(frozen=True)
class ApprovalContext:
    """Context required for approval-time path checks."""

    session_init_working_dir: str | None = None
    session_current_working_dir: str | None = None

    @classmethod
    def from_special_resources(cls, special_resources: dict | None) -> "ApprovalContext":
        sr = special_resources or {}
        return cls(
            session_init_working_dir=sr.get("session_init_working_dir"),
            session_current_working_dir=sr.get("session_current_working_dir"),
        )


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _get_session_init_cwd(ctx: ApprovalContext) -> str | None:
    """The session's initial CWD — always an approved root."""
    cwd = ctx.session_init_working_dir
    return str(Path(cwd).resolve()) if cwd else None


def _get_session_current_cwd(ctx: ApprovalContext) -> str | None:
    """The session's current CWD — used as an approved root for path checks.

    Tracks change_pwd calls; falls back to the session's initial CWD.
    Never falls back to os.getcwd() — that is the server process CWD and
    must never be treated as an approved root.
    """
    cwd = ctx.session_current_working_dir
    if cwd:
        return str(Path(cwd).resolve())
    return _get_session_init_cwd(ctx)


def _get_effective_cwd(ctx: ApprovalContext) -> str:
    """CWD used for anchoring relative paths in _resolve().

    Raises if neither the session's current CWD nor its initial CWD is set —
    this prevents the server process CWD from silently becoming the resolution
    base and potentially leaking paths into approval checks.
    """
    cwd = _get_session_current_cwd(ctx)
    if cwd:
        return cwd
    raise RuntimeError(
        "No session CWD is set for this approval check. "
        "special_resources with session working-directory context must be passed "
        "before resolving paths (via check_needs_approval)."
    )


def _resolve(raw_path: str, *, ctx: ApprovalContext) -> str:
    """Resolve a path to an absolute string, following all symlinks.

    Symlink resolution guards against symlink-based traversal attacks: a
    symlink pointing outside the approved root resolves to the target's real
    path, which then fails the _is_under_any_approved_root check.
    """
    p = (
        Path(raw_path)
        if os.path.isabs(raw_path)
        else Path(os.path.join(_get_effective_cwd(ctx), raw_path))
    )
    return str(p.resolve())


def _is_under(resolved: str, root: str) -> bool:
    try:
        Path(resolved).relative_to(root)
        return True
    except ValueError:
        return False


def _is_under_any_approved_root(resolved: str, *, ctx: ApprovalContext) -> bool:
    """True if resolved is under the session's current CWD or initial CWD.

    Both roots are always approved so the agent is not locked out after
    change_pwd, while still scoping free access to the project.
    """
    current = _get_session_current_cwd(ctx)
    if current and _is_under(resolved, current):
        return True
    init = _get_session_init_cwd(ctx)
    if init and init != current and _is_under(resolved, init):
        return True
    return False


def _is_under_cwd(resolved: str, *, ctx: ApprovalContext) -> bool:
    """Alias for _is_under_any_approved_root — kept for backward compatibility."""
    return _is_under_any_approved_root(resolved, ctx=ctx)


def is_path_in_scope(raw_path: str | None, *, ctx: ApprovalContext) -> bool:
    """Return True if raw_path resolves to a location within an approved session root.

    Unlike needs_path_approval, does NOT apply git-ignore filtering — suitable
    for read-only directory listing tools that handle ignore logic themselves.
    Returns False (out of scope) when no session CWD is set or path is outside roots.
    """
    if not raw_path:
        return True  # no path → operates on cwd → in scope
    try:
        return _is_under_any_approved_root(_resolve(raw_path, ctx=ctx), ctx=ctx)
    except RuntimeError:
        return False  # no session CWD set → treat as out of scope


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_cwd_for(path: str) -> str:
    """Directory to run git commands from so git finds the right repository.

    Uses the file's own directory via git -C so git discovers the .git root
    relative to the target, not relative to os.getcwd() — which may be a
    different directory after change_pwd.
    """
    d = path if os.path.isdir(path) else os.path.dirname(path)
    return d if d else "."


def _git_file_is_included(resolved: str) -> bool:
    """True if the file is tracked or untracked+non-ignored (auto-approve)."""
    git_cwd = _git_cwd_for(resolved)
    try:
        r = run_command(
            [
                "git", "-C", git_cwd,
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                resolved,
            ],
            timeout=_APPROVAL_CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False  # deny on timeout (safer than hanging)
    return bool(r.stdout.strip())


def _git_dir_is_ignored(resolved: str) -> bool:
    """True if git considers this directory ignored."""
    git_cwd = _git_cwd_for(resolved)
    try:
        r = run_command(
            ["git", "-C", git_cwd, "check-ignore", "-q", "--", resolved],
            timeout=_APPROVAL_CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return True  # deny on timeout (safer than hanging)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Public approval API
# ---------------------------------------------------------------------------


def file_needs_approval(args: dict, path_arg: str = "path", *, ctx: ApprovalContext) -> bool:
    """Convenience wrapper: approval check for a single path argument."""
    return needs_path_approval(args.get(path_arg), ctx=ctx)


def needs_path_approval(raw_path: str | None, *, ctx: ApprovalContext) -> bool:
    """Core approval check for a path argument.

    Returns False (auto-approved) when the resolved path is within the
    session's current CWD or initial CWD, and is not git-ignored.

    Returns True (approval required) for:
    - Paths outside both approved roots
    - Git-ignored files/directories within an approved root

    Security properties:
    - Path traversal: _resolve() calls Path.resolve() which normalises ..
      after following symlinks, so ../../../etc/passwd tricks are caught.
    - Symlink attacks: _resolve() follows all symlinks to the real target;
      a symlink pointing outside an approved root resolves to its real path
      which then fails the root check.
    - Git command injection: paths passed as list args (no shell=True).
    - Timeout safety: git commands that stall deny approval after 5 seconds.
    """
    if not raw_path:
        return False

    resolved = _resolve(raw_path, ctx=ctx)

    if not _is_under_any_approved_root(resolved, ctx=ctx):
        return True

    # Within an approved root — still block git-ignored paths.
    # The root directories themselves are always approved.
    current_cwd = _get_session_current_cwd(ctx)
    init_cwd = _get_session_init_cwd(ctx)
    if (current_cwd and resolved == current_cwd) or (
        init_cwd and resolved == init_cwd
    ):
        return False

    if os.path.isdir(resolved):
        return _git_dir_is_ignored(resolved)
    elif not os.path.exists(resolved):
        # File does not exist — git ls-files returns nothing for non-existent paths,
        # making _git_file_is_included return False and triggering a false approval
        # requirement. Use check-ignore instead: it evaluates gitignore patterns
        # against the path without requiring the file to be present on disk.
        return _git_dir_is_ignored(resolved)
    else:
        return not _git_file_is_included(resolved)
