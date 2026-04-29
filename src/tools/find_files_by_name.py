"""
Find files whose names match one or more glob patterns.
Fills the tool gap for `find -name`-style file discovery.

Reuses list_working_tree's git ls-files plumbing (with gitignore support),
falling back to list_dir._traverse when outside a git repo.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import time

from src.tools._subprocess import run_command
from src.utils.exceptions import ToolTimeoutError

DEFAULT_TIMEOUT = 15  # seconds

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "find_files_by_name",
        "description": (
            "Search for files whose names match one or more glob patterns (not regex). "
            "By default matches against the filename only. "
            "Use search_filesystem_by_regex to search inside file contents instead. "
            "By default respects .gitignore (same as list_working_tree). "
            "Falls back to a full recursive scan when outside a git repository."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One or more glob patterns (*, ?, [...]) to match against filenames. "
                        "A file is included if it matches ANY pattern (OR semantics). "
                        "Case-insensitive by default. "
                        "Examples: [\"*auth*\"], [\"*.env\"], [\"*login*\", \"*signup*\"]."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Root directory to search from. "
                        "Accepts relative (to cwd) or absolute paths. "
                        "Defaults to the current working directory."
                    ),
                },
                "use_gitignore": {
                    "type": "boolean",
                    "description": (
                        "If true (default), use git ls-files to enumerate files so that "
                        ".gitignore rules are respected automatically. "
                        "Set to false to scan all files regardless of gitignore rules."
                    ),
                },
                "partial_match": {
                    "type": "boolean",
                    "description": (
                        "Controls whether patterns must match the full segment or anywhere within it. "
                        "In glob mode: if true, plain words (no glob chars) are auto-wrapped as *word*; "
                        "patterns already containing *, ?, or [ are left as-is. "
                        "In regex mode: if false (default), ^ and $ are auto-appended so the pattern "
                        "must match the full segment; if true, re.search is used as-is. "
                        "Default: false."
                    ),
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": (
                        "If true, pattern matching is case-sensitive. "
                        "Default: false (case-insensitive)."
                    ),
                },
                "match_any_dir": {
                    "type": "boolean",
                    "description": (
                        "If true, match patterns against every segment of the relative path "
                        "(directory names and filename). A file is included if any segment matches. "
                        "Useful for finding files inside directories whose names match the pattern, "
                        "e.g. everything under any 'auth' folder. "
                        "Default: false (filename only)."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["glob", "regex"],
                    "description": (
                        "Pattern matching mode. "
                        "'glob' (default): patterns use glob syntax (*, ?, [...]); "
                        "partial_match wrapping applies. "
                        "'regex': patterns are Python regular expressions; "
                        "re.search is used so the pattern matches anywhere in the segment "
                        "(partial_match has no effect in this mode)."
                    ),
                },
            },
            "required": ["patterns"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    raw = args.get("path")
    if not raw:
        return False
    from src.tools._approval import _resolve, _is_under_cwd
    return not _is_under_cwd(_resolve(raw))


# ---------------------------------------------------------------------------
# File collection helpers
# ---------------------------------------------------------------------------

def _collect_files_git(root: str) -> list[str] | None:
    """
    Return absolute paths of all files under root via git ls-files.
    Returns None if root is not inside a git repository.
    Mirrors list_working_tree's plumbing exactly.
    """
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", root]
    try:
        result = run_command(cmd, timeout=DEFAULT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ToolTimeoutError("find_files_by_name", DEFAULT_TIMEOUT)

    if not result.success:
        if "not a git repository" in result.stderr.lower() or result.returncode == 128:
            return None
        return None  # any other git error — fall back to traverse

    cwd = os.getcwd()
    abs_paths: list[str] = []
    for line in result.stdout.splitlines():
        if line:
            abs_paths.append(os.path.normpath(os.path.join(cwd, line)))
    return abs_paths


def _collect_files_traverse(root: str, use_gitignore: bool) -> list[str]:
    """
    Return absolute paths of all files under root using list_dir._traverse.
    Reuses list_dir's gitignore machinery when use_gitignore=True.
    """
    from src.tools.list_dir import (
        _traverse,
        _find_gitignore_root,
        _get_ancestor_matchers,
        _get_effective_matchers,
        _collect_flat,
    )

    ancestor_matchers: list = []
    if use_gitignore:
        gitignore_root = _find_gitignore_root(root)
        ancestor_matchers = _get_ancestor_matchers(gitignore_root, root)
    effective_matchers = _get_effective_matchers(root, ancestor_matchers, use_gitignore)

    start = time.monotonic()
    children = _traverse(
        dir_path=root,
        recursive=True,
        follow_folder_symlinks=False,
        follow_file_symlinks=False,
        depth=None,
        visited_dirs={os.path.realpath(root)},
        matchers=effective_matchers,
        use_gitignore=use_gitignore,
        start_time=start,
        timeout=DEFAULT_TIMEOUT,
    )

    flat: list = []
    _collect_flat(children, "", "files", flat)
    # flat is [(rel_path_fwd_slash, entry), ...]
    return [os.path.normpath(os.path.join(root, rel)) for rel, _ in flat]


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _prepare_glob_patterns(patterns: list[str], partial_match: bool, case_sensitive: bool) -> list[str]:
    """
    Apply partial_match wrapping and case normalisation for glob mode.
    Uses fnmatchcase internally — case-insensitivity is achieved by lowercasing
    both pattern and target, which is platform-consistent.
    """
    result: list[str] = []
    for p in patterns:
        if partial_match and not any(c in p for c in ("*", "?", "[")):
            p = f"*{p}*"
        result.append(p if case_sensitive else p.lower())
    return result


def _compile_regex_patterns(patterns: list[str], case_sensitive: bool, partial_match: bool) -> list[re.Pattern]:
    """
    Compile raw regex strings into pattern objects.
    If partial_match=False, anchors each pattern with ^ and $ (unless already present)
    so it must match the full segment — equivalent to re.fullmatch semantics.
    If partial_match=True, patterns are left as-is and re.search finds them anywhere.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = []
    for p in patterns:
        if not partial_match:
            if not p.startswith("^"):
                p = "^" + p
            if not p.endswith("$"):
                p = p + "$"
        try:
            compiled.append(re.compile(p, flags))
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern {p!r}: {exc}") from exc
    return compiled


