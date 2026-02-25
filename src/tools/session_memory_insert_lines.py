from __future__ import annotations

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_insert_lines",
        "description": (
            "Insert text before a given 1-based line number in a session memory item. "
            "The key must hold a text value. The inserted text is treated as "
            "complete lines; a trailing newline is added automatically if absent. "
            "If before_line is 1 the text is prepended. If before_line exceeds the "
            "total line count the text is appended. "
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
                "before_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based line number to insert before. "
                        "Use 1 to prepend. Values beyond the last line append to the end."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The text to insert. Treated as complete lines. "
                        "A trailing newline is added automatically if absent."
                    ),
                },
            },
            "required": ["key", "before_line", "text"],
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

    before_line: int = args["before_line"]
    text: str = args["text"]

    if not text.endswith("\n"):
        text += "\n"

    lines = value.splitlines(keepends=True)
    insert_idx = min(before_line - 1, len(lines))
    insert_idx = max(insert_idx, 0)

    new_lines = value.splitlines(keepends=True)
    new_lines[insert_idx:insert_idx] = text.splitlines(keepends=True)
    memory[key] = "".join(new_lines)

    inserted_count = len(text.splitlines())
    return f"Inserted {inserted_count} line(s) before line {before_line} in {key!r}."
