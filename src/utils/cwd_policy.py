"""Validation for a new session's initial working directory.

The session cwd matters for more than convenience: with no git repo, path
approval auto-approves everything beneath it. So a cwd is classified as:

- ``ok``      -- usable as is.
- ``error``   -- never allowed (missing, not a folder, filesystem root, ...).
- ``warning`` -- needs explicit confirmation before use, for one or both of:
                 ``privileged`` (privileged / not recommended; "Proceed with
                 caution") and ``missing`` (the folder does not exist yet but
                 its parent does; "Create folder"). Only ONE missing level is
                 ever offered -- a missing parent is a hard error, which
                 guards against typos creating whole directory chains.

The per-OS directory lists below are the single source of truth for which
folders are hard errors and which are warnings. Each entry is
``(path, match_mode)``:

- ``MATCH_EXACT``   -- only that folder itself (``/home`` but not ``/home/me``).
- ``MATCH_SUBTREE`` -- that folder and everything beneath it.

Paths may start with ``~`` (the server user's home) and, on Windows, use
``%VAR%`` environment variables. ``FILESYSTEM_ROOT`` matches any root
(``/``, ``C:\\``, ...).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.utils.session_dirs import get_session_workspace_dir, is_valid_session_id

MATCH_EXACT = "exact"
MATCH_SUBTREE = "subtree"
FILESYSTEM_ROOT = "<filesystem-root>"

DirRule = tuple[str, str]

HARD_ERROR_DIRS_LINUX: tuple[DirRule, ...] = (
    (FILESYSTEM_ROOT, MATCH_EXACT),
    ("/proc", MATCH_SUBTREE),
    ("/sys", MATCH_SUBTREE),
    ("/dev", MATCH_SUBTREE),
    ("/boot", MATCH_SUBTREE),
    ("/run", MATCH_SUBTREE),
)

WARNING_DIRS_LINUX: tuple[DirRule, ...] = (
    ("~", MATCH_EXACT),
    ("~/.ssh", MATCH_SUBTREE),
    ("~/.gnupg", MATCH_SUBTREE),
    ("~/.aws", MATCH_SUBTREE),
    ("/home", MATCH_EXACT),
    ("/root", MATCH_SUBTREE),
    ("/etc", MATCH_SUBTREE),
    ("/usr", MATCH_SUBTREE),
    ("/bin", MATCH_SUBTREE),
    ("/sbin", MATCH_SUBTREE),
    ("/lib", MATCH_SUBTREE),
    ("/lib32", MATCH_SUBTREE),
    ("/lib64", MATCH_SUBTREE),
    ("/snap", MATCH_SUBTREE),
    ("/var", MATCH_EXACT),
    ("/var/lib", MATCH_SUBTREE),
    ("/var/log", MATCH_SUBTREE),
    ("/var/cache", MATCH_SUBTREE),
    ("/opt", MATCH_EXACT),
    ("/srv", MATCH_EXACT),
    ("/mnt", MATCH_EXACT),
    ("/media", MATCH_EXACT),
    ("/tmp", MATCH_EXACT),
)

HARD_ERROR_DIRS_MACOS: tuple[DirRule, ...] = (
    (FILESYSTEM_ROOT, MATCH_EXACT),
    ("/dev", MATCH_SUBTREE),
    ("/System", MATCH_SUBTREE),
)

WARNING_DIRS_MACOS: tuple[DirRule, ...] = (
    ("~", MATCH_EXACT),
    ("~/Library", MATCH_SUBTREE),
    ("~/.ssh", MATCH_SUBTREE),
    ("~/.gnupg", MATCH_SUBTREE),
    ("~/.aws", MATCH_SUBTREE),
    ("/Users", MATCH_EXACT),
    ("/Applications", MATCH_SUBTREE),
    ("/Library", MATCH_SUBTREE),
    ("/private", MATCH_SUBTREE),
    ("/etc", MATCH_SUBTREE),
    ("/usr", MATCH_SUBTREE),
    ("/bin", MATCH_SUBTREE),
    ("/sbin", MATCH_SUBTREE),
    ("/var", MATCH_SUBTREE),
    ("/tmp", MATCH_SUBTREE),
    ("/opt", MATCH_EXACT),
    ("/Volumes", MATCH_EXACT),
)

HARD_ERROR_DIRS_WINDOWS: tuple[DirRule, ...] = ((FILESYSTEM_ROOT, MATCH_EXACT),)

WARNING_DIRS_WINDOWS: tuple[DirRule, ...] = (
    ("~", MATCH_EXACT),
    ("~/AppData", MATCH_SUBTREE),
    ("~/.ssh", MATCH_SUBTREE),
    ("~/.aws", MATCH_SUBTREE),
    ("%SystemDrive%/Users", MATCH_EXACT),
    ("%SystemRoot%", MATCH_SUBTREE),
    ("%ProgramFiles%", MATCH_SUBTREE),
    ("%ProgramFiles(x86)%", MATCH_SUBTREE),
    ("%ProgramData%", MATCH_SUBTREE),
)

PRIVILEGED_CWD_WARNING = (
    "Path is privileged or not recommended for use. Consider using a more "
    "traditional path such as your home directory."
)

OsFamily = Literal["linux", "macos", "windows"]
CheckStatus = Literal["ok", "warning", "error"]


@dataclass(frozen=True)
class CwdCheck:
    status: CheckStatus
    # Absolute, forward-slash path the session should store (None on error).
    resolved_path: str | None = None
    # Error text for ``error``; the standard warning for ``warning``.
    message: str | None = None
    # Which rule triggered a warning/error, e.g. "/etc (and everything inside)".
    reason: str | None = None
    # ``warning`` only: the folder must be created (its parent exists).
    missing: bool = False
    # ``warning`` only: the folder matched a WARNING_DIRS_* rule.
    privileged: bool = False

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "resolved_path": self.resolved_path,
            "message": self.message,
            "reason": self.reason,
            "missing": self.missing,
            "privileged": self.privileged,
        }


def current_os_family() -> OsFamily:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def rules_for(family: OsFamily) -> tuple[tuple[DirRule, ...], tuple[DirRule, ...]]:
    """Return ``(hard_error_rules, warning_rules)`` for an OS family."""
    if family == "windows":
        return HARD_ERROR_DIRS_WINDOWS, WARNING_DIRS_WINDOWS
    if family == "macos":
        return HARD_ERROR_DIRS_MACOS, WARNING_DIRS_MACOS
    return HARD_ERROR_DIRS_LINUX, WARNING_DIRS_LINUX


def _portable(path: str) -> str:
    text = path.replace("\\", "/")
    # Keep a bare root ("/" or "C:/") intact; strip any other trailing slash.
    if len(text) > 1 and text.endswith("/") and not text.endswith(":/"):
        text = text.rstrip("/")
    return text


def _comparable(path: str, family: OsFamily) -> str:
    text = _portable(path)
    # Windows and default macOS filesystems are case-insensitive.
    return text.casefold() if family in ("windows", "macos") else text


def _expand_rule_path(rule_path: str, home: str) -> str | None:
    if rule_path == "~" or rule_path.startswith("~/"):
        return home + rule_path[1:] if home else None
    expanded = os.path.expandvars(rule_path)
    # An unset %VAR% stays literal; such a rule cannot match anything.
    if "%" in expanded or "$" in expanded:
        return None
    return expanded


def _is_filesystem_root(path: str) -> bool:
    p = Path(path)
    return p.parent == p


def _match_rule(
    candidates: list[str], rules: tuple[DirRule, ...], family: OsFamily, home: str
) -> str | None:
    """Return a human-readable description of the first matching rule."""
    for rule_path, mode in rules:
        if rule_path == FILESYSTEM_ROOT:
            if any(_is_filesystem_root(c) for c in candidates):
                return "the filesystem root"
            continue
        expanded = _expand_rule_path(rule_path, home)
        if expanded is None:
            continue
        target = _comparable(expanded, family)
        for candidate in candidates:
            cmp = _comparable(candidate, family)
            if cmp == target:
                return rule_path
            if mode == MATCH_SUBTREE and cmp.startswith(target + "/"):
                return f"{rule_path} (and everything inside it)"
    return None


def _has_control_chars(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def _home_or_none() -> str | None:
    try:
        return _portable(str(Path.home()))
    except (RuntimeError, KeyError, OSError):
        return None


def check_initial_cwd(
    raw: object,
    session_id: str | None = None,
    family: OsFamily | None = None,
) -> CwdCheck:
    """Classify a requested session cwd as ok / warning / error.

    ``session_id`` exempts that session's own (not yet created) workspace
    folder from the existence check -- it is created when the session starts.
    """
    family = family or current_os_family()
    if not isinstance(raw, str) or not raw.strip():
        return CwdCheck("error", message="Working directory is required.")
    text = raw.strip()
    if _has_control_chars(text):
        return CwdCheck(
            "error", message="Working directory contains invalid characters."
        )

    home = _home_or_none()
    if text == "~" or text.startswith(("~/", "~\\")):
        if home is None:
            return CwdCheck(
                "error", message="Could not determine the server's home directory."
            )
        text = home + text[1:]

    portable = _portable(text)
    if family == "windows" and portable.startswith("//"):
        return CwdCheck(
            "error",
            message="Network (UNC) paths are not allowed as a working directory.",
        )
    if not os.path.isabs(text):
        return CwdCheck("error", message="Working directory must be an absolute path.")

    normalized = _portable(os.path.normpath(text))

    if session_id and is_valid_session_id(session_id):
        workspace = get_session_workspace_dir(session_id)
        if _comparable(normalized, family) == _comparable(workspace, family):
            if os.path.exists(normalized) and not os.path.isdir(normalized):
                return CwdCheck("error", message="Path is not a directory.")
            return CwdCheck("ok", resolved_path=workspace)

    missing = False
    try:
        resolved = Path(normalized).resolve(strict=True)
    except FileNotFoundError:
        parent_check = _check_missing_parent(Path(normalized))
        if isinstance(parent_check, CwdCheck):
            return parent_check
        resolved, missing = parent_check, True
    except (OSError, RuntimeError):
        return CwdCheck("error", message="Path could not be resolved.")
    if not missing:
        if not resolved.is_dir():
            return CwdCheck("error", message="Path is not a directory.")
        if not os.access(resolved, os.R_OK | os.X_OK):
            return CwdCheck("error", message="Directory is not readable by the server.")

    resolved_text = _portable(str(resolved))
    candidates = (
        [normalized] if normalized == resolved_text else [normalized, resolved_text]
    )
    hard_rules, warning_rules = rules_for(family)
    rule_home = home or ""

    hard = _match_rule(candidates, hard_rules, family, rule_home)
    if hard:
        return CwdCheck(
            "error",
            message=f"This folder cannot be used as a working directory: {hard}.",
            reason=hard,
        )
    warning = _match_rule(candidates, warning_rules, family, rule_home)
    if warning or missing:
        return CwdCheck(
            "warning",
            resolved_path=resolved_text,
            message=PRIVILEGED_CWD_WARNING if warning else None,
            reason=warning,
            missing=missing,
            privileged=bool(warning),
        )
    return CwdCheck("ok", resolved_path=resolved_text)


def _check_missing_parent(path: Path) -> Path | CwdCheck:
    """For a cwd that does not exist: its would-be resolved path when exactly
    one folder is missing and the server can create it, else a hard error."""
    parent = path.parent
    try:
        resolved_parent = parent.resolve(strict=True)
    except FileNotFoundError:
        return CwdCheck(
            "error",
            message=(
                f"Folder does not exist, and neither does its parent "
                f"({_portable(str(parent))}). Only one new folder can be created "
                "-- check the path for typos."
            ),
        )
    except (OSError, RuntimeError):
        return CwdCheck("error", message="Path could not be resolved.")
    if not resolved_parent.is_dir():
        return CwdCheck(
            "error",
            message=f"Parent path is not a folder: {_portable(str(parent))}.",
        )
    if not os.access(resolved_parent, os.W_OK | os.X_OK):
        return CwdCheck(
            "error",
            message=(
                "Folder does not exist, and the server cannot create it in "
                f"{_portable(str(resolved_parent))} (no write permission)."
            ),
        )
    return resolved_parent / path.name
