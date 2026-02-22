from __future__ import annotations

import re

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_search_by_regex",
        "description": (
            "Search a session memory item (must hold a text value) for lines matching "
            "a Python regular expression. Returns matching lines with right-justified "
            "line numbers and matched substrings highlighted in bold (ANSI). "
            "Use this to locate relevant lines without reading the entire buffer into context. "
            "Supports full Python re syntax including lookahead/lookbehind."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The session memory key. Must hold a text value.",
                },
                "pattern": {
                    "type": "string",
                    "description": "The Python regular expression to search for.",
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


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def _highlight(line: str, pattern: str) -> str:
    try:
        return re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    except re.error:
        return line


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)

    key = args["key"]
    value = memory.get(key)
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    pattern: str = args["pattern"]

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}"

    lines = value.splitlines(keepends=False)
    total = len(lines)
    if total == 0:
        return f"Key {key!r} is empty — no matches."

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
