# NOTE: No timeout is enforced on this tool.
#
# python_ripgrep invokes ripgrep via a compiled Rust extension. There is no way to interrupt
# a blocking C/Rust call from Python: ThreadPoolExecutor.future.result(timeout=N) only makes
# the *caller* give up -- the extension thread keeps running, eating CPU and RAM, until ripgrep
# finishes on its own. Worse, the ThreadPoolExecutor context manager blocks on __exit__
# (shutdown(wait=True)), so the "timeout" would not even return early.
#
# TODO: once docker-based shell environments are implemented (sandboxed, with dirs mounted in),
# replace python_ripgrep with a real subprocess call to the rg binary inside the container.
# That gives us a PID we can kill(). Until then, no timeout is possible here without zombies.
# Design goal: docker and git-bash are the only required host binaries -- no rg on the host.

from __future__ import annotations

import os
import re
import time
from pathlib import Path

ENABLE_REDACTION = True

from python_ripgrep import search as _rg_search
from src.tools._list_dir_utils import (
    _traverse,
    _find_gitignore_root,
    _get_ancestor_matchers,
    _get_effective_matchers,
    _collect_flat,
)

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "search_filesystem_by_regex",
        "description": (
            "Search file contents under a given path using a regular expression. "
            "Powered by ripgrep — fast and .gitignore-aware. "
            "Results are grouped by file; matched substrings are highlighted in bold "
            "using ANSI escape codes.\n\n"
            "Regex restrictions (linear-time only):\n"
            "  - No backreferences (e.g. \\1)\n"
            "  - No lookahead (?=...) or (?!...)\n"
            "  - No lookbehind (?<=...) or (?<!...)\n"
            "  - No lookaround of any kind\n"
            "Standard features are allowed: character classes, alternation, "
            "quantifiers, anchors, non-capturing groups (?:...), Unicode categories."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "The regular expression to search for. Must be linear-time "
                        "(no backreferences, no lookahead/lookbehind/lookaround)."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory to search. Accepts relative (resolved from cwd) "
                        "or absolute paths. If a directory, all files are searched "
                        "recursively. Default: current working directory."
                    ),
                },
                "use_gitignore": {
                    "type": "boolean",
                    "description": (
                        "If true, respect .gitignore rules during search. "
                        "Inside a git repository, ripgrep handles this natively. "
                        "Outside a git repository, files are pre-filtered using "
                        "gitignore_parser so .gitignore rules still apply. "
                        "The .git directory is always excluded when enabled. "
                        "Default: true."
                    ),
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict, _session_data: dict | None = None, special_resources: dict | None = None) -> bool:
    from src.tools._approval import ApprovalContext, needs_path_approval

    return needs_path_approval(args.get("path"), ctx=ApprovalContext.from_special_resources(special_resources))


_BOLD = "\033[1m"
_RESET = "\033[0m"

_ENUMERATE_TIMEOUT = 30  # seconds for the pre-enumeration pass (non-git-repo case)


def _in_git_repo(path: str) -> bool:

    root = _find_gitignore_root(path)
    return (root / ".git").exists()


def _enumerate_gitignored_files(root: str) -> list[str]:
    """Return absolute paths of all non-gitignored files under root."""

    gitignore_root = _find_gitignore_root(root)
    ancestor_matchers = _get_ancestor_matchers(gitignore_root, root)
    effective_matchers = _get_effective_matchers(root, ancestor_matchers, True)

    start = time.monotonic()
    children = _traverse(
        dir_path=root,
        recursive=True,
        follow_folder_symlinks=False,
        follow_file_symlinks=False,
        depth=None,
        visited_dirs={os.path.realpath(root)},
        matchers=effective_matchers,
        use_gitignore=True,
        start_time=start,
        timeout=_ENUMERATE_TIMEOUT,
    )

    flat: list = []
    _collect_flat(children, "", "files", flat)
    return [os.path.normpath(os.path.join(root, rel)) for rel, _ in flat]


def _apply_bold(line: str, pattern: str) -> str:
    """Wrap every occurrence of pattern in the line with ANSI bold codes."""
    result = re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    return result


def execute(args: dict, _session_data: dict | None = None, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    session_cwd: str | None = sr.get("session_current_working_dir")
    pattern: str = args.get("pattern", "")
    raw_path: str = args.get("path", "")
    use_gitignore: bool = args.get("use_gitignore", True)

    display_path: str = raw_path if raw_path else "."
    path: str = raw_path or session_cwd or ""

    if path and not os.path.isabs(path):
        path = os.path.join(session_cwd or "", path)

    if not os.path.exists(path):
        return f"Error: path does not exist: {path!r}"

    is_single_file = os.path.isfile(path)

    # Determine which paths to pass to ripgrep
    if is_single_file or not use_gitignore:
        paths_to_search = [path]
    elif _in_git_repo(path):
        # rg handles .gitignore natively inside a git repo
        paths_to_search = [path]
    else:
        # Outside a git repo: pre-enumerate so .gitignore rules still apply
        try:
            paths_to_search = _enumerate_gitignored_files(path)
        except Exception:
            # Fall back to searching everything if enumeration fails
            paths_to_search = [path]
        if not paths_to_search:
            return f"Search path: {display_path}\n\nNo matches found."

    try:
        raw_results: list[str] = _rg_search(
            patterns=[pattern],
            paths=paths_to_search,
            line_number=True,
            heading=True,
        )
    except Exception as exc:
        return f"Error: {exc}"

    if not raw_results:
        return f"Search path: {display_path}\n\nNo matches found."

    # When searching a single file, python_ripgrep omits the file-path heading
    # even with heading=True. Only directory/multi-file searches include it.
    search_root: str = path

    output_blocks: list[str] = []

    for block in raw_results:
        lines = block.splitlines()
        if not lines:
            continue

        if is_single_file:
            rel_file_path = "."
            match_lines = lines
        else:
            abs_file_path = lines[0]
            rel_file_path = os.path.relpath(abs_file_path, search_root).replace(
                "\\", "/"
            )
            match_lines = lines[1:]

        rendered_matches: list[str] = []
        for raw_line in match_lines:
            colon_pos = raw_line.find(":")
            if colon_pos == -1:
                continue
            lineno = raw_line[:colon_pos]
            content = raw_line[colon_pos + 1 :]

            try:
                highlighted = _apply_bold(content, pattern)
            except re.error:
                highlighted = content
            rendered_matches.append(f"  {lineno}:")
            rendered_matches.append(f"  {highlighted}")

        if rendered_matches:
            block_lines = [f"{rel_file_path}:"] + rendered_matches
            output_blocks.append("\n".join(block_lines))

    if not output_blocks:
        return f"Search path: {display_path}\n\nNo matches found."

    return f"Search path: {display_path}\n\n" + "\n\n".join(output_blocks)
