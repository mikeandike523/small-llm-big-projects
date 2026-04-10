from __future__ import annotations

from io import StringIO

from src.tools._memory import ensure_session_memory
from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT_PER_ACTION = {
    "count_lines": ("OMIT", 0),
    "read_lines":  ("SHORT", 800),
}

_STUB_MARKER = "** STUBBED LONG RETURN VALUE **"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "return_stub_line_reader",
        "description": (
            "Read a stubbed tool return value by line range. "
            "When a tool result begins with '** STUBBED LONG RETURN VALUE **', the full content "
            "is stored in session memory at the key shown in the stub header. "
            "Use count_lines first to know the total, then read in chunks with start_line/end_line.\n\n"
            "Actions: count_lines, read_lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["count_lines", "read_lines"],
                    "description": (
                        "count_lines -- return the total number of lines in the stubbed value.\n"
                        "read_lines  -- return all or a line range of the stubbed value."
                    ),
                },
                "session_memory_key": {
                    "type": "string",
                    "description": "The session_memory_key shown in the stub header (e.g. 'stubs.a1b2c3d4').",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number to start reading from (inclusive). Used by: read_lines.",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number to stop reading at (inclusive). Used by: read_lines.",
                },
                "number_lines": {
                    "type": "boolean",
                    "description": "If true, prefix each returned line with its 1-based line number. Used by: read_lines.",
                },
                "delimiter": {
                    "type": "string",
                    "description": (
                        "Separator between line number and content when number_lines is true. "
                        "Defaults to ' | '. Used by: read_lines."
                    ),
                },
            },
            "required": ["action", "session_memory_key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _count_lines(text: str) -> int:
    """Count logical lines, treating \\n as the sole line boundary."""
    if text == "":
        return 0
    n = text.count("\n")
    return n if text.endswith("\n") else n + 1


def _read_lines_range(text: str, start_line: int | None, end_line: int | None) -> str:
    if start_line is None and end_line is None:
        return text
    effective_start = start_line if start_line is not None else 1
    selected: list[str] = []
    for lineno, line in enumerate(StringIO(text), start=1):
        if lineno < effective_start:
            continue
        if end_line is not None and lineno > end_line:
            break
        selected.append(line)
    return "".join(selected)


def execute(args: dict, session_data: dict) -> str:
    action = args.get("action")
    key = args.get("session_memory_key")

    if not key:
        return "Error: 'session_memory_key' is required."

    memory = ensure_session_memory(session_data)
    value = memory.get(key)

    if value is None:
        return f"Error: session memory key {key!r} not found."
    if not isinstance(value, str):
        return f"Error: session memory key {key!r} does not hold a text value."

    if action == "count_lines":
        return str(_count_lines(value))

    if action == "read_lines":
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        number_lines = bool(args.get("number_lines"))
        delimiter = args.get("delimiter")

        if start_line is not None and end_line is not None and end_line < start_line:
            return "Error: end_line must be >= start_line."

        contents = _read_lines_range(value, start_line, end_line)
        if number_lines:
            effective_start = start_line if start_line is not None else 1
            return add_line_numbers(contents, start_line=effective_start, delimiter=delimiter)
        return contents

    return f"Error: unknown action {action!r}."
