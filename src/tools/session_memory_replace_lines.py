from __future__ import annotations

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_replace_lines",
        "description": (
            "Replace an inclusive 1-based line range in a session memory item with new text. "
            "The key must hold a text value. The replacement text is treated as "
            "complete lines; a trailing newline is added automatically if absent. "
            "More efficient than delete-then-insert: avoids recalculating line numbers "
            "after deletion. "
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
                    "description": "1-based line number to start replacing from (inclusive).",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number to stop replacing at (inclusive).",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The replacement text. Treated as complete lines. "
                        "A trailing newline is added automatically if absent."
                    ),
                },
            },
            "required": ["key", "start_line", "end_line", "text"],
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
    text: str = args["text"]

    if end_line < start_line:
        return "Error: end_line must be >= start_line."

    if not text.endswith("\n"):
        text += "\n"

    lines = value.splitlines(keepends=True)
    total = len(lines)

    if start_line > total:
        return f"Error: start_line {start_line} exceeds total line count {total}."

    clamped_end = min(end_line, total)
    replacement_lines = text.splitlines(keepends=True)
    lines[start_line - 1:clamped_end] = replacement_lines
    memory[key] = "".join(lines)

    removed = clamped_end - start_line + 1
    added = len(replacement_lines)
    return (
        f"Replaced lines {start_line}–{clamped_end} ({removed} line(s)) "
        f"with {added} line(s) in {key!r}."
    )
