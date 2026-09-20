"""Release-notes helpers for the backend API.

Changelog/release-note data lives at <repo root>/backend-release-notes/ (see
release_manager.py). Paths are resolved against the repository root — found by
walking up from this file's directory until a .git folder is seen — never
against the process cwd, which is meaningless for the server process.
"""

from __future__ import annotations

import json
import pathlib

NOTES_DIR_NAME = "backend-release-notes"

_repo_root_cache: pathlib.Path | None = None


def find_repo_root_from(start: pathlib.Path) -> pathlib.Path | None:
    """Walk up from `start` (inclusive) until a directory containing .git is
    found. Stops at the drive/filesystem root (dir.parent == dir) or when a
    permission error prevents descending. Returns None when not found."""
    try:
        cur = start.resolve()
        while True:
            try:
                if (cur / ".git").exists():
                    return cur
            except OSError:
                pass
            parent = cur.parent
            if parent == cur:  # drive/filesystem root reached
                return None
            cur = parent
    except OSError:
        return None


def get_repo_root() -> pathlib.Path | None:
    """Cached repo root resolved from this file's location (not cwd)."""
    global _repo_root_cache
    if _repo_root_cache is None:
        _repo_root_cache = find_repo_root_from(pathlib.Path(__file__))
    return _repo_root_cache


def get_notes_dir() -> pathlib.Path | None:
    """Directory holding backend release notes, or None when unavailable."""
    root = get_repo_root()
    if root is None:
        return None
    return root / NOTES_DIR_NAME


def read_backend_version() -> str:
    """Backend version from the root package.json ("unknown" on failure)."""
    root = get_repo_root()
    if root is None:
        return "unknown"
    try:
        with open(root / "package.json", "r", encoding="utf-8") as fh:
            return json.load(fh).get("version", "unknown")
    except Exception:
        return "unknown"


def read_changelog_index() -> list[dict]:
    """Parsed changelog-index.json releases list ([] when unavailable)."""
    notes_dir = get_notes_dir()
    if notes_dir is None:
        return []
    try:
        idx = json.loads(
            (notes_dir / "changelog-index.json").read_text(encoding="utf-8")
        )
        return idx.get("releases", [])
    except Exception:
        return []


def read_release_message(version: str) -> str | None:
    """Message text for `version` from <version>.txt, or None when absent.

    `version` must be a plain X.Y.Z semver string — anything else is rejected
    to prevent path traversal."""
    if not version or not all(
        part.isdigit() for part in version.split(".")
    ) or version.count(".") != 2:
        return None
    notes_dir = get_notes_dir()
    if notes_dir is None:
        return None
    try:
        return (notes_dir / f"{version}.txt").read_text(encoding="utf-8")
    except Exception:
        return None


def latest_release_note() -> tuple[str, str]:
    """(message, date) of the newest release; ("", "") when unavailable."""
    releases = read_changelog_index()
    if not releases:
        return "", ""
    top = releases[0]
    msg = read_release_message(top.get("version", ""))
    return (msg.strip() if msg is not None else ""), top.get("date", "")
