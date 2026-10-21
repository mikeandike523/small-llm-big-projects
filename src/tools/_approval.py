from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.tools._subprocess import run_command
from src.utils.exceptions import ToolTimeoutError
from src.utils.approval_modes import (
    APPROVAL_MODE_AUTO_ACCEPT_EDITS,
    APPROVAL_MODE_DEFAULT,
    APPROVAL_MODE_FULL_AUTO,
)

_APPROVAL_CMD_TIMEOUT = 5  # seconds; deny approval if git commands stall


@dataclass(frozen=True)
class ApprovalContext:
    """Context required for approval-time path checks."""

    session_init_working_dir: str | None = None
    session_current_working_dir: str | None = None

    @classmethod
    def from_special_resources(
        cls, special_resources: dict | None
    ) -> "ApprovalContext":
        sr = special_resources or {}
        return cls(
            session_init_working_dir=sr.get("session_init_working_dir"),
            session_current_working_dir=sr.get("session_current_working_dir"),
        )


def get_approval_mode(special_resources: dict | None) -> str:
    sr = special_resources or {}
    mode = sr.get("approval_mode")
    return mode if isinstance(mode, str) and mode else APPROVAL_MODE_DEFAULT


def is_auto_accept_edits(special_resources: dict | None) -> bool:
    return get_approval_mode(special_resources) == APPROVAL_MODE_AUTO_ACCEPT_EDITS


def is_full_auto(special_resources: dict | None) -> bool:
    return get_approval_mode(special_resources) == APPROVAL_MODE_FULL_AUTO


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
#
# Policy for a path that is already inside an approved root
# (full write-up: general-notes/file-access-approval-policy.md):
#
#   * Inside .git/ (or the .git entry itself) -> ask. Git's own metadata is
#     never "part of the project", and git does not report it as ignored.
#   * Inside a git repo -> git decides. Tracked, or untracked but not ignored,
#     is auto-approved; ignored asks.
#   * Not inside any git repo -> auto-approved. Being under a session CWD is
#     enough. Stray .gitignore files above a non-repo directory are
#     deliberately NOT consulted for approval (the listing tools may still
#     use them to filter output — that is noise reduction, not permission).
#   * Git cannot give a clear answer (git missing, timeout, "dubious
#     ownership", unexpected exit code) -> ask.
# ---------------------------------------------------------------------------


def _nearest_existing_dir(path: str) -> str:
    """Closest directory at or above path that exists on disk.

    git -C fails with "cannot change to ..." (exit 128) when the directory is
    missing, so a not-yet-created path such as ignored-dir/new/file.txt must
    be checked from its nearest existing ancestor. Without this, that failure
    used to be misread as "not ignored" and auto-approved the path.
    """
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return d or "."


def _find_enclosing_git_root(start_dir: str) -> str | None:
    """Walk up from start_dir to the drive root; return the first directory
    holding a .git entry, or None if there is none.

    The .git entry may be a directory (normal repo) or a file (worktree,
    submodule). This walk — rather than git's exit code — is what decides
    "not a repo": git exits 128 both for "not a git repository" and for real
    failures like dubious ownership, and its message text is localized, so
    the exit code alone cannot safely tell the two apart.
    """
    p = Path(start_dir)
    while True:
        if (p / ".git").exists():
            return str(p)
        if p.parent == p:  # reached the drive root
            return None
        p = p.parent


def _is_git_metadata_path(resolved: str) -> bool:
    """True for the .git entry itself or anything inside a .git directory."""
    return any(part.casefold() == ".git" for part in Path(resolved).parts)


def _run_git(args: list[str], git_cwd: str):
    """Run a git command for an approval check; None means "no clear answer".

    Timeouts (run_command raises ToolTimeoutError, not TimeoutExpired) and a
    missing git executable (OSError) both map to None, which callers treat
    as "ask the user".
    """
    try:
        return run_command(["git", "-C", git_cwd, *args], timeout=_APPROVAL_CMD_TIMEOUT)
    except (ToolTimeoutError, OSError):
        return None


def _git_path_needs_approval(resolved: str, git_cwd: str) -> bool:
    """Ask git whether an in-repo path is ignored. True means ask the user."""
    if os.path.isdir(resolved) or not os.path.exists(resolved):
        # Directories and not-yet-existing paths: ls-files lists neither, so
        # use check-ignore, which matches patterns without needing the file.
        # Exit 0 = ignored, 1 = not ignored, anything else = git error.
        r = _run_git(["check-ignore", "-q", "--", resolved], git_cwd)
        return r is None or r.returncode != 1
    # Existing file: ls-files prints the path iff it is tracked, or untracked
    # but not ignored. Empty output or a git error means ask.
    r = _run_git(
        ["ls-files", "--cached", "--others", "--exclude-standard", "--", resolved],
        git_cwd,
    )
    return r is None or r.returncode != 0 or not r.stdout.strip()


# ---------------------------------------------------------------------------
# Public approval API
# ---------------------------------------------------------------------------


def file_needs_approval(
    args: dict, path_arg: str = "path", *, ctx: ApprovalContext
) -> bool:
    """Convenience wrapper: approval check for a single path argument."""
    return needs_path_approval(args.get(path_arg), ctx=ctx)


def needs_path_approval(raw_path: str | None, *, ctx: ApprovalContext) -> bool:
    """Core approval check for a path argument.

    Returns False (auto-approved) when the resolved path is within the
    session's current CWD or initial CWD, and either is not inside any git
    repository or is not git-ignored by its (nearest) repository.

    Returns True (approval required) for:
    - Paths outside both approved roots
    - Git-ignored files/directories within an approved root
    - .git metadata, and paths git cannot give a clear answer for

    Security properties:
    - Path traversal: _resolve() calls Path.resolve() which normalises ..
      after following symlinks, so ../../../etc/passwd tricks are caught.
    - Symlink attacks: _resolve() follows all symlinks to the real target;
      a symlink pointing outside an approved root resolves to its real path
      which then fails the root check.
    - Git command injection: paths passed as list args (no shell=True).
    - Timeout safety: git commands that stall require approval after 5 seconds.
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
    if (current_cwd and resolved == current_cwd) or (init_cwd and resolved == init_cwd):
        return False

    if _is_git_metadata_path(resolved):
        return True

    # Run git from the target's own (nearest existing) directory so it finds
    # the target's repo — including a repo nested below a non-repo CWD — not
    # the server process CWD's repo.
    git_cwd = _nearest_existing_dir(resolved)
    if _find_enclosing_git_root(git_cwd) is None:
        return False  # not in any repo: under an approved root is enough

    return _git_path_needs_approval(resolved, git_cwd)
