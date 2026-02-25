from __future__ import annotations

import os
import re

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 500

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_search_by_regex",
        "description": (
            "Search a project memory value (must hold a text value) for lines matching "
            "a Python regular expression. Returns matching lines with right-justified "
            "line numbers and matched substrings highlighted in bold (ANSI). "
            "Use this to locate relevant lines without reading the entire value into context. "
            "Supports full Python re syntax including lookahead/lookbehind."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The project memory key. Must hold a text value.",
                },
                "pattern": {
                    "type": "string",
                    "description": "The Python regular expression to search for.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the pinned initial working directory (or current "
                        "working directory if pinning is disabled)."
                    ),
                },
            },
            "required": ["key", "pattern"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


_BOLD = "\033[1m"
_RESET = "\033[0m"


def _get_project(args: dict, session_data: dict) -> str:
    explicit = args.get("project")
    if explicit:
        return explicit
    pinned = (session_data or {}).get("__pinned_project__")
    if pinned:
        return pinned
    return os.getcwd()


def _highlight(line: str, pattern: str) -> str:
    try:
        return re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    except re.error:
        return line


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    key = args["key"]
    pattern: str = args["pattern"]
    project = _get_project(args, session_data)

    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)

    if value is None:
        return f"(key {key!r} not found in project memory)"

    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}"

    lines = value.splitlines(keepends=False)
    total = len(lines)
    if total == 0:
        return f"Key {key!r} is empty -- no matches."

    line_no_width = len(str(total))
    matches: list[str] = []

    for i, line in enumerate(lines, start=1):
        if compiled.search(line):
            lineno = str(i).rjust(line_no_width)
            highlighted = _highlight(line, pattern)
            matches.append(f"{lineno} | {highlighted}")

    if not matches:
        return f"No matches found in {key!r}."

    return f"{len(matches)} match(es) in {key!r}:\n" + "\n".join(matches)
