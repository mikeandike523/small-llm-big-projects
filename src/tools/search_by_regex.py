from __future__ import annotations

import os
import re

from python_ripgrep import search as _rg_search

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

_BOLD = "\033[1m"
_RESET = "\033[0m"


def _apply_bold(line: str, pattern: str) -> str:
    """Wrap every occurrence of pattern in the line with ANSI bold codes."""
    result = re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    return result


def execute(args: dict, _session_data: dict | None = None) -> str:
    pattern: str = args.get("pattern", "")
    path: str = args.get("path", "") or os.getcwd()

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
        return "No matches found."

    # When searching a single file, python_ripgrep omits the file-path heading
    # even with heading=True. Only directory searches include it.
    is_single_file = os.path.isfile(path)

    output_blocks: list[str] = []

    for block in raw_results:
        lines = block.splitlines()
        if not lines:
            continue

        if is_single_file:
            # All lines are match lines; use the provided path as the header
            block_file_path = path
            match_lines = lines
        else:
            # First line is the file path heading
            block_file_path = lines[0]
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
            block_lines = [f"{block_file_path}:"] + rendered_matches
            output_blocks.append("\n".join(block_lines))

    if not output_blocks:
        return "No matches found."

    return "\n\n".join(output_blocks)
