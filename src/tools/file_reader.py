from __future__ import annotations

import os
from io import StringIO

from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT_PER_ACTION = {
    "count_lines": ("OMIT", 0),
    "read_lines":  ("SHORT", 800),
}

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "file_reader",
        "description": (
            "Read text file contents directly from disk by line range. "
            "Designed for chunked reading: use count_lines first to know the total, "
            "then read in chunks with start_line/end_line. "
            "No session memory step required.\n\n"
            "Actions: count_lines, read_lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["count_lines", "read_lines"],
                    "description": (
                        "count_lines -- return the total number of lines in the file.\n"
                        "read_lines  -- return all or a line range of the file."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Path to the file. Accepts relative (resolved from cwd) or absolute paths.",
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
            "required": ["action", "path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval
    return needs_path_approval(args.get("path"))


def _read_text(path: str) -> str:
    resolved = os.path.realpath(path)
    with open(resolved, "r", encoding="utf-8") as fh:
        return fh.read()


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
    path = args.get("path")

    if not path:
        return "Error: 'path' is required."

    try:
        text = _read_text(path)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except IsADirectoryError:
        return f"Error: path is a directory: {path}"
    except UnicodeDecodeError as e:
        return f"Error: file is not valid UTF-8: {e}"
    except OSError as e:
        return f"Error: {e}"

    if action == "count_lines":
        return str(_count_lines(text))

    if action == "read_lines":
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        number_lines = bool(args.get("number_lines"))
        delimiter = args.get("delimiter")

        if start_line is not None and end_line is not None and end_line < start_line:
            return "Error: end_line must be >= start_line."

        contents = _read_lines_range(text, start_line, end_line)
        if number_lines:
            effective_start = start_line if start_line is not None else 1
            return add_line_numbers(contents, start_line=effective_start, delimiter=delimiter)
        return contents

    return f"Error: unknown action {action!r}."