def _segment_matches_glob(rel_path: str, patterns: list[str], case_sensitive: bool, match_any_dir: bool) -> bool:
    segments = rel_path.split("/")
    targets = segments if match_any_dir else [segments[-1]]
    for seg in targets:
        s = seg if case_sensitive else seg.lower()
        if any(fnmatch.fnmatchcase(s, pat) for pat in patterns):
            return True
    return False


def _segment_matches_regex(rel_path: str, compiled: list[re.Pattern], match_any_dir: bool) -> bool:
    segments = rel_path.split("/")
    targets = segments if match_any_dir else [segments[-1]]
    for seg in targets:
        if any(rx.search(seg) for rx in compiled):
            return True
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute(args: dict, _session_data: dict = {}) -> str:
    raw_patterns: list[str] = args.get("patterns") or []
    path: str = args.get("path") or os.getcwd()
    use_gitignore: bool = bool(args.get("use_gitignore", True))
    partial_match: bool = bool(args.get("partial_match", False))
    case_sensitive: bool = bool(args.get("case_sensitive", False))
    match_any_dir: bool = bool(args.get("match_any_dir", False))
    mode: str = args.get("mode", "glob")

    if not raw_patterns:
        return "Error: at least one pattern is required."

    root = os.path.abspath(path)
    if not os.path.isdir(root):
        return f"Error: {root!r} is not a directory."

    # Prepare patterns for the chosen mode
    if mode == "regex":
        try:
            compiled_patterns = _compile_regex_patterns(raw_patterns, case_sensitive, partial_match)
        except ValueError as exc:
            return f"Error: {exc}"
        glob_patterns = None
    else:
        glob_patterns = _prepare_glob_patterns(raw_patterns, partial_match, case_sensitive)
        compiled_patterns = None

    # Collect candidate file paths
    if use_gitignore:
        abs_files = _collect_files_git(root)
        if abs_files is None:
            abs_files = _collect_files_traverse(root, use_gitignore=True)
    else:
        abs_files = _collect_files_traverse(root, use_gitignore=False)

    # Filter by pattern
    matches: list[str] = []
    for abs_path in abs_files:
        rel = os.path.relpath(abs_path, root).replace("\\", "/")
        if mode == "regex":
            hit = _segment_matches_regex(rel, compiled_patterns, match_any_dir)
        else:
            hit = _segment_matches_glob(rel, glob_patterns, case_sensitive, match_any_dir)
        if hit:
            matches.append(rel)

    if not matches:
        pats = ", ".join(repr(p) for p in raw_patterns)
        return f"No files found matching: {pats}"

    matches.sort()
    return "\n".join(matches)
