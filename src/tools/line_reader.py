from __future__ import annotations

import os
from io import StringIO

from src.tools._path_utils import _resolve_path

ENABLE_REDACTION = True

from src.tools._memory import ensure_session_memory
from src.utils.text.line_numbers import add_line_numbers

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "line_reader",
        "description": (
            "Read text content by line range from a file on disk OR from a session memory key. "
            "Provide exactly one of: 'path' (file on disk) or 'session_memory_key' (session memory). "
            "Designed for chunked reading: use count_lines first to know the total, "
            "then read in chunks with start_line/end_line.\n\n"
            "Actions: count_lines, read_lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["count_lines", "read_lines"],
                    "description": (
                        "count_lines -- return the total number of lines.\n"
                        "read_lines  -- return all or a line range of the content."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Path to a file on disk (relative or absolute). "
                        "Mutually exclusive with 'session_memory_key'. Provide exactly one."
                    ),
                },
                "session_memory_key": {
                    "type": "string",
                    "description": (
                        "Session memory key holding the text to read. "
                        "Use this for stub keys (e.g. 'stubs.a1b2c3d4') or any other session memory value. "
                        "Mutually exclusive with 'path'. Provide exactly one."
                    ),
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
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


def dirty_effects(args: dict, session_data: dict | None = None) -> dict:
    # Partial reads do not clean dirty state — only read_text_file or session_memory(get) can clean.
    # The per-range cleaning logic below is commented out because it caused agent loops:
    # the agent would do a partial read expecting it to clean, then get blocked on subsequent writes.
    #
    # if args.get("action") != "read_lines":
    #     return {}
    # start = args.get("start_line")
    # end = args.get("end_line")
    # # Must read from the beginning
    # if start is not None and start != 1:
    #     return {}
    # path = args.get("path")
    # key = args.get("session_memory_key")
    # # No upper bound — unconditionally a full read
    # if end is None:
    #     if path:
    #         return {"cleans_files": [path]}
    #     if key:
    #         return {"cleans_mem": [key]}
    #     return {}
    # # Explicit end — verify against the actual content length
    # if path:
    #     try:
    #         with open(os.path.realpath(path), "r", encoding="utf-8") as fh:
    #             content = fh.read()
    #         total = 0 if content == "" else content.count("\n") + (0 if content.endswith("\n") else 1)
    #         if end >= total:
    #             return {"cleans_files": [path]}
    #     except OSError:
    #         pass
    # if key and session_data is not None:
    #     memory = session_data.get("memory") or {}
    #     content = memory.get(key)
    #     if isinstance(content, str):
    #         total = 0 if content == "" else content.count("\n") + (0 if content.endswith("\n") else 1)
    #         if end >= total:
    #             return {"cleans_mem": [key]}
    return {}


def needs_approval(args: dict) -> bool:
    if args.get("path"):
        from src.tools._approval import needs_path_approval

        return needs_path_approval(args["path"])
    return False


def _load_text(args: dict, session_data: dict, session_cwd: str | None = None) -> tuple[str, str | None]:
    """Return (text, error_string). Exactly one of path/session_memory_key must be set."""
    raw_path = args.get("path")
    key = args.get("session_memory_key")

    if raw_path and key:
        return (
            "",
            "Error: provide exactly one of 'path' or 'session_memory_key', not both.",
        )
    if not raw_path and not key:
        return "", "Error: one of 'path' or 'session_memory_key' is required."

    if raw_path:
        path = _resolve_path(raw_path, session_cwd)
        try:
            resolved = os.path.realpath(path)
            with open(resolved, "r", encoding="utf-8") as fh:
                return fh.read(), None
        except FileNotFoundError:
            return "", f"Error: file not found: {raw_path}"
        except IsADirectoryError:
            return "", f"Error: path is a directory: {raw_path}"
        except UnicodeDecodeError as e:
            return "", f"Error: file is not valid UTF-8: {e}"
        except OSError as e:
            return "", f"Error: {e}"

    memory = ensure_session_memory(session_data)
    value = memory.get(key)
    if value is None:
        return "", f"Error: session memory key {key!r} not found."
    if not isinstance(value, str):
        return "", f"Error: session memory key {key!r} does not hold a text value."
    return value, None


def _count_lines(text: str) -> int:
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


def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    action = args.get("action")

    text, error = _load_text(args, session_data, session_cwd=sr.get("session_cwd"))
    if error:
        return error

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
            return add_line_numbers(
                contents, start_line=effective_start, delimiter=delimiter
            )
        return contents

    return f"Error: unknown action {action!r}."
