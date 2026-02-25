from __future__ import annotations

import os
import re

from python_ripgrep import search as _rg_search

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 600

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "search_by_regex",
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
                        "recursively (respecting .gitignore). Default: current working directory."
                    ),
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}

def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval
    return needs_path_approval(args.get("path"))


_BOLD = "\033[1m"
_RESET = "\033[0m"


def _apply_bold(line: str, pattern: str) -> str:
    """Wrap every occurrence of pattern in the line with ANSI bold codes."""
    result = re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    return result


def execute(args: dict, _session_data: dict | None = None) -> str:
    pattern: str = args.get("pattern", "")
    raw_path: str = args.get("path", "")
    display_path: str = raw_path if raw_path else "."
    path: str = raw_path or os.getcwd()

    # Resolve relative paths against cwd
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    if not os.path.exists(path):
        return f"Error: path does not exist: {path!r}"

    try:
        raw_results: list[str] = _rg_search(
            patterns=[pattern],
            paths=[path],
            line_number=True,
            heading=True,
        )
    except Exception as exc:
        return f"Error: {exc}"

    if not raw_results:
        return f"Search path: {display_path}\n\nNo matches found."

    # When searching a single file, python_ripgrep omits the file-path heading
    # even with heading=True. Only directory searches include it.
    is_single_file = os.path.isfile(path)

    # For relative path computation: use the directory as root for single files
    search_root: str = path

    output_blocks: list[str] = []

    for block in raw_results:
        lines = block.splitlines()
        if not lines:
            continue

        if is_single_file:
            # All lines are match lines; file is the search root so rel path is "."
            rel_file_path = "."
            match_lines = lines
        else:
            # First line is the absolute file path heading from ripgrep
            abs_file_path = lines[0]
            rel_file_path = os.path.relpath(abs_file_path, search_root).replace("\\", "/")
            match_lines = lines[1:]

        rendered_matches: list[str] = []
        for raw_line in match_lines:
            # Each line is "lineno:content"
            colon_pos = raw_line.find(":")
            if colon_pos == -1:
                continue
            lineno = raw_line[:colon_pos]
            content = raw_line[colon_pos + 1:]
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
