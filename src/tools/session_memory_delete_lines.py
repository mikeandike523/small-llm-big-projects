from __future__ import annotations

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_delete_lines",
        "description": (
            "Delete an inclusive 1-based line range from a session memory item. "
            "The key must hold a text value. "
            "Part of the in-memory text editor toolkit: "
            "read_text_file_to_session_memory → edit → write_text_file_from_session_memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The session memory key. Must hold a text value.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number to start deleting from (inclusive).",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number to stop deleting at (inclusive).",
                },
            },
            "required": ["key", "start_line", "end_line"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)

    key = args["key"]
    value = memory.get(key)
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    start_line: int = args["start_line"]
    end_line: int = args["end_line"]

    if end_line < start_line:
        return "Error: end_line must be >= start_line."

    lines = value.splitlines(keepends=True)
    total = len(lines)

    if start_line > total:
        return f"Error: start_line {start_line} exceeds total line count {total}."

    clamped_end = min(end_line, total)
    deleted_count = clamped_end - start_line + 1
    del lines[start_line - 1:clamped_end]
    memory[key] = "".join(lines)

    return f"Deleted {deleted_count} line(s) ({start_line}–{clamped_end}) from {key!r}."
