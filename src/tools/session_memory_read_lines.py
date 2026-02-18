from __future__ import annotations

from io import StringIO
from src.utils.text.line_numbers import add_line_numbers

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_read_lines",
        "description": (
            "Read all lines or an inclusive line range from a session memory "
            "item when the top-level value is a JSON string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to read.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Optional 1-based line number to start reading from "
                        "(inclusive)."
                    ),
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Optional 1-based line number to stop reading at "
                        "(inclusive)."
                    ),
                },
                "number_lines": {
                    "type": "boolean",
                    "description": "If true, prefix each returned line with its line number.",
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def _read_lines(text: str, start_line: int | None, end_line: int | None) -> str:
    if start_line is None and end_line is None:
        return text

    effective_start_line = start_line if start_line is not None else 1
    selected_lines: list[str] = []

    for line_number, line in enumerate(StringIO(text), start=1):
        if line_number < effective_start_line:
            continue
        if end_line is not None and line_number > end_line:
            break
        selected_lines.append(line)

    return "".join(selected_lines)


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)

    key = args["key"]
    value = memory.get(key)
    if not isinstance(value, str):
        return f"key {key} is not a json string"

    start_line = args.get("start_line")
    end_line = args.get("end_line")
    number_lines = bool(args.get("number_lines"))

    if start_line is not None and start_line < 1:
        return "Error: start_line must be >= 1"
    if end_line is not None and end_line < 1:
        return "Error: end_line must be >= 1"
    if start_line is not None and end_line is not None and end_line < start_line:
        return "Error: end_line must be >= start_line"

    contents = _read_lines(value, start_line, end_line)
    if number_lines:
        effective_start_line = start_line if start_line is not None else 1
        return add_line_numbers(contents, start_line=effective_start_line)
    return contents
